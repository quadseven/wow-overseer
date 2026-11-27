"""A member under LEVELLING_FIRST_LEVEL plays no PvP for an upgrade and is never
drafted as a cohort filler: its experience comes from dungeons and quests, and a
battleground queue that does not pop holds it out of both."""

import json
import unittest

import guildjobs
import pvpgear
from test_pvp_cohort import filler, run, wanter


def queued_filler(name="Low", age=5):
    aim = pvpgear._filler(filler(name, level=39), pvpgear.WSG)
    command = pvpgear.queue_command(aim)
    result = json.dumps(
        {
            "outcome": "queued",
            "reason": "",
            "retry": "",
            "character": name,
            "level": 39,
            "battleground": aim.battleground.key,
            "bg_type": 2,
            "bracket": 2,
            "as_group": False,
            "in_battleground": False,
            "queued_for_this": True,
            "deserter": False,
            "honor": 0,
            "request": command,
        },
        separators=(",", ":"),
    )
    return guildjobs.recent_from_rows(
        [
            {
                "id": 1,
                "target_name": name,
                "command": command,
                "source": guildjobs.source_for(pvpgear.ACTION, name),
                "status": "delivered",
                "age": age,
                "result": result,
            }
        ]
    )[0]


class LevellingFirst(unittest.TestCase):
    def test_the_floor_is_the_level_cap(self):
        self.assertEqual(pvpgear.LEVELLING_FIRST_LEVEL, 60)

    def test_a_member_under_the_floor_has_no_pvp_aim(self):
        aims = pvpgear.plan_aims([wanter("Low", level=59)])
        self.assertEqual(aims, {})

    def test_a_member_at_the_floor_still_wants_an_upgrade(self):
        aims = pvpgear.plan_aims([wanter("Even", level=60)])
        self.assertIn("Even", aims)

    def test_a_member_under_the_floor_is_not_drafted_as_a_filler(self):
        seekers = [wanter("W%02d" % i, level=60) for i in range(3)]
        seekers += [filler("F%02d" % i, level=55) for i in range(4)]
        _aims, _moves, cohorts = run(seekers, minimum=5)
        for c in cohorts:
            self.assertEqual(c.fillers, ())

    def test_a_filler_at_the_floor_is_still_drafted(self):
        seekers = [wanter("W%02d" % i, level=60) for i in range(3)]
        seekers += [filler("F%02d" % i, level=60) for i in range(4)]
        _aims, _moves, cohorts = run(seekers, minimum=5)
        self.assertEqual(sum(len(c.fillers) for c in cohorts), 2)

    def test_a_member_already_inside_a_battleground_below_the_floor_is_held(self):
        aims, moves, _cohorts = run(
            [filler("Low", level=39)], maps={"Low": pvpgear.WSG.map_id}
        )
        self.assertIn("Low", aims)
        self.assertEqual(moves["Low"].kind, pvpgear.INSIDE)
        self.assertTrue(moves["Low"].holds)

    def test_a_member_waiting_in_a_queue_below_the_floor_is_held(self):
        aims, moves, _cohorts = run(
            [filler("Low", level=39)], recent=(queued_filler(),)
        )
        self.assertIn("Low", aims)
        self.assertEqual(moves["Low"].kind, pvpgear.WAITING)
        member = guildjobs.Member(
            name="Low", guild="Cave", role=guildjobs.RAIDER, level=39,
            online=True, map_id=0, x=0.0, y=0.0, eligible=True,
        )  # fmt: skip
        step, _doing, held = guildjobs._pvp_first(
            member, (aims["Low"], moves["Low"]), (), 0
        )
        self.assertIsNone(step)
        self.assertTrue(held)

    def test_a_queued_member_stays_held_when_its_map_id_is_malformed(self):
        aims, moves, _cohorts = run(
            [filler("Low", level=39)],
            recent=(queued_filler(),),
            maps={"Low": "unread"},
        )
        self.assertIn("Low", aims)
        self.assertEqual(moves["Low"].kind, pvpgear.WAITING)

    def test_a_queue_that_ended_does_not_requeue_a_member_below_the_floor(self):
        aims, moves, cohorts = run(
            [filler("Low", level=39)],
            recent=(queued_filler(age=pvpgear.WAITING_MINUTES),),
        )
        self.assertNotIn("Low", aims)
        self.assertNotIn("Low", moves)
        self.assertTrue(all("Low" not in c.fillers for c in cohorts))


if __name__ == "__main__":
    unittest.main()
