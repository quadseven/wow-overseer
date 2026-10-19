"""A sustained wait for a vendor leads to a real sale trip."""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import jev_activity


BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def _vendor_pass_mode(namespace_extra=None):
    """The bridge's vendor pass mode, loaded on its own."""
    tree = ast.parse(BRIDGE)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_vendor_pass_mode"
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
    namespace.update(namespace_extra or {})
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace


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
        namespace = _vendor_pass_mode()
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Leader"], {"Leader": 12}, {"Leader": 2}, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)


class TheTripMakesTheFamilyRoom(unittest.TestCase):
    """#1204: the family at the floor whose sale is shared between its members.

    The dev realm on 2026-10-19: Grog, Og and Ugga each carried stacks a
    vendor would buy, and Bork held the family at the floor with 68 stacks no
    vendor will buy (34 uncommon or better, 24 profession stock, 5 a quest
    item, 5 with no vendor price). No single member's sale cleared the
    trigger of 3 free slots, so the pass took no trip, wrote no sale rows and
    logged "no vendor within reach" for the three of them on every pass - and
    the health endpoint read them as stuck for 2.2 hours.
    """

    NAMES = ["Bork", "Grog", "Ugga", "Og"]
    FREE = {"Bork": 0, "Grog": 0, "Ugga": 0, "Og": 10}
    SELLABLE = {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2}

    def test_the_trip_goes_when_the_family_frees_room_between_its_members(self):
        # No sustained wait either: the family has not been waiting for a
        # vendor, its sale is simply spread over three members.
        namespace = _vendor_pass_mode({"_fetch_vendor_wait_seconds": lambda names: 0})
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, self.NAMES, self.FREE, self.SELLABLE, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)

    def test_no_trip_when_the_family_carries_nothing_a_vendor_would_buy(self):
        # Bork alone at the floor, with 68 kept stacks: the trip cannot help
        # anybody, and infra#4190's answer still stands.
        namespace = _vendor_pass_mode({"_fetch_vendor_wait_seconds": lambda names: 0})
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Bork"], {"Bork": 0}, {"Bork": 0}, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_COUNTER, mode)
