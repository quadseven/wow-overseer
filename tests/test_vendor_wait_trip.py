"""A sustained wait for a vendor leads to a real sale trip."""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import jev_activity


BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


class VendorWaitTrip(unittest.TestCase):
    def test_carried_goods_get_a_trip_before_the_two_hour_stuck_finding(self):
        self.assertTrue(
            bag_pressure.vendor_wait_trip(
                wait_seconds=30 * 60,
                sellable_counts={"Leader": 2},
                in_run=False,
            )
        )

    def test_no_trip_without_a_sustained_wait_or_goods(self):
        self.assertFalse(bag_pressure.vendor_wait_trip(29 * 60, {"Leader": 2}, False))
        self.assertFalse(bag_pressure.vendor_wait_trip(30 * 60, {"Leader": 0}, False))
        self.assertFalse(bag_pressure.vendor_wait_trip(30 * 60, {"Leader": 2}, True))

    def test_vendor_pass_claims_a_trip_for_an_old_range_wait(self):
        tree = ast.parse(BRIDGE)
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_vendor_pass_mode"
        )
        namespace = {
            "asyncio": asyncio,
            "bag_pressure": bag_pressure,
            "jev_activity": jev_activity,
            "_town_first_hold": lambda names: False,
            "_campaign_waiting": lambda names: False,
            "_fetch_vendor_wait_seconds": lambda names: 30 * 60,
            "log": types.SimpleNamespace(info=lambda *args: None),
        }
        exec(
            compile(ast.Module(body=[method], type_ignores=[]), "bridge.py", "exec"),
            namespace,
        )
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Leader"], {"Leader": 12}, {"Leader": 2}, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)
