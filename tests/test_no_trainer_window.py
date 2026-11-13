"""A no-trainer refusal holds while the member stays on its map (#1453).

Measured on the dev realm 2026-11-03 to 2026-11-07: Brug, on the death
knight start map (609), was refused "no trainer on this map will teach this
character that skill" once a day for each of four skills, because the
refused row aged out of the job's one-day recent read and the walk was
planned again while the map had not changed.
"""

import json
import pathlib
import unittest
from unittest import mock

import guildjobs
from test_guildjobs import member
from test_guildsocial_bridge import bridge

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()

DAY = 24 * 60


def row(age, map_id=609, reason=guildjobs.NO_TRAINER_ON_MAP_REFUSAL, name="Brug"):
    return {
        "id": 1,
        "target_name": name,
        "command": "walk-to-trainer skill:762 learn:33388 max:20000",
        "source": "guildjobs:riding:%s" % name,
        "status": "error",
        "age": age,
        "target_arg": str(map_id),
        "result": json.dumps(
            {"outcome": "refused", "reason": reason, "retryable": False},
            separators=(",", ":"),
        ),
    }


def brug(map_id=609):
    order = guildjobs.purse.order("Brug", 60, 80000, 37600, 9, 0)
    return member("Brug", level=60, money=80000, map_id=map_id, purse=order)


class ARefusalOlderThanTheRecentRead(unittest.TestCase):
    def test_still_holds_the_riding_walk_on_the_same_map(self):
        kept = guildjobs.still_stranded([row(DAY + 30)], {"Brug": 609})
        step, note = guildjobs.riding_step(brug(), kept)
        self.assertIsNone(step)
        self.assertEqual(
            "Brug waits on the map change before walking to a riding trainer", note
        )

    def test_without_it_the_walk_is_planned_again(self):
        """The shape of the live bug: an empty recent read plans the walk."""
        step, _note = guildjobs.riding_step(brug(), ())
        self.assertEqual(guildjobs.RIDING_ACTION, step.action)

    def test_lets_go_once_the_member_leaves_the_map(self):
        kept = guildjobs.still_stranded([row(DAY + 30)], {"Brug": 1})
        self.assertEqual((), kept)
        step, _note = guildjobs.riding_step(brug(map_id=1), kept)
        self.assertEqual(guildjobs.RIDING_ACTION, step.action)

    def test_any_other_refusal_is_not_kept(self):
        kept = guildjobs.still_stranded(
            [row(DAY + 30, reason="died on the way")], {"Brug": 609}
        )
        self.assertEqual((), kept)

    def test_a_member_not_read_this_pass_is_not_held(self):
        self.assertEqual((), guildjobs.still_stranded([row(DAY + 30)], {}))


class TheBridgeReadsThem(unittest.TestCase):
    def test_a_member_without_a_lineup_role_reaches_class_quest_planning(self):
        rows = [
            {
                "name": "Unplaced",
                "guid": 17,
                "guild_name": "Cave",
                "level": 55,
                "class_id": 1,
                "race": 2,
                "online": 1,
                "map_id": 1,
                "pos_x": 10.0,
                "pos_y": 20.0,
            }
        ]
        with mock.patch.object(
            bridge.guildwork, "members_from_rows", return_value=([], {})
        ):
            facts = bridge._job_facts_from_rows(rows, [], set(), [], [], [], [], [])
        self.assertEqual(facts["members"], [])
        self.assertEqual(len(facts["class_candidates"]), 1)
        self.assertEqual(facts["class_candidates"][0].role, guildjobs.UNASSIGNED)

    def test_the_read_reaches_past_the_recent_window(self):
        sql = bridge._JOB_NO_TRAINER_SQL
        self.assertIn("created_at <= NOW() - INTERVAL 1 DAY", sql)
        self.assertIn("command LIKE 'walk-to-trainer%%'", sql)
        self.assertGreater(guildjobs.NO_TRAINER_READ_DAYS, 1)
        # One prefix per step keeps the read on the source index.
        self.assertIn("(source LIKE %s OR source LIKE %s)", sql)
        self.assertIn('guildjobs.SOURCE + ":train:%"', BRIDGE)

    def test_the_facts_carry_a_kept_refusal_beside_the_recent_rows(self):
        stranded = brug()
        with mock.patch.object(
            bridge,
            "_guild_members_and_crafters",
            return_value=([stranded], {}),
        ):
            facts = bridge._job_facts_from_rows(
                [],
                ["Brug"],
                {"Brug"},
                [],
                [],
                [],
                [],
                [],
                stranded_rows=[row(DAY + 30), row(DAY + 30, map_id=1)],
            )
        kept = [r for r in facts["recent"] if r.name == "Brug"]
        self.assertEqual(1, len(kept))
        self.assertEqual(609, kept[0].map_id)
        step, _note = guildjobs.riding_step(stranded, facts["recent"])
        self.assertIsNone(step)


if __name__ == "__main__":
    unittest.main()
