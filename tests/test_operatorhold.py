"""The operator hold (#2403): one row stands a family's automatic planning down.

Two halves. The pure module (operatorhold.py) reads the rows, answers which
family a hold covers and says the line. The bridge's passes are held at their
public seam: each pass is lifted out of bridge.py's own source, run against a
fake world with the real `_operator_held` method bound in, and the test reads
what the pass wrote.
"""

from __future__ import annotations

import ast
import asyncio
import functools
import pathlib
import types
import unittest

import campaignqueue
import jev
import operatorhold
import test_campaign_queue as queue_fixture

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102 - bridge.py's own source
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = debug = info


def _row(family, reason="manual control", live=1, expires_at=None, source="sql"):
    return {
        "family": family,
        "reason": reason,
        "live": live,
        "expires_at": expires_at,
        "source": source,
    }


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def _held_method(rows, log=None, clock=None):
    """The real `_operator_held`, bound to a stand-in bridge.

    `rows` is a list the test can change between passes; an exception in it
    is raised by the read.
    """
    log = log or _Log()
    clock = clock or _Clock()

    def fetch():
        for row in rows:
            if isinstance(row, Exception):
                raise row
        return list(rows)

    ns = _load(
        ["_operator_held"],
        {
            "asyncio": asyncio,
            "campaignqueue": campaignqueue,
            "operatorhold": operatorhold,
            "log": log,
            "time": clock,
            "_fetch_operator_holds": fetch,
        },
    )
    me = types.SimpleNamespace(_operator_hold_notice=operatorhold.Notice())
    return functools.partial(ns["_operator_held"], me), me, log, clock


# --- the pure module ---------------------------------------------------------


class TheRowsRead(unittest.TestCase):
    def test_a_live_row_holds_its_family_and_no_other(self):
        holds = operatorhold.read([_row("Grug")])
        self.assertIsNotNone(operatorhold.held(holds, "Grug"))
        self.assertIsNone(operatorhold.held(holds, "Zug"))

    def test_the_family_is_matched_without_case(self):
        holds = operatorhold.read([_row("grug")])
        self.assertIsNotNone(operatorhold.held(holds, "Grug"))

    def test_an_expired_row_holds_nothing(self):
        holds = operatorhold.read([_row("Grug", live=0)])
        self.assertIsNone(operatorhold.held(holds, "Grug"))

    def test_the_star_row_holds_every_family(self):
        holds = operatorhold.read([_row(operatorhold.EVERY_FAMILY)])
        self.assertIsNotNone(operatorhold.held(holds, "Grug"))
        self.assertIsNotNone(operatorhold.held(holds, "Zug"))
        # A family nothing could name is still covered by the star.
        self.assertIsNotNone(operatorhold.held(holds, ""))

    def test_a_family_row_wins_over_the_star_for_its_reason(self):
        holds = operatorhold.read([_row("*", "everyone"), _row("Zug", "zug only")])
        self.assertEqual("zug only", operatorhold.held(holds, "Zug").reason)
        self.assertEqual("everyone", operatorhold.held(holds, "Grug").reason)

    def test_no_rows_hold_nothing(self):
        self.assertIsNone(operatorhold.held(operatorhold.read([]), "Grug"))
        self.assertIsNone(operatorhold.held(operatorhold.read(None), "Grug"))


class TheLine(unittest.TestCase):
    def test_it_names_the_writer_the_family_and_the_reason(self):
        hold = operatorhold.read([_row("Grug", "testing by hand")])["grug"]
        line = operatorhold.line("levelroute", "Grug's family", hold)
        self.assertIn("levelroute", line)
        self.assertIn("Grug's family", line)
        self.assertIn("held by operator: testing by hand", line)
        self.assertIn("until cleared", line)

    def test_an_expiry_is_named(self):
        hold = operatorhold.read([_row("Grug", expires_at="2026-11-14 02:00:00")])[
            "grug"
        ]
        self.assertIn(
            "until 2026-11-14 02:00:00 UTC",
            operatorhold.line("queue", "Grug's family", hold),
        )

    def test_a_blank_reason_says_so(self):
        hold = operatorhold.read([_row("Grug", "")])["grug"]
        self.assertIn(
            "held by operator: no reason given",
            operatorhold.line("queue", "Grug's family", hold),
        )


class TheNoticeIsRateLimited(unittest.TestCase):
    def test_once_per_window_per_writer_and_family(self):
        hold = operatorhold.read([_row("Grug")])["grug"]
        notice = operatorhold.Notice(every=600)
        self.assertTrue(notice.due("queue", "Grug", hold, 0.0))
        self.assertFalse(notice.due("queue", "Grug", hold, 599.0))
        self.assertTrue(notice.due("council", "Grug", hold, 1.0))
        self.assertTrue(notice.due("queue", "Grug", hold, 601.0))

    def test_a_new_reason_is_said_at_once(self):
        notice = operatorhold.Notice(every=600)
        first = operatorhold.read([_row("Grug", "one")])["grug"]
        second = operatorhold.read([_row("Grug", "two")])["grug"]
        self.assertTrue(notice.due("queue", "Grug", first, 0.0))
        self.assertTrue(notice.due("queue", "Grug", second, 1.0))


class TheSql(unittest.TestCase):
    def test_the_table_is_created_idempotently(self):
        self.assertTrue(
            operatorhold.CREATE_SQL.startswith(
                "CREATE TABLE IF NOT EXISTS overseer_operator_hold ("
            )
        )

    def test_expiry_is_judged_by_the_database_clock(self):
        # The bridge's clock and the database's can disagree on the zone;
        # the row's expiry is compared where it was written.
        self.assertIn("UTC_TIMESTAMP()", operatorhold.SELECT_SQL)


# --- the bridge's reader ------------------------------------------------------


class TheBridgeReadsEveryPass(unittest.TestCase):
    def test_it_returns_the_held_keys_and_says_one_line(self):
        held, _me, log, _clock = _held_method([_row("Grug", "hands on")])
        out = asyncio.run(held({"Grug", "Zug"}, "queue"))
        self.assertEqual({"Grug"}, out)
        self.assertEqual(1, len(log.lines))
        self.assertIn("held by operator: hands on", log.lines[0])

    def test_the_line_is_not_repeated_every_pass(self):
        held, _me, log, clock = _held_method([_row("Grug")])
        asyncio.run(held({"Grug"}, "queue"))
        clock.now += 60
        asyncio.run(held({"Grug"}, "queue"))
        self.assertEqual(1, len(log.lines))

    def test_a_cleared_row_releases_on_the_next_pass(self):
        rows = [_row("Grug")]
        held, _me, _log, _clock = _held_method(rows)
        self.assertEqual({"Grug"}, asyncio.run(held({"Grug"}, "queue")))
        rows.clear()
        self.assertEqual(set(), asyncio.run(held({"Grug"}, "queue")))

    def test_a_failed_read_keeps_the_holds_last_read(self):
        rows = [_row("Grug")]
        held, _me, log, _clock = _held_method(rows)
        asyncio.run(held({"Grug"}, "queue"))
        # The database goes away: a hiccup is not the operator letting go.
        rows[:] = [RuntimeError("database away")]
        self.assertEqual({"Grug"}, asyncio.run(held({"Grug"}, "queue")))
        self.assertTrue(any("could not be read" in line for line in log.lines))


# --- the queue pass ------------------------------------------------------------


class TheQueueStepsNothingForAHeldFamily(unittest.TestCase):
    """Acceptance: a queued entry is not stepped and no job row is written."""

    def test_a_held_family_gets_no_dungeon_job(self):
        world = queue_fixture.FakeWorld(
            [queue_fixture._q(1, "ragefire", 50, "queued", 0)]
        )
        held, _me, log, _clock = _held_method([_row("Zug", "manual control")])
        queue_fixture._queue_pass(world, _operator_held=held)
        self.assertEqual([], world.jobs)
        self.assertEqual("queued", world.queue[0]["status"])
        self.assertEqual({"quest"}, {r["job"] for r in world.family("Zug")})
        self.assertTrue(
            any(
                "queue" in line and "held by operator: manual control" in line
                for line in log.lines
            )
        )

    def test_an_unheld_family_still_steps(self):
        world = queue_fixture.FakeWorld(
            [queue_fixture._q(1, "ragefire", 50, "queued", 0)]
        )
        held, _me, _log, _clock = _held_method([_row("Grug")])
        queue_fixture._queue_pass(world, _operator_held=held)
        self.assertEqual("dungeon:ragefire", world.row("Zug")["job"])

    def test_the_other_queue_passes_see_no_held_family(self):
        """The stand-in, the spire, the trade turn and the dungeon quests
        are each handed the pass's families without the held one."""
        world = queue_fixture.FakeWorld(
            [queue_fixture._q(1, "ragefire", 50, "queued", 0)]
        )
        held, _me, _log, _clock = _held_method([_row("Zug")])
        seen = {}

        async def standin(pending, fams):
            seen["standin"] = (set(pending), set(fams))
            return fams

        async def spire(pending, fams):
            seen["spire"] = (set(pending), set(fams))
            return False

        async def trade(pending, fams):
            seen["trade"] = (set(pending), set(fams))
            return pending

        async def quests(pending, fams):
            seen["quests"] = (set(pending), set(fams))
            return set()

        queue_fixture._queue_pass(
            world,
            _operator_held=held,
            _standin_pass=standin,
            _spire_pass=spire,
            _trade_turn_pass=trade,
            _dungeonquest_pass=quests,
        )
        for name, (pending, fams) in seen.items():
            self.assertNotIn("Zug", pending, name)
            self.assertNotIn("Zug", fams, name)
            self.assertIn("Grug", fams, name)
        self.assertEqual({"standin", "spire", "trade", "quests"}, set(seen))
        self.assertEqual([], world.jobs)


# --- the council --------------------------------------------------------------


class TheCouncilWritesNoGoalForAHeldFamily(unittest.TestCase):
    def _run(self, rows):
        held, _me, log, _clock = _held_method(rows)
        reached = []

        def protected():
            reached.append("council")
            raise _Stop()

        ns = _load(
            ["_council_once"],
            {
                "asyncio": asyncio,
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
                "_cohort_of": lambda name: "Grug",
                "_protected_guids": protected,
                "_persist_council_plan": lambda *a, **k: reached.append("goal"),
                "log": log,
            },
        )
        me = types.SimpleNamespace(_operator_held=held)
        try:
            asyncio.run(ns["_council_once"](me))
        except _Stop:
            pass
        return reached, log

    def test_a_held_family_holds_no_council_and_writes_no_goal(self):
        reached, log = self._run([_row("Grug", "hands on")])
        self.assertEqual([], reached)
        self.assertTrue(
            any(
                "council" in line and "held by operator: hands on" in line
                for line in log.lines
            )
        )

    def test_an_unheld_family_still_sits(self):
        reached, _log = self._run([_row("Zug")])
        self.assertEqual(["council"], reached)


class _Stop(Exception):
    pass


# --- the activity choice and the leveling route -------------------------------


def _roster():
    return [dict(r) for r in queue_fixture.roster_rows()]


class TheActivityChoiceWritesNothingForAHeldFamily(unittest.TestCase):
    def test_only_the_unheld_family_is_chosen_for(self):
        held, _me, log, _clock = _held_method([_row("Zug", "by hand")])
        chosen = []

        async def activity_for(key, fam, rows, own, rule):
            chosen.append(key)

        ns = _load(
            ["_activity_once"],
            {
                "asyncio": asyncio,
                "jev": jev,
                "jev_activity": types.SimpleNamespace(
                    policy=lambda: types.SimpleNamespace(mode=jev.ACT), KIND="activity"
                ),
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
                "campaignqueue": campaignqueue,
                "_cohort_of": lambda name: "Grug",
                "_fetch_queue_roster": _roster,
                "_fetch_queue_rows": lambda: [],
                "log": log,
            },
        )
        me = types.SimpleNamespace(
            _jev=types.SimpleNamespace(ready=lambda kind: True),
            _operator_held=held,
            _activity_for=activity_for,
        )
        asyncio.run(ns["_activity_once"](me))
        self.assertEqual(["Grug"], chosen)
        self.assertTrue(
            any(
                "activity" in line and "held by operator: by hand" in line
                for line in log.lines
            )
        )


class TheLevelingRouteWalksNoHeldFamily(unittest.TestCase):
    def test_only_the_unheld_family_is_routed(self):
        held, _me, log, _clock = _held_method([_row("Grug", "by hand")])
        routed = []

        async def route_for(key, fam, own):
            routed.append(key)

        ns = _load(
            ["_level_route_once"],
            {
                "asyncio": asyncio,
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Grug"),
                "campaignqueue": campaignqueue,
                "_cohort_of": lambda name: "Grug",
                "_fetch_queue_roster": _roster,
                "log": log,
            },
        )
        me = types.SimpleNamespace(_operator_held=held, _level_route_for=route_for)
        asyncio.run(ns["_level_route_once"](me))
        self.assertEqual(["Zug"], routed)
        self.assertTrue(
            any(
                "levelroute" in line and "held by operator: by hand" in line
                for line in log.lines
            )
        )


if __name__ == "__main__":
    unittest.main()
