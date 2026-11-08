"""The item plan in shadow (#1972): logs, disagrees, changes nothing.

Rows are shaped like the economy pass's carried query and gear query rows.
"""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import itemplan  # noqa: E402
import itemplan_shadow as shadow  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

ON = {"ITEMPLAN_SHADOW": "on"}


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


def fixture():
    rows = [
        row("Ana", 1, 2589, "Linen Cloth", item_class=7, count=20, sell=13),
        row("Ana", 2, 4540, "Tough Hunk of Bread", item_class=0, sell=25),
        row("Ana", 3, 9999, "Odd Trinket", quality=1, sell=900),
        # A green the sale pass refuses (uncommon quality) that the plan sells.
        row("Ana", 4, 7777, "Plain Green Cloak", quality=2, sell=4000, item_class=4),
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


class Capture:
    def __init__(self):
        self.lines = []

    def info(self, fmt, *args):
        self.lines.append(fmt % args)

    def exception(self, fmt, *args):
        self.lines.append("EXC " + fmt % args)


class AdapterTest(unittest.TestCase):
    def test_give_route_has_an_independent_switch(self):
        self.assertFalse(shadow.give_enabled({}))
        self.assertFalse(shadow.give_enabled({"ITEMPLAN_GIVE": "off"}))
        self.assertTrue(shadow.give_enabled({"ITEMPLAN_GIVE": "on"}))

    def test_give_executor_uses_the_plan_and_existing_gift_writer(self):
        start = BRIDGE.index("    async def _itemplan_give(")
        end = BRIDGE.index("    async def _clearance_plan(", start)
        executor = BRIDGE[start:end]
        self.assertIn("itemplan_shadow.give_enabled()", executor)
        self.assertIn("decision.route != itemplan.GIVE", executor)
        self.assertIn("not stack.tradable", executor)
        self.assertIn("await self._write_guild_gifts(gifts)", executor)
        self.assertIn("_run_itemplan_give(", BRIDGE)

    def test_auction_route_has_an_independent_switch(self):
        self.assertFalse(shadow.auction_enabled({}))
        self.assertFalse(shadow.auction_enabled({"ITEMPLAN_AUCTION": "off"}))
        self.assertTrue(shadow.auction_enabled({"ITEMPLAN_AUCTION": "on"}))

    def test_auction_executor_uses_the_plan_and_existing_listing_path(self):
        start = BRIDGE.index("    async def _itemplan_auction(")
        end = BRIDGE.index("    async def _clearance_plan(", start)
        executor = BRIDGE[start:end]
        self.assertIn("itemplan_shadow.auction_enabled()", executor)
        self.assertIn("decision.route != itemplan.AUCTION", executor)
        self.assertIn("not stack.tradable", executor)
        self.assertIn("auction.list_command(", executor)
        self.assertIn("_insert_auction", executor)
        self.assertIn("_run_itemplan_auction(", BRIDGE)

    def test_rows_become_stacks_and_members(self):
        rows, gear, worn, free = fixture()
        stacks = shadow.build_stacks(rows, gear)
        self.assertEqual(len(stacks), 4)
        cloak = stacks[3]
        self.assertEqual(
            (cloak.item_level, cloak.req_level, cloak.subclass), (40, 50, 4)
        )
        self.assertEqual(stacks[0].item_level, 1)
        members = shadow.build_members(
            ["Ana"], "Fam", stacks, free, shadow.characters_from_worn(worn)
        )
        self.assertEqual(members[0].carried_slots, 7)
        self.assertEqual((members[0].class_id, members[0].level), (8, 54))

    def test_switch_is_off_by_default(self):
        self.assertFalse(shadow.enabled({}))
        self.assertFalse(shadow.enabled({"ITEMPLAN_SHADOW": "off"}))
        self.assertTrue(shadow.enabled(ON))


def ore_extras(market, instance_soulbound=None):
    tpl = {
        "item_class": 15,
        "subclass": 0,
        "bonding": 0,
        "inventory_type": 0,
        "item_level": 1,
        "req_level": 0,
        "required_skill_rank": 0,
        "container_slots": 0,
        "fire_res": 0,
        "stats": {},
    }
    sb = {1: False, 2: False}
    if instance_soulbound is not None:
        sb.update(instance_soulbound)
    return shadow.Extras(
        market=market,
        templates={1001: tpl, 1002: tpl},
        instance_soulbound=sb,
    )


class RunTest(unittest.TestCase):
    def setUp(self):
        shadow.reset()

    def test_off_skips_and_touches_nothing(self):
        rows, gear, worn, free = fixture()
        before = copy.deepcopy((rows, gear, worn, free))
        cap = Capture()
        out = shadow.run(
            ["Ana"],
            "Fam",
            rows,
            free,
            environ={},
            logger=cap,
            gear_rows=gear,
            worn_rows=worn,
        )
        self.assertIsNone(out)
        self.assertEqual(cap.lines, [])
        self.assertEqual((rows, gear, worn, free), before)

    def test_on_logs_one_plan_line_per_member_and_changes_no_row(self):
        rows, gear, worn, free = fixture()
        rows.append(row("Bo", 10, 2589, "Linen Cloth", item_class=7, sell=13))
        worn.append({"name": "Bo", "class_id": 4, "level": 40})
        free["Bo"] = 10
        before = copy.deepcopy((rows, gear, worn, free))
        cap = Capture()
        report = shadow.run(
            ["Ana", "Bo"],
            "Fam",
            rows,
            free,
            environ=ON,
            logger=cap,
            gear_rows=gear,
            worn_rows=worn,
        )
        self.assertEqual((rows, gear, worn, free), before)
        plans = [x for x in cap.lines if x.startswith("itemplan: plan ")]
        self.assertEqual(len(plans), 2)
        self.assertIn("free now 3", plans[0])
        self.assertIn("free after", plans[0])
        self.assertTrue(all(x.startswith("itemplan:") for x in cap.lines))
        self.assertIn("ran without:", cap.lines[-1])
        self.assertIn("auction prices", cap.lines[-1])
        self.assertEqual(len(report.lines), 2)

    def test_names_a_stack_the_sale_pass_keeps_and_the_plan_sells(self):
        rows, gear, worn, free = fixture()
        extras = shadow.Extras(
            open_quest_items={"Ana": frozenset()},
            templates={
                entry: {
                    "item_class": item_class,
                    "subclass": 0,
                    "bonding": 0,
                    "inventory_type": 0,
                    "item_level": 1,
                    "req_level": 0,
                    "required_skill_rank": 0,
                    "container_slots": 0,
                    "fire_res": 0,
                    "stats": {},
                }
                for entry, item_class in (
                    (2589, 7),
                    (4540, 0),
                    (9999, 15),
                    (7777, 4),
                )
            },
            instance_soulbound={1: False, 2: False, 3: False, 4: False},
            fire_gear=frozenset(),
        )
        cap = Capture()
        report = shadow.run(
            ["Ana"],
            "Fam",
            rows,
            free,
            environ=ON,
            logger=cap,
            gear_rows=gear,
            worn_rows=worn,
            extras=extras,
        )
        hits = [
            x
            for x in cap.lines
            if x.startswith("itemplan: disagree ") and "Plain Green Cloak" in x
        ]
        self.assertEqual(len(hits), 1, cap.lines)
        self.assertIn("sale pass keeps (uncommon or better)", hits[0])
        self.assertIn("plan SELL_VENDOR", hits[0])
        self.assertEqual(
            len(report.disagreements),
            len([x for x in cap.lines if x.startswith("itemplan: disagree ")]),
        )

    def test_other_passes_are_compared(self):
        rows, gear, worn, free = fixture()
        placement = SimpleNamespace(holder="Ana", to="guild")
        report = shadow.shadow(
            ["Ana"],
            "Fam",
            rows,
            free,
            gear_rows=gear,
            worn_rows=worn,
            bank_keeps={3: placement},
        )
        self.assertTrue(
            any("bank pass routes it to GUILD_BANK" in x for x in report.disagreements),
            report.disagreements,
        )

    def test_a_failure_inside_the_plan_is_logged_and_swallowed(self):
        cap = Capture()
        out = shadow.run(["Ana"], "Fam", [{"entry": 1}], {}, environ=ON, logger=cap)
        self.assertIsNone(out)
        self.assertTrue(cap.lines and cap.lines[0].startswith("EXC itemplan:"))

    def test_extras_plug_in_without_the_missing_note(self):
        rows, gear, worn, free = fixture()
        extras = shadow.Extras(
            open_quest_items={"Ana": frozenset()}, market={9999: (100000, 1)}
        )
        report = shadow.shadow(
            ["Ana"], "Fam", rows, free, gear_rows=gear, worn_rows=worn, extras=extras
        )
        self.assertNotIn("auction prices", report.missing)
        self.assertFalse(any(m.startswith("quest log") for m in report.missing))

    def test_shadow_run_with_quotes_lists_over_4x_vendor_and_not_at_3_4x(self):
        rows = [
            row("Ana", 1, 1001, "Dear Ore", count=3, sell=1000, item_class=7),
            row("Ana", 2, 1002, "Cheap Ore", count=3, sell=1000, item_class=7),
        ]
        extras = ore_extras(
            {
                1001: (4400, 5),
                1002: (3400, 5),
            }
        )
        cap = Capture()
        report = shadow.run(
            ["Ana"],
            "Fam",
            rows,
            {"Ana": 10},
            environ=ON,
            logger=cap,
            extras=extras,
        )
        decisions = {d.entry: d.route for d in report.plan.decisions}
        self.assertEqual(decisions.get(1001), itemplan.AUCTION)
        self.assertEqual(decisions.get(1002), itemplan.SELL_VENDOR)
        self.assertTrue(any("AUCTION 1" in line for line in report.lines))


class AuctionExecutorTest(unittest.IsolatedAsyncioTestCase):
    async def test_itemplan_auction_lists_only_when_enabled(self):
        from test_guildsocial_bridge import bridge

        rows = [
            row("Ana", 1, 1001, "Dear Ore", count=3, sell=1000, item_class=7),
            row("Ana", 2, 1002, "Cheap Ore", count=3, sell=1000, item_class=7),
        ]
        extras = ore_extras(
            {
                1001: (4400, 5),
                1002: (3400, 5),
            }
        )
        inserted = []

        def fake_insert(member, command, source="auction"):
            inserted.append((member, command))
            return 1

        b = SimpleNamespace()
        with (
            mock.patch.object(
                bridge.itemplan_shadow, "auction_enabled", return_value=False
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras),
            mock.patch.object(bridge, "_recent_auction_keys", return_value=set()),
            mock.patch.object(bridge, "_insert_auction", side_effect=fake_insert),
        ):
            await bridge.Bridge._itemplan_auction(b, ["Ana"], "Fam", rows, {"Ana": 10})
            self.assertEqual(inserted, [])

        with (
            mock.patch.object(
                bridge.itemplan_shadow, "auction_enabled", return_value=True
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras),
            mock.patch.object(bridge, "_recent_auction_keys", return_value=set()),
            mock.patch.object(bridge, "_insert_auction", side_effect=fake_insert),
        ):
            await bridge.Bridge._itemplan_auction(b, ["Ana"], "Fam", rows, {"Ana": 10})
            self.assertEqual(len(inserted), 1)
            member, cmd = inserted[0]
            self.assertEqual(member, "Ana")
            self.assertIn("guid:1", cmd)
            self.assertIn("buyout:13200", cmd)
            self.assertIn("bid:10560", cmd)
            self.assertIn("hours:12", cmd)

    async def test_itemplan_auction_skips_recent_seen_keys(self):
        from test_guildsocial_bridge import bridge

        rows = [
            row("Ana", 1, 1001, "Dear Ore", count=3, sell=1000, item_class=7),
        ]
        extras = ore_extras({1001: (4400, 5)})
        inserted = []
        cmd = "list guid:1 bid:10560 buyout:13200 hours:12"
        b = SimpleNamespace()
        with (
            mock.patch.object(
                bridge.itemplan_shadow, "auction_enabled", return_value=True
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras),
            mock.patch.object(
                bridge, "_recent_auction_keys", return_value={("Ana", cmd)}
            ),
            mock.patch.object(
                bridge,
                "_insert_auction",
                side_effect=lambda m, c: inserted.append((m, c)),
            ),
        ):
            await bridge.Bridge._itemplan_auction(b, ["Ana"], "Fam", rows, {"Ana": 10})
            self.assertEqual(inserted, [])

    async def test_itemplan_auction_skips_untradable(self):
        from test_guildsocial_bridge import bridge

        rows = [
            row("Ana", 1, 1001, "Dear Ore", count=3, sell=1000, item_class=7),
        ]
        extras = ore_extras(
            {1001: (4400, 5)},
            instance_soulbound={1: True},
        )
        inserted = []
        b = SimpleNamespace()
        with (
            mock.patch.object(
                bridge.itemplan_shadow, "auction_enabled", return_value=True
            ),
            mock.patch.object(bridge, "_itemplan_reads", return_value=extras),
            mock.patch.object(bridge, "_recent_auction_keys", return_value=set()),
            mock.patch.object(
                bridge,
                "_insert_auction",
                side_effect=lambda m, c: inserted.append((m, c)),
            ),
        ):
            await bridge.Bridge._itemplan_auction(b, ["Ana"], "Fam", rows, {"Ana": 10})
            self.assertEqual(inserted, [])


class BridgeShapeTest(unittest.TestCase):
    def test_one_guarded_call_after_the_sale_inputs_exist(self):
        at = BRIDGE.index('"_shadow_itemplan", lambda')
        self.assertEqual(BRIDGE.count('"_shadow_itemplan", lambda'), 1)
        self.assertLess(BRIDGE.index("_count_sales(sellable_counts, gear_sales)"), at)
        self.assertLess(at, BRIDGE.index("held_seller_for_leader = await"))

    def test_one_guarded_auction_call_after_give(self):
        at = BRIDGE.index('"_run_itemplan_auction"')
        self.assertEqual(BRIDGE.count('"_run_itemplan_auction"'), 1)
        self.assertLess(BRIDGE.index('"_run_itemplan_give"'), at)
        self.assertLess(at, BRIDGE.index("held_seller_for_leader = await"))


if __name__ == "__main__":
    unittest.main()
