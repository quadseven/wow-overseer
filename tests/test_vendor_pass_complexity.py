"""The vendor pass stays small enough to read (wow-overseer#977).

The review on #975 measured `_vendor_once` at cyclomatic 26 / cognitive 33 and
`_settle_vendor_errand` at 19 / 27, against caps of 15 and 25. By the time the
finding was picked up `_settle_vendor_errand` had already been split (its
stall recovery is `_apply_vendor_stall_decision`), and `_vendor_once` had grown
to 28 / 35. The aim, the per-holder sell rows and the outcome report are now
their own functions, and the pass is orchestration.

The metric below is the review's own: cyclomatic is 1 + each branch, loop,
handler, `with`, conditional expression, comprehension and `assert`, plus one
per extra boolean operand; cognitive charges each `if`/loop/handler 1 plus its
nesting depth and each boolean sequence 1. A refactor that only moved code
around inside the function would not change either number.

The behaviour tests run the extracted pieces on their own, with fakes for the
world, so the split is checked for what it does as well as for its size.
"""

import ast
import asyncio
import pathlib
import types
import unittest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (PACKAGE / "bridge.py").read_text(encoding="utf-8")
TREE = ast.parse(BRIDGE)

CYCLOMATIC_CAP = 15
COGNITIVE_CAP = 25

_CYCLO_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
    ast.comprehension,
    ast.Assert,
)
_NESTERS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)


def _function(name):
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _cyclomatic(func) -> int:
    score = 1
    for node in ast.walk(func):
        if isinstance(node, _CYCLO_NODES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.match_case):
            wildcard = isinstance(node.pattern, ast.MatchAs) and (
                node.pattern.pattern is None
            )
            score += 0 if wildcard else 1
    return score


def _cognitive(func) -> int:
    def walk(node, depth):
        total = 0
        for child in ast.iter_child_nodes(node):
            inc, child_depth = 0, depth
            if isinstance(child, _NESTERS):
                inc, child_depth = 1 + depth, depth + 1
            elif isinstance(child, ast.BoolOp):
                inc = 1
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_depth = depth + 1
            total += inc + walk(child, child_depth)
        return total

    return walk(func, 0)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = debug = info


def _thread(fn, *a, **k):
    async def run():
        return fn(*a, **k)

    return run()


class TheVendorPassIsUnderTheReviewCaps(unittest.TestCase):
    FUNCTIONS = (
        "_vendor_once",
        "_settle_vendor_errand",
        "_take_vendor_aim",
        "_queue_vendor_sales",
        "_report_vendor_claim",
        "_count_sales",
    )

    def test_each_piece_is_under_the_cyclomatic_cap(self):
        for name in self.FUNCTIONS:
            with self.subTest(function=name):
                self.assertLessEqual(_cyclomatic(_function(name)), CYCLOMATIC_CAP)

    def test_each_piece_is_under_the_cognitive_cap(self):
        for name in self.FUNCTIONS:
            with self.subTest(function=name):
                self.assertLessEqual(_cognitive(_function(name)), COGNITIVE_CAP)

    def test_the_metric_counts_what_the_review_counts(self):
        """A hand-worked sample, so a copy of the metric that quietly stopped
        counting something cannot pass a function the review would flag."""
        sample = ast.parse(
            "def f(a, b):\n"
            "    if a and b:\n"
            "        for x in a:\n"
            "            if x:\n"
            "                return [y for y in b]\n"
            "    return 1 if a else 2\n"
        ).body[0]
        # 1 + if + bool(1) + for + if + comprehension + ifexp
        self.assertEqual(7, _cyclomatic(sample))
        # if 1 + bool 1 + for 2 + if 3
        self.assertEqual(7, _cognitive(sample))


class ThePassHandsTheRowsAndTheReportToItsHelpers(unittest.TestCase):
    def test_the_aim_comes_before_the_rows_and_the_report_after(self):
        body = ast.get_source_segment(BRIDGE, _function("_vendor_once"))
        aim = body.index("aimed = await self._take_vendor_aim(step, leader, cohort)")
        rows = body.index("inserted = await _queue_vendor_sales(")
        report = body.index("_report_vendor_claim(slot, aimed, inserted)")
        self.assertLess(aim, rows)
        self.assertLess(rows, report)


class _Slot:
    def __init__(self):
        self.calls = []

    def productive(self, claimant):
        self.calls.append(("productive", claimant))

    def fruitless(self, claimant, now):
        self.calls.append(("fruitless", claimant))
        return now + 60.0


def _report_ns():
    log = _Log()
    ns = _load(
        ["_report_vendor_claim"],
        {"log": log, "time": types.SimpleNamespace(monotonic=lambda: 100.0)},
    )
    return ns, log


class TheReportOnlyCountsAClaimThePassHeld(unittest.TestCase):
    def test_a_claim_that_wrote_sales_is_productive(self):
        ns, _ = _report_ns()
        slot = _Slot()
        ns["_report_vendor_claim"](slot, True, 3)
        self.assertEqual([("productive", "economy")], slot.calls)

    def test_a_claim_that_wrote_nothing_is_fruitless_and_says_so(self):
        ns, log = _report_ns()
        slot = _Slot()
        ns["_report_vendor_claim"](slot, True, 0)
        self.assertEqual([("fruitless", "economy")], slot.calls)
        self.assertTrue(any("suppressed for 60s" in ln for ln in log.lines))

    def test_no_claim_is_neither(self):
        ns, _ = _report_ns()
        slot = _Slot()
        ns["_report_vendor_claim"](slot, False, 0)
        self.assertEqual([], slot.calls)


class _Candidate(types.SimpleNamespace):
    pass


def _queue(vendor_at, queue_holders):
    log = _Log()
    written = []

    def plan(candidates, attempts, at_vendor):
        return types.SimpleNamespace(write=tuple(candidates), skipped=())

    ns = _load(
        ["_queue_vendor_sales"],
        {
            "log": log,
            "asyncio": types.SimpleNamespace(to_thread=_thread),
            "_fetch_town": lambda name: types.SimpleNamespace(vendor=name in vendor_at),
            "_insert_sell": lambda c: written.append(c.item_guid) or 1,
            "item_plan": types.SimpleNamespace(
                plan=plan, reasons=lambda skipped: "nothing"
            ),
            "bag_pressure": types.SimpleNamespace(
                vendor_holders_to_queue=lambda *a, **k: set(queue_holders),
                counter_holders=lambda holders, *a: holders,
            ),
        },
    )
    candidates = (
        _Candidate(holder="Zug", item_guid=1),
        _Candidate(holder="Oz", item_guid=2),
        _Candidate(holder="Oz", item_guid=3),
    )
    inserted = asyncio.run(
        ns["_queue_vendor_sales"](candidates, "Zug", True, "trip", {})
    )
    return inserted, written, log.lines


class TheRowsAreWrittenOnlyForHoldersTheGateLetsThrough(unittest.TestCase):
    def test_every_holder_let_through_is_written(self):
        inserted, written, _ = _queue({"Zug", "Oz"}, {"Zug", "Oz"})
        self.assertEqual(3, inserted)
        self.assertEqual([2, 3, 1], written)

    def test_a_holder_held_back_is_skipped_at_a_vendor_or_away(self):
        """The two branches this used to have logged the same line and both
        skipped the holder; one gate now does both."""
        for vendor_at in ({"Zug", "Oz"}, {"Zug"}):
            with self.subTest(vendor_at=sorted(vendor_at)):
                inserted, written, lines = _queue(vendor_at, {"Zug"})
                self.assertEqual((1, [1]), (inserted, written))
                self.assertTrue(
                    any(
                        "2 carried candidate(s) for Oz but no vendor" in ln
                        for ln in lines
                    ),
                    lines,
                )

    def test_a_holder_let_through_away_from_a_vendor_is_still_written(self):
        """A follower walking behind the leader's aim is queued (#297)."""
        inserted, written, _ = _queue({"Zug"}, {"Zug", "Oz"})
        self.assertEqual((3, [2, 3, 1]), (inserted, written))


if __name__ == "__main__":
    unittest.main()
