"""The planner rests a family whose last campaign entries formed no run (#1261).

Measured on the dev realm over 48 hours: four level 60 families spent about
half their head time on dungeon jobs and opened no run at all. The stall bar is
per door, so each entry the stall breaker gave up barred only its own door and
the planner queued the next one at once: one family went through nine doors
back to back. These tests pin the family-wide rest. Every test runs on fake
rows with placeholder names; none touches a database.
"""

import pathlib
import unittest

import campaignplan

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

EASTERN_KINGDOMS = 0
FAMILY = (("A1", 1), ("A2", 1), ("A3", 1), ("A4", 7), ("A5", 3))
HOUR = 3600.0


def facts(unformed=None):
    rows = tuple(
        {
            "name": n,
            "level": 60,
            "race": race,
            "map_id": EASTERN_KINGDOMS,
            "lead": int(i == 0),
        }
        for i, (n, race) in enumerate(FAMILY)
    )
    return campaignplan.Facts(
        family="A1", level_rows=rows, done={}, failed={}, unformed=unformed
    )


class TheRest(unittest.TestCase):
    def test_a_capped_family_is_offered_doors_with_no_history(self):
        self.assertTrue(campaignplan.options(facts()))

    def test_two_entries_with_no_run_formed_plan_nothing(self):
        f = facts(unformed=((False, 0.5 * HOUR), (False, 3 * HOUR)))
        self.assertEqual(campaignplan.options(f), [])
        self.assertIsNone(campaignplan.heuristic(campaignplan.options(f)))
        line = campaignplan.nothing_line(f)
        self.assertIn("no run formed", line)
        self.assertIn("330 more minutes", line)

    def test_a_run_formed_in_either_entry_keeps_the_planner_going(self):
        for entries in (
            ((True, 0.5 * HOUR), (False, 3 * HOUR)),
            ((False, 0.5 * HOUR), (True, 3 * HOUR)),
        ):
            self.assertTrue(campaignplan.options(facts(unformed=entries)), entries)

    def test_one_unformed_entry_is_not_yet_a_rest(self):
        self.assertTrue(campaignplan.options(facts(unformed=((False, 60.0),))))

    def test_the_rest_ends_and_one_door_is_tried_again(self):
        f = facts(unformed=((False, 6 * HOUR), (False, 9 * HOUR)))
        self.assertEqual(campaignplan.formation_rest(f.unformed), "")
        self.assertTrue(campaignplan.options(f))

    def test_an_unread_record_rests_nothing(self):
        self.assertEqual(campaignplan.formation_rest(None), "")


class TheRead(unittest.TestCase):
    def test_rows_become_formed_and_age_newest_first(self):
        got = campaignplan.unformed(
            [{"formed": 0, "age": 120}, {"formed": 1, "age": 7200}]
        )
        self.assertEqual(got, ((False, 120.0), (True, 7200.0)))

    def test_the_statement_reads_started_ended_entries_against_the_run_ledger(self):
        sql = campaignplan.UNFORMED_SQL
        for part in (
            "overseer_dungeon_queue",
            "overseer_dungeon_run",
            "started_at IS NOT NULL",
            "ORDER BY q.finished_at DESC",
        ):
            self.assertIn(part, sql)
        names = ["A1", "A2"]
        args = campaignplan.unformed_args(names, "A1")
        self.assertEqual(
            sql.format(holes=campaignplan.holes(len(names))).count("%s"), len(args)
        )

    def test_the_bridge_hands_the_read_to_the_planner(self):
        self.assertIn("campaignplan.UNFORMED_SQL.format(holes=marks)", BRIDGE)
        self.assertIn("unformed=_read_or_none(campaignplan.unformed, ended)", BRIDGE)


if __name__ == "__main__":
    unittest.main()
