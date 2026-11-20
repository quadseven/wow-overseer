"""A member no vendor can clear does not hold a gathering walk (#1261).

A gathering walk yields the travel column to the vendor trip while any member
sits at or below three free slots. The bag-floor release already drops a member
a vendor cannot lift (fruitless visits, nothing sellable) from every other floor
gate, but the gathering walk read the raw slots: such a member kept the family
where it stood, waiting on a trip that could never help, for hours.

Pinned here: the pure block skips released members, farmjob.decide walks for a
family whose only full member is released, and the bridge helper names exactly
the members `_floor_release` drops.
"""

import ast
import pathlib
import unittest

import bag_pressure
import farmjob
import gatheraim
from test_farmjob import FAMILY, order, reads

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


class _Log:
    def info(self, *a, **k):
        pass

    warning = exception = debug = info


class PureBlock(unittest.TestCase):
    def test_a_released_member_does_not_block(self):
        free = {"Ann": 0, "Bea": 3, "Cyn": 20}
        self.assertTrue(gatheraim.bags_block_gathering(free))
        self.assertEqual(
            "", gatheraim.bags_block_gathering(free, released={"Ann", "Bea"})
        )

    def test_an_unreleased_full_member_still_blocks(self):
        free = {"Ann": 0, "Bea": 3, "Cyn": 20}
        why = gatheraim.bags_block_gathering(free, released={"Ann"})
        self.assertIn("Bea", why)
        self.assertNotIn("Ann", why)

    def test_an_unreadable_reading_still_refuses(self):
        self.assertTrue(gatheraim.bags_block_gathering({}, released={"Bea"}))


class FarmDecision(unittest.TestCase):
    def test_a_family_whose_full_member_is_released_walks(self):
        free = {name: 20 for name in FAMILY}
        free["Og"] = 0
        before = farmjob.decide(order(), reads(free_slots=free))
        self.assertEqual(farmjob.TOWN, before.action)
        after = farmjob.decide(
            order(), reads(free_slots=free, released=frozenset({"Og"}))
        )
        self.assertNotEqual(farmjob.TOWN, after.action)


def _load(visits):
    wanted = {"_released_for_gathering", "_at_floor", "_floor_release"}
    nodes = [
        n
        for n in ast.walk(ast.parse(BRIDGE))
        if isinstance(n, ast.FunctionDef) and n.name in wanted
    ]
    ns = {
        "bag_pressure": bag_pressure,
        "log": _Log(),
        "_note_vendor_visits": lambda names: None,
        "_VENDOR_SELLABLE": {"A": 5, "B": 5},
        "_VISITS_UNCHANGED": dict(visits),
        "_FLOOR_RELEASED_SAID": set(),
        "_FLOOR_KEPT": {},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102
    return ns


class BridgeHelper(unittest.TestCase):
    def test_names_the_members_the_floor_release_drops(self):
        ns = _load({"A": bag_pressure.VENDOR_VISIT_LIMIT})
        self.assertEqual(
            frozenset({"A"}),
            ns["_released_for_gathering"](["A", "B"], {"A": 0, "B": 0}),
        )

    def test_a_member_a_vendor_can_still_clear_is_not_released(self):
        ns = _load({"A": 0})
        self.assertEqual(
            frozenset(), ns["_released_for_gathering"](["A", "B"], {"A": 0, "B": 0})
        )

    def test_the_farm_and_gather_passes_read_it(self):
        self.assertIn('"released": _released_for_gathering(names, free)', BRIDGE)
        self.assertIn("gatheraim.bags_block_gathering(free, released=released)", BRIDGE)


if __name__ == "__main__":
    unittest.main()
