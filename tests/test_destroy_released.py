"""Released quest items no vendor will buy are queued for destruction.

wow-overseer#241 releases a quest item (item class 12) once its holder no
longer needs it, and a priced one then sells. An unpriced one could never
leave the bags, because the core's sale refuses a SellPrice of 0.
mod-overseer#614 added a `destroy guid:<n> count:<n>` grammar on the
kind='sell' row, and this pins the side that writes it:

  * `bag_pressure.destroy_candidates` picks only class-12 stacks the row
    explicitly marks as no longer a quest item, with a price of exactly 0,
    of Uncommon quality or below, and not a reagent, trade stock or an
    owner-kept name.
  * `bag_pressure.destroy_command` renders the whole stack and allows
    nothing, so the world refuses bound gear and rare items by default.
  * `_destroy_released` writes one row per candidate through
    `_insert_destroy`, skips a stack the world already answered, and needs
    no vendor.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import item_plan

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


def leftover(**kw):
    """One carried Un'Goro Soil stack, as _VENDOR_ITEMS_SQL returns it."""
    base = dict(
        holder="Ugg",
        item_guid=7001,
        count=99,
        entry=11018,
        name="Un'Goro Soil",
        quality=1,
        sell_price=0,
        item_class=12,
        bag_family=0,
        quest_item=0,
        reagent=0,
        profession_needed=False,
    )
    base.update(kw)
    return base


class TheCandidatesAreReleasedUnpricedQuestItems(unittest.TestCase):
    def test_a_released_unpriced_quest_stack_is_a_candidate(self):
        got = bag_pressure.destroy_candidates([leftover()])
        self.assertEqual(
            [("Ugg", 7001, 99)], [(c.holder, c.item_guid, c.count) for c in got]
        )

    def test_a_stack_a_quest_still_needs_is_not(self):
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(quest_item=1)]))

    def test_a_row_that_does_not_say_is_kept(self):
        row = leftover()
        del row["quest_item"]
        self.assertEqual((), bag_pressure.destroy_candidates([row]))

    def test_a_priced_stack_goes_to_the_vendor_instead(self):
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(sell_price=5)]))

    def test_only_quest_class(self):
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(item_class=15)]))

    def test_nothing_above_uncommon(self):
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(quality=3)]))
        self.assertEqual(1, len(bag_pressure.destroy_candidates([leftover(quality=2)])))

    def test_trade_stock_and_reagents_are_kept(self):
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(reagent=1)]))
        self.assertEqual(
            (), bag_pressure.destroy_candidates([leftover(profession_needed=True)])
        )

    def test_an_owner_kept_name_is_kept(self):
        self.assertEqual(
            (),
            bag_pressure.destroy_candidates([leftover()], keep_names=("un'goro soil",)),
        )

    def test_a_garbled_row_is_skipped_not_raised(self):
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(count="x")]))
        self.assertEqual((), bag_pressure.destroy_candidates([leftover(count=0)]))

    def test_the_command_is_the_whole_stack_and_allows_nothing(self):
        (candidate,) = bag_pressure.destroy_candidates([leftover()])
        self.assertEqual(
            "destroy guid:7001 count:99", bag_pressure.destroy_command(candidate)
        )

    def test_the_world_answer_is_read_back_by_guid(self):
        """item_plan keys a destroy row on the same guid as a sale."""
        self.assertEqual(
            (7001, 99), item_plan.parse_request("destroy guid:7001 count:99")
        )


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _thread(fn, *a, **k):
    async def run():
        return fn(*a, **k)

    return run()


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


def _run(rows, attempts=(), insert=None):
    written = []
    log = _Log()
    namespace = {
        "asyncio": types.SimpleNamespace(to_thread=_thread),
        "bag_pressure": bag_pressure,
        "item_plan": item_plan,
        "log": log,
        "OWNER_KEEPS": (),
        "SELL_MEMORY_HOURS": 24,
        "_sell_attempts": lambda hours: list(attempts),
        "_insert_destroy": insert
        or (lambda c: written.append(bag_pressure.destroy_command(c)) or 1),
    }
    module = ast.Module(body=[_function("_destroy_released")], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
    asyncio.run(namespace["_destroy_released"](None, rows))
    return written, log.lines


class ThePassWritesOneDestroyPerStack(unittest.TestCase):
    def test_a_released_unpriced_stack_is_written(self):
        written, lines = _run(
            [leftover(), leftover(item_guid=7002, count=65, sell_price=4)]
        )
        self.assertEqual(["destroy guid:7001 count:99"], written, lines)
        self.assertTrue(any("queued 1/1 destroy" in ln for ln in lines), lines)

    def test_a_stack_the_world_already_answered_is_not_written_again(self):
        done = item_plan.Attempt(
            holder="Ugg", item_guid=7001, status="delivered", count=99
        )
        written, _ = _run([leftover()], attempts=[done])
        self.assertEqual([], written)

    def test_a_failed_insert_is_logged_and_never_raised(self):
        def broken(candidate):
            raise RuntimeError("lost connection")

        written, lines = _run([leftover()], insert=broken)
        self.assertEqual([], written)
        self.assertTrue(
            any("the sales behind it carry on" in ln for ln in lines), lines
        )

    def test_nothing_to_destroy_writes_and_logs_nothing(self):
        written, lines = _run([leftover(quest_item=1)])
        self.assertEqual(([], []), (written, lines))


class TheWriterIsTheSellRow(unittest.TestCase):
    def test_insert_destroy_writes_kind_sell_with_the_destroy_command(self):
        body = ast.get_source_segment(BRIDGE, _function("_insert_destroy"))
        self.assertIn("'sell'", body)
        self.assertIn("bag_pressure.destroy_command(candidate)", body)

    def test_the_vendor_pass_destroys_before_any_vendor_gate(self):
        body = ast.get_source_segment(BRIDGE, _function("_vendor_once"))
        self.assertLess(
            body.index("_destroy_released(rows)"), body.index("_vendor_pass_mode")
        )


if __name__ == "__main__":
    unittest.main()
