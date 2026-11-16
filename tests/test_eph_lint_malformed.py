"""Lint returns findings for any malformed decree; it never raises."""

import copy
import pathlib
import unittest

from ephemeral import anchors as anchors_mod
from ephemeral import dbschema, lint
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECREES = sorted(
    p for p in (ROOT / "data" / "decrees").glob("*.yaml") if p.name != "anchors.yaml"
)
ANCHORS = anchors_mod.Anchors.load()
SCHEMA = dbschema.Schema.load()
JUNK = (None, [], {}, "", "x", 0, 7, True, [1], {"k": "v"}, {"map": "x"})


def run(doc):
    return lint.lint_document(doc, ANCHORS, SCHEMA)


def paths(node, prefix=()):
    """Every (path, container) position in a nested document."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield prefix + (k,)
            yield from paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield prefix + (i,)
            yield from paths(v, prefix + (i,))


def at(doc, path):
    for p in path[:-1]:
        doc = doc[p]
    return doc


class MalformedMappingsTest(unittest.TestCase):
    def test_instance_with_map_but_no_alias_is_a_finding(self):
        d = loads(DECREES[0].read_text(encoding="utf-8"))
        d["arrange"] = [{"instance": {"map": "Blackrock Depths"}}]
        found = run(d)
        self.assertTrue(
            [f for f in found if f.level == "error" and "instance.as" in f.path]
        )

    def test_group_creature_act_and_log_missing_fields_are_findings(self):
        d = loads(DECREES[0].read_text(encoding="utf-8"))
        d["arrange"] = [
            {"group": {"members": "family:grug"}},
            {"creature": {"name": "X"}},
        ]
        d["act"] = [
            {"at": "0s", "roster": {"who": "Grug"}},
            {"at": "0s", "command": {"who": "Grug"}},
        ]
        d["observe"].append(
            {"name": "log-one", "role": "check", "log": {"pattern": "x"}}
        )
        errs = [f for f in run(d) if f.level == "error"]
        for needle in (
            "group.leader",
            "creature.in",
            "roster.job",
            "command.kind",
            "log.expect",
        ):
            self.assertTrue(any(needle in f.path for f in errs), needle)

    def test_every_single_field_removed_or_replaced_never_raises(self):
        for decree in DECREES:
            base = loads(decree.read_text(encoding="utf-8"))
            for path in list(paths(base)):
                for junk in JUNK:
                    d = copy.deepcopy(base)
                    at(d, path)[path[-1]] = junk
                    try:
                        run(d)
                    except Exception as exc:  # noqa: BLE001 - the point of the test
                        self.fail(f"{decree.name}: {path} = {junk!r} raised {exc!r}")
                d = copy.deepcopy(base)
                container = at(d, path)
                if isinstance(container, dict):
                    del container[path[-1]]
                    try:
                        run(d)
                    except Exception as exc:  # noqa: BLE001
                        self.fail(f"{decree.name}: removing {path} raised {exc!r}")

    def test_non_mapping_documents_are_findings(self):
        for doc in (None, [], "x", 3, {}):
            self.assertTrue(run(doc))


class DuplicateAliasTest(unittest.TestCase):
    def test_two_instances_with_one_alias_are_rejected(self):
        d = loads(DECREES[0].read_text(encoding="utf-8"))
        d["arrange"] = [
            {"instance": {"map": "Blackrock Depths", "as": "brd"}},
            {"instance": {"map": "Molten Core", "as": "brd"}},
        ]
        errs = [f for f in run(d) if f.level == "error"]
        self.assertTrue(
            any("instance.as" in f.path and "duplicate" in f.message for f in errs)
        )

    def test_distinct_aliases_are_fine(self):
        d = loads(DECREES[0].read_text(encoding="utf-8"))
        d["arrange"] = [
            {"instance": {"map": "Blackrock Depths", "as": "brd"}},
            {"instance": {"map": "Molten Core", "as": "mc"}},
        ]
        self.assertEqual(
            [f for f in run(d) if f.level == "error" and "instance" in f.path], []
        )


if __name__ == "__main__":
    unittest.main()
