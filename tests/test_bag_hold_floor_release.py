"""The dungeon quest bag hold honours a member released from the floor (#1261).

The campaign gate and the town errand read free slots through `_floor_release`,
which drops a member no vendor can clear. The dungeon quest hold read the raw
slots, so a released member still pinned the family at "waits for bag room"
while the trip it waited for could not lift that member.

Pinned here: `_bag_hold_reads` returns the slots with a released member
dropped, so `jev_activity.withheld` no longer holds, and a member still
clearable by a vendor keeps the hold.
"""

import ast
import pathlib
import unittest

import bag_pressure
import jev_activity

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
NAMES = ["A", "B", "C", "D", "E"]
FREE = {"A": 10, "B": 0, "C": 17, "D": 0, "E": 20}


class _Log:
    def info(self, *a, **k):
        pass

    warning = exception = debug = info


def _load(visits):
    wanted = {"_bag_hold_reads", "_at_floor", "_floor_release"}
    nodes = [
        n
        for n in ast.walk(ast.parse(BRIDGE))
        if isinstance(n, ast.FunctionDef) and n.name in wanted
    ]
    ns = {
        "bag_pressure": bag_pressure,
        "log": _Log(),
        "_present_members": lambda names, leader="": list(names),
        "_fetch_free_slots": lambda names: {n: FREE[n] for n in names},
        "_current_travel_npc": lambda name: "vendor",
        "_note_vendor_visits": lambda names: None,
        "_VENDOR_SELLABLE": {n: 5 for n in NAMES},
        "_VISITS_UNCHANGED": dict(visits),
        "_FLOOR_RELEASED_SAID": set(),
        "_FLOOR_KEPT": {},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102
    return ns


class BagHoldFloorRelease(unittest.TestCase):
    def test_released_members_do_not_hold_the_quest_walk(self):
        limit = bag_pressure.VENDOR_VISIT_LIMIT
        ns = _load({"B": limit, "D": limit})
        here, free, column = ns["_bag_hold_reads"](NAMES, "A")
        self.assertEqual(here, NAMES)
        self.assertEqual(column, "vendor")
        self.assertNotIn("B", free)
        self.assertNotIn("D", free)
        self.assertFalse(jev_activity.withheld(True, free))

    def test_a_member_a_vendor_can_still_clear_keeps_the_hold(self):
        ns = _load({"B": 0, "D": 0})
        _here, free, _column = ns["_bag_hold_reads"](NAMES, "A")
        self.assertEqual(free["B"], 0)
        self.assertTrue(jev_activity.withheld(True, free))


if __name__ == "__main__":
    unittest.main()
