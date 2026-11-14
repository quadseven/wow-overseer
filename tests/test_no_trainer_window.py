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
from test_classquest import book as class_quest_book
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
        # Keep assigned members in the real lineup so the surplus seat below
        # follows the same roster path as production instead of a mock.
        rows = [
            {
                "name": "Filler%02d" % index,
                "guid": index + 1,
                "guild_name": "Research Guild",
                "level": 10 if index >= 40 else 55,
                "class_id": 1,
                "race": 2,
                "online": 1,
                "map_id": 1,
                "pos_x": 10.0,
                "pos_y": 20.0,
            }
            for index in range(50)
        ]
        rows.extend(
            {
                "name": "Summoner%02d" % index,
                "guid": 100 + index,
                "guild_name": "Research Guild",
                "level": 55,
                "class_id": 9,
                "race": 2,
                "online": 1,
                "map_id": 1,
                "pos_x": 10.0,
                "pos_y": 20.0,
            }
            for index in range(21)
        )
        rows.append(
            {
                "name": "Unplaced",
                "guid": 999,
                "guild_name": "Research Guild",
                "level": 55,
                "class_id": 1,
                "race": 2,
                "online": 1,
                "map_id": 1,
                "pos_x": 186.0,
                "pos_y": -3597.0,
            }
        )
        facts = bridge._job_facts_from_rows(
            rows=rows,
            family_names=[],
            eligible=set(),
            skill_rows=[],
            spell_rows=[],
            item_rows=[],
            recent_rows=[],
            pending_rows=[],
            done_rows=[{"guid": 999, "quest": 1505}],
        )
        assigned = {member.name for member in facts["members"]}
        candidates = {member.name: member for member in facts["class_candidates"]}
        self.assertIn("Filler00", assigned)
        self.assertNotIn("Unplaced", assigned)
        self.assertEqual(candidates["Unplaced"].role, guildjobs.UNASSIGNED)
        plan = guildjobs.plan(
            [],
            classes=class_quest_book(),
            class_candidates=facts["class_candidates"],
            masters={"Research Guild": "Unplaced"},
        )
        self.assertIn("Unplaced", {step.holder for step in plan.steps})

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
