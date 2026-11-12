"""A vendor errand whose sale queue can never be answered is handed back.

The case for #1983, read live on the dev realm on 2026-11-10: a family
leader stood on a vendor errand for over 55 minutes with all five
members stuck, the leader stalled and the other four on holds, the
third vendor-shaped family stall in 24 hours. The leader stands at a
counter in a city; the sale queue never drains, because the rows in it
belong to holders the world cannot serve from where they stand. Every
recovery the settle already had treats that queue as a reason to hold:
the movement release and the counter yield both require a drained
queue, and the bag-wait yield does not reach a leader at a counter.
So the errand, and the family the module holds for the leader, waited
on rows that could never be answered.

The settle now also reads the age of the oldest unanswered sale row,
and past the bound in vendor_stall.queue_bound the errand is handed
back whole: the release is the signal that starts the held members
walking back, and the rows are refused as their holders are polled
away from the counter. A queue still being answered, however slowly,
is left exactly as it was.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import jev_family_intent
import vendor_stall

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()

NOW = 10_000.0
LEADER = "Grug"
NAMES = ["Grug", "Ugga", "Zork"]
POSITIONS = {
    "Grug": {"map_id": 1, "pos_x": 0.0, "pos_y": 0.0},
    "Ugga": {"map_id": 1, "pos_x": 3500.0, "pos_y": 0.0},
    "Zork": {"map_id": 1, "pos_x": 5500.0, "pos_y": 0.0},
}
MEMBERS_STATE = "Ugga|held too far to walk|3500\nZork|held too far to walk|5500"


def _settle_method():
    tree = ast.parse(BRIDGE)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_settle_vendor_errand"
    )


def _settle(outstanding, oldest, sale_counts=None):
    """Run the bridge's own `_settle_vendor_errand` on the brief's case.

    The leader stands at a vendor with `outstanding` sales unanswered,
    the oldest of them `oldest` seconds old, and its sellers held far
    away. Returns (step, decision or None): the decision is the one the
    stall recovery was asked to apply.
    """
    decided = []

    async def apply(leader, decision, stall, bag_wait_seconds, free_slots):
        decided.append(decision)
        if decision.action == vendor_stall.YIELD:
            return vendor_stall.YIELD
        if decision.action == vendor_stall.RELEASE:
            return bag_pressure.VENDOR_ERRAND_RELEASE
        return None

    namespace = {
        "asyncio": asyncio,
        "bag_pressure": bag_pressure,
        "jev_family_intent": jev_family_intent,
        "vendor_stall": vendor_stall,
        "time": types.SimpleNamespace(monotonic=lambda: NOW),
        "log": types.SimpleNamespace(
            info=lambda *args: None,
            warning=lambda *args: None,
            debug=lambda *args: None,
        ),
        "_fetch_town": lambda name: types.SimpleNamespace(vendor=True),
        "_outstanding_sales": lambda names: outstanding,
        "_oldest_outstanding_sale_seconds": lambda names: oldest,
        "_fetch_free_slots": lambda names: {n: 0 for n in names},
        "_current_travel_npc": lambda name: "vendor",
        "_fetch_family_intents": lambda: {
            LEADER: {
                "leader_name": LEADER,
                "current_kind": "economy",
                "current_for": 60,
                "members_state": MEMBERS_STATE,
            }
        },
        "_fetch_vendor_position": lambda name: (1, 0.0, 0.0, 0.0),
        "_fetch_positions": lambda names: {n: POSITIONS[n] for n in names},
        "_fetch_vendor_wait_seconds": lambda names: 60,
        "_vendor_sale_counts": lambda names: (
            {"Grug": 0, "Ugga": 3, "Zork": 2} if sale_counts is None else sale_counts
        ),
        "_release_trade_errand": lambda name, kind: True,
    }
    exec(
        compile(
            ast.Module(body=[_settle_method()], type_ignores=[]), "bridge.py", "exec"
        ),
        namespace,
    )
    me = types.SimpleNamespace(
        _vendor_movement={},
        _vendor_family_movement={},
        _apply_vendor_stall_decision=apply,
    )
    result = asyncio.run(namespace["_settle_vendor_errand"](me, NAMES, LEADER))
    return result, decided[0] if decided else None


class AnUnanswerableQueueHandsTheErrandBack(unittest.TestCase):
    def test_the_errand_is_handed_back_once_the_queue_outlasts_the_bound(self):
        result, decision = _settle(2, vendor_stall.QUEUE_BOUND_SECONDS)
        self.assertIsNotNone(decision)
        self.assertEqual(vendor_stall.RELEASE, decision.action)
        self.assertIn("unanswered", decision.reason)
        self.assertEqual(bag_pressure.VENDOR_ERRAND_RELEASE, result)

    def test_a_queue_just_inside_the_bound_is_left_alone(self):
        result, decision = _settle(2, vendor_stall.QUEUE_BOUND_SECONDS - 1)
        self.assertIsNotNone(decision)
        self.assertEqual(vendor_stall.HOLD, decision.action)
        self.assertEqual(bag_pressure.VENDOR_ERRAND_HOLD, result)

    def test_a_young_queue_mid_sale_is_left_alone(self):
        result, decision = _settle(2, 60)
        self.assertIsNotNone(decision)
        self.assertEqual(vendor_stall.HOLD, decision.action)
        self.assertEqual(bag_pressure.VENDOR_ERRAND_HOLD, result)

    def test_a_drained_queue_settles_as_it_always_did(self):
        result, decision = _settle(
            0, None, sale_counts={"Grug": 0, "Ugga": 0, "Zork": 0}
        )
        self.assertIsNotNone(decision)
        self.assertEqual(vendor_stall.HOLD, decision.action)
        self.assertEqual(bag_pressure.VENDOR_ERRAND_RELEASE, result)


if __name__ == "__main__":
    unittest.main()
