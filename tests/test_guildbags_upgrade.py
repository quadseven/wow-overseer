"""A guild member whose four bag positions are full buys a bigger bag (Refs #2435).

`guildbags.plan` bought only for an empty bag position, so 95 of 162 guild
members stayed in four 6-slot pouches with gold in the purse. With one free
slot for it to land in, a member now buys the largest vendor bag it can pay for
that beats its smallest worn bag by `bag_market.MIN_UPGRADE_GAIN` slots, and
puts it on with the same `e` row.
"""

import unittest
from dataclasses import replace

import bag_market
import bag_pressure as bp
import bag_upgrade as bu
import guildbags
from test_guildjobs import member

SACK = bp.BagOffer(805, "Huge Brown Sack", 12, 100000)
POUCH = bp.BagOffer(4496, "Small Brown Pouch", 6, 500)


def sixes():
    return bu.Member(
        "Tailor",
        4,
        worn=tuple(bu.Bag("Pouch", 6, used=6, entry=4496) for _ in range(4)),
    )


def tailor(free_slots=2, **changes):
    return member(
        "Tailor", level=43, money=300000, free_slots=free_slots, bag_slots=24, **changes
    )


def vendors(*offers):
    return {"Tailor": (bp.BagVendor(900001, "Vendor", 0, 40, offers=offers),)}


class AFullMemberBuysABiggerBag(unittest.TestCase):
    def test_four_pouches_two_free_slots_and_thirty_gold_buy_the_sack(self):
        steps, _ = guildbags.plan([tailor()], [sixes()], vendors(POUCH, SACK))
        step = steps["Tailor"].step
        self.assertEqual(
            [("buy", "entry:805 count:1 max:100000"), ("bot", "e Hitem:805:0")],
            [(r.kind, r.command) for r in step.rows],
        )
        self.assertEqual("walk-to-vendor item:805", step.walk.command)

    def test_a_member_with_no_free_slot_buys_nothing(self):
        m = tailor(free_slots=0)
        self.assertEqual({}, guildbags.plan([m], [sixes()], vendors(SACK))[0])

    def test_a_purse_below_the_reserve_and_the_price_buys_nothing(self):
        m = replace(tailor(), money=bp.bag_reserve(43) + SACK.price - 1)
        self.assertEqual({}, guildbags.plan([m], [sixes()], vendors(SACK))[0])

    def test_a_bag_that_gains_less_than_the_minimum_is_not_bought(self):
        close = bp.BagOffer(
            806, "Brown Leather Satchel", 6 + bag_market.MIN_UPGRADE_GAIN - 1, 900
        )
        self.assertEqual(
            {}, guildbags.plan([tailor()], [sixes()], vendors(POUCH, close))[0]
        )

    def test_the_largest_bag_the_purse_pays_for_wins(self):
        mid = bp.BagOffer(4497, "Brown Leather Satchel", 8, 2000)
        poor = replace(tailor(), money=bp.bag_reserve(43) + 2000)
        steps, _ = guildbags.plan([poor], [sixes()], vendors(mid, SACK))
        self.assertEqual(
            "entry:4497 count:1 max:2000", steps["Tailor"].step.rows[0].command
        )

    def test_an_empty_position_is_still_bought_for_the_old_way(self):
        empty = bu.Member(
            "Tailor", 4, worn=(bu.Bag("Pouch", 6, used=6, entry=4496),) * 3
        )
        steps, _ = guildbags.plan([tailor()], [empty], vendors(POUCH))
        self.assertEqual(
            "entry:4496 count:1 max:500", steps["Tailor"].step.rows[0].command
        )
