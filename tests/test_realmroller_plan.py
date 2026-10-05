"""The realm roller's act plans: digests, edits, folds, reverts, verdicts (#590)."""

import copy
import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import realmroller as rr  # noqa: E402
import realmroller_plan as plan  # noqa: E402

EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "realm_roller_example"
T0 = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)
WS = "sha256:" + "a1" * 32
DI = "sha256:" + "b2" * 32
OTHER = "sha256:" + "c3" * 32


def _channel_raw():
    return json.loads((EXAMPLE / "channel.json").read_text())


def _release_raw(name):
    return json.loads((EXAMPLE / "releases" / ("%s.json" % name)).read_text())


def _channel():
    return rr.parse_channel(_channel_raw())


def _act():
    raw = _channel_raw()
    return plan.parse_act(raw["act"], rr.parse_channel(raw))


def _build():
    return _act().builds["worldserver"]


def _log(*lines):
    """A build log as GitHub serves it: every line behind a timestamp."""
    return "\n".join(
        "2026-10-05T03:00:%02d.1234567Z %s" % (i % 60, ln) for i, ln in enumerate(lines)
    )


TAG = "core-111111111111-mod-222222222222"


def _push(repo, digest, tag=TAG):
    return [
        "The push refers to repository [%s]" % repo,
        "5f70bf18a086: Layer already exists",
        "%s: digest: %s size: 1234" % (tag, digest),
        "The push refers to repository [%s]" % repo,
        "latest: digest: %s size: 1234" % digest,
    ]


class ActBlock(unittest.TestCase):
    def test_the_example_parses(self):
        act = _act()
        self.assertEqual(act.base, "main")
        self.assertEqual(set(act.builds), {"worldserver"})
        self.assertEqual(act.prove_within, timedelta(minutes=10))

    def test_a_missing_block_is_invalid(self):
        with self.assertRaises(rr.Invalid):
            plan.parse_act(None, _channel())

    def test_every_problem_is_reported(self):
        raw = _channel_raw()["act"]
        del raw["builds"]["worldserver"]["pin_keys"]["core"]
        raw["builds"]["worldserver"]["image_repos"].pop("db-import")
        raw["edits"][0]["if_component"] = "worldserver"  # both conditions
        raw["edits"][1]["pattern"] = "(unclosed {source:core}"
        raw["gitlinks"][0]["source"] = "nope"
        with self.assertRaises(rr.Invalid) as cm:
            plan.parse_act(raw, _channel())
        text = str(cm.exception)
        for want in (
            "pin_keys lacks core",
            "image_repos must name exactly worldserver, db-import",
            "exactly one of if_source or if_component",
            "pattern:",
            "source nope is not a source",
        ):
            self.assertIn(want, text)

    def test_a_prove_block_without_a_namespace_is_invalid(self):
        # The namespace is where the throwaway pod runs; an empty one would
        # send the pod to a path the API rejects, long after the parse.
        raw = _channel_raw()["act"]
        del raw["prove"]["namespace"]
        with self.assertRaisesRegex(rr.Invalid, "act.prove.namespace"):
            plan.parse_act(raw, _channel())

    def test_a_missing_or_null_prove_block_is_invalid_not_a_crash(self):
        for value in (None, "x"):
            raw = _channel_raw()["act"]
            raw["prove"] = value
            with self.assertRaisesRegex(rr.Invalid, "act.prove must be an object"):
                plan.parse_act(raw, _channel())

    def test_a_placeholder_must_name_a_source(self):
        raw = _channel_raw()["act"]
        raw["edits"][0]["replace"] = "X={source:mod-nothing}"
        with self.assertRaises(rr.Invalid) as cm:
            plan.parse_act(raw, _channel())
        self.assertIn("{source:mod-nothing} is not a source", str(cm.exception))

    def test_every_verify_log_must_be_readable(self):
        ch = _channel()
        rel = rr.parse_release(_release_raw("r2026.10.04-2"), ch)
        act = _act()
        plan.check_logs(act, {rel.name: rel})
        del act.logs["worldserver"]
        with self.assertRaises(rr.Invalid):
            plan.check_logs(act, {rel.name: rel})


class Digests(unittest.TestCase):
    def test_pairs_each_digest_with_its_repository(self):
        text = _log(
            *_push("registry.example/worldserver", WS),
            *_push("registry.example/authserver", OTHER),
            *_push("registry.example/db-import", DI),
        )
        self.assertEqual(
            plan.read_digests(text, _build()), {"worldserver": WS, "db-import": DI}
        )

    def test_sha256_lines_between_pushes_cannot_shift_the_pairing(self):
        # buildx prints its own sha256 lines; a positional read would take one.
        noise = [
            "#12 exporting manifest sha256:%s 0.0s done" % ("d4" * 32),
            "#12 writing image digest: sha256:%s done" % ("e5" * 32),
        ]
        text = _log(
            *noise,
            *_push("registry.example/db-import", DI),
            *noise,
            *_push("registry.example/worldserver", WS),
        )
        self.assertEqual(
            plan.read_digests(text, _build()), {"worldserver": WS, "db-import": DI}
        )

    def test_a_push_with_no_digest_is_refused(self):
        lines = _push("registry.example/worldserver", WS)
        del lines[2]
        text = _log(*lines, *_push("registry.example/db-import", DI))
        with self.assertRaisesRegex(plan.PairingError, "has no digest line"):
            plan.read_digests(text, _build())

    def test_a_digest_with_no_repository_is_refused(self):
        text = _log(
            "%s: digest: %s size: 1" % (TAG, WS),
            *_push("registry.example/worldserver", WS),
            *_push("registry.example/db-import", DI),
        )
        with self.assertRaisesRegex(plan.PairingError, "no repository before it"):
            plan.read_digests(text, _build())

    def test_tag_and_latest_must_agree(self):
        lines = _push("registry.example/worldserver", WS)
        lines[4] = "latest: digest: %s size: 1" % OTHER
        text = _log(*lines, *_push("registry.example/db-import", DI))
        with self.assertRaisesRegex(plan.PairingError, "2 different digests"):
            plan.read_digests(text, _build())

    def test_a_missing_image_is_refused(self):
        text = _log(*_push("registry.example/worldserver", WS))
        with self.assertRaisesRegex(
            plan.PairingError, "no push of registry.example/db-import"
        ):
            plan.read_digests(text, _build())

    def test_two_tags_are_two_builds(self):
        text = _log(
            *_push("registry.example/worldserver", WS),
            *_push(
                "registry.example/db-import",
                DI,
                tag="core-999999999999-mod-222222222222",
            ),
        )
        with self.assertRaisesRegex(plan.PairingError, "different tags"):
            plan.read_digests(text, _build())

    def test_the_log_must_name_every_pin(self):
        rel = rr.parse_release(_release_raw("r2026.10.04-2"), _channel())
        named = " ".join(sha[:12] for sha in rel.sources.values())
        self.assertEqual(plan.build_log_lacks(named, _build(), rel), [])
        missing = named.replace(rel.sources["mod-overseer"][:12], "")
        self.assertEqual(plan.build_log_lacks(missing, _build(), rel), ["mod-overseer"])

    def test_build_inputs_carry_every_pin(self):
        rel = rr.parse_release(_release_raw("r2026.10.04-2"), _channel())
        inputs = plan.build_inputs(_build(), rel)
        self.assertEqual(inputs["release"], "r2026.10.04-2")
        self.assertIn("OVERSEER_SHA=" + "8" * 40, inputs["pins"].split())
        self.assertEqual(len(inputs["pins"].split()), 5)


class Edits(unittest.TestCase):
    OLD = {
        "source:core": "1" * 40,
        "image:worldserver": WS,
        "release": "r1",
        "run": "5",
    }
    NEW = {
        "source:core": "9" * 40,
        "image:worldserver": OTHER,
        "release": "r2",
        "run": "6",
    }

    def edit(self, pattern, replace, count=1, if_source="core", if_component=""):
        return plan.Edit("f", pattern, replace, count, if_source, if_component)

    def test_replaces_old_values_with_new(self):
        e = self.edit("^CORE={source:core}$", "CORE={source:core}")
        out = plan.apply_edits(
            {"f": "A=1\nCORE=%s\n" % ("1" * 40)},
            (e,),
            self.OLD,
            self.NEW,
            {"core"},
            set(),
        )
        self.assertEqual(out["f"], "A=1\nCORE=%s\n" % ("9" * 40))

    def test_groups_and_templates_together(self):
        e = self.edit(
            "(name: ws\\n)(?:  #[^\\n]*\\n)*  digest: {image:worldserver}",
            "\\g<1>  # Build {run}: {release}\\n  digest: {image:worldserver}",
            if_source="",
            if_component="worldserver",
        )
        text = "name: ws\n  # old\n  # older\n  digest: %s\n" % WS
        out = plan.apply_edits(
            {"f": text}, (e,), self.OLD, self.NEW, set(), {"worldserver"}
        )
        self.assertEqual(out["f"], "name: ws\n  # Build 6: r2\n  digest: %s\n" % OTHER)

    def test_a_file_not_at_the_current_release_is_refused(self):
        # Someone moved the pin by hand: the old value is not there.
        e = self.edit("^CORE={source:core}$", "CORE={source:core}")
        with self.assertRaisesRegex(plan.PlanError, "matched 0 time"):
            plan.apply_edits(
                {"f": "CORE=%s\n" % ("7" * 40)},
                (e,),
                self.OLD,
                self.NEW,
                {"core"},
                set(),
            )

    def test_an_edit_for_an_unchanged_source_does_not_apply(self):
        e = self.edit("^CORE={source:core}$", "CORE={source:core}")
        out = plan.apply_edits({"f": "nothing"}, (e,), self.OLD, self.NEW, set(), set())
        self.assertEqual(out["f"], "nothing")

    def test_the_count_is_exact(self):
        e = self.edit("{source:core}", "{source:core}")
        with self.assertRaisesRegex(plan.PlanError, "matched 2"):
            plan.apply_edits(
                {"f": "%s %s" % ("1" * 40, "1" * 40)},
                (e,),
                self.OLD,
                self.NEW,
                {"core"},
                set(),
            )

    def test_old_values_are_escaped(self):
        old = dict(self.OLD, release="r2026.10.04-1")
        e = self.edit("rel {release}", "rel {release}", if_source="core")
        # An unescaped "." would match the "x" and rewrite the wrong line.
        with self.assertRaises(plan.PlanError):
            plan.apply_edits(
                {"f": "rel r2026x10x04-1"}, (e,), old, self.NEW, {"core"}, set()
            )
        out = plan.apply_edits(
            {"f": "rel r2026.10.04-1"}, (e,), old, self.NEW, {"core"}, set()
        )
        self.assertEqual(out["f"], "rel r2")


class Overlay(unittest.TestCase):
    def raw(self, *states):
        d = _release_raw("r2026.10.04-2")
        d["history"] = d["history"][: len(states)]
        d["state"] = states[-1] if states else "proposed"
        return d

    def test_a_longer_status_history_wins(self):
        main = {"r2026.10.04-2": self.raw("building")}
        held = {"r2026.10.04-2": self.raw("building", "built", "proven")}
        out, dropped = plan.overlay(main, held)
        self.assertEqual(out["r2026.10.04-2"]["state"], "proven")
        self.assertEqual(dropped, [])

    def test_a_person_edit_wins(self):
        main = {"r2026.10.04-2": self.raw("building")}
        held = {"r2026.10.04-2": self.raw("building", "built")}
        main["r2026.10.04-2"]["history"][0]["at"] = "2026-10-04T21:03:00-04:00"
        out, dropped = plan.overlay(main, held)
        self.assertEqual(out["r2026.10.04-2"]["state"], "building")
        self.assertEqual(dropped, ["r2026.10.04-2"])

    def test_the_deploy_repo_catching_up_drops_the_status_copy(self):
        main = {"r2026.10.04-2": self.raw("building", "built", "proven")}
        held = {"r2026.10.04-2": self.raw("building", "built", "proven")}
        self.assertEqual(plan.overlay(main, held)[1], ["r2026.10.04-2"])

    def test_a_release_gone_from_the_repo_is_dropped(self):
        self.assertEqual(
            plan.overlay({}, {"r2026.10.04-9": self.raw("building")})[1],
            ["r2026.10.04-9"],
        )

    def test_advance_refuses_an_illegal_move(self):
        with self.assertRaises(plan.PlanError):
            plan.advance(self.raw("building"), "proven", T0, "skip")

    def test_advance_records_the_build(self):
        d = plan.advance(self.raw(), "building", T0, "run", run=77)
        self.assertEqual((d["state"], d["build"]["run"]), ("building", 77))
        self.assertEqual(d["history"][-1]["by"], "roller")


class RollerFiles(unittest.TestCase):
    def test_a_roll_moves_current_previous_and_the_queue(self):
        ch = _channel_raw()
        ch["queue"] = ["r2026.10.04-2", "r2026.10.04-3"]
        older = copy.deepcopy(_release_raw("r2026.10.04-2"))
        raws = {
            "r2026.10.04-1": _release_raw("r2026.10.04-1"),
            "r2026.10.04-2": older,
            "r2026.10.04-3": dict(copy.deepcopy(older), release="r2026.10.04-3"),
        }
        files = plan.roll_roller_files(
            "roller", ch, raws, "r2026.10.04-3", ("r2026.10.04-2",), T0
        )
        chan = json.loads(files["roller/channel.json"])
        self.assertEqual(
            (chan["current"], chan["previous"]), ("r2026.10.04-3", "r2026.10.04-1")
        )
        self.assertEqual(chan["queue"], [])
        self.assertEqual(
            json.loads(files["roller/releases/r2026.10.04-3.json"])["state"], "rolling"
        )
        self.assertEqual(
            json.loads(files["roller/releases/r2026.10.04-2.json"])["state"],
            "superseded",
        )
        # The files parse back into a valid set.
        rels = {n: json.loads(t) for n, t in files.items() if "/releases/" in n}
        rels = {d["release"]: d for d in rels.values()}
        rels.setdefault("r2026.10.03-3", _release_raw("r2026.10.03-3"))
        plan.parse_set(chan, rels)

    def test_a_rollback_pauses_with_the_reason(self):
        ch = _channel_raw()
        ch.update(
            current="r2026.10.04-2", previous="r2026.10.04-1", queue=[], paused=False
        )
        raws = {
            "r2026.10.04-2": plan.advance(
                _release_raw("r2026.10.04-2"), "rolling", T0, ""
            )
        }
        files = plan.rollback_roller_files(
            "roller", ch, raws, "r2026.10.04-2", "r2026.10.04-1", "log signature: X", T0
        )
        chan = json.loads(files["roller/channel.json"])
        self.assertTrue(chan["paused"])
        self.assertIn("log signature: X", chan["paused_reason"])
        self.assertEqual(chan["current"], "r2026.10.04-1")
        self.assertEqual(
            json.loads(files["roller/releases/r2026.10.04-2.json"])["state"],
            "rolled_back",
        )


class FoldsAndReverts(unittest.TestCase):
    def test_a_clean_fold_takes_the_head_blob(self):
        f = plan.FoldFile("cfg/a.conf", "b1", "b1", "h1")
        self.assertEqual(
            plan.fold_entries("#5", [f], ("roller",)), {"cfg/a.conf": "h1"}
        )

    def test_a_file_changed_on_base_since_is_refused(self):
        f = plan.FoldFile("cfg/a.conf", "b1", "b2", "h1")
        with self.assertRaisesRegex(plan.PlanError, "changed on the base branch"):
            plan.fold_entries("#5", [f], ("roller",))

    def test_a_fold_may_not_touch_the_roller_or_a_submodule(self):
        with self.assertRaisesRegex(plan.PlanError, "the roller owns"):
            plan.fold_entries(
                "#5", [plan.FoldFile("roller/channel.json", "a", "a", "b")], ("roller",)
            )
        with self.assertRaisesRegex(plan.PlanError, "submodule"):
            plan.fold_entries(
                "#5", [plan.FoldFile("modules/x", "a", "a", "b", gitlink=True)], ()
            )

    def test_a_revert_restores_the_parent(self):
        sides = [
            plan.Side(
                "pins.env", ("100644", "old"), ("100644", "new"), ("100644", "new")
            ),
            plan.Side(
                "modules/x", ("160000", "c1"), ("160000", "c2"), ("160000", "c2")
            ),
            plan.Side("added.yaml", None, ("100644", "n"), ("100644", "n")),
            plan.Side(
                "roller/channel.json", ("100644", "a"), ("100644", "b"), ("100644", "c")
            ),
        ]
        self.assertEqual(
            plan.revert_entries(sides, "roller"),
            {
                "pins.env": ("100644", "old"),
                "modules/x": ("160000", "c1"),
                "added.yaml": None,
            },
        )

    def test_a_path_changed_after_the_roll_is_refused(self):
        sides = [
            plan.Side(
                "pins.env", ("100644", "old"), ("100644", "new"), ("100644", "newer")
            )
        ]
        with self.assertRaisesRegex(plan.PlanError, "changed after the roll commit"):
            plan.revert_entries(sides, "roller")


def _check(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


class Verdicts(unittest.TestCase):
    PR = {
        "state": "open",
        "merged": False,
        "mergeable": True,
        "mergeable_state": "clean",
    }

    def v(self, checks, threads=0, pr=None, statuses=(), block=True):
        return plan.pr_verdict(
            pr or self.PR, checks, list(statuses), threads, ("ci",), block
        )

    def test_ready_when_everything_passed(self):
        self.assertEqual(
            self.v([_check("ci"), _check("lint", conclusion="skipped")]).kind, "ready"
        )

    def test_a_required_check_not_yet_reported_is_pending(self):
        self.assertEqual(self.v([_check("lint")]).kind, "pending")

    def test_a_running_check_is_pending(self):
        self.assertEqual(
            self.v(
                [_check("ci"), _check("e", status="in_progress", conclusion=None)]
            ).kind,
            "pending",
        )

    def test_a_failed_check_or_status_fails(self):
        self.assertEqual(self.v([_check("ci", conclusion="failure")]).kind, "failed")
        v = self.v([_check("ci")], statuses=[{"context": "scan", "state": "error"}])
        self.assertEqual((v.kind, v.why), ("failed", "failing: scan"))

    def test_an_open_thread_holds_a_roll_but_not_a_rollback(self):
        self.assertEqual(self.v([_check("ci")], threads=1).kind, "pending")
        self.assertEqual(self.v([_check("ci")], threads=1, block=False).kind, "ready")

    def test_conflict_closed_and_merged(self):
        self.assertEqual(self.v([], pr=dict(self.PR, mergeable=False)).kind, "conflict")
        self.assertEqual(self.v([], pr=dict(self.PR, state="closed")).kind, "closed")
        self.assertEqual(self.v([], pr=dict(self.PR, merged=True)).kind, "merged")

    def test_unknown_mergeability_waits(self):
        self.assertEqual(
            self.v([_check("ci")], pr=dict(self.PR, mergeable=None)).kind, "pending"
        )


class ProvePod(unittest.TestCase):
    def test_the_pod_carries_no_token_and_runs_read_only(self):
        rel = rr.parse_release(_release_raw("r2026.10.04-2"), _channel())
        pod = plan.prove_pod(_act(), rel, "worldserver", "registry.example/worldserver")
        spec = pod["spec"]
        self.assertFalse(spec["automountServiceAccountToken"])
        c = spec["containers"][0]
        self.assertEqual(
            c["image"], "registry.example/worldserver@" + rel.images["worldserver"]
        )
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(c["command"][-1], "worldbuff disabled")
        self.assertEqual(pod["metadata"]["namespace"], "roller-prove")
        self.assertLessEqual(len(pod["metadata"]["name"]), 63)

    def test_counts(self):
        self.assertEqual(plan.prove_counts("count=2\ncount=0\n", 2), [2, 0])
        self.assertIsNone(plan.prove_counts("count=\n", 1))  # the binary was unreadable
        self.assertIsNone(plan.prove_counts("count=1\n", 2))

    def test_names(self):
        self.assertEqual(
            plan.k8s_name("prove", "r2026.10.04-2", "db-import"),
            "prove-r2026-10-04-2-db-import",
        )


class Scan(unittest.TestCase):
    def test_seen_and_signatures(self):
        check = rr.Check(
            "worldserver", "guild death recorded", False, timedelta(minutes=5), False
        )
        seen, bad = plan.scan(
            ["boot", "x guild death recorded y", "ASSERTION FAILED: z"],
            [check],
            ("ASSERTION FAILED",),
        )
        self.assertEqual(seen, {check.label})
        self.assertEqual(bad, "ASSERTION FAILED")


class Bodies(unittest.TestCase):
    def test_the_roll_body_has_the_readiness_sections(self):
        ch = _channel()
        rel = rr.parse_release(_release_raw("r2026.10.04-2"), ch)
        cur = rr.parse_release(_release_raw("r2026.10.04-1"), ch)
        body = plan.roll_body(
            rel, cur, ["worldserver"], (), ["#104"], "wow-overseer#590"
        )
        for heading in (
            "## Why",
            "## What",
            "## Acceptance",
            "Size: XS",
            "## Out of scope",
        ):
            self.assertIn(heading, body)
        acceptance = body.split("## Acceptance")[1].split("Size:")[0]
        self.assertEqual(acceptance.count("\n- "), 3)
        self.assertIn("mod-overseer `77777777` -> `88888888`", body)
        body.encode("ascii")


if __name__ == "__main__":
    unittest.main()
