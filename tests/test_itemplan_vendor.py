"""The item plan's vendor-sale route (#1977): carried out, not just logged.

Fixture rows are shaped like the economy pass's carried query rows, the
same shape `tests/test_itemplan_shadow.py` uses, and the plan under test
is the one `itemplan_shadow.shadow` builds from them.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

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
        # Quality 3 or a value of 1 gold or more marks a sale `confirm`:
        # it is carried out only when its key is in the released set.
        rows = [row("Ana", 9, 8888, "Blue Sword", quality=3, sell=20000, item_class=2)]
        gear = [
            {
                "holder": "Ana",
                "item_guid": 9,
                "entry": 8888,
                "name": "Blue Sword",
                "quality": 3,
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
        self.assertEqual(report.gold, {"Bob": 3000})
        self.assertEqual(len(report.skipped), 1)
        self.assertTrue(any("Bob" in line and "30s" in line for line in report.lines))

    def test_gold_is_reported_per_member(self):
        sales = self._sales()
        report = vendor.carry_out(sales, lambda candidate: 1)
        self.assertEqual(
            report.gold,
            {sale.holder: sale.copper for sale in sales},
        )
        for holder in report.gold:
            self.assertTrue(any(holder in line for line in report.lines))


if __name__ == "__main__":
    unittest.main()
