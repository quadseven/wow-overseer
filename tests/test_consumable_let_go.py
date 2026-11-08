"""A member sells the white scrolls and odd consumables nothing uses (#1592).

Read on the dev realm on 2026-11-08 (read-only SELECT on character_inventory,
item_instance and item_template): of the 120 members of Cave and Bonkers with
one free bag slot or fewer, white consumables held 644 slots, about 11 gold at
a vendor (Scroll of Spirit 42 times, Scroll of Protection 38, Enriched Lasher
Root 64, Glowing Wax Stick 17, Explosive Rocket 17). The members' carried read
never selected class 0 outside food and the verdict kept the whole class, so
the sale could not offer one. Selling the priced white scrolls, generic and
other-kind stacks that no open quest names would take the members at one free
slot or fewer from 102 to 24 in the same read.

Kept on purpose: potions, elixirs, flasks, food and drink and bandages.
"""

import dataclasses
import unittest

import guildjobs
import keep
import vendorsale
from test_guildsocial_bridge import bridge
from test_member_income import MOUNT, bonk


def stack(guid, name, subclass, quality=1, price=250, needed=False):
    return guildjobs.Carried(
        guid=guid,
        entry=guid,
        name=name,
        count=3,
        item_class=0,
        subclass=subclass,
        quality=quality,
        sell_price=price,
        item_level=1,
        quest_needed=needed,
    )


SCROLL = stack(8101, "Scroll of Spirit", 4)
OTHER = stack(8102, "Enriched Lasher Root", 8, price=25)
GENERIC = stack(8103, "Bag of Marbles", 0, price=82)
POTION = stack(8104, "Healing Potion", 1)
ELIXIR = stack(8105, "Troll Blood Elixir", 2)
FLASK = stack(8106, "Flask of Rock", 3)
FOOD = stack(8107, "Cured Ham Steak", 5)
BANDAGE = stack(8108, "Linen Bandage", 7, price=8)
ENHANCER = stack(8109, "Sharpening Stone", 6)
NEEDED = dataclasses.replace(SCROLL, guid=8110, name="Needed Scroll", quest_needed=True)
UNPRICED = dataclasses.replace(SCROLL, guid=8111, name="Soulstone", sell_price=0)
GREEN = dataclasses.replace(SCROLL, guid=8112, name="Green Scroll", quality=2)
UNSAID = guildjobs.Carried(
    guid=8113, entry=8113, name="Unsaid", item_class=0, subclass=4, quality=1,
    sell_price=250,
)


def full(*carried):
    return bonk(
        name="Ekka", level=35, free_slots=0, bag_slots=16, carried=tuple(carried)
    )


def sold(member, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(member, kept)}


class AScrollOrOddConsumableNothingNeedsSells(unittest.TestCase):
    def test_the_verdict_sells_each_kind(self):
        for item in (SCROLL, OTHER, GENERIC):
            with self.subTest(item.name):
                verdict = vendorsale.verdict(item, guildjobs.vendor_judge(full(item)))
                self.assertIs(vendorsale.SELL, verdict[0])
                self.assertIn("no open quest names", verdict[1])

    def test_a_full_member_walks_to_sell_only_those(self):
        member = full(SCROLL, OTHER, GENERIC, POTION, FOOD, BANDAGE, MOUNT)
        self.assertEqual({SCROLL.name, OTHER.name, GENERIC.name}, sold(member))
        step = guildjobs._full_bags_first(member, None, (), 600.0)
        self.assertIsNotNone(step)
        self.assertEqual("sell", step.action)
        self.assertEqual(
            {"guid:%d" % c.guid for c in (SCROLL, OTHER, GENERIC)},
            {r.command for r in step.rows},
        )


class WhatAMemberDrinksOrHealsWithStays(unittest.TestCase):
    def test_potions_elixirs_flasks_food_bandages_and_enhancers_are_kept(self):
        for item in (POTION, ELIXIR, FLASK, FOOD, BANDAGE, ENHANCER):
            with self.subTest(item.name):
                verdict = vendorsale.verdict(item, guildjobs.vendor_judge(full(item)))
                self.assertEqual(
                    (vendorsale.KEEP, "its own AI eats, drinks or uses it"), verdict
                )

    def test_a_needed_unpriced_uncommon_or_unsaid_stack_is_kept(self):
        self.assertEqual(set(), sold(full(NEEDED, UNPRICED, GREEN)))
        self.assertTrue(UNSAID.quest_needed)
        self.assertEqual(set(), sold(full(UNSAID)))

    def test_a_reservation_still_holds_it(self):
        kept = keep.with_guids(keep.Reservations(), [("Ekka", SCROLL.guid)])
        self.assertEqual(set(), sold(full(SCROLL), kept=kept))


class TheBridgeReadsThem(unittest.TestCase):
    def test_the_carried_read_selects_priced_white_scrolls_and_odd_kinds(self):
        sql = bridge._JOB_ITEMS_SQL
        self.assertIn(
            "it.class = 0 AND it.Quality <= 1 AND it.subclass IN (0, 4, 8) "
            "AND it.SellPrice > 0",
            sql,
        )

    def test_the_need_is_asked_of_a_consumable_too(self):
        sql = bridge._JOB_ITEMS_SQL
        self.assertIn("(it.class IN (0, 12) AND ", sql)
        self.assertIn("character_queststatus qs", sql)
        self.assertEqual(sql.count("("), sql.count(")"))

    def test_the_class_12_expression_is_unchanged(self):
        import bag_pressure

        self.assertTrue(bag_pressure.QUEST_NEEDED_SQL.startswith("(it.class = 12 AND"))
        self.assertIn(
            bag_pressure.STACK_QUEST_NEEDED_SQL, bag_pressure.QUEST_NEEDED_SQL
        )


if __name__ == "__main__":
    unittest.main()
