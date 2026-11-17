"""A seat buys food and drink for the next stretch, not one stack (ticket 2621).

Read on the dev realm on 2026-11-15: 213 supply buys were applied in 24 hours
and 36 of the 38 seats that bought were empty again, because the plan bought
at most one stack of each kind (restsupply.STACK = 20) and a seat that fights
alone and dies often eats 20 units in a handful of pulls. mod-playerbots drinks
only below its LowMana line (15 percent) and only from drink in the bags, and
its grind strategy pulls with no mana gate, so a bag with no drink is a bot
that never sits down.

The plan now buys up to TARGET stacks of a kind, one buy row per stack, within
the free bag slots, the half share of the purse and the vendor's unlimited
stock. A poor purse buys what it bought before.
"""

import unittest

import guildjobs
import restsupply

PRIEST = 5
WARRIOR = 1
FOOD, DRINK = restsupply.FOOD_CATEGORY, restsupply.DRINK_CATEGORY


def offer(vendor, entry, price, req, category, count=5):
    return {
        "vendor": vendor,
        "vendor_name": "Vendor %d" % vendor,
        "map_id": 0,
        "yards": 100.0,
        "entry": entry,
        "item_name": "Item %d" % entry,
        "price": price,
        "buy_count": count,
        "required_level": req,
        "category": category,
        "enemy_group": 2,
    }


INN = [
    offer(1, 4606, 500, 15, FOOD),
    offer(1, 1205, 500, 15, DRINK),
]


def seat(**over):
    base = dict(
        name="Mirth",
        guild="Cave",
        role=guildjobs.RAIDER,
        level=40,
        class_id=PRIEST,
        race=5,
        online=True,
        map_id=0,
        x=10.0,
        y=10.0,
        zone_id=12,
        money=500000,
        eligible=True,
        food=30,
        drink=0,
    )
    base.update(over)
    return guildjobs.Member(**base)


def stacks_of(buys, category):
    return [b for b in buys if b.category == category]


class HowManyStacks(unittest.TestCase):
    def test_two_free_slots_plan_two_stacks_of_drink(self):
        buys, why = restsupply.plan(seat(), INN, 0, room=2)
        self.assertEqual(why, "")
        self.assertEqual(len(stacks_of(buys, DRINK)), 2)
        self.assertTrue(all(b.units <= restsupply.STACK for b in buys))

    def test_one_free_slot_plans_one_stack(self):
        buys, _why = restsupply.plan(seat(), INN, 0, room=1)
        self.assertEqual(len(buys), 1)

    def test_the_plan_never_exceeds_the_free_slots(self):
        for room in range(1, 8):
            both = seat(food=0, drink=0)
            buys, _why = restsupply.plan(both, INN, 0, room=room)
            self.assertLessEqual(len(buys), room, room)

    def test_both_kinds_share_the_room_before_either_takes_a_second(self):
        both = seat(food=0, drink=0)
        buys, _why = restsupply.plan(both, INN, 0, room=2)
        self.assertEqual(sorted(b.category for b in buys), sorted([FOOD, DRINK]), buys)

    def test_a_caster_stocks_more_drink_than_a_warrior_stocks_food(self):
        caster, _ = restsupply.plan(seat(food=0, drink=0), INN, 0, room=9)
        warrior, _ = restsupply.plan(seat(class_id=WARRIOR, food=0), INN, 0, room=9)
        self.assertGreater(len(stacks_of(caster, DRINK)), len(warrior))

    def test_unread_room_buys_the_single_stack_it_always_did(self):
        buys, _why = restsupply.plan(seat(), INN, 0)
        self.assertEqual(len(buys), 1)


class WhatItSpends(unittest.TestCase):
    def test_never_more_than_the_half_share_of_the_purse(self):
        for money in (3000, 9000, 40000, 500000):
            both = seat(food=0, drink=0, money=money)
            buys, _why = restsupply.plan(both, INN, 0, room=6)
            self.assertLessEqual(sum(b.ceiling for b in buys), money // 2, money)

    def test_a_poor_purse_buys_the_single_stack_it_bought_before(self):
        poor = seat(money=2600)
        before, _ = restsupply.plan(poor, INN, 0)
        more, _ = restsupply.plan(poor, INN, 0, room=6)
        self.assertEqual(
            [(b.entry, b.units) for b in more], [(b.entry, b.units) for b in before]
        )

    def test_a_stack_is_only_bought_whole_or_not_at_all_below_the_minimum(self):
        buys, _why = restsupply.plan(seat(money=9000), INN, 0, room=6)
        self.assertTrue(all(b.units >= restsupply.MIN_UNITS for b in buys), buys)


class InTheStep(unittest.TestCase):
    def test_the_step_buys_a_row_per_stack_within_the_free_slots(self):
        step, _why = guildjobs.supply_step(
            seat(free_slots=2, bag_slots=16), INN, 20000.0
        )
        rows = [r for r in step.rows if r.kind == "buy"]
        self.assertEqual(len(rows), 2)

    def test_no_free_slot_still_refuses(self):
        step, why = guildjobs.supply_step(
            seat(free_slots=0, bag_slots=16), INN, 20000.0
        )
        self.assertIsNone(step)
        self.assertIn("no room", why)

    def test_unread_bags_buy_one_stack(self):
        step, _why = guildjobs.supply_step(seat(), INN, 20000.0)
        self.assertEqual(len([r for r in step.rows if r.kind == "buy"]), 1)


if __name__ == "__main__":
    unittest.main()
