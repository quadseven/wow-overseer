"""One bad cycle is a logged cycle, not a dead pass (#1850).

Every pass is a forever-loop started once. An exception that escapes its
loop ends that pass until the next restart: `_pass_done` logs it and nothing
starts it again, by policy (the comment above `setup_hook`). So each loop
keeps its per-cycle work inside a try, and these drive the two that did not:

- `_loot_council_loop` read each open row outside its try, so one row
  `lootcouncil.council_from_row` could not read ended the loot council.
- `_narrate_events` diffed, filtered and split the events outside its try,
  so one bad snapshot ended the world's narration.

And the headless start path: `run_headless` awaited a plain gather over the
passes with no done-callback, so the first pass to die ended the gather and
with it the whole headless bridge, every other pass included.

bridge.py imports discord, which the suite does not install; it is imported
under a stub the way test_bridge_loops_stay_alive does it.
"""

import asyncio
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()


class _Stop(BaseException):
    """Ends a `while True` loop from its sleep; no `except Exception` takes it."""


def _sleeps_then_stops(cycles):
    """A loop sleep that returns `cycles` times, then ends the loop."""
    calls = []

    async def sleep(seconds):
        calls.append(seconds)
        if len(calls) > cycles:
            raise _Stop

    return sleep


async def _ready():
    return None


class TheLootCouncilSurvivesABadRow(unittest.TestCase):
    def _client(self, answered):
        client = object.__new__(bridge.Bridge)
        client.wait_until_ready = _ready
        client._jev_tasks = {}

        async def answer(council_row, asking):
            answered.append(council_row.key)
            asking.discard(council_row.key)

        client._answer_loot_council = answer
        return client

    def _run(self, client, rows, council_from_row, cycles=2):
        sleep = _sleeps_then_stops(cycles)

        async def run():
            try:
                await client._loot_council_loop()
            except _Stop:
                pass
            # Let the answer tasks the last cycle made finish.
            for _ in range(3):
                await asyncio.sleep(0)

        real_sleep = asyncio.sleep

        async def patched_sleep(seconds):
            if seconds == 0:
                return await real_sleep(0)
            return await sleep(seconds)

        with (
            mock.patch.object(bridge, "_fetch_open_councils", return_value=rows),
            mock.patch.object(
                bridge.lootcouncil, "council_from_row", side_effect=council_from_row
            ),
            mock.patch.object(bridge.asyncio, "sleep", patched_sleep),
            mock.patch.object(bridge.log, "exception") as logged,
        ):
            asyncio.run(run())
        return logged

    def test_a_row_that_raises_is_logged_and_the_next_cycle_runs(self):
        reads = []

        def council_from_row(row):
            reads.append(row["council_key"])
            if len(reads) == 1:
                raise ValueError("candidates is not JSON")
            return None

        logged = self._run(self._client([]), [{"council_key": "a"}], council_from_row)
        self.assertEqual(["a", "a"], reads, "the second cycle never ran")
        logged.assert_called_once()
        self.assertIn("loot council", logged.call_args.args[0])

    def test_one_bad_row_does_not_cost_the_rows_after_it(self):
        def council_from_row(row):
            if row["council_key"] == "bad":
                raise ValueError("candidates is not JSON")
            return bridge.lootcouncil.Council(
                key=row["council_key"],
                kind="",
                family="",
                source="",
                item_entry=1,
                item_name="",
                candidates=(),
                heuristic="",
                heuristic_why="",
            )

        answered = []
        logged = self._run(
            self._client(answered),
            [{"council_key": "bad"}, {"council_key": "good"}],
            council_from_row,
            cycles=1,
        )
        self.assertEqual(["good"], answered)
        logged.assert_called_once()


class TheNarratorSurvivesABadCycle(unittest.TestCase):
    def test_a_cycle_whose_diff_raises_is_logged_and_the_next_runs(self):
        detected = [bridge.events.Event("death", "Ugga", {})]
        written = []
        client = object.__new__(bridge.Bridge)
        client.wait_until_ready = _ready
        closed = iter([False, False, True])
        client.is_closed = lambda: next(closed)

        async def no_sleep(_seconds):
            return None

        with (
            mock.patch.multiple(
                bridge,
                _fetch_event_snapshot=mock.Mock(return_value=[]),
                _fetch_notable_names=mock.Mock(return_value=set()),
                _insert_thought=lambda name, kind, text: written.append(name),
            ),
            mock.patch.object(
                bridge.events,
                "detect_events",
                side_effect=[RuntimeError("a snapshot row had no map"), detected],
            ) as detect,
            mock.patch.object(
                bridge.events, "filter_for_story", side_effect=lambda found, _n: found
            ),
            mock.patch.object(bridge.llmmode, "enabled", return_value=False),
            mock.patch.object(bridge.asyncio, "sleep", no_sleep),
            mock.patch.object(bridge.log, "exception") as logged,
        ):
            asyncio.run(client._narrate_events())
        self.assertEqual(2, detect.call_count, "the second cycle never ran")
        self.assertEqual(["Ugga"], written)
        logged.assert_called_once()
        self.assertIn("event cycle", logged.call_args.args[0])

    def test_a_broken_split_is_a_logged_cycle_too(self):
        """split_for_voicing and the strict zip sit inside the same try."""
        client = object.__new__(bridge.Bridge)
        client.wait_until_ready = _ready
        closed = iter([False, True])
        client.is_closed = lambda: next(closed)

        async def no_sleep(_seconds):
            return None

        with (
            mock.patch.multiple(
                bridge,
                _fetch_event_snapshot=mock.Mock(return_value=[]),
                _fetch_notable_names=mock.Mock(return_value=set()),
            ),
            mock.patch.object(bridge.events, "detect_events", return_value=[]),
            mock.patch.object(
                bridge.events, "split_for_voicing", side_effect=TypeError("cap")
            ),
            mock.patch.object(bridge.asyncio, "sleep", no_sleep),
            mock.patch.object(bridge.log, "exception") as logged,
        ):
            asyncio.run(client._narrate_events())
        logged.assert_called_once()


class AHeadlessPassThatDiesLeavesTheOthersRunning(unittest.TestCase):
    def test_the_death_is_logged_and_the_sibling_pass_keeps_going(self):
        ran = []

        async def dies():
            raise RuntimeError("the first read raised")

        async def keeps_going():
            for cycle in range(5):
                await asyncio.sleep(0)
                ran.append(cycle)

        client = object.__new__(bridge.HeadlessBridge)

        async def no_stores():
            return None

        client._ensure_stores = no_stores
        client._pass_coroutines = lambda headless: [dies, keeps_going]
        with self.assertLogs(bridge.log, "ERROR") as logged:
            asyncio.run(client.run_headless())
        self.assertEqual([0, 1, 2, 3, 4], ran)
        died = [line for line in logged.output if "died" in line]
        self.assertEqual(1, len(died), logged.output)
        self.assertIn("dies", died[0])


if __name__ == "__main__":
    unittest.main()
