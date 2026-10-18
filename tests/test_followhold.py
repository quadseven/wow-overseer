"""followhold: when a guild member's own walk is held because it follows (#995)."""

import unittest

import followhold as fh

FOLLOWS = fh.Group(guid=7, leader_guid=3, leader="Tanky", age=4.0)
LEADS = fh.Group(guid=3, leader_guid=3, leader="Tanky", age=4.0)
ALONE = fh.Group(guid=7, leader_guid=0, age=4.0)
WALK = "walk-to-vendor item:2901"


class TheSnapshot(unittest.TestCase):
    def test_a_member_somebody_else_leads_follows(self):
        self.assertTrue(FOLLOWS.follows)
        self.assertFalse(LEADS.follows)
        self.assertFalse(ALONE.follows)

    def test_a_row_reads_into_a_group_and_no_row_into_none(self):
        row = {"guid": 7, "group_leader": 3, "leader_name": "Tanky", "age": 4}
        self.assertEqual(fh.group_from_row(row), FOLLOWS)
        self.assertIsNone(fh.group_from_row(None))
        self.assertIsNone(fh.group_from_row({"guid": "x", "group_leader": 3}))

    def test_only_the_four_walks_are_gated(self):
        for command in (
            "walk-to-mailbox max:600",
            WALK,
            "walk-to-trainer skill:197",
            "walk-to-spawn creature:10076 near:3",
        ):
            self.assertTrue(fh.is_walk(command), command)
        for command in ("2901 1", "send money:500", "job quest", "walk-to-the-shop"):
            self.assertFalse(fh.is_walk(command), command)


class AHold(unittest.TestCase):
    def test_a_follower_s_walk_is_held_and_says_so_naming_the_leader(self):
        why = fh.Holds().held("Blingz", WALK, FOLLOWS, 0.0)
        self.assertIn("Blingz is grouped as a follower of Tanky", why)
        self.assertIn("walk-to-vendor is held until it is ungrouped", why)

    def test_a_leader_without_a_name_is_named_by_its_guid(self):
        why = fh.Holds().held("Blingz", WALK, fh.Group(guid=7, leader_guid=3), 0.0)
        self.assertIn("follower of guid 3", why)

    def test_the_leader_the_ungrouped_and_a_non_walk_are_written(self):
        holds = fh.Holds()
        self.assertEqual(holds.held("Tanky", WALK, LEADS, 0.0), "")
        self.assertEqual(holds.held("Blingz", WALK, ALONE, 0.0), "")
        self.assertEqual(holds.held("Blingz", "2901 1", FOLLOWS, 0.0), "")


class ARefusal(unittest.TestCase):
    def refused(self, at=100.0):
        holds = fh.Holds()
        holds.note_answer("Blingz", fh.REFUSAL, at)
        return holds

    def test_a_refusal_holds_a_member_with_no_fresh_snapshot(self):
        why = self.refused().held("Blingz", WALK, None, 160.0)
        self.assertIn("refused Blingz's last walk 60 seconds ago", why)
        self.assertIn("held until it is ungrouped", why)

    def test_a_snapshot_older_than_the_refusal_does_not_lift_it(self):
        stale = fh.Group(guid=7, leader_guid=0, age=90.0)
        self.assertNotEqual(self.refused().held("Blingz", WALK, stale, 160.0), "")

    def test_a_snapshot_newer_than_the_refusal_lifts_it(self):
        holds = self.refused()
        self.assertEqual(holds.held("Blingz", WALK, ALONE, 160.0), "")
        self.assertEqual(holds.held("Blingz", WALK, None, 161.0), "")

    def test_the_hold_runs_out(self):
        later = 100.0 + fh.REFUSAL_HOLD_SECONDS
        self.assertEqual(self.refused().held("Blingz", WALK, None, later), "")

    def test_another_answer_is_not_a_refusal(self):
        holds = fh.Holds()
        holds.note_answer("Blingz", "character is in combat", 100.0)
        holds.note_answer("", fh.REFUSAL, 100.0)
        self.assertEqual(holds.held("Blingz", WALK, None, 160.0), "")


if __name__ == "__main__":
    unittest.main()
