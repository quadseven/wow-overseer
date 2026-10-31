"""A vendor that has no sale left yields the family to its other town work."""

import ast
import asyncio
import pathlib
import time
import types
import unittest

import bag_pressure
import vendor_stall

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def settle(sellable, outstanding=0, at_counter=True):
    tree = ast.parse(BRIDGE.read_text())
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_settle_vendor_errand"
    )
    released = []
    names = ["Grug", "Bork", "Og"]
    position = {"map_id": 0, "pos_x": 0, "pos_y": 0, "pos_z": 0}

    def quiet(*args):
        return None

    namespace = {
        "asyncio": asyncio,
        "time": time,
        "bag_pressure": bag_pressure,
        "vendor_stall": vendor_stall,
        "jev_family_intent": types.SimpleNamespace(parse_members=lambda value: []),
        "_fetch_town": lambda name: types.SimpleNamespace(vendor=at_counter),
        "_outstanding_sales": lambda names: outstanding,
        "_fetch_free_slots": lambda names: {"Grug": 4, "Bork": 0, "Og": 0},
        "_current_travel_npc": lambda name: "vendor",
        "_fetch_family_intents": lambda: {},
        "_fetch_vendor_position": lambda name: (0, 0, 0, 0),
        "_fetch_positions": lambda names: {name: position for name in names},
        "_release_trade_errand": lambda *args: released.append(args) or 1,
        "_VENDOR_SELLABLE": sellable,
        "log": types.SimpleNamespace(info=quiet, warning=quiet, debug=quiet),
    }
    exec(
        compile(ast.Module(body=[fn], type_ignores=[]), "bridge.py", "exec"), namespace
    )

    async def no_recovery(*args):
        return None

    owner = types.SimpleNamespace(
        _vendor_movement={},
        _vendor_family_movement={},
        _apply_vendor_stall_decision=no_recovery,
    )
    result = asyncio.run(namespace["_settle_vendor_errand"](owner, names, "Grug"))
    return result, released


class EmptyVendorHandsBackTheAim(unittest.TestCase):
    def test_full_protected_bags_do_not_hold_an_empty_vendor(self):
        step, released = settle({"Grug": 0, "Bork": 0, "Og": 0, "Zug": 12})
        self.assertEqual(step, bag_pressure.VENDOR_ERRAND_RELEASE)
        self.assertEqual(released, [("Grug", "vendor")])

    def test_a_follower_with_something_to_sell_keeps_the_counter(self):
        step, released = settle({"Grug": 0, "Bork": 1, "Og": 0})
        self.assertEqual(step, bag_pressure.VENDOR_ERRAND_HOLD)
        self.assertEqual(released, [])

    def test_an_unread_member_keeps_the_counter(self):
        step, released = settle({"Grug": 0, "Bork": 0})
        self.assertEqual(step, bag_pressure.VENDOR_ERRAND_HOLD)
        self.assertEqual(released, [])

    def test_queued_or_unreadable_sales_keep_the_counter(self):
        for outstanding in (1, -1):
            with self.subTest(outstanding=outstanding):
                step, released = settle({"Grug": 0, "Bork": 0, "Og": 0}, outstanding)
                self.assertEqual(step, bag_pressure.VENDOR_ERRAND_HOLD)
                self.assertEqual(released, [])

    def test_empty_read_does_not_abandon_a_trip_before_arrival(self):
        step, released = settle({"Grug": 0, "Bork": 0, "Og": 0}, at_counter=False)
        self.assertEqual(step, bag_pressure.VENDOR_ERRAND_AIM)
        self.assertEqual(released, [])
