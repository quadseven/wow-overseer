"""A member sells the second-best of the upgrades it kept (#1592).

Read on the dev realm on 2026-11-08 (read-only SELECT): after the other rules
let go what they can, 280 slots of the full members' bags (about 129 gold at a
vendor) were weapons and armor kept as "an upgrade", judged one piece at a
time against the worn one. A member that looted four belts above its own kept
all four (Durg held two belts above its worn 42, Hugga two identical staffs).
Keeping the best of each slot and selling the second-bests frees 193 slots, 77
gold, in the same read.

The rule: of the pieces kept as an upgrade, the best by item level of each
slot stays (three weapons, as a main hand, an off hand and a spare); an
uncommon-or-lower piece beyond them sells. Rare pieces, pieces the member
would not wear and unreserved pieces keep their old answers.
"""

import dataclasses
import unittest

import gear
import guildjobs
import keep
import vendorsale
from test_member_income import bonk

WORN = gear.CharacterState(
    name="Ekka", class_id=2, level=35, equipped={"waist": 20, "main_hand": 20}
)


def belt(guid, item_level, quality=2):
    return guildjobs.Carried(
        guid=guid,
        entry=guid,
        name="Belt %d" % guid,
        item_class=4,
        subclass=3,
        quality=quality,
        sell_price=500,
        item_level=item_level,
        required_level=item_level - 5,
        inventory_type=6,
    )


def sword(guid, item_level):
    return guildjobs.Carried(
        guid=guid,
        entry=guid,
        name="Sword %d" % guid,
        item_class=2,
        subclass=7,
        quality=2,
        sell_price=900,
        item_level=item_level,
        required_level=item_level - 5,
        inventory_type=13,
    )


def member(*carried):
    return bonk(
        name="Ekka",
        level=35,
        free_slots=0,
        bag_slots=16,
        worn=WORN,
        carried=tuple(carried),
    )


def sold(m, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(m, kept)}


class OnlyTheBestOfASlotIsKept(unittest.TestCase):
    def test_the_second_and_third_belts_sell(self):
        m = member(belt(1, 30), belt(2, 32), belt(3, 28))
        self.assertEqual({"Belt 1", "Belt 3"}, sold(m))

    def test_each_is_still_an_upgrade_one_piece_at_a_time(self):
        m = member(belt(1, 30), belt(2, 32))
        judge = guildjobs.vendor_judge(m)
        for c in m.carried:
            self.assertIs(vendorsale.KEEP, vendorsale.verdict(c, judge)[0])
        self.assertEqual(
            frozenset({1}), vendorsale.redundant_upgrades(m.carried, judge)
        )

    def test_two_identical_pieces_sell_one(self):
        self.assertEqual(1, len(sold(member(belt(1, 32), belt(2, 32)))))

    def test_a_full_member_walks_to_sell_the_second_best(self):
        step = guildjobs._full_bags_first(
            member(belt(1, 30), belt(2, 32)), None, (), 600.0
        )
        self.assertIsNotNone(step)
        self.assertEqual({"guid:1"}, {r.command for r in step.rows})

    def test_three_weapons_are_kept_and_the_fourth_sells(self):
        m = member(sword(11, 30), sword(12, 31), sword(13, 32), sword(14, 29))
        self.assertEqual({"Sword 14"}, sold(m))


class AMemberWithRoomDoesNotWalkToSell(unittest.TestCase):
    def test_no_sale_step_while_the_bags_have_room(self):
        roomy = dataclasses.replace(member(belt(1, 30), belt(2, 32)), free_slots=12)
        self.assertIsNone(guildjobs._full_bags_first(roomy, None, (), 600.0))


class WhatIsNotARedundantUpgradeStays(unittest.TestCase):
    def test_a_lone_upgrade_and_one_per_slot_stay(self):
        self.assertEqual(set(), sold(member(belt(1, 30), sword(11, 30))))

    def test_a_rare_second_best_is_left_alone(self):
        m = member(belt(1, 32), belt(2, 30, quality=3))
        self.assertEqual(
            frozenset(),
            vendorsale.redundant_upgrades(m.carried, guildjobs.vendor_judge(m)),
        )

    def test_a_reservation_still_holds_the_second_best(self):
        kept = keep.with_guids(keep.Reservations(), [("Ekka", 1)])
        self.assertEqual(set(), sold(member(belt(1, 30), belt(2, 32)), kept=kept))

    def test_nothing_is_redundant_while_the_worn_gear_is_unread(self):
        m = bonk(name="Ekka", level=35, worn=None, carried=(belt(1, 30), belt(2, 32)))
        judge = guildjobs.vendor_judge(m)
        self.assertEqual(frozenset(), vendorsale.redundant_upgrades(m.carried, judge))


if __name__ == "__main__":
    unittest.main()
