"""The item plan (#1967): where every stack should be, and why.

Pure: rows in, a plan out. These tests build Stack and Member rows by hand and
one block from rows of the 2026-11-07 dump (a level 54 druid's blue items).
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan  # noqa: E402
from itemplan import (  # noqa: E402
    AUCTION,
    BANK_PERSONAL,
    DESTROY,
    GIVE,
    GUILD_BANK,
    KEEP_CARRY,
    SELL_VENDOR,
    Context,
    Member,
    Stack,
)

TAILORING, FIRST_AID, LEATHERWORKING = 197, 129, 165
MAGE, DRUID, PALADIN = 8, 11, 2

_counter = [0]


def stack(holder="Ana", loc="carried_bag", entry=1, name="Thing", **kw):
    _counter[0] += 1
    base = dict(
        item_class=15,
        subclass=0,
        quality=1,
        count=1,
        sell=0,
        bind=0,
        req_level=0,
        item_level=1,
        stackable=1,
        index=_counter[0],
    )
    base.update(kw)
    return Stack(holder, loc, entry, name, **base)


def member(name="Ana", level=54, cls=MAGE, skills=(), **kw):
    base = dict(family="Fam", carried_slots=72, bank_slots=88)
    base.update(kw)
    return Member(name, base.pop("family"), level, cls, tuple(skills), **base)


def decide(stacks, members, ctx=None):
    plan = itemplan.plan(stacks, members, ctx)
    return {d.key: d for d in plan.decisions}, plan


def one(stacks, members, target, ctx=None):
    by_key, _plan = decide(stacks, members, ctx)
    return by_key[target.key]


class QuestItems(unittest.TestCase):
    def test_open_quest_item_is_kept_carried(self):
        q = stack(entry=5, name="Rune", item_class=12, sell=300, bind=1)
        ctx = Context(open_quest_items={"Ana": frozenset({5})})
        d = one([q], [member()], q, ctx)
        self.assertEqual((d.route, d.goal), (KEEP_CARRY, itemplan.QUEST))

    def test_unread_quest_log_never_sells_or_destroys(self):
        priced = stack(entry=6, item_class=12, sell=625, bind=0)
        free = stack(entry=7, item_class=12, sell=0, bind=4)
        by_key, _ = decide([priced, free], [member(carried_slots=13)])
        for s in (priced, free):
            self.assertNotIn(by_key[s.key].route, itemplan.IRREVERSIBLE)


class TradeStock(unittest.TestCase):
    TAILOR = (TAILORING, 145, 225)

    def test_needed_reagent_kept_and_surplus_routed(self):
        dye = [
            stack(
                entry=6260,
                name="Blue Dye",
                item_class=7,
                subclass=11,
                sell=12,
                count=20,
            )
            for _ in range(3)
        ]
        tailor = member(skills=[self.TAILOR])
        ctx = Context(guild_free={("Fam", itemplan.GUILD_TAB_MATERIALS): 5})
        by_key, _ = decide(dye, [tailor], ctx)
        routes = [by_key[s.key].route for s in dye]
        # Azure Silk Hood: 2 dye a cast, 12 casts = 24 units: two whole stacks.
        self.assertEqual(routes.count(KEEP_CARRY), 2)
        self.assertEqual(routes.count(GUILD_BANK), 1)
        surplus = [by_key[s.key] for s in dye if by_key[s.key].route == GUILD_BANK][0]
        self.assertEqual(surplus.tab, itemplan.GUILD_TAB_MATERIALS)

    def test_surplus_goes_to_the_family_member_who_works_the_trade(self):
        cloth = stack(
            holder="Bo",
            entry=4306,
            name="Silk Cloth",
            item_class=7,
            subclass=5,
            sell=60,
            count=20,
        )
        bo = member("Bo", cls=DRUID)
        tailor = member("Ana", skills=[self.TAILOR])
        d = one([cloth], [bo, tailor], cloth)
        self.assertEqual((d.route, d.target), (GIVE, "Ana"))

    def test_grey_recipe_asks_for_nothing(self):
        # Bolt of Linen is grey at skill 145: raw Linen Cloth is surplus.
        linen = stack(
            entry=2589, name="Linen Cloth", item_class=7, subclass=5, sell=13, count=20
        )
        d = one([linen], [member(skills=[(TAILORING, 145, 225)])], linen)
        self.assertEqual(d.route, SELL_VENDOR)


class Capacity(unittest.TestCase):
    def test_full_bag_evicts_lowest_value_per_slot_first(self):
        thread = stack(
            entry=2321, name="Fine Thread", item_class=7, subclass=5, sell=25, count=20
        )
        dye = stack(
            entry=6260, name="Blue Dye", item_class=7, subclass=11, sell=12, count=10
        )
        bolt = stack(
            entry=4305,
            name="Bolt of Silk Cloth",
            item_class=7,
            subclass=5,
            sell=500,
            count=5,
        )
        silk = stack(
            entry=4306, name="Silk Cloth", item_class=7, subclass=5, sell=60, count=8
        )
        # 13 slots, 4 held: 9 free is under the trigger, so the carry budget is 1.
        tailor = member(skills=[(TAILORING, 145, 225)], carried_slots=13)
        by_key, _ = decide([thread, dye, bolt, silk], [tailor])
        self.assertEqual(by_key[bolt.key].route, KEEP_CARRY)
        self.assertEqual(by_key[thread.key].route, BANK_PERSONAL)
        self.assertEqual(by_key[dye.key].route, BANK_PERSONAL)
        self.assertEqual(by_key[silk.key].route, BANK_PERSONAL)

    def test_no_eviction_above_the_trigger(self):
        thread = stack(entry=2321, item_class=7, subclass=5, sell=25, count=20)
        dye = stack(entry=6260, item_class=7, subclass=11, sell=12, count=10)
        tailor = member(skills=[(TAILORING, 145, 225)], carried_slots=20)
        by_key, _ = decide([thread, dye], [tailor])
        self.assertEqual(by_key[thread.key].route, KEEP_CARRY)
        self.assertEqual(by_key[dye.key].route, KEEP_CARRY)

    def test_second_tab_costs_what_the_guild_bank_says(self):
        cost, per_slot = itemplan.tab_slot_cost(1)
        self.assertEqual(cost, 2_500_000)
        self.assertEqual(per_slot, cost // 98)


class Gear(unittest.TestCase):
    def test_soulbound_upgrade_for_the_holder_is_kept_not_sold(self):
        robe = stack(
            entry=77,
            name="Robe",
            item_class=4,
            subclass=1,
            quality=3,
            sell=11000,
            bind=1,
            req_level=48,
            item_level=54,
        )
        d = one([robe], [member()], robe)
        self.assertIn(d.route, (KEEP_CARRY, BANK_PERSONAL))
        self.assertNotIn(d.route, itemplan.IRREVERSIBLE)

    def test_soulbound_piece_is_never_given_to_a_sibling(self):
        plate = stack(
            holder="Bo",
            entry=78,
            item_class=4,
            subclass=4,
            quality=3,
            sell=9000,
            bind=1,
            req_level=52,
            item_level=56,
        )
        pal = member("Pal", cls=PALADIN, level=54)
        bo = member("Bo", cls=MAGE)
        d = one([plate], [bo, pal], plate)
        self.assertNotEqual(d.route, GIVE)

    def test_bind_on_equip_upgrade_goes_to_the_sibling(self):
        plate = stack(
            holder="Bo",
            entry=79,
            item_class=4,
            subclass=4,
            quality=3,
            sell=9000,
            bind=2,
            req_level=50,
            item_level=55,
        )
        pal = member("Pal", cls=PALADIN, level=54)
        bo = member("Bo", cls=MAGE)
        d = one([plate], [bo, pal], plate)
        self.assertEqual((d.route, d.target), (GIVE, "Pal"))

    def test_outgrown_green_is_sold_and_marked_refusable(self):
        ring = stack(
            entry=80,
            item_class=4,
            subclass=0,
            quality=2,
            sell=900,
            bind=2,
            req_level=20,
            item_level=25,
        )
        d = one([ring], [member()], ring)
        self.assertEqual(d.route, SELL_VENDOR)
        self.assertTrue(d.irreversible and d.refusable)

    def test_epic_is_never_sold(self):
        epic = stack(
            entry=81,
            item_class=4,
            subclass=0,
            quality=4,
            sell=90000,
            bind=2,
            req_level=10,
            item_level=60,
        )
        d = one([epic], [member()], epic)
        self.assertNotIn(d.route, itemplan.IRREVERSIBLE)

    def test_blue_sale_waits_for_a_release(self):
        blue = stack(
            entry=82,
            item_class=4,
            subclass=0,
            quality=3,
            sell=6000,
            bind=1,
            req_level=20,
            item_level=25,
        )
        d = one([blue], [member()], blue)
        self.assertEqual(d.route, SELL_VENDOR)
        self.assertTrue(d.confirm)


class Destroy(unittest.TestCase):
    def test_only_the_item_with_no_price_and_no_use_is_destroyed(self):
        junk = stack(entry=90, name="Used Scrap", item_class=15, sell=0)
        priced = stack(entry=91, name="Vendor Trinket", item_class=15, sell=40)
        blue = stack(
            entry=92,
            item_class=4,
            subclass=0,
            quality=3,
            sell=0,
            bind=1,
            req_level=5,
            item_level=9,
        )
        quest = stack(entry=93, item_class=12, sell=0, bind=4)
        tight = member(bank_slots=itemplan.BANK_RESERVE)  # no bank room at all
        by_key, _ = decide([junk, priced, blue, quest], [tight])
        destroyed = [d.name for d in by_key.values() if d.route == DESTROY]
        self.assertEqual(destroyed, ["Used Scrap"])

    def test_bank_is_preferred_to_destroy_when_it_has_room(self):
        junk = stack(entry=90, name="Used Scrap", item_class=15, sell=0)
        d = one([junk], [member()], junk)
        self.assertEqual(d.route, BANK_PERSONAL)


class Auction(unittest.TestCase):
    def test_vendor_is_the_floor_without_a_price(self):
        s = stack(entry=95, item_class=15, sell=1000, count=1)
        d = one([s], [member()], s)
        self.assertEqual(d.route, SELL_VENDOR)

    def test_a_price_over_the_margin_lists_it_and_holds_down_to_three(self):
        s = stack(entry=95, item_class=15, sell=1000, count=3)
        ctx = Context(market={95: (4400, 5)})
        self.assertEqual(one([s], [member()], s, ctx).route, AUCTION)
        weak = Context(market={95: (3400, 5)})
        self.assertEqual(one([s], [member()], s, weak).route, SELL_VENDOR)
        held = Context(market={95: (3400, 5)}, previous={("Ana", 95): AUCTION})
        self.assertEqual(one([s], [member()], s, held).route, AUCTION)


class Raid(unittest.TestCase):
    def test_raid_reagent_goes_to_the_raid_tab(self):
        dreamfoil = stack(
            entry=13463, name="Dreamfoil", item_class=7, subclass=9, sell=300, count=10
        )
        ctx = Context(guild_free={("Fam", itemplan.GUILD_TAB_RAID): 3})
        d = one([dreamfoil], [member()], dreamfoil, ctx)
        self.assertEqual((d.route, d.tab), (GUILD_BANK, itemplan.GUILD_TAB_RAID))

    def test_full_raid_tab_banks_rather_than_sells(self):
        dreamfoil = stack(
            entry=13463, name="Dreamfoil", item_class=7, subclass=9, sell=300, count=10
        )
        d = one([dreamfoil], [member()], dreamfoil)
        self.assertEqual(d.route, BANK_PERSONAL)


class Stability(unittest.TestCase):
    def rows(self):
        return [
            stack(
                entry=2321,
                name="Fine Thread",
                item_class=7,
                subclass=5,
                sell=25,
                count=20,
            ),
            stack(
                entry=6260,
                name="Blue Dye",
                item_class=7,
                subclass=11,
                sell=12,
                count=10,
            ),
            stack(
                entry=4305,
                name="Bolt of Silk Cloth",
                item_class=7,
                subclass=5,
                sell=500,
                count=5,
            ),
            stack(
                entry=80,
                item_class=4,
                subclass=0,
                quality=2,
                sell=900,
                bind=2,
                req_level=20,
                item_level=25,
            ),
            stack(entry=90, name="Used Scrap", item_class=15, sell=0),
        ]

    def test_same_input_same_plan(self):
        m = [member(skills=[(TAILORING, 145, 225)], carried_slots=13)]
        rows = self.rows()
        a = itemplan.plan(rows, m)
        b = itemplan.plan(list(reversed(rows)), m)
        self.assertEqual(a.decisions, b.decisions)

    def test_no_flip_flop_when_a_slot_frees_up(self):
        m = [member(skills=[(TAILORING, 145, 225)], carried_slots=13)]
        rows = self.rows()
        first = itemplan.plan(rows, m)
        ctx = Context(previous=first.routes())
        # The executor left one row behind and the bag gained a slot: free slots
        # cross the trigger, and no stack's route changes.
        roomy = [member(skills=[(TAILORING, 145, 225)], carried_slots=15)]
        second = itemplan.plan(rows, roomy, ctx)
        self.assertEqual(first.routes(), second.routes())

    def test_planned_sale_is_not_undone_by_a_discretionary_goal(self):
        food = stack(
            entry=1487,
            name="Conjured Pumpernickel",
            item_class=0,
            subclass=5,
            sell=50,
            count=18,
        )
        ctx = Context(previous={("Ana", 1487): SELL_VENDOR})
        self.assertEqual(one([food], [member()], food, ctx).route, SELL_VENDOR)
        self.assertEqual(one([food], [member()], food).route, KEEP_CARRY)

    def test_planned_sale_yields_to_a_real_need(self):
        thread = stack(entry=2321, item_class=7, subclass=5, sell=25, count=20)
        m = [member(skills=[(TAILORING, 145, 225)])]
        ctx = Context(previous={("Ana", 2321): SELL_VENDOR})
        self.assertEqual(one([thread], m, thread, ctx).route, KEEP_CARRY)


# Zork's blue stacks in the 2026-11-07 dump: (entry, name, class, subclass,
# loc, count, sell, bind, required level, item level). A level 54 druid.
ZORK_BLUES = [
    (3230, "Black Wolf Bracers", 4, 2, "bank", 1, 922, 1, 20, 26),
    (6319, "Girdle of the Blindwatcher", 4, 2, "bank", 1, 964, 1, 19, 26),
    (12979, "Firebane Cloak", 4, 1, "bank", 1, 617, 2, 16, 21),
    (6314, "Wolfmaster Cape", 4, 1, "bank", 1, 1217, 1, 20, 27),
    (6318, "Odo's Ley Staff", 2, 10, "bank", 1, 4803, 1, 21, 26),
    (14148, "Crystalline Cuffs", 4, 1, "bank", 1, 250, 1, 13, 18),
    (9389, "Revelosh's Spaulders", 4, 2, "bank_bag", 1, 5198, 1, 36, 41),
    (17740, "Soothsayer's Headdress", 4, 2, "carried_bag", 1, 11401, 1, 46, 52),
    (17737, "Cloud Stone", 4, 0, "carried_bag", 1, 10163, 1, 48, 53),
    (17740, "Soothsayer's Headdress", 4, 2, "carried_bag", 1, 11401, 1, 46, 52),
    (17707, "Gemshard Heart", 4, 0, "carried_bag", 1, 11631, 1, 48, 54),
    (10776, "Silky Spider Cape", 4, 1, "bank_bag", 1, 4800, 1, 35, 42),
    (9449, "Manual Crowd Pummeler", 2, 5, "bank_bag", 1, 9564, 1, 28, 34),
    (13045, "Viscous Hammer", 2, 5, "bank_bag", 1, 10809, 2, 30, 35),
    (9390, "Revelosh's Gloves", 4, 1, "bank_bag", 1, 2576, 1, 35, 40),
    (9398, "Worn Running Boots", 4, 2, "bank_bag", 1, 1493, 1, 35, 40),
    (17750, "Chloromesh Girdle", 4, 1, "carried_bag", 1, 6115, 1, 46, 51),
    (13093, "Blush Ember Ring", 4, 0, "carried_bag", 1, 3381, 2, 32, 37),
    (18082, "Zum'rah's Vexing Cane", 2, 10, "carried_bag", 1, 28161, 1, 42, 47),
    (13084, "Kaleidoscope Chain", 4, 0, "carried_bag", 1, 6614, 2, 30, 35),
    (9479, "Embrace of the Lycan", 4, 2, "carried_bag", 1, 10858, 1, 45, 50),
    (18083, "Jumanza Grips", 4, 1, "carried_bag", 1, 4522, 1, 42, 47),
    (11310, "Flameseer Mantle", 4, 1, "bank_bag", 1, 6598, 1, 40, 47),
    (9479, "Embrace of the Lycan", 4, 2, "bank_bag", 1, 10858, 1, 45, 50),
]


class ZorkBlues(unittest.TestCase):
    def setUp(self):
        self.rows = [
            Stack("Zork", loc, e, n, c, sub, 3, cnt, sell, bind, rl, il, 1, i)
            for i, (e, n, c, sub, loc, cnt, sell, bind, rl, il) in enumerate(ZORK_BLUES)
        ]
        self.zork = Member("Zork", "Zug", 54, DRUID, ((LEATHERWORKING, 1, 75),), 64, 78)
        self.plan = itemplan.plan(self.rows, [self.zork])
        self.by_name = {}
        for d in self.plan.decisions:
            self.by_name.setdefault(d.name, []).append(d)

    def test_nothing_is_destroyed(self):
        self.assertFalse([d for d in self.plan.decisions if d.route == DESTROY])

    def test_every_blue_sale_waits_for_a_release(self):
        sales = [d for d in self.plan.decisions if d.route == SELL_VENDOR]
        self.assertTrue(sales)
        self.assertTrue(all(d.confirm and d.refusable for d in sales))

    def test_the_levelled_leather_set_is_banked_not_sold(self):
        for name in ("Embrace of the Lycan", "Soothsayer's Headdress"):
            for d in self.by_name[name]:
                self.assertEqual(d.route, BANK_PERSONAL, name)

    def test_the_outgrown_staff_and_cloth_go_to_the_vendor(self):
        # Level 42 staff and cloth the druid cannot wear at its level.
        self.assertEqual(self.by_name["Zum'rah's Vexing Cane"][0].route, SELL_VENDOR)
        self.assertEqual(self.by_name["Chloromesh Girdle"][0].route, SELL_VENDOR)

    def test_the_spare_set_is_capped(self):
        banked = [
            d
            for d in self.plan.decisions
            if d.rule == "R4" and d.route == BANK_PERSONAL
        ]
        self.assertLessEqual(len(banked), itemplan.SPARE_SET_MAX)


class Shapes(unittest.TestCase):
    def test_every_decision_has_a_reason_goal_and_rule(self):
        rows = Stability().rows()
        plan = itemplan.plan(rows, [member(skills=[(TAILORING, 145, 225)])])
        self.assertEqual(len(plan.decisions), len(rows))
        for d in plan.decisions:
            self.assertTrue(d.reason and d.goal in itemplan.TIER and d.rule)
            self.assertIn(d.route, itemplan.ROUTES)

    def test_worn_bags_and_keys_stay(self):
        bag = stack(loc="equipped_or_other", item_class=1, entry=14046, item_level=52)
        d = one([bag], [member()], bag)
        self.assertEqual(d.route, KEEP_CARRY)

    def test_capacities_split_carried_and_bank_bags(self):
        worn = [
            stack(loc="equipped_or_other", item_class=1, entry=14046, item_level=52)
            for _ in range(4)
        ] + [stack(loc="equipped_or_other", item_class=1, entry=4499, item_level=35)]
        carried, bank, empty, _ = itemplan.capacities(worn, 2)
        self.assertEqual((carried, bank, empty), (16 + 4 * 14, 28 + 12, 1))


if __name__ == "__main__":
    unittest.main()
