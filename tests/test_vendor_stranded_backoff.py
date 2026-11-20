"""A vendor trip that sold for one holder only does not re-take the column.

The family was held for hours: the one member standing at a counter had a sale
queued every pass, which cleared the urgent-claim streak, while the members out
of reach of any counter kept full bags. The trip then took the travel column
again at once. A trip that left holders stranded is fruitless for backoff.
"""

import ast
import asyncio
import pathlib
import time
import types
import unittest

import bag_pressure
import item_plan
import townslot

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


async def _no_reading(holder, standing, age):
    return None


def _load(name, namespace):
    fn = next(
        n
        for n in ast.walk(ast.parse(BRIDGE))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    exec(
        compile(ast.Module(body=[fn], type_ignores=[]), "bridge.py", "exec"), namespace
    )
    return namespace[name]


def _candidate(holder, guid):
    return bag_pressure.SellCandidate(
        holder=holder,
        item_guid=guid,
        count=1,
        item=bag_pressure.ItemForSale(quality=0, sell_price=5),
    )


def _env(at_counter, inserted, logged):
    return {
        "asyncio": asyncio,
        "time": time,
        "bag_pressure": bag_pressure,
        "item_plan": item_plan,
        "_fetch_town": lambda name: types.SimpleNamespace(vendor=name in at_counter),
        "_insert_sell": lambda c: inserted.append(c) or True,
        "_recent_range_refusals": lambda seconds: {},
        "_fetch_vendor_position": lambda name: None,
        "_log_sale_reading": _no_reading,
        "_SALE_WRITE_SPOT": {},
        "log": types.SimpleNamespace(
            info=lambda msg, *a: logged.append(msg % a if a else msg),
            warning=lambda msg, *a: None,
        ),
    }


class StrandedHolders(unittest.TestCase):
    def _pass(self, at_counter, holders):
        inserted, logged = [], []
        env = _env(at_counter, inserted, logged)
        queue = _load("_queue_vendor_sales", env)
        report = _load("_report_vendor_claim", env)
        cands = [_candidate(h, 100 + i) for i, h in enumerate(holders)]
        wrote = asyncio.run(
            queue(cands, "Traveller", False, bag_pressure.VENDOR_MODE_COUNTER, [])
        )
        return env, report, wrote, logged

    def test_a_holder_in_reach_is_queued_while_the_traveller_is_elsewhere(self):
        _env_, _r, wrote, _log = self._pass({"Seller"}, ["Seller", "Other"])
        self.assertEqual(1, wrote)

    def test_a_trip_that_left_a_holder_stranded_does_not_clear_the_streak(self):
        env, report, wrote, _log = self._pass({"Seller"}, ["Seller", "Other"])
        slot = townslot.Slot()
        report(slot, True, wrote)
        self.assertEqual(1, slot._fruitless["economy"][0])

    def test_a_trip_that_reached_everybody_is_productive(self):
        env, report, wrote, _log = self._pass({"A", "B"}, ["A", "B"])
        slot = townslot.Slot()
        slot.fruitless("economy", time.monotonic())
        report(slot, True, wrote)
        self.assertNotIn("economy", slot._fruitless)

    def test_the_backoff_holds_urgency_then_lets_it_back(self):
        slot = townslot.Slot()
        until = slot.fruitless("economy", 1000.0)
        self.assertGreater(until, 1000.0)
        self.assertEqual(1, slot._fruitless["economy"][0])
        self.assertGreaterEqual(until - 1000.0, townslot.URGENT_BACKOFF_SECONDS)

    def test_the_no_vendor_line_is_said_once_per_window(self):
        env, _r, _w, logged = self._pass({"Seller"}, ["Seller", "Other"])
        queue = env["_queue_vendor_sales"]
        asyncio.run(
            queue(
                [_candidate("Other", 7)],
                "T",
                False,
                bag_pressure.VENDOR_MODE_COUNTER,
                [],
            )
        )
        said = [m for m in logged if "no vendor within reach" in m]
        self.assertEqual(1, len(said))


if __name__ == "__main__":
    unittest.main()
