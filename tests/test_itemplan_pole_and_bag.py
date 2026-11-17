"""The item plan keeps a fisher's pole and a bag bigger than a worn one (#2274).

The plan sent two kinds of item to the vendor that a player would never sell:

  * a fishing pole. It is not in `disposition.TOOL_TRADES`, so the tool rule
    never saw it and the gear rule sold it as a weapon nobody will wear.
  * a carried bag. The spare-bag rule sells a bag "no bigger than a worn
    one", and the seam that builds the plan gave it no worn bags, so that
    held for every carried bag, one bigger than the worn bags included.

These tests hold the plan's two rules, the seam that hands the plan each
member's worn bags and the family's fishers, the reads behind them, and the
tick line that counts what the two rules kept.
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan  # noqa: E402
import itemplan_data  # noqa: E402
import itemplan_reads as reads  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
from itemplan import (  # noqa: E402
    BANK_PERSONAL,
    GIVE,
    KEEP_CARRY,
    SELL_VENDOR,
    Context,
)
from tests.test_itemplan import member, one, stack  # noqa: E402
from tests.test_itemplan_reads import FakeConn, FakeCursor  # noqa: E402
from tests.test_itemplan_shadow import Capture, row  # noqa: E402

FISHING = itemplan.FISHING
POLE_ENTRY, BAG_ENTRY = 6256, 4497
ON = {"ITEMPLAN_SHADOW": "on"}
WORN_BAGS_MARKER = "SELECT c.name AS member, ci.slot AS slot, it.ContainerSlots"


def pole(holder="Ana", **kw):
    base = dict(
        entry=POLE_ENTRY,
        name="Fishing Pole",
        item_class=itemplan.C_WEAPON,
        subclass=itemplan.FISHING_POLE_SUBCLASS,
        sell=100,
    )
    base.update(kw)
    return stack(holder=holder, **base)


def bag(slots, holder="Ana", **kw):
    base = dict(
        entry=BAG_ENTRY,
        name="Heavy Brown Bag",
        item_class=itemplan.C_CONTAINER,
        sell=400,
        container_slots=slots,
    )
    base.update(kw)
    return stack(holder=holder, **base)


class AFishingPoleIsATool(unittest.TestCase):
    def test_the_holder_fishes_so_the_pole_is_kept(self):
        p = pole()
        d = one([p], [member(skills=[(FISHING, 75, 150)])], p)
        self.assertEqual((d.route, d.goal, d.rule), (KEEP_CARRY, itemplan.TOOLS, "R5"))

    def test_a_fisher_named_by_the_seam_keeps_it_too(self):
        # The seam's skills leave fishing out; it names the fishers instead.
        p = pole()
        d = one([p], [member()], p, Context(fishers=frozenset({"Ana"})))
        self.assertEqual((d.route, d.goal), (KEEP_CARRY, itemplan.TOOLS))

    def test_a_family_member_fishes_so_the_pole_goes_to_it_never_the_vendor(self):
        p = pole()
        family = [member(), member("Bo", skills=[(FISHING, 1, 75)])]
        d = one([p], family, p)
        self.assertEqual((d.route, d.target), (GIVE, "Bo"))
        self.assertNotIn(SELL_VENDOR, d.options)
        named = one([p], [member(), member("Bo")], p, Context(fishers={"Bo"}))
        self.assertEqual((named.route, named.target), (GIVE, "Bo"))

    def test_a_bound_pole_in_a_fishing_family_is_banked_not_sold(self):
        p = pole(soulbound=True, bind=1)
        family = [member(), member("Bo", skills=[(FISHING, 1, 75)])]
        d = one([p], family, p)
        self.assertEqual(d.route, BANK_PERSONAL)
        self.assertNotIn(SELL_VENDOR, d.options)

    def test_in_a_family_where_nobody_fishes_the_tool_rule_leaves_it(self):
        p = pole()
        d = one([p], [member(), member("Bo")], p)
        self.assertNotEqual(d.rule, "R5")
        self.assertFalse(d.reason.startswith(itemplan.FISHING_POLE_PREFIX))

    def test_a_pole_is_told_by_class_and_subclass(self):
        self.assertTrue(itemplan.fishing_pole(pole()))
        self.assertFalse(itemplan.fishing_pole(pole(subclass=7)))
        self.assertFalse(itemplan.fishing_pole(pole(item_class=itemplan.C_ARMOR)))


class ACarriedBagAgainstTheWornOnes(unittest.TestCase):
    WORN = {"Ana": (16, 16, 14, 10)}

    def decide(self, slots, worn_bags):
        b = bag(slots)
        return one([b], [member()], b, Context(worn_bags=worn_bags))

    def test_a_bag_bigger_than_the_smallest_worn_one_is_kept(self):
        d = self.decide(12, self.WORN)
        self.assertEqual((d.route, d.rule), (KEEP_CARRY, "R2"))
        self.assertEqual(d.reason, itemplan.BIGGER_BAG_REASON)

    def test_a_bag_no_bigger_than_every_worn_one_is_still_a_spare(self):
        for slots in (10, 6):
            d = self.decide(slots, self.WORN)
            self.assertEqual((d.route, d.rule), (SELL_VENDOR, "R2"), slots)
            self.assertIn("spare bag", d.reason)

    def test_fewer_than_four_worn_bags_still_compare(self):
        d = self.decide(16, {"Ana": (6, 6)})
        self.assertEqual(d.reason, itemplan.BIGGER_BAG_REASON)
        self.assertEqual(self.decide(6, {"Ana": (6, 6)}).route, SELL_VENDOR)

    def test_a_member_wearing_no_bag_keeps_it(self):
        d = self.decide(6, {"Ana": ()})
        self.assertEqual((d.route, d.reason), (KEEP_CARRY, itemplan.NO_WORN_BAG_REASON))

    def test_unread_worn_bags_keep_the_bag(self):
        # Nothing read at all, and a read that does not name the holder.
        for worn_bags in (None, {}, {"Bo": (16,)}):
            d = self.decide(6, worn_bags)
            self.assertEqual(
                (d.route, d.reason), (KEEP_CARRY, itemplan.UNREAD_BAGS_REASON)
            )

    def test_worn_bags_among_the_stacks_still_count(self):
        worn = [
            stack(
                loc=itemplan.WORN,
                item_class=itemplan.C_CONTAINER,
                entry=14046,
                container_slots=14,
            )
            for _ in range(4)
        ]
        small, big = bag(10), bag(16)
        self.assertEqual(one(worn + [small], [member()], small).route, SELL_VENDOR)
        self.assertEqual(one(worn + [big], [member()], big).route, KEEP_CARRY)

    def test_the_plan_counts_what_the_two_rules_kept(self):
        stacks = [bag(12), bag(10), pole()]
        plan = itemplan.plan(
            stacks,
            [member()],
            Context(worn_bags=self.WORN, fishers=frozenset({"Ana"})),
        )
        self.assertEqual(itemplan.kept_for_use(plan), (1, 1))
        none = itemplan.plan([bag(10)], [member()], Context(worn_bags=self.WORN))
        self.assertEqual(itemplan.kept_for_use(none), (0, 0))


# ---- the seam that builds the plan -------------------------------------------

WORN_ROWS = [{"name": "Ana", "class_id": 8, "level": 54}]
BAG_ROW = row("Ana", 19, BAG_ENTRY, "Heavy Brown Bag", sell=400, item_class=1)
POLE_ROW = row("Ana", 20, POLE_ENTRY, "Fishing Pole", sell=100, item_class=2)


def extras(slots=12, **kw):
    return shadow.Extras(
        templates={
            BAG_ENTRY: {
                "subclass": 0,
                "bonding": 0,
                "req_level": 1,
                "item_level": 5,
                "container_slots": slots,
            },
            POLE_ENTRY: {
                "subclass": itemplan.FISHING_POLE_SUBCLASS,
                "bonding": 0,
                "req_level": 1,
                "item_level": 5,
            },
        },
        instance_soulbound={19: False, 20: False},
        open_quest_items={},
        fire_gear=frozenset(),
        **kw,
    )


def shadowed(rows, ex):
    report = shadow.shadow(
        ["Ana"], "Fam", rows, {"Ana": 5}, worn_rows=WORN_ROWS, extras=ex
    )
    return report, {d.entry: d for d in report.plan.decisions}


class TheSeamGivesThePlanTheWornBags(unittest.TestCase):
    def test_the_worn_bags_reach_the_plan(self):
        _rep, kept = shadowed([BAG_ROW], extras(12, worn_bags={"Ana": (16, 14, 10)}))
        self.assertEqual(kept[BAG_ENTRY].route, KEEP_CARRY)
        self.assertEqual(kept[BAG_ENTRY].reason, itemplan.BIGGER_BAG_REASON)
        _rep, spare = shadowed([BAG_ROW], extras(10, worn_bags={"Ana": (16, 14, 10)}))
        self.assertEqual(spare[BAG_ENTRY].route, SELL_VENDOR)

    def test_the_context_carries_both_reads(self):
        ex = extras(worn_bags={"Ana": (16,)}, fishers=frozenset({"Ana"}))
        ctx = shadow._context(ex, {})
        self.assertEqual(ctx.worn_bags, {"Ana": (16,)})
        self.assertEqual(ctx.fishers, frozenset({"Ana"}))

    def test_an_unread_bag_read_keeps_the_bag_and_is_named(self):
        report, by_entry = shadowed([BAG_ROW], extras(12))
        self.assertEqual(by_entry[BAG_ENTRY].route, KEEP_CARRY)
        self.assertEqual(by_entry[BAG_ENTRY].reason, itemplan.UNREAD_BAGS_REASON)
        self.assertIn(shadow.WORN_BAGS, report.missing)
        read, _ = shadowed([BAG_ROW], extras(12, worn_bags={"Ana": ()}))
        self.assertNotIn(shadow.WORN_BAGS, read.missing)
        self.assertIn(shadow.WORN_BAGS, shadow.INPUTS)

    def test_the_familys_fishers_reach_the_plan(self):
        _rep, kept = shadowed([POLE_ROW], extras(fishers=frozenset({"Ana"})))
        self.assertEqual(kept[POLE_ENTRY].route, KEEP_CARRY)
        _rep, sold = shadowed([POLE_ROW], extras(fishers=frozenset()))
        self.assertNotEqual(sold[POLE_ENTRY].rule, "R5")

    def test_the_tick_line_counts_the_bags_and_poles_it_kept(self):
        shadow.reset()
        cap = Capture()
        shadow.run(
            ["Ana"],
            "Fam",
            [BAG_ROW, POLE_ROW],
            {"Ana": 5},
            environ=ON,
            logger=cap,
            worn_rows=WORN_ROWS,
            extras=extras(
                12, worn_bags={"Ana": (16, 14, 10)}, fishers=frozenset({"Ana"})
            ),
        )
        tick = [x for x in cap.lines if " tick: " in x]
        self.assertEqual(len(tick), 1)
        self.assertIn("kept for use: bigger bags 1, fishing poles 1", tick[0])
        shadow.reset()


# ---- the reads ----------------------------------------------------------------


class TheWornBagRead(unittest.TestCase):
    def test_the_query_reads_the_four_bag_positions(self):
        sql = itemplan_data.WORN_BAGS_SQL
        self.assertTrue(sql.startswith(WORN_BAGS_MARKER))
        self.assertIn("ci.bag = 0 AND ci.slot BETWEEN 19 AND 22", sql)
        self.assertIn("c.name IN (%s)", sql)

    def test_the_query_parses_as_mysql(self):
        try:
            import sqlglot
        except ImportError:
            self.skipTest("sqlglot not installed")
        sqlglot.parse_one(itemplan_data.WORN_BAGS_SQL % "'Ana', 'Bo'", read="mysql")

    def test_rows_become_sizes_per_member_largest_first(self):
        rows = [
            {"member": "Ana", "slot": 19, "container_slots": 10},
            {"member": "Ana", "slot": 21, "container_slots": 16},
            {"member": "Zed", "slot": 19, "container_slots": 12},
            {"member": "Ana", "slot": 20, "container_slots": None},
            {"member": "Ana", "slot": 22},
        ]
        self.assertEqual(
            itemplan_data.worn_bags(rows, ["Ana", "Bo"]), {"Ana": (16, 10), "Bo": ()}
        )
        self.assertEqual(itemplan_data.worn_bags(None, ["Ana"]), {"Ana": ()})


def read_with(cur, roster=None):
    return reads.read(
        ["Ana", "Bo"],
        "Fam",
        [BAG_ROW],
        (),
        WORN_ROWS,
        connect=lambda: FakeConn(cur),
        bank_rows=lambda names: [],
        guild_setup=lambda names: None,
        roster=roster or (lambda names: []),
    )


def roster_member(name, family, skills):
    return SimpleNamespace(
        name=name,
        family=family,
        online=True,
        class_id=8,
        level=54,
        rank_in=lambda line: skills.get(line, 0),
    )


class TheReadsBehindTheSeam(unittest.TestCase):
    def test_the_worn_bags_are_read_for_every_member(self):
        cur = FakeCursor(
            tables={
                WORN_BAGS_MARKER: [
                    {"member": "Ana", "slot": 19, "container_slots": 16},
                    {"member": "Ana", "slot": 20, "container_slots": 10},
                ]
            }
        )
        ex = read_with(cur)
        self.assertEqual(ex.worn_bags, {"Ana": (16, 10), "Bo": ()})
        self.assertNotIn(shadow.WORN_BAGS, ex.unread)
        asked = [(sql, params) for sql, params in cur.executed if "BETWEEN 19" in sql]
        self.assertEqual(len(asked), 1)
        self.assertEqual(list(asked[0][1]), ["Ana", "Bo"])

    def test_a_failed_bag_read_is_unread_not_empty(self):
        ex = read_with(FakeCursor(fail=(WORN_BAGS_MARKER,)))
        self.assertIsNone(ex.worn_bags)
        self.assertEqual(ex.unread[shadow.WORN_BAGS], "read failed: RuntimeError")
        # The other inputs of the same cursor were still read.
        self.assertIsNotNone(ex.worn)

    def test_the_roster_names_the_family_members_who_fish(self):
        roster = [
            roster_member("Ana", True, {FISHING: 120}),
            roster_member("Bo", True, {197: 200}),
            roster_member("Guildmate", False, {FISHING: 300}),
        ]
        ex = read_with(FakeCursor(), roster=lambda names: roster)
        self.assertEqual(ex.fishers, frozenset({"Ana"}))
        # Fishing stays out of the trade skills the plan stocks reagents for.
        self.assertEqual(ex.family_skills["Ana"], ())

    def test_an_unread_roster_names_no_fishers(self):
        self.assertIsNone(read_with(FakeCursor()).fishers)


if __name__ == "__main__":
    unittest.main()
