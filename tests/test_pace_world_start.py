"""The pace pass reads the worldserver start in its real shape (#1369).

`acore_auth.uptime.starttime` is unix seconds, while the run ledger's times
come back as datetimes. These drive `bridge._pace_reads` with the uptime row
as the database returns it and hand the result to the restart check, so a
start passed on as a bare integer fails here and not live.
"""

import datetime
import unittest

import dungeonpace
from test_guildsocial_bridge import bridge

NOW_AT = datetime.datetime(2026, 10, 26, 12, 0, 0)
NOW_UNIX = 1_793_016_000
STARTED_UNIX = NOW_UNIX - 3600
RESTARTED = NOW_AT - datetime.timedelta(hours=1)
REASON = "heartbeat cold - nobody from the roster seen on the map"


def _run(outcome, started, last_progress, ended):
    return {
        "id": 1,
        "map_id": 48,
        "outcome": outcome,
        "started_at": started,
        "last_progress_at": last_progress,
        "ended_at": ended,
        "ended_reason": REASON,
    }


class _Cursor:
    def __init__(self, runs):
        self.runs = runs
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        self.sql = sql

    def fetchall(self):
        if "acore_auth.uptime" in self.sql:
            row = {"started": STARTED_UNIX, "now_unix": NOW_UNIX, "now_at": NOW_AT}
            return [row]
        if self.sql.startswith(
            "SELECT id, map_id, outcome, started_at, last_progress_at"
        ):
            return self.runs
        return []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _Conn:
    def __init__(self, runs):
        self.runs = runs

    def cursor(self):
        return _Cursor(self.runs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _reads(runs):
    original = bridge._connect
    bridge._connect = lambda: _Conn(runs)
    try:
        return bridge._pace_reads("Grug", {"names": ["Grug"]}, [], [])
    finally:
        bridge._connect = original


class ThePaceReadsTheWorldStart(unittest.TestCase):
    def test_integer_uptime_start_reaches_the_restart_check_as_a_datetime(self):
        crossed = _run(
            "client_lost",
            RESTARTED - datetime.timedelta(minutes=20),
            RESTARTED - datetime.timedelta(minutes=2),
            RESTARTED + datetime.timedelta(minutes=2),
        )
        reads = _reads([crossed])
        record = dungeonpace.viability(
            reads["runs"], 48, world_started_at=reads["world_started_at"]
        )
        self.assertEqual(0, record.uncleared_streak)
        self.assertEqual(RESTARTED, reads["world_started_at"])

    def test_a_run_after_the_start_still_counts(self):
        after = _run(
            "stalled",
            RESTARTED + datetime.timedelta(minutes=20),
            RESTARTED + datetime.timedelta(minutes=25),
            RESTARTED + datetime.timedelta(minutes=30),
        )
        reads = _reads([after])
        record = dungeonpace.viability(
            reads["runs"], 48, world_started_at=reads["world_started_at"]
        )
        self.assertEqual(1, record.uncleared_streak)

    def test_no_uptime_row_is_no_start(self):
        self.assertIsNone(dungeonpace.world_start(None))
        self.assertIsNone(dungeonpace.world_start([{"started": None}]))


if __name__ == "__main__":
    unittest.main()
