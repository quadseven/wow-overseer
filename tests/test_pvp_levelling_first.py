"""A member under LEVELLING_FIRST_LEVEL plays no PvP for an upgrade and is never
drafted as a cohort filler: its experience comes from dungeons and quests, and a
battleground queue that does not pop holds it out of both."""

import unittest

import pvpgear
from test_pvp_cohort import ALLIANCE, filler, run, wanter


class LevellingFirst(unittest.TestCase):
    def test_the_floor_is_fifty(self):
        self.assertEqual(pvpgear.LEVELLING_FIRST_LEVEL, 50)

    def test_a_member_under_the_floor_has_no_pvp_aim(self):
        aims = pvpgear.plan_aims([wanter("Low", level=49)])
        self.assertEqual(aims, {})

    def test_a_member_at_the_floor_still_wants_an_upgrade(self):
        aims = pvpgear.plan_aims([wanter("Even", level=50)])
        self.assertIn("Even", aims)

    def test_a_member_under_the_floor_is_not_drafted_as_a_filler(self):
        seekers = [wanter("W%02d" % i, level=50) for i in range(3)]
        seekers += [filler("F%02d" % i, level=45) for i in range(4)]
        _aims, _moves, cohorts = run(seekers, minimum=5)
        for c in cohorts:
            self.assertEqual(c.fillers, ())

    def test_a_filler_at_the_floor_is_still_drafted(self):
        seekers = [wanter("W%02d" % i, level=50) for i in range(3)]
        seekers += [filler("F%02d" % i, level=50) for i in range(4)]
        _aims, _moves, cohorts = run(seekers, minimum=5)
        self.assertEqual(sum(len(c.fillers) for c in cohorts), 2)

    def test_a_member_already_inside_a_battleground_below_the_floor_is_held(self):
        aim = pvpgear.Aim(
            "In", "Cave", 45, 1, "x", 100, 0, pvpgear.WSG, faction=ALLIANCE
        )
        move = pvpgear.next_move(aim, pvpgear.WSG.map_id, False, ())
        self.assertTrue(move.holds)


if __name__ == "__main__":
    unittest.main()
