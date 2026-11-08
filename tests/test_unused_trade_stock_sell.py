"""A member sells the trade stock none of its own trades uses (#1592).

Read on the dev realm on 2026-11-08 (read-only SELECT): of the 162 members of
Cave and Bonkers only 71 held any trade, and 102 had one free bag slot or
fewer. The bank forecast reserves a material for the guild as a whole, so
every member that looted linen, silk or meat kept the stack although it could
not craft with it, and kept the recipes it could not learn: 384 slots of white
trade goods no held trade eats and 519 slots of recipes for a trade the holder
lacks. Selling them takes the members at one free slot or fewer from 102 to 39
in the same read, about 65 gold at a vendor.

The rule: a white trade good whose feeding trades the member holds none of, and
an uncommon-or-lower recipe for a trade the member lacks, sell. A member that
holds the trade keeps both. Unread trades keep the old answer.
"""

import dataclasses
import unittest

import guildjobs
import guildshare
import keep
import vendorsale
from test_member_income import MOUNT, bonk

TAILORING, FIRST_AID, COOKING = 197, 129, 185


def goods(guid, name, item_class, subclass, quality=1, price=40):
    return guildjobs.Carried(
        guid=guid,
        entry=guid,
        name=name,
        count=20,
        item_class=item_class,
        subclass=subclass,
        quality=quality,
        sell_price=price,
        item_level=1,
    )


LINEN = goods(8201, "Linen Cloth", 7, 5)
MEAT = goods(8202, "Tough Wolf Meat", 7, 8)
GREEN_LEATHER = goods(8203, "Rugged Leather", 7, 6, quality=2)
HOT_LION = goods(8204, "Recipe: Hot Lion Chops", 9, 5)
PATTERN = goods(8205, "Pattern: Dark Leather Tunic", 9, 1, quality=2, price=2000)
RARE_PATTERN = goods(8206, "Pattern: Rare Thing", 9, 1, quality=3, price=9000)
GEM = goods(8207, "Malachite", 3, 0, quality=2)
ALL = (LINEN, MEAT, GREEN_LEATHER, HOT_LION, PATTERN, RARE_PATTERN, GEM)


def member(skills, read=True, reserved=None, carried=ALL):
    # Everything reserved by the guild forecast: the old rule kept the lot.
    keep_all = frozenset(c.entry for c in carried) if reserved is None else reserved
    return bonk(
        name="Ekka",
        level=35,
        free_slots=0,
        bag_slots=16,
        carried=tuple(carried),
        reserved=keep_all,
        skills={s: (150, 300) for s in skills},
        skills_read=read,
    )


def sold(m, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(m, kept)}


class AMaterialNoHeldTradeUsesSells(unittest.TestCase):
    def test_a_member_with_no_trade_sells_the_goods_and_the_recipes(self):
        got = sold(member(()))
        self.assertEqual({LINEN.name, MEAT.name, HOT_LION.name, PATTERN.name}, got)

    def test_the_verdict_says_why(self):
        judge = guildjobs.vendor_judge(member(()))
        self.assertEqual(
            (vendorsale.SELL, "a material none of this member's trades uses"),
            vendorsale.verdict(LINEN, judge),
        )
        self.assertEqual(
            (vendorsale.SELL, "a recipe for a trade this member does not hold"),
            vendorsale.verdict(PATTERN, judge),
        )

    def test_a_member_walks_to_sell_them_when_its_bags_are_full(self):
        step = guildjobs._full_bags_first(member(()), None, (), 600.0)
        self.assertIsNotNone(step)
        self.assertEqual("sell", step.action)


class WhatAHeldTradeNeedsStays(unittest.TestCase):
    def test_a_tailor_keeps_cloth_and_the_tailoring_pattern(self):
        got = sold(member((TAILORING,)))
        self.assertNotIn(LINEN.name, got)
        self.assertIn(MEAT.name, got)

    def test_first_aid_keeps_cloth(self):
        self.assertNotIn(LINEN.name, sold(member((FIRST_AID,))))

    def test_a_cook_keeps_meat_and_its_recipe(self):
        got = sold(member((COOKING,)))
        self.assertNotIn(MEAT.name, got)
        self.assertNotIn(HOT_LION.name, got)
        self.assertIn(LINEN.name, got)

    def test_a_green_good_a_rare_recipe_and_a_gem_stay(self):
        got = sold(member(()))
        self.assertTrue(
            {GREEN_LEATHER.name, RARE_PATTERN.name, GEM.name}.isdisjoint(got)
        )


class UnreadTradesKeepTheOldAnswer(unittest.TestCase):
    def test_trades_not_read_sells_nothing_the_forecast_reserves(self):
        self.assertEqual(set(), sold(member((), read=False)))

    def test_a_judge_with_no_trades_is_inert(self):
        judge = vendorsale.Judge(level=35, reserved=frozenset({LINEN.entry}))
        self.assertIsNone(judge.trades)
        self.assertEqual(vendorsale.KEEP, vendorsale.verdict(LINEN, judge)[0])

    def test_a_reservation_on_the_stack_still_holds_it(self):
        kept = keep.with_guids(keep.Reservations(), [("Ekka", LINEN.guid)])
        self.assertNotIn(LINEN.name, sold(member(()), kept=kept))

    def test_an_unpriced_stack_stays(self):
        free = dataclasses.replace(LINEN, guid=8210, name="Free Cloth", sell_price=0)
        self.assertEqual(set(), sold(member((), carried=(free, MOUNT))) - {MOUNT.name})


class TheBridgeSaysTheTradesWereRead(unittest.TestCase):
    def test_the_job_member_is_built_with_its_skills_read(self):
        from test_guildsocial_bridge import bridge

        src = open(bridge.__file__, encoding="utf-8").read()
        self.assertIn(
            "skills=skills.get(guid, {}),\n            skills_read=True,", src
        )


class TheTablesAgreeWithTheGuildShare(unittest.TestCase):
    def test_trade_good_users_are_guildshare_feeds_in_skill_ids(self):
        want = {
            sub: frozenset(guildshare.SKILL_LINES[t] for t in trades)
            for sub, trades in guildshare.FEEDS.items()
        }
        self.assertEqual(want, vendorsale.TRADE_GOOD_USERS)

    def test_recipe_trades_are_known_skill_lines(self):
        for skill in vendorsale.RECIPE_TRADE.values():
            self.assertIn(skill, guildshare.SKILL_LINES.values())


if __name__ == "__main__":
    unittest.main()
