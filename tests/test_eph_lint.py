"""`eph lint`: decree schema v1 and the rules that keep a decree honest."""

import contextlib
import copy
import io
import pathlib
import unittest

from ephemeral import anchors as anchors_mod
from ephemeral import dbschema, lint
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECREES = sorted(
    p for p in (ROOT / "data" / "decrees").glob("*.yaml") if p.name != "anchors.yaml"
)

BASE = """
decree: v1
id: sample-decree
proves:
  - {repo: owner/repo, issue: 5, criterion: "the thing works"}
fix: {repo: owner/repo, commit: abcdef1}
world: {class: lean, image: follow-dev, bridge: off, random_bots: 0, config: {}}
runs: {control: 3, treatment: 3}
duration: 20m
cast:
  - who: Grug
    set: {alive: true, at: {creature: "Some Creature"}}
act:
  - at: 0s
    roster: {who: Grug, job: quest}
observe:
  - name: reached
    role: precondition
    when: end
    sql: "SELECT COUNT(*) FROM characters WHERE guid = @cast0"
    expect: {scalar: ">= 1"}
  - name: nobody-died
    role: check
    when: end
    sql: "SELECT character_name FROM overseer_death WHERE created_at >= @t0"
    expect: {rows: 0}
"""

ANCHORS = anchors_mod.Anchors(
    {
        "real-spot": {
            "map": 1,
            "zone": 2,
            "x": 1.5,
            "y": 2.5,
            "z": 3.5,
            "o": 0.0,
            "provenance": {
                "source": "overseer_death",
                "ref": "row 1",
                "observed": "2026-01-01",
            },
        },  # fmt: skip
        "later-spot": {"pending": True, "todo": "copy it"},
    }
)
SCHEMA = dbschema.Schema.load()


def doc():
    return copy.deepcopy(loads(BASE))


def run(d):
    return lint.lint_document(d, ANCHORS, SCHEMA)


def errors(d):
    return [f for f in run(d) if f.level == "error"]


def rules(d):
    return {f.rule for f in errors(d)}


def scattered_doc():
    d = doc()
    d["cast"][0]["who"] = "family:grug"
    d["cast"][0]["set"].pop("at")
    d["cast"][0]["set"]["at_each"] = [
        {"creature": "Some Creature"},
        {"areatrigger": 2},
    ]
    return d


class CleanTest(unittest.TestCase):
    def test_base_is_clean(self):
        self.assertEqual(run(doc()), [])

    def test_unknown_top_key(self):
        d = doc()
        d["surprise"] = 1
        self.assertIn("schema", rules(d))

    def test_bad_yaml_is_a_finding(self):
        out = lint.lint_text("a: 1\na: 2\n", ANCHORS, SCHEMA)
        self.assertEqual(out[0].rule, "yaml")


class CoordinatesTest(unittest.TestCase):
    def test_family_at_each_anchor_forms_are_accepted(self):
        self.assertEqual(errors(scattered_doc()), [])

    def test_at_each_is_restricted_to_family_selectors(self):
        d = scattered_doc()
        d["cast"][0]["who"] = "Grug"
        self.assertIn("scatter", rules(d))

    def test_at_each_requires_at_least_two_points(self):
        d = scattered_doc()
        d["cast"][0]["set"]["at_each"] = [{"creature": "Some Creature"}]
        self.assertIn("scatter", rules(d))

    def test_at_each_rejects_repeated_point_references(self):
        d = scattered_doc()
        d["cast"][0]["set"]["at_each"] = [
            {"creature": "Some Creature"},
            {"creature": "Some Creature"},
        ]
        self.assertIn("scatter", rules(d))

    def test_at_and_at_each_are_mutually_exclusive(self):
        d = scattered_doc()
        d["cast"][0]["set"]["at"] = {"creature": "Some Creature"}
        self.assertIn("scatter", rules(d))

    def test_at_each_rejects_literal_coordinates(self):
        d = scattered_doc()
        d["cast"][0]["set"]["at_each"][0] = {"x": 1, "y": 2, "z": 3}
        self.assertIn("coordinates", rules(d))

    def test_at_each_rejects_non_spawn_and_non_point_anchors(self):
        d = scattered_doc()
        d["cast"][0]["set"]["at_each"][0] = {"captured": "real-spot"}
        self.assertIn("coordinates", rules(d))

    def test_with_anchor_on_an_at_each_family_is_refused_naming_the_entry(self):
        for key in ("at", "homebind"):
            d = scattered_doc()
            d["cast"].append(
                {"who": "Zork", "set": {"alive": True, "at": {"creature": "X"}}}
            )
            d["cast"][1]["set"][key] = {"with": "family:grug"}
            found = [f for f in errors(d) if f.rule == "scatter"]
            self.assertEqual(len(found), 1, key)
            self.assertIn(f"decree.cast[1].set.{key}", found[0].path)
            self.assertIn("decree.cast[0]", found[0].message)

    def test_with_anchor_on_a_plain_member_is_still_accepted(self):
        d = scattered_doc()
        d["cast"].append(
            {"who": "Zork", "set": {"alive": True, "at": {"with": "Grug"}}}
        )
        self.assertNotIn("scatter", rules(d))

    def test_literal_position_list_is_rejected(self):
        d = doc()
        d["cast"][0]["set"]["at"] = [1.0, 2.0, 3.0]
        self.assertIn("coordinates", rules(d))

    def test_xyz_keys_are_rejected(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"x": 1, "y": 2, "z": 3}
        self.assertIn("coordinates", rules(d))

    def test_coordinate_key_nested_anywhere_in_cast_is_rejected(self):
        d = doc()
        d["cast"][0]["set"]["corpse_at"] = {"captured": "real-spot", "z": 5}
        self.assertIn("coordinates", rules(d))

    def test_coordinate_literal_in_sql_is_rejected(self):
        d = doc()
        d["observe"][1]["sql"] = "SELECT guid FROM characters WHERE position_z < -100"
        self.assertIn("coordinates", rules(d))

    def test_anchor_forms_are_accepted(self):
        for anchor in (
            {"creature": "Some Creature"},
            {"gameobject": "Some Chest"},
            {"areatrigger": 2},
            {"graveyard": 4},
            {"with": "Grug"},
            {"captured": "real-spot"},
        ):
            d = doc()
            d["cast"][0]["set"]["at"] = anchor
            self.assertEqual(errors(d), [], anchor)

    def test_unknown_captured_key_is_rejected(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"captured": "never-captured"}
        self.assertIn("anchor", rules(d))

    def test_pending_captured_key_is_a_warning(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"captured": "later-spot"}
        self.assertEqual(errors(d), [])
        self.assertTrue(
            [f for f in run(d) if f.level == "warning" and f.rule == "anchor"]
        )

    def test_numeric_issue_and_box_are_accepted_for_batch_reporting(self):
        d = doc()
        d["proves"] = 42
        d["box"] = "The family leaves without a defeat"
        self.assertEqual(errors(d), [])

    def test_numeric_issue_requires_box_text(self):
        d = doc()
        d["proves"] = 42
        self.assertIn("schema", rules(d))

    def test_box_cannot_be_attached_to_legacy_issue_list(self):
        d = doc()
        d["box"] = "The family leaves without a defeat"
        self.assertIn("schema", rules(d))

    def test_numeric_issue_must_be_positive(self):
        d = doc()
        d["proves"] = 0
        d["box"] = "The family leaves without a defeat"
        self.assertIn("schema", rules(d))

    def test_two_anchor_keys_are_rejected(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"creature": "A", "captured": "real-spot"}
        self.assertIn("coordinates", rules(d))

    def test_nearest_graveyard_needs_a_corpse(self):
        d = doc()
        d["cast"][0]["set"]["at"] = {"graveyard": "nearest"}
        self.assertIn("schema", rules(d))


class GmAndAuctionTest(unittest.TestCase):
    def test_kind_gm_is_rejected(self):
        d = doc()
        d["act"] = [
            {"at": "0s", "command": {"who": "Grug", "kind": "gm", "text": ".additem 1"}}
        ]
        self.assertIn("gm", rules(d))

    def test_unknown_kind_is_rejected(self):
        d = doc()
        d["act"] = [
            {"at": "0s", "command": {"who": "Grug", "kind": "teleport", "text": "x"}}
        ]
        self.assertIn("schema", rules(d))

    def test_real_kind_is_accepted(self):
        d = doc()
        d["act"] = [
            {"at": "0s", "command": {"who": "Grug", "kind": "job", "text": "quest"}}
        ]
        self.assertEqual(errors(d), [])

    def test_auction_seed_outside_the_auction_family_is_rejected(self):
        d = doc()
        d["arrange"] = [{"auction": {"item": "Copper Bar", "count": 5}}]
        self.assertIn("auction", rules(d))

    def test_auction_seed_inside_the_auction_family_is_allowed(self):
        d = doc()
        d["family"] = "auction-house"
        d["arrange"] = [{"auction": {"item": "Copper Bar", "count": 5}}]
        self.assertNotIn("auction", rules(d))

    def test_auction_bot_config_is_rejected(self):
        d = doc()
        d["world"]["config"] = {"AuctionHouseBot.Seller.Enabled": 1}
        self.assertIn("auction", rules(d))

    def test_a_real_bots_auction_verb_is_not_seeding(self):
        d = doc()
        d["act"] = [
            {"at": "0s", "command": {"who": "Grug", "kind": "auction", "text": "sell"}}
        ]
        self.assertNotIn("auction", rules(d))


class PreconditionAndCeilingTest(unittest.TestCase):
    def test_needs_a_precondition(self):
        d = doc()
        d["observe"] = [d["observe"][1]]
        self.assertIn("preconditions", rules(d))

    def test_needs_a_check(self):
        d = doc()
        d["observe"] = [d["observe"][0]]
        self.assertIn("preconditions", rules(d))

    def test_grant_needs_a_ceiling(self):
        d = doc()
        d["cast"][0]["set"]["money"] = 100
        self.assertIn("ceiling", rules(d))

    def test_grant_with_ceiling_is_fine(self):
        d = doc()
        d["cast"][0]["set"]["money"] = 100
        d["cast"][0]["ceiling"] = "the issue reports 100 copper"
        self.assertEqual(errors(d), [])

    def test_grant_above_a_nothing_granted_ceiling_is_rejected(self):
        d = doc()
        d["cast"][0]["set"]["items"] = [{"name": "Copper Bar", "count": 1}]
        d["cast"][0]["ceiling"] = "nothing granted but position"
        self.assertIn("ceiling", rules(d))

    def test_level_outside_the_stated_range_is_rejected(self):
        d = doc()
        d["cast"][0]["set"]["level"] = 70
        d["cast"][0]["ceiling"] = "levels 56 to 60, own gear"
        self.assertIn("ceiling", rules(d))

    def test_unknown_guild_role_is_rejected(self):
        d = doc()
        d["cast"][0]["who"] = "guild:Cave:wizard"
        self.assertIn("schema", rules(d))

    def test_dead_needs_a_corpse(self):
        d = doc()
        d["cast"][0]["set"]["alive"] = False
        self.assertIn("schema", rules(d))


class BridgeAndActTest(unittest.TestCase):
    def test_wow_overseer_fix_needs_the_bridge(self):
        d = doc()
        d["fix"]["repo"] = "quadseven/wow-overseer"
        self.assertIn("bridge", rules(d))

    def test_roster_step_with_the_bridge_on_is_fine_because_it_is_a_job_command(self):
        d = doc()
        d["world"]["bridge"] = "on"
        self.assertEqual(errors(d), [])

    def test_command_with_the_bridge_on_is_fine(self):
        d = doc()
        d["world"]["bridge"] = "on"
        d["act"] = [
            {"at": "0s", "command": {"who": "cast[0]", "kind": "job", "text": "quest"}}
        ]
        self.assertEqual(errors(d), [])

    def test_when_must_name_an_observation(self):
        d = doc()
        d["act"].append(
            {"when": "no-such-thing", "roster": {"who": "Grug", "job": "rest"}}
        )
        self.assertIn("schema", rules(d))

    def test_when_names_an_observation(self):
        d = doc()
        d["act"].append({"when": "reached", "roster": {"who": "Grug", "job": "rest"}})
        self.assertEqual(errors(d), [])


class ObserveSqlTest(unittest.TestCase):
    def test_unknown_column_is_rejected(self):
        d = doc()
        d["observe"][1]["sql"] = (
            "SELECT t.name FROM acore_world.creature c JOIN acore_world.creature_template t ON t.entry = c.id1"
        )
        self.assertIn("sql", rules(d))

    def test_unknown_table_is_rejected(self):
        d = doc()
        d["observe"][1]["sql"] = "SELECT COUNT(*) FROM overseer_dungeon_event"
        self.assertIn("sql", rules(d))

    def test_write_is_rejected(self):
        d = doc()
        d["observe"][1]["sql"] = "DELETE FROM characters"
        self.assertIn("sql", rules(d))

    def test_stacked_statement_is_rejected(self):
        d = doc()
        d["observe"][1]["sql"] = "SELECT 1; DELETE FROM characters"
        self.assertIn("sql", rules(d))

    def test_constant_only_observations_are_a_lint_error(self):
        d = doc()
        d["observe"][0]["sql"] = "SELECT 1"
        d["observe"][1]["sql"] = "SELECT 1"
        found = [f for f in errors(d) if f.rule == "sql"]
        self.assertEqual(len(found), 2)

    def test_unknown_variable_is_rejected(self):
        d = doc()
        d["observe"][1]["sql"] = "SELECT guid FROM characters WHERE guid = @nobody"
        self.assertIn("sql", rules(d))

    def test_bad_expectation_is_rejected(self):
        d = doc()
        d["observe"][1]["expect"] = {"scalar": "about three"}
        self.assertIn("schema", rules(d))

    def test_log_assertion_is_a_check_only(self):
        d = doc()
        d["observe"].append(
            {
                "name": "log-rule",
                "role": "precondition",
                "log": {"pattern": "x", "expect": {"count": 0}},
            }
        )
        self.assertIn("schema", rules(d))


class LogBoundTest(unittest.TestCase):
    """#2767: a log check takes a bound, so it can require a line too."""

    def with_expect(self, expect):
        d = doc()
        d["observe"].append(
            {
                "name": "log-rule",
                "role": "check",
                "log": {"pattern": "x", "expect": expect},
            }
        )
        return d

    def test_each_bound_is_accepted(self):
        for expect in (
            {"count": 0},
            {"exactly": 0},
            {"exactly": 3},
            {"at_least": 1},
            {"at_most": 0},
            {"at_least": 1, "at_most": 4},
            {"at_least": 2, "at_most": 2},
        ):
            self.assertEqual(errors(self.with_expect(expect)), [], expect)

    def test_a_negative_bound_is_rejected(self):
        for key in ("count", "exactly", "at_least", "at_most"):
            self.assertIn("schema", rules(self.with_expect({key: -1})), key)

    def test_a_missing_bound_is_rejected(self):
        for expect in ({}, None, {"at_least": None}, {"exactly": None}, 3, "1"):
            self.assertIn("schema", rules(self.with_expect(expect)), expect)

    def test_a_bound_that_is_not_a_whole_number_is_rejected(self):
        for value in ("1", 1.5, True, [1]):
            self.assertIn("schema", rules(self.with_expect({"at_least": value})), value)

    def test_an_unknown_bound_is_rejected(self):
        self.assertIn("schema", rules(self.with_expect({"about": 1})))
        self.assertIn("schema", rules(self.with_expect({"at_least": 1, "about": 1})))

    def test_an_exact_bound_stands_alone(self):
        for expect in (
            {"count": 1, "exactly": 1},
            {"count": 1, "at_least": 1},
            {"exactly": 1, "at_most": 2},
        ):
            self.assertIn("schema", rules(self.with_expect(expect)), expect)

    def test_a_range_that_can_never_hold_is_rejected(self):
        self.assertIn("schema", rules(self.with_expect({"at_least": 3, "at_most": 2})))

    def test_at_least_zero_is_rejected_because_it_always_holds(self):
        self.assertIn("schema", rules(self.with_expect({"at_least": 0})))


class TodoTest(unittest.TestCase):
    def test_todo_placeholders_warn_and_do_not_fail(self):
        d = doc()
        d["proves"][0]["issue"] = "TODO"
        d["fix"]["commit"] = "TODO"
        self.assertEqual(errors(d), [])
        self.assertEqual({f.rule for f in run(d)}, {"todo"})


class ShippedDecreesTest(unittest.TestCase):
    def test_there_are_three_examples(self):
        self.assertGreaterEqual(len(DECREES), 3)

    def test_every_shipped_decree_lints_without_errors(self):
        anchors = anchors_mod.Anchors.load()
        for path in DECREES:
            findings = lint.lint_path(path, anchors, SCHEMA)
            self.assertEqual([f for f in findings if f.level == "error"], [], path.name)

    def test_anchors_file_is_valid(self):
        text = (ROOT / "data" / "decrees" / "anchors.yaml").read_text(encoding="utf-8")
        self.assertEqual(anchors_mod.validate(loads(text)), [])

    def test_guzzler_kills_plugger_in_act_not_in_arrange(self):
        text = (
            ROOT / "data" / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"
        ).read_text(encoding="utf-8")
        d = loads(text)
        self.assertNotIn("creature", [k for e in d.get("arrange", []) for k in e])
        self.assertEqual(d["act"][1]["when"], "plugger-was-dead")

    def test_guzzler_uses_the_real_column_names(self):
        text = (
            ROOT / "data" / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("t.entry = c.id\n", text)
        self.assertNotIn("id1", text)
        self.assertNotIn("overseer_dungeon_event", text)

    def test_no_literal_coordinates_in_any_decree(self):
        for path in DECREES:
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?m)^\s*(x|y|z):")

    def test_no_em_dash_in_decrees_or_package(self):
        for path in [*DECREES, *(ROOT / "ephemeral").glob("*.py")]:
            self.assertNotIn(chr(0x2014), path.read_text(encoding="utf-8"), path.name)


class CliTest(unittest.TestCase):
    def test_exit_codes(self):
        from ephemeral.__main__ import main

        good = str(
            ROOT / "data" / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["lint", good]), 0)
            self.assertEqual(
                main(["lint", "--strict", good]), 1
            )  # TODO warnings fail strictly


if __name__ == "__main__":
    unittest.main()
