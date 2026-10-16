"""A vendor trip is not called off for a member the module holds for a fetch.

mod-overseer holds a member that is too far to walk back where it stands and
sends the leader back for it (the `fetch` intent), but it refuses to start that
walk while the bridge's `vendor` errand sits in the leader's travel column. The
vendor stall rule used to count that held member as the family failing to
follow, released the vendor aim after STALL_AFTER_SECONDS, the fetch took the
leader, and the sale was asked for again afterwards: the seller waited for a
vendor for hours while the leader turned between the two walks (#1046).
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
NAMES = ["Grug", "Bork", "Zork"]
# Grug walks toward the vendor with Bork beside him; Zork is held 900 yards back.
POSITIONS = {
    "Grug": {"map_id": 0, "pos_x": 100.0, "pos_y": 0.0},
    "Bork": {"map_id": 0, "pos_x": 105.0, "pos_y": 0.0},
    "Zork": {"map_id": 0, "pos_x": -800.0, "pos_y": 0.0},
}


def _settle_method():
    tree = ast.parse(BRIDGE)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_settle_vendor_errand"
    )


def _settle(members_state: str):
    """Run the bridge's own `_settle_vendor_errand` and return its stall decision.

    The family has been split for longer than the stall window (the previous
    reading says so) while the leader keeps walking.
    """
    decided = []

    async def apply(leader, decision, stall, bag_wait_seconds, free_slots):
        decided.append(decision)
        return "decided"

    namespace = {
        "asyncio": asyncio,
        "bag_pressure": bag_pressure,
        "jev_family_intent": jev_family_intent,
        "vendor_stall": vendor_stall,
        "time": types.SimpleNamespace(monotonic=lambda: NOW),
        "_fetch_town": lambda name: types.SimpleNamespace(vendor=None),
        "_outstanding_sales": lambda names: 0,
        "_fetch_free_slots": lambda names: {n: 0 for n in names},
        "_current_travel_npc": lambda name: "vendor",
        "_fetch_family_intents": lambda: {
            LEADER: {
                "leader_name": LEADER,
                "current_kind": "economy",
                "current_for": 1500,
                "members_state": members_state,
            }
        },
        "_fetch_vendor_position": lambda name: (0, 100.0, 0.0, 0.0),
        "_fetch_positions": lambda names: {n: POSITIONS[n] for n in names},
    }
    exec(
        compile(
            ast.Module(body=[_settle_method()], type_ignores=[]), "bridge.py", "exec"
        ),
        namespace,
    )
    split_at = NOW - vendor_stall.STALL_AFTER_SECONDS - 60
    me = types.SimpleNamespace(
        # The leader was 40 yards back a moment ago: he is still walking.
        _vendor_movement={LEADER: vendor_stall.Movement(0, 60.0, 0.0, 0.0, NOW)},
        _vendor_family_movement={
            LEADER: vendor_stall.FamilyMovement(
                tuple(
                    (n, POSITIONS[n]["map_id"], POSITIONS[n]["pos_x"], 0.0)
                    for n in NAMES
                ),
                split_at,
                split_at,
            )
        },
        _apply_vendor_stall_decision=apply,
    )
    result = asyncio.run(namespace["_settle_vendor_errand"](me, NAMES, LEADER))
    assert result == "decided", result
    return decided[0]


class AHeldMemberDoesNotCallOffTheVendorTrip(unittest.TestCase):
    def test_a_member_held_for_the_leader_keeps_the_walk_to_the_vendor(self):
        decision = _settle("Bork|following|5\nZork|held too far to walk|900")
        self.assertEqual(vendor_stall.HOLD, decision.action)

    def test_a_member_held_off_a_deadly_walk_keeps_it_too(self):
        decision = _settle("Bork|following|5\nZork|held off a deadly walk|900")
        self.assertEqual(vendor_stall.HOLD, decision.action)

    def test_a_member_left_behind_while_following_still_releases_it(self):
        decision = _settle("Bork|following|5\nZork|following|900")
        self.assertEqual(vendor_stall.RELEASE, decision.action)
        self.assertIn("family split", decision.reason)


class WhoTheSplitClockWatches(unittest.TestCase):
    def test_members_held_for_the_leader_are_left_out(self):
        states = {"Bork": "following", "Zork": "held too far to walk"}
        self.assertEqual(
            ("Grug", "Bork"), vendor_stall.following(("Grug", "Bork", "Zork"), states)
        )

    def test_every_other_state_is_watched(self):
        states = {"Bork": "walking back", "Zork": "on an errand of its own"}
        self.assertEqual(
            ("Grug", "Bork", "Zork"),
            vendor_stall.following(("Grug", "Bork", "Zork"), states),
        )

    def test_no_intent_row_watches_everyone(self):
        self.assertEqual(("Grug", "Bork"), vendor_stall.following(("Grug", "Bork"), {}))


if __name__ == "__main__":
    unittest.main()
