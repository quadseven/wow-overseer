"""A member that reaches a vendor counter is sold for, not re-aimed or skipped (#2215).

Two hand-off gaps were seen on the dev realm, both from a cut-off member that
had reached a counter with sellable stacks and 0 free slots:

- A fresh vendor aim was written to a member standing at a counter, and the
  module dropped the counter hold it had put on that member ("it has been sent
  somewhere else and cannot be both at a counter and on its way to one").
- The vendor pass returned on a leader yield before it queued any sale, so a
  member held at a counter for its full hold got no row ("nothing came back
  for it").
"""

import ast
import pathlib
import unittest

import bag_pressure
import vendor_stall

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _method(name):
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == name
    )


class AMemberAlreadyAtACounterIsNotReAimed(unittest.TestCase):
    NAMES = ("Grug", "Bork", "Grog")
    POSITIONS = {
        "Grug": {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0},
        "Bork": {"map_id": 0, "pos_x": 2000.0, "pos_y": 0.0},
        "Grog": {"map_id": 0, "pos_x": 1400.0, "pos_y": 0.0},
    }
    SLOTS = {"Grug": 13, "Bork": 2, "Grog": 0}

    def aims(self, at_counter=None):
        kwargs = {} if at_counter is None else {"at_counter": at_counter}
        return bag_pressure.stranded_vendor_aims(
            self.NAMES,
            "Grug",
            self.POSITIONS,
            self.SLOTS,
            pressure=True,
            in_run=False,
            **kwargs,
        )

    def test_both_cut_off_members_are_aimed_when_neither_is_at_a_counter(self):
        self.assertEqual(self.aims(frozenset()), ("Bork", "Grog"))

    def test_the_one_standing_at_a_counter_is_left_to_sell(self):
        self.assertEqual(self.aims(frozenset({"Grog"})), ("Bork",))

    def test_both_at_a_counter_get_no_aim(self):
        self.assertEqual(self.aims(frozenset({"Bork", "Grog"})), ())

    def test_the_default_reads_nobody_as_at_a_counter(self):
        self.assertEqual(self.aims(), ("Bork", "Grog"))

    def test_the_bridge_reads_each_candidate_counter_before_aiming(self):
        body = ast.unparse(_method("_aim_stranded_bag_pressure_members"))
        self.assertIn("at_counter=", body)
        self.assertIn('globals().get("_fetch_town")', body.replace("'", '"'))


class AVendorYieldStillSellsForThoseAtACounter(unittest.TestCase):
    def test_a_yield_becomes_a_hold_and_other_steps_are_unchanged(self):
        self.assertEqual(
            bag_pressure.step_after_yield(vendor_stall.YIELD),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )
        for step in (
            bag_pressure.VENDOR_ERRAND_AIM,
            bag_pressure.VENDOR_ERRAND_HOLD,
            bag_pressure.VENDOR_ERRAND_RELEASE,
        ):
            self.assertEqual(bag_pressure.step_after_yield(step), step)

    def test_the_vendor_pass_no_longer_returns_on_a_yield(self):
        for node in ast.walk(_method("_vendor_once")):
            if isinstance(node, ast.If) and "vendor_stall.YIELD" in ast.unparse(
                node.test
            ):
                self.assertFalse(
                    any(isinstance(stmt, ast.Return) for stmt in node.body),
                    "a vendor yield must not end the pass before it queues sales",
                )

    def test_the_vendor_pass_asks_for_the_step_after_a_yield(self):
        body = ast.unparse(_method("_vendor_once"))
        self.assertIn("bag_pressure.step_after_yield(step)", body)


if __name__ == "__main__":
    unittest.main()
