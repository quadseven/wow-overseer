"""Stale ledger rows are timed out by the overseer.

The stream agent reads the ledger only while it drives that stream, so a
request it never saw would stay pending forever. A pending row whose window
end is over 15 minutes old becomes no_view; a cutting row not touched for over
10 minutes becomes failed. Each update names the state it replaces, so a row the
agent finished in the meantime is left alone.
"""

import pathlib
import sys
import unittest
from datetime import datetime, timedelta

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import clipledger

NOW = datetime(2026, 11, 9, 12, 0, 0)


def row(id, state, window_end=NOW, updated_at=NOW):
    return {
        "id": id,
        "state": state,
        "window_end": window_end,
        "updated_at": updated_at,
    }


class WhichRowsAreStale(unittest.TestCase):
    def plan(self, *rows):
        return clipledger.stale_changes(rows, now=NOW)

    def test_pending_past_fifteen_minutes_becomes_no_view(self):
        old = NOW - timedelta(minutes=15, seconds=1)
        self.assertEqual(
            [(c["id"], c["from"], c["to"]) for c in self.plan(row(1, "pending", old))],
            [(1, "pending", "no_view")],
        )

    def test_pending_at_exactly_fifteen_minutes_waits(self):
        self.assertEqual(self.plan(row(1, "pending", NOW - timedelta(minutes=15))), [])

    def test_a_fresh_pending_row_waits(self):
        self.assertEqual(self.plan(row(1, "pending", NOW - timedelta(minutes=3))), [])

    def test_cutting_not_updated_for_over_ten_minutes_becomes_failed_with_a_detail(
        self,
    ):
        stale = NOW - timedelta(minutes=10, seconds=1)
        (change,) = self.plan(row(2, "cutting", updated_at=stale))
        self.assertEqual((change["from"], change["to"]), ("cutting", "failed"))
        self.assertTrue(0 < len(change["detail"]) <= 80)

    def test_cutting_is_judged_on_updated_at_not_on_the_window(self):
        ancient_window = NOW - timedelta(days=2)
        self.assertEqual(
            self.plan(row(2, "cutting", window_end=ancient_window, updated_at=NOW)), []
        )

    def test_every_other_state_is_left_alone(self):
        old = NOW - timedelta(days=3)
        rows = [
            row(i, s, old, old)
            for i, s in enumerate(
                ["ready", "no_view", "failed", "expired", "deleted"], 1
            )
        ]
        self.assertEqual(self.plan(*rows), [])


class FakeCursor:
    """A one-table cursor that applies UPDATE ... WHERE id = %s AND state = %s
    to its rows, so a changed state really does stop the update."""

    def __init__(self, rows, finish_before_update=()):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.finish = dict(finish_before_update)
        self.statements = []
        self.rowcount = 0
        self._out = []

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params)))
        if sql.startswith("SELECT"):
            self._out = [
                dict(r)
                for r in self.rows.values()
                if r["state"] in ("pending", "cutting")
            ]
            # The agent finishes these rows after they were read.
            for rid, state in self.finish.items():
                self.rows[rid]["state"] = state
            return
        self.assert_conditional(sql)
        to = params[0]
        if "detail" in sql:
            detail, rid, was = params[1], params[2], params[3]
            applies = self.rows[rid]["state"] == was
            if applies:
                self.rows[rid].update(state=to, detail=detail)
        else:
            rid, was = params[1], params[2]
            applies = self.rows[rid]["state"] == was
            if applies:
                self.rows[rid]["state"] = to
        self.rowcount = 1 if applies else 0

    def assert_conditional(self, sql):
        assert "AND state = %s" in sql, sql

    def fetchall(self):
        return list(self._out)


class TimeOutRun(unittest.TestCase):
    def test_stale_rows_are_changed_and_counted(self):
        cur = FakeCursor(
            [
                row(1, "pending", NOW - timedelta(minutes=20)),
                row(2, "cutting", updated_at=NOW - timedelta(hours=2)),
                row(3, "pending", NOW - timedelta(minutes=1)),
            ]
        )
        counts = clipledger.time_out(cur, now=NOW)
        self.assertEqual(counts, {"no_view": 1, "failed": 1})
        self.assertEqual(cur.rows[1]["state"], "no_view")
        self.assertEqual(cur.rows[2]["state"], "failed")
        self.assertTrue(cur.rows[2]["detail"])
        self.assertEqual(cur.rows[3]["state"], "pending")

    def test_a_row_the_agent_finished_meanwhile_is_not_overwritten(self):
        cur = FakeCursor(
            [
                row(1, "pending", NOW - timedelta(minutes=20)),
                row(2, "cutting", updated_at=NOW - timedelta(hours=2)),
            ],
            finish_before_update={1: "ready", 2: "ready"},
        )
        counts = clipledger.time_out(cur, now=NOW)
        self.assertEqual(counts, {"no_view": 0, "failed": 0})
        self.assertEqual(cur.rows[1]["state"], "ready")
        self.assertEqual(cur.rows[2]["state"], "ready")

    def test_nothing_stale_writes_nothing(self):
        cur = FakeCursor([row(1, "pending", NOW)])
        clipledger.time_out(cur, now=NOW)
        self.assertTrue(all(s[0].startswith("SELECT") for s in cur.statements))


if __name__ == "__main__":
    unittest.main()
