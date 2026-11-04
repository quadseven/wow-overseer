"""A counter visit ends when the sellers' wait reaches the wait trip.

The brief's case for #1261: the family is in counter mode, the leader
stands at a vendor with no sale queued, and the sellers are held far
away with their range retries spent, so nothing they carry can be sold
from where they stand. The module fetches a held seller only once the
bridge's vendor errand leaves the leader's column, so the visit has to
end on the sellers' clock: the fresh no-vendor wait age the bridge
already reads for the vendor-wait trip. The leader's own step age
cannot carry that bound - its intent keeps changing while the sellers
stay held, so the step restarts and the wait outlasts every bound the
step was ever going to reach.
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
# The leader stands at the vendor; the sellers are held 3,500 and 5,500
# yards away, too far to walk back while the errand stands.
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


def _settle(wait_seconds):
    """Run the bridge's own `_settle_vendor_errand` on the brief's case.

    The leader's current step is a minute old and no sale is outstanding:
    the sellers' stacks are all held back on spent range retries, which
    is why the queue is empty while they still carry goods a vendor
    would buy. Returns (step, decision or None).
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
        "_outstanding_sales": lambda names: 0,
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
        "_fetch_vendor_wait_seconds": lambda names: wait_seconds,
        "_vendor_sale_counts": lambda names: {"Grug": 0, "Ugga": 3, "Zork": 2},
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


class ACounterVisitEndsOnTheSellersWait(unittest.TestCase):
    def test_the_visit_yields_when_the_sellers_wait_reaches_the_trip(self):
        result, decision = _settle(vendor_stall.MAX_IDLE_COUNTER_SECONDS)
        self.assertIsNotNone(decision)
        self.assertEqual(vendor_stall.YIELD, decision.action)
        self.assertIn("held sellers rejoin", decision.reason)
        self.assertEqual(vendor_stall.YIELD, result)

    def test_the_visit_holds_while_the_sellers_wait_is_young(self):
        result, decision = _settle(vendor_stall.MAX_IDLE_COUNTER_SECONDS - 1)
        self.assertIsNotNone(decision)
        self.assertEqual(vendor_stall.HOLD, decision.action)
        self.assertEqual(bag_pressure.VENDOR_ERRAND_HOLD, result)


if __name__ == "__main__":
    unittest.main()
