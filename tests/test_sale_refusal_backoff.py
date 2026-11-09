"""A refused sale is not written again from the same spot (wow-overseer#1962).

Several family members were written a fresh pass of sell rows every five
minutes and the world refused every one with `vendor not in range`, because
the bridge's counter read said "in reach" while the core said otherwise. One
refusal must not become a pass of rows every cycle: a member just refused is
left alone until it has moved, or ten minutes have gone by.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import item_plan

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (PACKAGE / "bridge.py").read_text(encoding="utf-8")

HERE = (1, 100.0, 200.0, 30.0)


class RangeBackoff(unittest.TestCase):
    def test_a_fresh_refusal_from_the_same_spot_holds_the_rows(self):
        held = item_plan.range_backoff(300, None, HERE, HERE)
        self.assertTrue(held)
        self.assertIn("vendor not in range", held)

    def test_a_few_yards_of_drift_is_not_moving(self):
        near = (1, 102.0, 203.0, 30.0)
        self.assertTrue(item_plan.range_backoff(120, None, HERE, near))

    def test_moving_more_than_a_few_yards_releases_the_hold(self):
        far = (1, 130.0, 200.0, 30.0)
        self.assertEqual("", item_plan.range_backoff(120, None, HERE, far))

    def test_another_map_counts_as_moved(self):
        other = (0, 100.0, 200.0, 30.0)
        self.assertEqual("", item_plan.range_backoff(120, None, HERE, other))

    def test_the_hold_lapses_after_the_bounded_time(self):
        self.assertEqual(
            "",
            item_plan.range_backoff(
                item_plan.RANGE_BACKOFF_SECONDS + 1, None, HERE, HERE
            ),
        )

    def test_no_refusal_no_hold(self):
        self.assertEqual("", item_plan.range_backoff(None, None, HERE, HERE))

    def test_a_sale_served_after_the_refusal_ends_it(self):
        self.assertEqual("", item_plan.range_backoff(300, 60, HERE, HERE))

    def test_a_sale_served_before_the_refusal_does_not(self):
        self.assertTrue(item_plan.range_backoff(60, 900, HERE, HERE))

    def test_unknown_positions_hold_until_the_time_is_up(self):
        self.assertTrue(item_plan.range_backoff(300, None, None, None))
        self.assertTrue(item_plan.range_backoff(300, None, None, HERE))
        self.assertEqual(
            "",
            item_plan.range_backoff(item_plan.RANGE_BACKOFF_SECONDS, None, None, None),
        )


class SaleReadingLine(unittest.TestCase):
    def test_it_names_position_counter_both_distances_and_the_refusal(self):
        line = item_plan.sale_reading("Ekka", HERE, (6.0, 6.0, 0.0), 120)
        self.assertIn("Ekka", line)
        self.assertIn("100.0", line)
        self.assertIn("euclid=8.5", line)
        self.assertIn("per-axis=6.0/6.0/0.0", line)
        self.assertIn("refused 120s ago", line)

    def test_no_counter_and_no_refusal_still_say_so(self):
        line = item_plan.sale_reading("Ekka", None, None, None)
        self.assertIn("no counter", line)
        self.assertIn("no refusal", line)


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return ast.get_source_segment(BRIDGE, node)
    raise AssertionError(name)


class Wired(unittest.TestCase):
    def test_the_sale_pass_asks_the_backoff_before_it_inserts(self):
        body = _function("_queue_vendor_sales")
        self.assertIn("item_plan.range_backoff(", body)
        self.assertLess(
            body.index("item_plan.range_backoff("), body.index("_insert_sell")
        )

    def test_the_counter_yards_box_is_untouched(self):
        self.assertIn("\nTOWN_COUNTER_YARDS = 8\n", BRIDGE)


def _run_pass(refusals, standing, spot):
    """The real `_queue_vendor_sales` with a fake world; (inserted, lines)."""
    inserted, lines = [], []

    async def reading(holder, where, age):
        return None

    namespace = {
        "asyncio": asyncio,
        "bag_pressure": bag_pressure,
        "item_plan": item_plan,
        "_fetch_town": lambda name: types.SimpleNamespace(vendor=True),
        "_insert_sell": lambda c: inserted.append(c) or True,
        "_recent_range_refusals": lambda seconds: refusals,
        "_fetch_vendor_position": lambda name: standing,
        "_log_sale_reading": reading,
        "_SALE_WRITE_SPOT": spot,
        "log": types.SimpleNamespace(
            info=lambda msg, *a: lines.append(msg % a if a else msg)
        ),
    }
    fn = next(
        n
        for n in ast.walk(ast.parse(BRIDGE))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_queue_vendor_sales"
    )
    exec(
        compile(ast.Module(body=[fn], type_ignores=[]), "bridge.py", "exec"), namespace
    )
    candidates = tuple(
        bag_pressure.SellCandidate(
            holder="Ugga",
            item_guid=100 + i,
            count=1,
            item=bag_pressure.ItemForSale(quality=0, sell_price=5),
        )
        for i in range(3)
    )
    asyncio.run(namespace["_queue_vendor_sales"](candidates, "Ugga", False, "trip", ()))
    return inserted, lines


class TheSalePass(unittest.TestCase):
    def test_a_refused_member_that_has_not_moved_gets_no_rows(self):
        inserted, lines = _run_pass({"Ugga": (200, None)}, HERE, {"Ugga": HERE})
        self.assertEqual([], inserted)
        self.assertTrue(any("wait" in line for line in lines))

    def test_a_refused_member_that_walked_on_is_written_again(self):
        far = (1, 150.0, 200.0, 30.0)
        spot = {"Ugga": HERE}
        inserted, _ = _run_pass({"Ugga": (200, None)}, far, spot)
        self.assertEqual(3, len(inserted))
        self.assertEqual(far, spot["Ugga"])

    def test_a_member_nobody_refused_is_written_as_before(self):
        inserted, _ = _run_pass({}, HERE, {})
        self.assertEqual(3, len(inserted))


if __name__ == "__main__":
    unittest.main()
