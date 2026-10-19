"""The guild job plan's time on the event loop is logged (#833).

guildjobs.plan once blocked the gateway heartbeat for 40+ seconds. It stays on
the loop (it mutates the hunt and owing clocks other tasks read), so the bridge
times it and logs the seconds, which is how the "about 1 s or less" target is
read. The timer must measure only the synchronous plan: an `await` inside the
call's arguments would hand the loop to other tasks inside the timed stretch.
bridge.py is read as text by the tests, as for the other bridge-only seams.
"""

import ast
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def _plan_guild_jobs():
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_plan_guild_jobs":
            return node
    raise AssertionError("bridge.py has no async def _plan_guild_jobs")


def _is_plan_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "plan"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "guildjobs"
    )


def _statements():
    """The function's top-level statements, and the index of `plan = ...`."""
    body = _plan_guild_jobs().body
    for i, stmt in enumerate(body):
        if isinstance(stmt, ast.Assign) and _is_plan_call(stmt.value):
            return body, i
    raise AssertionError("_plan_guild_jobs has no plan = guildjobs.plan(...)")


class ThePlanTimer(unittest.TestCase):
    def test_no_await_runs_inside_the_timed_plan_call(self):
        body, i = _statements()
        awaits = [n for n in ast.walk(body[i].value) if isinstance(n, ast.Await)]
        self.assertEqual(
            awaits,
            [],
            "every awaited input is read before the plan call, so the timer "
            "measures only the synchronous plan",
        )

    def test_the_timer_starts_right_before_the_plan(self):
        body, i = _statements()
        before = ast.unparse(body[i - 1])
        self.assertIn("time.perf_counter()", before)

    def test_the_plan_time_is_logged_right_after_the_plan(self):
        body, i = _statements()
        after = ast.unparse(body[i + 1])
        self.assertIn("log.info", after)
        self.assertIn("the plan took", after)
        self.assertIn("time.perf_counter() - plan_started", after)
        self.assertIn("_family_label(cohort)", after)


if __name__ == "__main__":
    unittest.main()
