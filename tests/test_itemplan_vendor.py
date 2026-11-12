"""The item plan's vendor-sale route (#1977): carried out, not just logged.

Fixture rows are shaped like the economy pass's carried query rows, the
same shape `tests/test_itemplan_shadow.py` uses, and the plan under test
is the one `itemplan_shadow.shadow` builds from them.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bag_pressure  # noqa: E402
import itemplan  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402
import itemplan_vendor as vendor  # noqa: E402

ON = {"ITEMPLAN_SELL_VENDOR": "on"}


def row(holder, guid, entry, name, quality=1, count=1, sell=50, item_class=15, **kw):
    base = {
        "holder": holder,
        "item_guid": guid,
        "entry": entry,
        "name": name,
        "quality": quality,
        "count": count,
        "sell_price": sell,
        "item_class": item_class,
        "bag_family": 0,
        "quest_item": False,
        "reagent": False,
        "profession_needed": False,
    }
    base.update(kw)
    return base


def pairs(rows, gear=()):
    stacks = shadow.build_stacks(rows, gear)
    return list(zip(stacks, rows, strict=True))


def plan_and_pairs(rows, gear=(), worn=(), free=None):
    # The soulbound flags are read, as `itemplan_reads` reads them: a stack
    # whose flag was never read is kept by rule R1, failing closed.
    extras = shadow.Extras(
        instance_soulbound={int(r["item_guid"]): False for r in rows},
        fire_gear=frozenset(),
    )
    report = shadow.shadow(
        sorted({r["holder"] for r in rows}),
        "Fam",
        rows,
        free or {},
        gear_rows=gear,
        worn_rows=worn,
        extras=extras,
    )
    return report.plan, pairs(rows, gear)


def green_cloak():
    rows = [
        row("Ana", 4, 7777, "Plain Green Cloak", quality=2, sell=4000, item_class=4)
    ]
    gear = [
        {
            "holder": "Ana",
            "item_guid": 4,
            "entry": 7777,
            "name": "Plain Green Cloak",
            "quality": 2,
            "sell_price": 4000,
            "item_class": 4,
            "item_subclass": 4,
            "bonding": 0,
            "required_level": 50,
            "item_level": 40,
            "level": 54,
        }
    ]
    worn = [{"name": "Ana", "class_id": 8, "level": 54}]
    return rows, gear, worn, {"Ana": 3}


class SwitchTest(unittest.TestCase):
    def test_switch_is_off_by_default(self):
        self.assertFalse(vendor.enabled({}))
        self.assertFalse(vendor.enabled({"ITEMPLAN_SELL_VENDOR": "off"}))
        self.assertTrue(vendor.enabled(ON))


class SalesForTest(unittest.TestCase):
    def test_kept_green_the_plan_sells_is_a_route_sale(self):
        rows, gear, worn, free = green_cloak()
        # The current protection keeps it: uncommon or better.
        self.assertNotEqual(bag_pressure.vendor_refusal(rows[0]), "")
        plan_, prs = plan_and_pairs(rows, gear, worn, free)
        sales = vendor.sales_for(plan_, prs)
        self.assertEqual(len(sales), 1)
        sale = sales[0]
        self.assertEqual(
            (sale.holder, sale.name, sale.copper), ("Ana", "Plain Green Cloak", 4000)
        )
        self.assertIsInstance(sale.candidate, bag_pressure.SellCandidate)
        self.assertEqual((sale.candidate.item_guid, sale.candidate.count), (4, 1))
        self.assertEqual(sale.key, prs[0][0].key)
        self.assertEqual(sale.candidate.holder, "Ana")

    def test_a_stack_the_current_pass_already_sells_is_not_the_routes(self):
        # A grey junk stack: the sale pass sells it itself, so the route,
        # which acts only where the current protection would keep a stack,
        # must leave it to that pass even when the plan also sells it.
        rows = [row("Ana", 1, 1111, "Broken Fang", quality=0, sell=30)]
        self.assertEqual(bag_pressure.vendor_refusal(rows[0]), "")
        plan_, prs = plan_and_pairs(rows, free={"Ana": 3})
        routes = [d.route for d in plan_.decisions]
        if itemplan.SELL_VENDOR in routes:
            self.assertEqual(vendor.sales_for(plan_, prs), ())

    def test_confirm_sale_waits_for_a_release(self):
        # A value of 1 gold or more marks a sale `confirm`:
        # it is carried out only when its key is in the released set.
        rows = [row("Ana", 9, 8888, "Green Sword", quality=2, sell=20000, item_class=2)]
        gear = [
            {
                "holder": "Ana",
                "item_guid": 9,
                "entry": 8888,
                "name": "Green Sword",
                "quality": 2,
                "sell_price": 20000,
                "item_class": 2,
                "item_subclass": 0,
                "bonding": 0,
                "required_level": 50,
                "item_level": 40,
                "level": 54,
            }
        ]
        worn = [{"name": "Ana", "class_id": 8, "level": 54}]
        plan_, prs = plan_and_pairs(rows, gear, worn, {"Ana": 3})
        confirms = [d for d in plan_.decisions if d.route == itemplan.SELL_VENDOR]
        if not confirms:
            self.skipTest("fixture did not plan a vendor sale")
        self.assertTrue(all(d.confirm for d in confirms))
        self.assertEqual(vendor.sales_for(plan_, prs), ())
        released = frozenset(d.key for d in confirms)
        sales = vendor.sales_for(plan_, prs, released=released)
        self.assertEqual(len(sales), len(confirms))


def fallback_fixture(
    options, value=4000, item_class=4, subclass=0, name="Plain Green Cloak"
):
    """One carried green and a plan whose only decision sells it."""
    item = row("Ana", 4, 7777, name, quality=2, sell=4000, item_class=item_class)
    key = ("Ana", 7777, 0)
    decision = itemplan.Decision(
        holder="Ana",
        entry=7777,
        name=name,
        count=1,
        from_loc=itemplan.CARRIED_BAG,
        route=itemplan.SELL_VENDOR,
        goal=itemplan.ROOM,
        reason="sold",
        rule="R8",
        value=value,
        irreversible=True,
        refusable=True,
        key=key,
        options=options,
    )
    plan_ = types.SimpleNamespace(decisions=(decision,))
    stack = types.SimpleNamespace(key=key, item_class=item_class, subclass=subclass)
    return plan_, [(stack, item)], item


class FallbackSaleTest(unittest.TestCase):
    def test_a_sale_chosen_after_a_better_route_failed_is_held_back(self):
        plan_, prs, _ = fallback_fixture((itemplan.GUILD_BANK, itemplan.SELL_VENDOR))
        held = []
        self.assertEqual(vendor.sales_for(plan_, prs, held=held), ())
        self.assertEqual(
            [(d.name, why) for d, why in held],
            [("Plain Green Cloak", vendor.HELD_FALLBACK)],
        )

    def test_a_valuable_fallback_sale_is_held_back_too(self):
        plan_, prs, _ = fallback_fixture(
            (itemplan.GUILD_BANK, itemplan.SELL_VENDOR), value=900000
        )
        held = []
        self.assertEqual(
            vendor.sales_for(
                plan_, prs, released=frozenset([prs[0][0].key]), held=held
            ),
            (),
        )
        self.assertEqual([why for _d, why in held], [vendor.HELD_FALLBACK])

    def test_a_sale_that_was_the_first_choice_still_goes_out(self):
        for options in ((itemplan.SELL_VENDOR, itemplan.BANK_PERSONAL), ()):
            with self.subTest(options=options):
                plan_, prs, _ = fallback_fixture(options)
                held = []
                self.assertEqual(len(vendor.sales_for(plan_, prs, held=held)), 1)
                self.assertEqual(held, [])

    def test_the_held_back_line_names_the_holder_count_and_stacks(self):
        plan_, prs, _ = fallback_fixture((itemplan.GUILD_BANK, itemplan.SELL_VENDOR))
        held = []
        vendor.sales_for(plan_, prs, held=held)
        self.assertEqual(
            vendor.held_lines(held),
            (
                "itemplan vendor: Ana holds back 1 sale(s): Plain Green Cloak (%s)"
                % vendor.HELD_FALLBACK,
            ),
        )


def held_fixture(*specs):
    """Several carried stacks the plan sells but the route holds back.

    Each spec is a dict: entry, value, and optionally holder, quality, confirm,
    options, item_class and subclass. A confirm stack is a first choice that
    needs a release; the default options make it a fallback sale instead.
    """
    decisions, pairs_ = [], []
    for spec in specs:
        holder = spec.get("holder", "Ana")
        entry = spec["entry"]
        quality = spec.get("quality", 2)
        item_class = spec.get("item_class", 4)
        key = (holder, entry, 0)
        options = spec.get("options", (itemplan.GUILD_BANK, itemplan.SELL_VENDOR))
        decisions.append(
            itemplan.Decision(
                holder=holder,
                entry=entry,
                name="Stack %d" % entry,
                count=1,
                from_loc=itemplan.CARRIED_BAG,
                route=itemplan.SELL_VENDOR,
                goal=itemplan.ROOM,
                reason="sold",
                rule="R8",
                value=spec["value"],
                irreversible=True,
                refusable=True,
                confirm=spec.get("confirm", False),
                key=key,
                options=options,
            )
        )
        stack = types.SimpleNamespace(
            key=key, item_class=item_class, subclass=spec.get("subclass", 0)
        )
        item = row(
            holder,
            entry,
            entry,
            "Stack %d" % entry,
            quality=quality,
            sell=spec["value"],
            item_class=item_class,
        )
        pairs_.append((stack, item))
    return types.SimpleNamespace(decisions=tuple(decisions)), pairs_


FIRST = (itemplan.SELL_VENDOR, itemplan.BANK_PERSONAL)


class PressureReleaseTest(unittest.TestCase):
    """A member short of room gets a bounded release of held sales."""

    def entries(self, sales):
        return sorted(s.candidate.item_guid for s in sales)

    def test_without_pressure_held_sales_stay_held(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=3000, confirm=True, options=FIRST),
            dict(entry=2, value=1000),
        )
        held = []
        self.assertEqual(vendor.sales_for(plan_, prs, held=held), ())
        self.assertEqual(vendor.sales_for(plan_, prs, pressure={}), ())
        self.assertEqual(vendor.sales_for(plan_, prs, pressure={"Ana": 0}), ())

    def test_pressure_releases_the_cheapest_stacks_and_no_more_than_needed(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=3000, confirm=True, options=FIRST),
            dict(entry=2, value=1000, confirm=True, options=FIRST),
            dict(entry=3, value=2000),
        )
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 2})
        self.assertEqual(self.entries(sales), [2, 3])
        one = vendor.sales_for(plan_, prs, pressure={"Ana": 1})
        self.assertEqual(self.entries(one), [2])

    def test_a_released_fallback_sale_leaves_the_held_list(self):
        plan_, prs = held_fixture(dict(entry=1, value=1500), dict(entry=2, value=9000))
        held = []
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 1}, held=held)
        self.assertEqual(self.entries(sales), [1])
        self.assertEqual([d.entry for d, _why in held], [2])

    def test_released_sales_are_marked_for_the_log(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=1000, confirm=True, options=FIRST),
            dict(entry=2, value=2000),
        )
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 2})
        kinds = {s.candidate.item_guid: s.released for s in sales}
        self.assertEqual(
            kinds, {1: vendor.RELEASED_CONFIRM, 2: vendor.RELEASED_FALLBACK}
        )

    def test_a_stack_above_the_value_ceiling_stays_held(self):
        over = vendor.RELEASE_CEILING_COPPER + 1
        plan_, prs = held_fixture(
            dict(entry=1, value=over, confirm=True, options=FIRST),
            dict(entry=2, value=over),
        )
        held = []
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 5}, held=held)
        self.assertEqual(sales, ())
        self.assertEqual([d.entry for d, _why in held], [2])

    def test_a_stack_at_the_ceiling_is_still_released(self):
        plan_, prs = held_fixture(
            dict(
                entry=1,
                value=vendor.RELEASE_CEILING_COPPER,
                confirm=True,
                options=FIRST,
            )
        )
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 1})
        self.assertEqual(self.entries(sales), [1])

    def test_epic_quality_is_never_released(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=100, quality=4, confirm=True, options=FIRST),
            dict(entry=2, value=100, quality=5),
        )
        self.assertEqual(vendor.sales_for(plan_, prs, pressure={"Ana": 5}), ())

    def test_a_bag_and_a_tool_are_never_released(self):
        for confirm in (False, True):
            with self.subTest(confirm=confirm):
                plan_, prs = held_fixture(
                    dict(
                        entry=1,
                        value=100,
                        item_class=itemplan.C_CONTAINER,
                        confirm=confirm,
                        options=FIRST,
                    ),
                    dict(
                        entry=2,
                        value=100,
                        item_class=itemplan.C_WEAPON,
                        subclass=20,
                        confirm=confirm,
                        options=FIRST,
                    ),
                )
                held = []
                sales = vendor.sales_for(plan_, prs, pressure={"Ana": 5}, held=held)
                self.assertEqual(sales, ())
                if not confirm:
                    self.assertEqual(
                        sorted(why for _d, why in held),
                        sorted([vendor.HELD_BAG, vendor.HELD_TOOL]),
                    )

    def test_only_the_holder_under_pressure_releases(self):
        plan_, prs = held_fixture(
            dict(holder="Ana", entry=1, value=100, confirm=True, options=FIRST),
            dict(holder="Bob", entry=2, value=100, confirm=True, options=FIRST),
        )
        sales = vendor.sales_for(plan_, prs, pressure={"Bob": 1})
        self.assertEqual([s.holder for s in sales], ["Bob"])

    def test_each_holder_has_its_own_pressure(self):
        plan_, prs = held_fixture(
            dict(holder="Ana", entry=1, value=100, confirm=True, options=FIRST),
            dict(holder="Ana", entry=2, value=200, confirm=True, options=FIRST),
            dict(holder="Bob", entry=3, value=100, confirm=True, options=FIRST),
            dict(holder="Bob", entry=4, value=200, confirm=True, options=FIRST),
        )
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 1, "Bob": 2})
        self.assertEqual(self.entries(sales), [1, 3, 4])

    def test_ordinary_route_sales_count_against_the_pressure(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=500, options=FIRST),
            dict(entry=2, value=1000, confirm=True, options=FIRST),
            dict(entry=3, value=2000),
        )
        # Entry 1 is a plain first-choice sale and already frees one slot.
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 1})
        self.assertEqual(self.entries(sales), [1])
        more = vendor.sales_for(plan_, prs, pressure={"Ana": 2})
        self.assertEqual(self.entries(more), [1, 2])

    def test_a_released_confirm_key_still_sells_without_pressure(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=3000, confirm=True, options=FIRST)
        )
        sales = vendor.sales_for(plan_, prs, released=frozenset([prs[0][0].key]))
        self.assertEqual(self.entries(sales), [1])
        self.assertEqual(sales[0].released, "")

    def test_a_stack_the_current_pass_sells_is_not_released_twice(self):
        # The ordinary pass would sell a white stack: it is not the route's.
        plan_, prs = held_fixture(
            dict(entry=1, value=100, quality=1, confirm=True, options=FIRST)
        )
        self.assertEqual(vendor.sales_for(plan_, prs, pressure={"Ana": 3}), ())

    def test_the_release_line_names_the_holder_count_worth_and_stacks(self):
        plan_, prs = held_fixture(
            dict(entry=1, value=1000, confirm=True, options=FIRST),
            dict(entry=2, value=2500),
        )
        sales = vendor.sales_for(plan_, prs, pressure={"Ana": 2})
        self.assertEqual(
            vendor.release_lines(sales),
            (
                "itemplan vendor: Ana releases 2 held sale(s) under bag pressure,"
                " worth %s: Stack 1, Stack 2" % vendor_money(3500),
            ),
        )

    def test_no_release_line_without_a_release(self):
        plan_, prs = held_fixture(dict(entry=1, value=1000, options=FIRST))
        self.assertEqual(vendor.release_lines(vendor.sales_for(plan_, prs)), ())


def vendor_money(copper):
    import vendorsale

    return vendorsale.money(copper)


class PressureTest(unittest.TestCase):
    """How much room a member still has to make."""

    def test_a_member_under_the_trigger_needs_slots_up_to_the_target(self):
        need = vendor.pressure_for(["Ana"], {"Ana": 0}, {})
        self.assertEqual(need, {"Ana": vendor.RELEASE_TARGET_FREE})
        need = vendor.pressure_for(["Ana"], {"Ana": itemplan.TRIGGER_FREE - 1}, {})
        self.assertEqual(
            need, {"Ana": vendor.RELEASE_TARGET_FREE - itemplan.TRIGGER_FREE + 1}
        )

    def test_a_member_at_or_over_the_trigger_needs_nothing(self):
        for free in (itemplan.TRIGGER_FREE, itemplan.TRIGGER_FREE + 5):
            self.assertEqual(vendor.pressure_for(["Ana"], {"Ana": free}, {}), {})

    def test_the_ordinary_sellable_count_is_taken_off(self):
        need = vendor.pressure_for(["Ana"], {"Ana": 0}, {"Ana": 4})
        self.assertEqual(need, {"Ana": vendor.RELEASE_TARGET_FREE - 4})
        full = vendor.pressure_for(["Ana"], {"Ana": 0}, {"Ana": 99})
        self.assertEqual(full, {})

    def test_an_unread_member_is_not_under_pressure(self):
        self.assertEqual(vendor.pressure_for(["Ana"], {}, {}), {})
        self.assertEqual(vendor.pressure_for(["Ana"], {"Ana": None}, {}), {})

    def test_the_target_sits_above_the_trigger(self):
        self.assertGreater(vendor.RELEASE_TARGET_FREE, itemplan.TRIGGER_FREE)


class ReleaseSwitchTest(unittest.TestCase):
    def test_the_release_is_off_by_default(self):
        self.assertFalse(vendor.release_enabled({}))
        self.assertFalse(vendor.release_enabled({**ON, "ITEMPLAN_SELL_RELEASE": "off"}))
        for word in ("on", "1", "true", "yes"):
            self.assertTrue(
                vendor.release_enabled({**ON, "ITEMPLAN_SELL_RELEASE": word})
            )

    def test_the_release_needs_the_route_switch_too(self):
        self.assertFalse(vendor.release_enabled({"ITEMPLAN_SELL_RELEASE": "on"}))


class CarryOutTest(unittest.TestCase):
    def _sales(self):
        rows, gear, worn, free = green_cloak()
        rows.append(
            row("Bob", 5, 7778, "Plain Green Hat", quality=2, sell=3000, item_class=4)
        )
        gear.append(
            {
                "holder": "Bob",
                "item_guid": 5,
                "entry": 7778,
                "name": "Plain Green Hat",
                "quality": 3 - 1,
                "sell_price": 3000,
                "item_class": 4,
                "item_subclass": 4,
                "bonding": 0,
                "required_level": 50,
                "item_level": 40,
                "level": 54,
            }
        )
        worn.append({"name": "Bob", "class_id": 8, "level": 54})
        free["Bob"] = 3
        plan_, prs = plan_and_pairs(rows, gear, worn, free)
        return vendor.sales_for(plan_, prs)

    def test_refused_row_is_skipped_and_the_rest_still_sell(self):
        sales = self._sales()
        if len(sales) < 2:
            self.skipTest("fixture planned fewer than two route sales")
        queued = []

        def insert(candidate):
            if candidate.holder == "Ana":
                return 0  # the executor refuses this refusable row
            queued.append(candidate)
            return 1

        report = vendor.carry_out(sales, insert)
        self.assertEqual([c.holder for c in queued], ["Bob"])
        self.assertEqual(report.worth, {"Bob": 3000})
        self.assertEqual(len(report.skipped), 1)
        self.assertTrue(any("Bob" in line and "30s" in line for line in report.lines))

    def test_each_line_pairs_its_own_holders_count_with_its_own_worth(self):
        sales = (
            route_sale("Ana", 1, 3000),
            route_sale("Ana", 2, 3000),
            route_sale("Bob", 3, 6000),
            route_sale("Cy", 4, 1),
        )
        report = vendor.carry_out(sales, lambda c: 0 if c.holder == "Cy" else 1)
        self.assertEqual(report.worth, {"Ana": 6000, "Bob": 6000})
        self.assertEqual(
            report.lines,
            (
                "itemplan vendor: Ana: 2 sale(s) queued, worth 60s",
                "itemplan vendor: Bob: 1 sale(s) queued, worth 60s",
            ),
        )

    def test_the_line_says_queued_and_worth_not_sold(self):
        sales = self._sales()
        report = vendor.carry_out(sales, lambda candidate: 1)
        self.assertTrue(report.lines)
        for line in report.lines:
            self.assertIn("sale(s) queued, worth ", line)
            self.assertNotIn("carried out", line)
            self.assertNotIn("gold", line)

    def test_worth_is_reported_per_member(self):
        sales = self._sales()
        report = vendor.carry_out(sales, lambda candidate: 1)
        self.assertEqual(
            report.worth,
            {sale.holder: sale.copper for sale in sales},
        )
        for holder in report.worth:
            self.assertTrue(any(holder in line for line in report.lines))


def plan_one(item_row, sub=0, **template):
    """The plan the shadow builds for one carried row, with its binding read."""
    tpl = {"subclass": sub, "bonding": 0, "req_level": 1, "item_level": 5}
    tpl.update(template)
    extras = shadow.Extras(
        templates={item_row["entry"]: tpl},
        instance_soulbound={item_row["item_guid"]: False},
        open_quest_items={"Ana": frozenset({3000})},
        fire_gear=frozenset(),
    )
    report = shadow.shadow(
        ["Ana"],
        "Fam",
        [item_row],
        {"Ana": 5},
        worn_rows=[{"name": "Ana", "class_id": 8, "level": 54}],
        extras=extras,
    )
    stacks = shadow.build_stacks(
        [item_row], (), extras.templates, extras.instance_soulbound
    )
    return report.plan, list(zip(stacks, [item_row], strict=True))


def tool_row(guid, entry, name):
    return row("Ana", guid, entry, name, sell=100, item_class=2, profession_needed=True)


# Working stock the current protection keeps (profession stock, quest item,
# no price): none of it may reach a vendor through this route.
PROTECTED_STOCK = {
    "mining pick": (tool_row(11, 2901, "Mining Pick"), 14),
    "skinning knife": (tool_row(12, 7005, "Skinning Knife"), 14),
    "blacksmith hammer": (tool_row(13, 5956, "Blacksmith Hammer"), 14),
    "hearthstone": (row("Ana", 15, 6948, "Hearthstone", sell=0, item_class=15), 0),
    "key": (row("Ana", 16, 5396, "Skeleton Key", sell=10, item_class=13), 0),
    "quest item of an open quest": (
        row("Ana", 17, 3000, "Crate of Tools", sell=10, item_class=12, quest_item=True),
        0,
    ),
}


class ProtectedStockTest(unittest.TestCase):
    def test_tools_keys_and_quest_items_are_never_route_sales(self):
        for label, (item_row, sub) in PROTECTED_STOCK.items():
            with self.subTest(label):
                plan_, prs = plan_one(item_row, sub)
                self.assertEqual(vendor.sales_for(plan_, prs), ())

    def test_fishing_pole_is_held_back_as_a_profession_tool(self):
        # The plan routes the pole SELL_VENDOR (rule R8; it is not in
        # `disposition.TOOL_TRADES`), so the route holds it back itself, by
        # item class 2 subclass 20.
        plan_, prs = plan_one(tool_row(14, 6256, "Fishing Pole"), 20)
        self.assertEqual([d.route for d in plan_.decisions], [itemplan.SELL_VENDOR])
        held = []
        self.assertEqual(vendor.sales_for(plan_, prs, held=held), ())
        self.assertEqual(
            [(d.name, why) for d, why in held],
            [("Fishing Pole", vendor.HELD_TOOL)],
        )
        self.assertEqual(
            vendor.HELD_TOOL, "a profession tool is never sold by the route"
        )

    def test_a_bag_is_held_back_as_a_bag(self):
        # The shadow's plan sees no worn bags, so rule R2 routes any carried
        # bag SELL_VENDOR; the route holds it back by item class 1.
        bag = row("Ana", 19, 4497, "Heavy Brown Bag", quality=2, sell=400, item_class=1)
        plan_, prs = plan_one(bag, 0, container_slots=10)
        self.assertEqual([d.route for d in plan_.decisions], [itemplan.SELL_VENDOR])
        held = []
        self.assertEqual(vendor.sales_for(plan_, prs, held=held), ())
        self.assertEqual(
            [(d.name, why) for d, why in held],
            [("Heavy Brown Bag", vendor.HELD_BAG)],
        )
        self.assertEqual(vendor.HELD_BAG, "a bag is never sold by the route")

    def test_an_ordinary_first_choice_vendor_sale_still_goes_through(self):
        rows, gear, worn, free = green_cloak()
        plan_, prs = plan_and_pairs(rows, gear, worn, free)
        held = []
        self.assertEqual(len(vendor.sales_for(plan_, prs, held=held)), 1)
        self.assertEqual(held, [])


def import_bridge():
    discord = types.ModuleType("discord")
    discord.Client = object
    return fresh_import("bridge", discord=discord, pymysql=PYMYSQL)


def route_sale(holder, guid, copper=4000):
    return vendor.Sale(
        holder=holder,
        name="Plain Green Cloak",
        count=1,
        copper=copper,
        key=(holder, guid),
        candidate=bag_pressure.SellCandidate(
            holder=holder,
            item_guid=guid,
            count=1,
            item=bag_pressure.ItemForSale(quality=2, sell_price=copper),
        ),
    )


def grey(holder, guid):
    return bag_pressure.SellCandidate(
        holder=holder,
        item_guid=guid,
        count=1,
        item=bag_pressure.ItemForSale(quality=0, sell_price=5),
    )


class RouteSalesAtTheBridgeTest(unittest.TestCase):
    """The bridge seam, run for real with a fake world (#1977)."""

    def setUp(self):
        self.bridge = import_bridge()

    def run_pass(self, candidates, route_sales, at_counter=("Ana", "Cy")):
        written, lines = [], []
        bridge = self.bridge

        async def no_reading(*args):
            return None

        fake_log = types.SimpleNamespace(
            info=lambda msg, *a: lines.append(msg % a if a else msg)
        )
        with (
            mock.patch.object(
                bridge,
                "_fetch_town",
                side_effect=lambda n: types.SimpleNamespace(vendor=n in at_counter),
            ),
            mock.patch.object(
                bridge, "_insert_sell", side_effect=lambda c: written.append(c) or 1
            ),
            mock.patch.object(bridge, "_recent_range_refusals", return_value={}),
            mock.patch.object(bridge, "_fetch_vendor_position", return_value=None),
            mock.patch.object(bridge, "_log_sale_reading", no_reading),
            mock.patch.object(bridge, "_SALE_WRITE_SPOT", {}),
            mock.patch.object(bridge, "log", fake_log),
        ):
            inserted = asyncio.run(
                bridge._queue_vendor_sales(
                    tuple(candidates),
                    "Lead",
                    False,
                    "trip",
                    (),
                    route_sales=tuple(route_sales),
                )
            )
        return inserted, [c.item_guid for c in written], lines

    def test_switch_off_reads_nothing_and_returns_no_sales(self):
        bridge = self.bridge
        env = {k: v for k, v in os.environ.items() if k != "ITEMPLAN_SELL_VENDOR"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(bridge, "_itemplan_reads") as reads,
        ):
            out = bridge._itemplan_vendor_sales(["Ana"], "Fam", [], {})
        self.assertEqual(out, ())
        reads.assert_not_called()

    def test_a_failed_plan_read_is_logged_and_returns_no_sales(self):
        bridge = self.bridge
        fake_log = mock.Mock()
        with (
            mock.patch.dict(os.environ, ON),
            mock.patch.object(bridge, "_itemplan_reads", side_effect=OSError("down")),
            mock.patch.object(bridge, "log", fake_log),
        ):
            out = bridge._itemplan_vendor_sales(["Ana"], "Fam", [], {})
        self.assertEqual(out, ())
        fake_log.exception.assert_called_once()
        self.assertIn("the route failed", fake_log.exception.call_args.args[0])

    def test_a_route_sale_is_written_only_for_a_holder_at_a_counter(self):
        # Ana stands at a counter; Bob does not. Each also has an ordinary row.
        inserted, guids, _ = self.run_pass(
            [grey("Ana", 1), grey("Bob", 2)],
            [route_sale("Ana", 10), route_sale("Bob", 20)],
        )
        self.assertIn(10, guids)
        self.assertNotIn(20, guids)
        self.assertNotIn(2, guids)
        self.assertEqual(inserted, len(guids))

    def test_the_route_executor_writes_for_the_holders_it_is_given_only(self):
        # `_queue_vendor_sales` owns the counter gate and hands the executor
        # only holders that passed it; the executor must not widen that set.
        bridge = self.bridge
        written = []
        with mock.patch.object(
            bridge, "_insert_sell", side_effect=lambda c: written.append(c) or 1
        ):
            wrote, asked = asyncio.run(
                bridge._queue_route_sales(
                    (route_sale("Ana", 10), route_sale("Bob", 20)),
                    ["Ana"],
                    (),
                )
            )
        self.assertEqual([c.item_guid for c in written], [10])
        self.assertEqual((wrote, asked), (1, 1))

    def test_a_route_only_holder_at_a_counter_gets_its_sale(self):
        _, guids, _ = self.run_pass(
            [grey("Ana", 1)], [route_sale("Cy", 30), route_sale("Dee", 40)]
        )
        self.assertIn(30, guids)
        self.assertNotIn(40, guids)

    def test_an_item_is_written_once_when_it_is_also_an_ordinary_candidate(self):
        # The gear, lock, clearance and bag sales ride in `candidates`; a
        # route sale for the same guid must not queue a second sell row.
        _, guids, _ = self.run_pass([grey("Ana", 7)], [route_sale("Ana", 7)])
        self.assertEqual(guids.count(7), 1)

    def test_the_summary_counts_route_rows_on_both_sides(self):
        inserted, _, lines = self.run_pass([grey("Ana", 1)], [route_sale("Ana", 10)])
        self.assertEqual(inserted, 2)
        summary = [ln for ln in lines if ln.startswith("economy: queued ")]
        self.assertEqual(len(summary), 1)
        self.assertIn("queued 2/2 vendor sale(s)", summary[0])

    def test_the_seam_logs_the_fallback_sales_it_held_back(self):
        bridge = self.bridge
        plan_, prs, item = fallback_fixture((itemplan.GUILD_BANK, itemplan.SELL_VENDOR))
        fake_log = mock.Mock()
        with (
            mock.patch.dict(os.environ, ON),
            mock.patch.object(
                bridge,
                "_itemplan_reads",
                return_value=types.SimpleNamespace(
                    templates=None, instance_soulbound=None
                ),
            ),
            mock.patch.object(
                bridge.itemplan_shadow,
                "shadow",
                return_value=types.SimpleNamespace(plan=plan_),
            ),
            mock.patch.object(
                bridge.itemplan_shadow, "build_stacks", return_value=[prs[0][0]]
            ),
            mock.patch.object(bridge, "log", fake_log),
        ):
            out = bridge._itemplan_vendor_sales(["Ana"], "Fam", [item], {})
        self.assertEqual(out, ())
        fake_log.info.assert_called_once_with(
            "%s",
            "itemplan vendor: Ana holds back 1 sale(s): Plain Green Cloak (%s)"
            % vendor.HELD_FALLBACK,
        )

    def seam(self, free, env, counts=None, value=4000):
        """`_itemplan_vendor_sales` over a one-stack plan whose sale is held."""
        bridge = self.bridge
        plan_, prs, item = fallback_fixture(
            (itemplan.GUILD_BANK, itemplan.SELL_VENDOR), value=value
        )
        fake_log = mock.Mock()
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(
                bridge,
                "_itemplan_reads",
                return_value=types.SimpleNamespace(
                    templates=None, instance_soulbound=None
                ),
            ),
            mock.patch.object(
                bridge.itemplan_shadow,
                "shadow",
                return_value=types.SimpleNamespace(plan=plan_),
            ),
            mock.patch.object(
                bridge.itemplan_shadow, "build_stacks", return_value=[prs[0][0]]
            ),
            mock.patch.object(bridge, "log", fake_log),
        ):
            out = bridge._itemplan_vendor_sales(
                ["Ana"], "Fam", [item], free, sellable_counts=counts
            )
        return out, fake_log

    def test_release_on_sells_a_held_stack_for_a_member_at_the_floor(self):
        env = {**ON, "ITEMPLAN_SELL_RELEASE": "on"}
        out, fake_log = self.seam({"Ana": 0}, env, counts={})
        self.assertEqual([s.name for s in out], ["Plain Green Cloak"])
        self.assertEqual(out[0].released, vendor.RELEASED_FALLBACK)
        lines = [c.args[1] for c in fake_log.info.call_args_list]
        self.assertIn(
            "itemplan vendor: Ana releases 1 held sale(s) under bag pressure, "
            "worth %s: Plain Green Cloak" % vendor_money(4000),
            lines,
        )

    def test_release_on_sells_nothing_for_a_member_with_room(self):
        env = {**ON, "ITEMPLAN_SELL_RELEASE": "on"}
        out, _ = self.seam({"Ana": 20}, env, counts={})
        self.assertEqual(out, ())

    def test_release_off_keeps_the_stack_held_at_the_floor(self):
        out, _ = self.seam({"Ana": 0}, ON, counts={})
        self.assertEqual(out, ())

    def test_release_on_leaves_a_valuable_stack_held(self):
        env = {**ON, "ITEMPLAN_SELL_RELEASE": "on"}
        out, _ = self.seam(
            {"Ana": 0}, env, counts={}, value=vendor.RELEASE_CEILING_COPPER + 1
        )
        self.assertEqual(out, ())

    def test_the_ordinary_sellable_count_lowers_the_pressure(self):
        env = {**ON, "ITEMPLAN_SELL_RELEASE": "on"}
        out, _ = self.seam({"Ana": 0}, env, counts={"Ana": 99})
        self.assertEqual(out, ())

    def test_the_trip_seam_hands_the_sellable_counts_to_the_release(self):
        bridge = self.bridge
        counts = {"Ana": 99}
        with mock.patch.object(
            bridge, "_itemplan_vendor_sales", return_value=()
        ) as sales:
            bridge._route_sales_for_trip(["Ana"], "Lead", [], {"Ana": 0}, counts)
        self.assertEqual(sales.call_args.kwargs["sellable_counts"], {"Ana": 99})

    def test_the_dockerfile_ships_the_route(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        docker = (root / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("itemplan_vendor.py", docker)


if __name__ == "__main__":
    unittest.main()
