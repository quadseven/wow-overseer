"""A member at one free slot or fewer sells the reserved cloth it carries
beyond its fullest stacks (#1592, cause 1).

Read on the dev realm on 2026-11-09 (read-only SELECT): 441 slots of white
cloth (92 gold at a vendor) sat in the bags of members at one free slot or
fewer, because the bank forecast reserves cloth for the guild and a tailor or
first aider keeps its own. A member that is short of room keeps the
CLOTH_STACKS_KEPT fullest cloth stacks and lets the rest go. A member with
room keeps all of it. Quality above white, the quest-log hold and the keep list
are untouched, and the sale still passes lootpolicy.allowed.
"""

import dataclasses
import unittest

import guildjobs
import keep
import lootpolicy
import vendorsale
from test_member_income import bonk

TAILORING = 197


def cloth(guid, entry, name, count, quality=1, price=30):
    return guildjobs.Carried(
        guid=guid,
        entry=entry,
        name=name,
        count=count,
        item_class=7,
        subclass=5,
        quality=quality,
        sell_price=price,
        item_level=1,
    )


LINEN_A = cloth(9001, 2589, "Linen Cloth", 20)
LINEN_B = cloth(9002, 2589, "Linen Cloth", 7)
WOOL = cloth(9003, 2592, "Wool Cloth", 12)
SILK = cloth(9004, 4306, "Silk Cloth", 3)
MAGEWEAVE = cloth(9005, 4338, "Mageweave Cloth", 1)
RUNE_EPIC = cloth(9006, 9999, "Epic Cloth", 5, quality=4, price=900)
ALL = (LINEN_A, LINEN_B, WOOL, SILK, MAGEWEAVE, RUNE_EPIC)


def member(free=0, carried=ALL, skills=(TAILORING,)):
    return bonk(
        name="Ekka",
        level=35,
        free_slots=free,
        bag_slots=16,
        carried=tuple(carried),
        reserved=frozenset(c.entry for c in carried),
        skills={s: (150, 300) for s in skills},
        skills_read=True,
    )


def sold(m, kept=None):
    return {c.guid for c in guildjobs.vendor_stacks(m, kept)}


class ATightMemberKeepsItsFullestClothAndSellsTheRest(unittest.TestCase):
    def test_the_two_fullest_stacks_stay_and_the_rest_sells(self):
        self.assertEqual(
            {LINEN_B.guid, SILK.guid, MAGEWEAVE.guid}, sold(member(free=0))
        )
        self.assertEqual(
            {LINEN_B.guid, SILK.guid, MAGEWEAVE.guid},
            sold(member(free=1)),
        )

    def test_the_overflow_is_the_stacks_beyond_the_fullest_two(self):
        judge = guildjobs.vendor_judge(member(free=0))
        got = vendorsale.cloth_overflow(ALL, judge)
        self.assertEqual({LINEN_B.guid, SILK.guid, MAGEWEAVE.guid}, got)

    def test_a_member_with_room_keeps_all_of_it(self):
        self.assertEqual(set(), sold(member(free=2)))

    def test_free_slots_unread_keeps_it(self):
        self.assertEqual(set(), sold(member(free=None)))


class WhatStaysStays(unittest.TestCase):
    def test_an_epic_is_never_sold(self):
        self.assertNotIn(RUNE_EPIC.guid, sold(member(free=0)))

    def test_a_keep_list_stack_is_never_sold(self):
        kept = keep.with_guids(keep.Reservations(), [("Ekka", SILK.guid)])
        self.assertNotIn(SILK.guid, sold(member(free=0), kept))

    def test_an_unpriced_stack_stays(self):
        free = dataclasses.replace(SILK, sell_price=0)
        got = sold(member(free=0, carried=(LINEN_A, LINEN_B, WOOL, free)))
        self.assertNotIn(free.guid, got)

    def test_a_protected_entry_stays(self):
        judge = vendorsale.Judge(
            level=35,
            reserved=frozenset(c.entry for c in ALL),
            protected=frozenset({SILK.entry}),
            tight=True,
        )
        self.assertNotIn(SILK.guid, vendorsale.cloth_overflow(ALL, judge))

    def test_other_trade_goods_are_not_cloth(self):
        meat = dataclasses.replace(SILK, guid=9010, entry=3, subclass=8)
        got = sold(
            member(
                free=0,
                carried=(LINEN_A, WOOL, meat, SILK, MAGEWEAVE),
                skills=(TAILORING, 185),
            )
        )
        self.assertNotIn(meat.guid, got)


class TheSaleStillPassesTheLootPolicy(unittest.TestCase):
    def test_white_cloth_is_a_vendor_verdict(self):
        row = {
            "quality": 1,
            "item_class": 7,
            "subclass": 5,
            "instance_flags": 0,
            "bonding": 0,
            "quest_needed": False,
        }
        verdict = lootpolicy.decide(row, ())
        self.assertTrue(lootpolicy.allowed(verdict, "sell"))


if __name__ == "__main__":
    unittest.main()
