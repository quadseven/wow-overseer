"""Per-member production: the record, the reason, and GET /api/v2/production.

The bridge is not imported here (CI has no discord package): the recorder in
bridge.py is checked as source, and the pure rules and the handler are driven
directly.
"""

import json
import pathlib
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import production
    import realmread
    from apiv2 import production as v2production
    from apiv2._context import Context

NOW = 1_800_000_000


class TheSkillRecord(unittest.TestCase):
    def test_the_first_sight_is_a_baseline_with_no_times(self):
        record = production.observe(None, {"mining": 16}, NOW)
        self.assertEqual(record["skills"], {"mining": 16})
        self.assertIsNone(record["skill_at"])
        self.assertIsNone(record["gather_at"])

    def test_a_rise_moves_the_skill_time_and_an_unchanged_value_does_not(self):
        first = production.observe(None, {"tailoring": 150}, NOW)
        held = production.observe(first, {"tailoring": 150}, NOW + 60)
        self.assertIsNone(held["skill_at"])
        rose = production.observe(held, {"tailoring": 151}, NOW + 120)
        self.assertEqual(rose["skill_at"], NOW + 120)
        again = production.observe(rose, {"tailoring": 151}, NOW + 180)
        self.assertEqual(again["skill_at"], NOW + 120)

    def test_only_a_gathering_skill_moves_the_gather_time(self):
        first = production.observe(None, {"tailoring": 150, "mining": 10}, NOW)
        tailored = production.observe(first, {"tailoring": 151, "mining": 10}, NOW + 60)
        self.assertEqual(tailored["skill_at"], NOW + 60)
        self.assertIsNone(tailored["gather_at"])
        mined = production.observe(tailored, {"tailoring": 151, "mining": 11}, NOW + 90)
        self.assertEqual(mined["gather_at"], NOW + 90)

    def test_a_fall_moves_nothing(self):
        first = production.observe(None, {"mining": 10}, NOW)
        self.assertIsNone(production.observe(first, {"mining": 5}, NOW + 5)["skill_at"])

    def test_the_record_survives_a_json_round_trip_unchanged(self):
        record = production.observe(
            production.observe(None, {"mining": 1}, NOW), {"mining": 2}, NOW + 1
        )
        self.assertEqual(json.loads(json.dumps(record)), record)


def why(**over):
    facts = dict(
        job="craft",
        enabled=True,
        craft_spell=3275,
        skills={"leatherworking": (57, 150)},
        craft_at=NOW - 3600,
        request=None,
        deferred=None,
        now=NOW,
    )
    facts.update(over)
    return production.stuck_because(**facts)


class TheStuckReason(unittest.TestCase):
    def test_a_member_that_crafted_lately_has_no_reason(self):
        self.assertEqual(why(), "")

    def test_a_job_that_is_not_a_production_job_is_never_judged(self):
        self.assertEqual(why(job="quest", craft_at=None), "")
        self.assertIsNone(production.producing("quest", None, None, NOW))

    def test_a_short_reagent_after_the_last_craft_is_the_reason(self):
        line = why(
            craft_at=NOW - 7 * 3600,
            request={
                "at": NOW - 600,
                "subject": "Linen Bandage",
                "detail": "short 1x Linen Cloth (needs 1, has 0)",
            },
        )
        self.assertIn("short of material", line)
        self.assertIn("Linen Cloth", line)

    def test_a_reason_older_than_the_last_craft_is_not_a_reason(self):
        request = {"at": NOW - 7200, "subject": "x", "detail": "short"}
        self.assertEqual(why(request=request), "")

    def test_a_deferred_craft_says_what_it_waits_for(self):
        line = why(
            deferred={
                "at": NOW - 60,
                "subject": "Smelt Copper",
                "detail": "waiting for a town stop with a Forge",
            }
        )
        self.assertIn("its craft waits", line)
        self.assertIn("Forge", line)

    def test_no_craft_order_is_said_plainly(self):
        self.assertIn("no craft order", why(craft_spell=0))

    def test_a_farm_job_without_the_gathering_skill_says_so(self):
        line = why(
            job="farm:mining",
            skills={"leatherworking": (1, 75), "skinning": (1, 75)},
            craft_at=None,
        )
        self.assertIn("holds no Mining", line)

    def test_a_stale_craft_with_no_recorded_reason_is_still_reported(self):
        self.assertIn("no craft for 10 hours", why(craft_at=NOW - 10 * 3600))
        self.assertIn("no craft recorded", why(craft_at=None))

    def test_a_disabled_member_says_so(self):
        self.assertIn("disabled", why(enabled=False))


MEMBERS = [
    {
        "name": "Bork",
        "family": "Grug",
        "job": "craft",
        "craft_spell": 3275,
        "enabled": 1,
    },
    {
        "name": "Zork",
        "family": "Zug",
        "job": "farm:mining",
        "craft_spell": 2881,
        "enabled": 1,
    },
]
SKILL_ROWS = [
    {"name": "Bork", "skill": 165, "value": 57, "max": 150},
    {"name": "Bork", "skill": 164, "value": 2, "max": 75},
    {"name": "Zork", "skill": 165, "value": 1, "max": 75},
    {"name": "Zork", "skill": 393, "value": 1, "max": 75},
    {"name": "Zork", "skill": 100, "value": 300, "max": 300},
]
EVENT_ROWS = [
    {
        "name": "Bork",
        "kind": "craft",
        "subject_name": "Cloak",
        "detail": "",
        "at": NOW - 9 * 3600,
    },
    {
        "name": "Bork",
        "kind": "material-request",
        "subject_name": "Linen Bandage",
        "detail": "short 1x Linen Cloth (needs 1, has 0)",
        "at": NOW - 100,
    },
]


def make_ctx(memo_rows=()):
    answers = {
        v2production.ROSTER_SQL: MEMBERS,
        v2production.SKILLS_SQL: SKILL_ROWS,
        v2production.EVENTS_SQL: EVENT_ROWS,
        v2production.MEMO_SQL: list(memo_rows),
        v2production.CLOCK_SQL: [{"now_at": NOW}],
    }
    families = types.SimpleNamespace(names=lambda: ["Bork", "Zork"])
    return Context(read=realmread.Memory(answers), server=None, families=families)


class TheEndpoint(unittest.TestCase):
    def rows(self, memo_rows=()):
        status, payload = v2production.production_report({}, make_ctx(memo_rows))
        self.assertEqual(status, 200)
        return {m["name"]: m for m in payload["members"]}

    def test_it_is_routed_under_v2(self):
        self.assertIn("/api/v2/production", v2production.ROUTES)

    def test_each_member_carries_every_field_the_owner_asked_for(self):
        bork = self.rows()["Bork"]
        for key in (
            "job",
            "professions",
            "last_craft_at",
            "last_skill_gain_at",
            "last_gather_at",
            "stuck_because",
            "producing",
            "measured",
        ):
            self.assertIn(key, bork)
        self.assertEqual(bork["job"], "craft")
        self.assertEqual(
            [(p["name"], p["value"]) for p in bork["professions"]],
            [("blacksmithing", 2), ("leatherworking", 57)],
        )
        self.assertEqual(bork["last_craft_at"], NOW - 9 * 3600)

    def test_a_member_never_watched_reads_unmeasured_not_zero(self):
        bork = self.rows()["Bork"]
        self.assertFalse(bork["measured"])
        self.assertIsNone(bork["last_skill_gain_at"])
        self.assertIsNone(bork["last_gather_at"])

    def test_a_watched_member_reports_the_recorded_times(self):
        memo = {
            "skills": {"leatherworking": 57},
            "skill_at": NOW - 500,
            "gather_at": None,
        }
        bork = self.rows([{"name": "Bork", "value": json.dumps(memo)}])["Bork"]
        self.assertTrue(bork["measured"])
        self.assertEqual(bork["last_skill_gain_at"], NOW - 500)

    def test_the_reason_is_built_from_the_passes_own_records(self):
        rows = self.rows()
        self.assertFalse(rows["Bork"]["producing"])
        self.assertIn("Linen Cloth", rows["Bork"]["stuck_because"])
        self.assertIn("holds no Mining", rows["Zork"]["stuck_because"])

    def test_a_gap_in_a_table_reads_as_no_rows_not_a_failure(self):
        ctx = make_ctx()
        ctx.read.answers[v2production.EVENTS_SQL] = realmread.MISSING_TABLE
        status, payload = v2production.production_report({}, ctx)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["members"]), 2)


class TheBridgeRecordsIt(unittest.TestCase):
    """The recorder runs in the profession loop, and only writes a change."""

    SRC = (HERE / "bridge.py").read_text(encoding="utf-8")

    def test_the_profession_loop_calls_the_recorder_with_the_skills_it_read(self):
        body = self.SRC[self.SRC.index("async def _prof_loop_for(") :]
        body = body[: body.index("async def _prof_loop_facts(")]
        self.assertIn("_record_production, names, skills", body)

    def test_the_recorder_writes_only_a_changed_record(self):
        body = self.SRC[self.SRC.index("def _record_production(") :]
        body = body[: body.index("# --- the profession loop")]
        self.assertIn("if after != before:", body)
        self.assertIn("production.observe(", body)
        self.assertIn("production.MEMO_KIND", body)

    def test_the_image_ships_the_module(self):
        docker = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("production.py", docker)


if __name__ == "__main__":
    unittest.main()
