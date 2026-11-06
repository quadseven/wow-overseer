"""A member in a death loop with nothing to eat or drink buys food first.

WHY THIS EXISTS. Read on the dev realm on 2026-11-06 at 00:15 UTC: the stuck
reader listed 34 members in death loops. 31 of the 34 carried no food and no
drink (the other three were mages with conjured food), and most of their
recent deaths were to creatures at or under their own level, so the zone was
not too hard for them: they never rested. mod-playerbots rests a bot only on
food and drink in its bags (restsupply.py), so a member with none rises from
its corpse at half health and pulls again.

The death loop's way out (guildjobs.death_loop_first) was a hearth home, then
a level walk, and once the member stood in town, out of the loop's zone, the
pass planned it as usual: its class quest, a stood-still hearth or a level
walk came ahead of the food errand, and the food vendor reads (12 a pass,
rotated over about 120 hungry members) seldom fell on it while it stood
beside a vendor. So it walked back out as hungry as it came.

NOW: while its loop is listed, a member short of food or drink with a vendor
in reach takes the supply step before anything else, in the loop's zone or
out of it, and the bridge reads the vendors around such members ahead of the
rotation (guildjobs.supply_reads).
"""

import unittest

import deathloop
import guildjobs
import guildroute
import restsupply
import standstill
from test_guild_rest_supply import BATES, member

NAME = "Femur"
LOOP_ZONE = 130


def loop_of(zone=LOOP_ZONE):
    return deathloop.Loop(
        name=NAME,
        zone=zone,
        map_id=0,
        deaths=6,
        killer="Giant Grizzled Bear",
        level=14,
        first_age=3000,
        last_age=120,
    )


def plan(m, loops=None, still=None, supply=None):
    return guildjobs.plan(
        [m],
        masters={"Bonkers": "Zug"},
        cap=guildroute.FAR_WALK_YARDS,
        supply={NAME: BATES} if supply is None else supply,
        still=still or {},
        loops=loops or {},
    )


def actions(result):
    return [s.action for s in result.steps if s.holder == NAME]


class FoodBeforeTheWayOut(unittest.TestCase):
    def test_in_the_loop_zone_with_a_vendor_in_reach_it_buys_food_first(self):
        result = plan(member(), loops={NAME: loop_of()})
        self.assertEqual(actions(result), [restsupply.ACTION])

    def test_in_the_loop_zone_with_no_vendor_in_reach_it_hearths(self):
        result = plan(member(), loops={NAME: loop_of()}, supply={})
        self.assertEqual(actions(result), ["hearth"])

    def test_in_town_after_the_hearth_food_comes_before_a_stood_still_hearth(self):
        # Out of the loop's zone (the hearth put it in town), stood still long
        # enough for the stood-still hearth: the food comes first, or it
        # hearths again and walks back out hungry.
        town = member(zone_id=85)
        result = plan(
            town,
            loops={NAME: loop_of()},
            still={NAME: standstill.STILL_MINUTES + 5},
        )
        self.assertEqual(actions(result), [restsupply.ACTION])

    def test_without_a_loop_the_stood_still_hearth_keeps_its_place(self):
        town = member(zone_id=85)
        result = plan(town, still={NAME: standstill.STILL_MINUTES + 5})
        self.assertEqual(actions(result), ["hearth"])

    def test_a_looper_with_food_and_drink_takes_the_way_out(self):
        fed = member(food=restsupply.STACK, drink=restsupply.STACK)
        result = plan(fed, loops={NAME: loop_of()})
        self.assertEqual(actions(result), ["hearth"])


class LoopersAreReadFirst(unittest.TestCase):
    def test_loopers_take_the_reads_ahead_of_the_rotation(self):
        wanted = ["a%02d" % i for i in range(30)] + ["Looper"]
        chosen, _offset = guildjobs.supply_reads(wanted, {"Looper"}, 0, 12)
        self.assertEqual(len(chosen), 12)
        self.assertEqual(chosen[0], "Looper")

    def test_the_rest_rotate_as_before(self):
        wanted = ["a%02d" % i for i in range(30)]
        self.assertEqual(
            guildjobs.supply_reads(wanted, set(), 5, 12),
            guildjobs.rotate_reads(wanted, 5, 12),
        )

    def test_more_loopers_than_reads_rotate_among_themselves(self):
        loopers = ["L%02d" % i for i in range(20)]
        first, offset = guildjobs.supply_reads(loopers, set(loopers), 0, 12)
        second, _ = guildjobs.supply_reads(loopers, set(loopers), offset, 12)
        self.assertEqual(len(first), 12)
        self.assertTrue(set(loopers) - set(first) <= set(second))


if __name__ == "__main__":
    unittest.main()
