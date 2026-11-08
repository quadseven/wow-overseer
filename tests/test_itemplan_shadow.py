"""The item plan in shadow (#1972): logs, disagrees, changes nothing.

Rows are shaped like the economy pass's carried query and gear query rows.
"""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

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


class BridgeShapeTest(unittest.TestCase):
    def test_one_guarded_call_after_the_sale_inputs_exist(self):
        at = BRIDGE.index('"_shadow_itemplan", lambda')
        self.assertEqual(BRIDGE.count('"_shadow_itemplan", lambda'), 1)
        self.assertLess(BRIDGE.index("_count_sales(sellable_counts, gear_sales)"), at)
        self.assertLess(at, BRIDGE.index("held_seller_for_leader = await"))


if __name__ == "__main__":
    unittest.main()
