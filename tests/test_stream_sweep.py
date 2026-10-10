"""Quiet streams expire on a timer, not on somebody's read.

A viewer who closes the tab sends nothing again, so their silence cannot end
the stream by itself. GET /api/watch used to run the expiry on every read,
which worked while the classic page polled it. Nothing polls it now, so the
map server runs the same expiry on a daemon thread of its own.
"""

import logging
import pathlib
import sys
import threading
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402
import stream  # noqa: E402


class FakeStore:
    """overseer_stream behind `_connect`: hands back `rows` to the SELECT and
    records every statement, so a test sees exactly what reached the realm."""

    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params)))

    def fetchall(self):
        return list(self.rows)

    def writes(self):
        return [s for s in self.statements if not s[0].lstrip().startswith("SELECT")]


NOW = 10_000.0


def row(name, quiet_for, state="live", mode="pov"):
    return {
        "character": name,
        "mode": mode,
        "state": state,
        "last_seen_seconds": NOW - quiet_for,
        "requested_seconds": NOW - quiet_for,
    }


class TheSweep(unittest.TestCase):
    def sweep(self, rows):
        store = FakeStore(rows)
        with mock.patch.object(map_server, "_connect", store.connect):
            expired = map_server.sweep_quiet_streams(clock=lambda: NOW)
        return expired, store

    def test_a_watch_nobody_beat_for_is_asked_to_stop(self):
        stale = stream.STALE_AFTER_SECONDS + 1
        expired, store = self.sweep([row("Grug", stale), row("Zug", 5)])
        self.assertEqual(expired, ["Grug"])
        (write,) = store.writes()
        self.assertIn("SET state = 'stopping'", write[0])
        self.assertIn("nobody was watching", write[0])
        self.assertEqual(write[1], ("Grug",))

    def test_nothing_quiet_means_nothing_is_written(self):
        expired, store = self.sweep([row("Grug", 5), row("Og", 999, state="ended")])
        self.assertEqual(expired, [])
        self.assertEqual(store.writes(), [])

    def test_a_shot_keeps_its_own_longer_leash(self):
        quiet = stream.STALE_AFTER_SECONDS + 30
        expired, store = self.sweep(
            [row("Ugga", quiet, state="requested", mode="shot")]
        )
        self.assertEqual(expired, [])
        self.assertEqual(store.writes(), [])

    def test_what_it_expired_is_logged(self):
        with self.assertLogs("wow-map", level="INFO") as logs:
            self.sweep([row("Grug", stream.STALE_AFTER_SECONDS + 1)])
        self.assertTrue(any("Grug" in line for line in logs.output))


class TheTimer(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)

    def test_it_is_a_daemon_that_keeps_sweeping(self):
        calls = []
        thrice = threading.Event()

        def sweep():
            calls.append(1)
            if len(calls) >= 3:
                thrice.set()

        thread = map_server.start_stream_sweeper(
            every=0.01, sweep=sweep, stop=self.stop
        )
        self.assertTrue(thread.daemon)
        self.assertTrue(thrice.wait(5), "the sweep did not repeat")
        self.stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_a_failed_sweep_is_logged_and_the_next_one_still_runs(self):
        calls = []
        again = threading.Event()

        def sweep():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("world unreachable")
            again.set()

        with self.assertLogs("wow-map", level="ERROR") as logs:
            map_server.start_stream_sweeper(every=0.01, sweep=sweep, stop=self.stop)
            self.assertTrue(again.wait(5), "one failure stopped the sweeper")
        self.assertTrue(any("world unreachable" in line for line in logs.output))

    def test_the_cadence_is_well_inside_the_stale_window(self):
        """A quiet watch should cost at most one sweep beyond its minute."""
        self.assertGreater(map_server.STREAM_SWEEP_SECONDS, 0)
        self.assertLessEqual(
            map_server.STREAM_SWEEP_SECONDS, stream.STALE_AFTER_SECONDS / 2
        )


class FakeServer:
    def __init__(self, order):
        self.order = order

    def serve_forever(self):
        self.order.append("serve")


class TheServerStartsIt(unittest.TestCase):
    def start(self, ensure):
        order = []
        sweeper = mock.Mock(side_effect=lambda *a, **k: order.append("sweeper"))
        with (
            mock.patch.object(map_server, "_ensure_stream_store", ensure),
            mock.patch.object(map_server, "start_stream_sweeper", sweeper),
            mock.patch.object(
                map_server, "ThreadingHTTPServer", lambda *a: FakeServer(order)
            ),
            mock.patch.object(logging, "basicConfig"),
        ):
            map_server.main()
        return order, sweeper

    def test_main_starts_the_sweeper_before_serving(self):
        order, sweeper = self.start(mock.Mock())
        sweeper.assert_called_once_with()
        self.assertEqual(order, ["sweeper", "serve"])

    def test_a_broken_store_does_not_stop_the_sweeper_starting(self):
        """The store degrades loudly and the map keeps serving; the sweeper
        starts anyway and logs its own failures until the store comes back."""
        with self.assertLogs("wow-map", level="ERROR"):
            order, sweeper = self.start(mock.Mock(side_effect=OSError("down")))
        sweeper.assert_called_once_with()
        self.assertEqual(order, ["sweeper", "serve"])


if __name__ == "__main__":
    unittest.main()
