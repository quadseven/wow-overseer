"""A stack the world already sold is not a reason to wait for a vendor (#1261).

Measured on the dev realm after the 30-minute vendor-wait trip shipped: the
trip fired for hours on one family while every one of its sale passes wrote
nothing ("queued 0/1 vendor sale(s), held back 1 delivered"). Each holder
still carried one candidate whose sale the world had already answered
`delivered`, and the save file had not caught up. `item_plan` held that
candidate back every pass, so no vendor visit could ever sell it, yet the
holder gate logged "no vendor within reach" for it whenever the holder was
away from a counter. That line is the `no_vendor` step the stuck read names
"Waiting for a vendor within reach", and its age is what the wait trip reads,
so the wait never ended and the trip re-fired into a sale of nothing.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import item_plan
import nowstatus

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def _queue_vendor_sales(town_vendor: dict, logged: list, inserted: list):
    tree = ast.parse(BRIDGE)
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_queue_vendor_sales"
    )
    namespace = {
        "asyncio": asyncio,
        "bag_pressure": bag_pressure,
        "item_plan": item_plan,
        "_fetch_town": lambda name: types.SimpleNamespace(
            vendor=town_vendor.get(name, False)
        ),
        "_insert_sell": lambda candidate: inserted.append(candidate) or True,
        "log": types.SimpleNamespace(
            info=lambda msg, *args: logged.append(msg % args if args else msg)
        ),
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "bridge.py", "exec"),
         namespace)
    return namespace["_queue_vendor_sales"]


def _candidate(holder, guid):
    return bag_pressure.SellCandidate(
        holder=holder, item_guid=guid, count=1,
        item=bag_pressure.ItemForSale(quality=0, sell_price=5),
    )


def _no_vendor_steps(lines):
    """The `no_vendor` steps the now-status tap would store for these lines."""
    return [
        step
        for line in lines
        for step in nowstatus.classify(line)
        if step.kind == "no_vendor"
    ]


class AnAnsweredSaleIsNotAVendorWait(unittest.TestCase):
    def _run(self, attempts):
        logged, inserted = [], []
        queue = _queue_vendor_sales({}, logged, inserted)
        asyncio.run(queue(
            [_candidate("Ugga", 101)], "Grug", False,
            bag_pressure.VENDOR_MODE_COUNTER, attempts,
        ))
        return logged, inserted

    def test_a_holder_whose_only_stack_was_sold_writes_no_vendor_wait(self):
        sold = [item_plan.Attempt(holder="Ugga", item_guid=101,
                                  status="delivered")]
        logged, inserted = self._run(sold)
        self.assertEqual([], inserted)
        self.assertEqual([], _no_vendor_steps(logged))

    def test_a_holder_with_an_unsold_stack_still_waits_for_a_vendor(self):
        logged, inserted = self._run([])
        self.assertEqual([], inserted)
        self.assertEqual(1, len(_no_vendor_steps(logged)))

    def test_a_queued_sale_still_waits_for_the_holder_to_reach_a_vendor(self):
        # An open row is not answered: it sells only once its holder stands at
        # a counter, so that holder is still waiting for a vendor.
        open_row = [item_plan.Attempt(holder="Ugga", item_guid=101,
                                      status="pending")]
        logged, _ = self._run(open_row)
        self.assertEqual(1, len(_no_vendor_steps(logged)))


if __name__ == "__main__":
    unittest.main()
