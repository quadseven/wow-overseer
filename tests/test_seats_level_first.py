"""A raid seat below the level cap levels first, and errands wait unless they block play.

WHY THIS EXISTS. The guild job pass spent a day of its rows on supply 1388,
PvP 549, sale 448, class quest walks 336, level walks 325 and room 169, so
levelling was a small slice of what an approved raid seat was asked to do, and
about a third of each guild read "on a guild job" in the dungeon asks' census
for as long as a step lasted. The target is every seat at the cap, and
dungeons in a full level-matched party are the fastest honest way there, so a
seat below the cap is given no errand that does not block play: no food walk
while it still carries food, no sale while its bags have room, no riding,
mount, weapon-master, post, trainer, profession or mail-collection walk. What
blocks play stays: the class quest (first, as ever), an empty ration bag, bags
below the room floor, a death loop's way out, and the level walk itself.
`SEATS_LEVEL_FIRST=off` restores the old order. A member that is not an
approved seat, and a seat at the cap, are planned exactly as before.
"""

import unittest

import guildjobs
import guildlevel
import guildroute
import restsupply
from test_guild_rest_supply import BATES, FEMUR, grey
from test_guildlevel_open_quests import WORLD, member as quest_member

SEAT = "Hurk"  # an approved Cave seat
NOT_A_SEAT = "Nobody"


def hungry_member(name=SEAT, **over):
    base = dict(FEMUR, name=name, guild="Cave", food=2, drink=2)
    base.update(over)
    return guildjobs.Member(**base)


def plan(members, **kw):
    kw.setdefault("masters", {"Cave": "Grug", "Bonkers": "Zug"})
    kw.setdefault("supply", {SEAT: BATES, NOT_A_SEAT: BATES})
    return guildjobs.plan(members, **kw)


def actions(result, name):
    return [s.action for s in result.steps if s.holder == name]


class TheSeatSet(unittest.TestCase):
    def test_an_approved_seat_below_the_cap_levels_first(self):
        self.assertTrue(guildjobs.levelling_first(hungry_member()))

    def test_a_seat_at_the_cap_does_not(self):
        self.assertFalse(guildjobs.levelling_first(hungry_member(level=60)))

    def test_a_member_off_the_approved_lineup_does_not(self):
        self.assertFalse(guildjobs.levelling_first(hungry_member(NOT_A_SEAT)))

    def test_the_switch_turns_it_off(self):
        for word in ("off", "0", "false", "no"):
            self.assertFalse(
                guildjobs.levelling_first(
                    hungry_member(), {guildjobs.SEATS_LEVEL_FIRST_ENV: word}
                ),
                word,
            )


class TheFoodWalk(unittest.TestCase):
    def test_a_member_off_the_lineup_low_on_food_still_walks_for_it(self):
        result = plan([hungry_member(NOT_A_SEAT)])
        self.assertEqual(actions(result, NOT_A_SEAT), [restsupply.ACTION])

    def test_a_seat_low_on_food_but_not_out_of_it_does_not(self):
        result = plan([hungry_member()])
        self.assertNotIn(restsupply.ACTION, actions(result, SEAT))

    def test_a_seat_with_nothing_to_eat_still_buys_food(self):
        result = plan([hungry_member(food=0, drink=0)])
        self.assertEqual(actions(result, SEAT), [restsupply.ACTION])

    def test_a_seat_at_the_cap_is_planned_as_before(self):
        result = plan([hungry_member(level=60)])
        self.assertEqual(actions(result, SEAT), [restsupply.ACTION])


class TheSale(unittest.TestCase):
    def junk(self):
        return tuple(grey(20 + i, 400) for i in range(10))

    def test_a_seat_with_room_in_its_bags_does_not_walk_to_a_vendor_to_sell(self):
        m = hungry_member(
            food=20, drink=20, carried=self.junk(), free_slots=12, bag_slots=20
        )
        stop = (guildjobs.Recent(SEAT, "gear", 180, "delivered"),)
        self.assertEqual(actions(plan([m], supply={}, recent=stop), SEAT), [])

    def test_the_same_junk_is_sold_by_a_member_off_the_lineup(self):
        m = hungry_member(
            NOT_A_SEAT,
            food=20,
            drink=20,
            carried=self.junk(),
            free_slots=12,
            bag_slots=20,
        )
        self.assertIn("sell", actions(plan([m], supply={}), NOT_A_SEAT))

    def test_a_seat_with_two_free_slots_still_sells(self):
        m = hungry_member(
            food=20, drink=20, carried=self.junk(), free_slots=2, bag_slots=20
        )
        self.assertIn("sell", actions(plan([m], supply={}), SEAT))

    def test_a_seat_at_the_cap_is_planned_as_before(self):
        # A seat's trainer walk (its raid plan's trades) is the step it had
        # before this change, ahead of the sale; at the cap it still has it.
        m = hungry_member(
            level=60,
            food=20,
            drink=20,
            carried=self.junk(),
            free_slots=12,
            bag_slots=20,
        )
        self.assertEqual(actions(plan([m], supply={}), SEAT), ["train"])


class TheLevelWalk(unittest.TestCase):
    def test_a_seat_that_has_outgrown_its_zone_gets_the_level_step(self):
        m = quest_member(
            "Hurk",
            food=20,
            drink=20,
            carried=tuple(grey(20 + i, 400) for i in range(10)),
            free_slots=12,
            bag_slots=20,
        )
        result = guildjobs.plan(
            [m],
            masters={"Cave": "Grug", "Bonkers": "Zug"},
            leveling=WORLD,
            cap=guildroute.FAR_WALK_YARDS,
        )
        self.assertEqual(actions(result, "Hurk"), [guildlevel.ACTION])


class TheProfessionErrand(unittest.TestCase):
    """A seat below the cap learns its assigned trade on a town stop it already
    made, never on a walk of its own."""

    def seat(self):
        from test_guildjobs_professions import SEATS, member as pro_member

        return pro_member(SEATS[10])

    def plan(self, rows):
        from test_guildjobs_professions import FOCUS_DUNGEON

        return guildjobs.plan([self.seat()], recent=rows, focus=FOCUS_DUNGEON)

    def errands(self, result):
        from test_guildjobs_professions import errands

        return errands(result)

    def test_a_town_stop_just_made_carries_the_errand(self):
        from test_guildjobs_professions import SEATS, recent

        rows = (recent(SEATS[10].name, "sell", 20),)
        self.assertEqual(1, len(self.errands(self.plan(rows))))

    def test_a_stop_a_few_hours_back_does_not_earn_a_dedicated_errand(self):
        from test_guildjobs_professions import SEATS, recent

        rows = (recent(SEATS[10].name, "gear", guildjobs.DEDICATED_AFTER_MINUTES - 60),)
        self.assertEqual([], self.errands(self.plan(rows)))

    def test_no_stop_for_six_hours_is_the_backstop(self):
        from test_guildjobs_professions import SEATS, recent

        rows = (recent(SEATS[10].name, "gear", guildjobs.DEDICATED_AFTER_MINUTES + 30),)
        self.assertEqual(1, len(self.errands(self.plan(rows))))
        self.assertEqual(1, len(self.errands(self.plan(()))))

    def test_with_the_switch_off_the_dedicated_errand_comes_back(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {guildjobs.SEATS_LEVEL_FIRST_ENV: "off"}):
            self.assertEqual(1, len(self.errands(self.plan(()))))


if __name__ == "__main__":
    unittest.main()
