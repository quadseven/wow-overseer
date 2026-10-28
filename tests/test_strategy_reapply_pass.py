"""The strategy replay pass keeps what it owes until it is paid (#1584).

The owed set lives in the bridge's memory. The pass used to save the new
worldserver start as soon as it saw it, so a bridge restart before every
member was back read that start, saw nothing new, and the members still
owed a replay never got one. A refused row was dropped the same way. This
drives the real bridge._reapply_strategies with the database stubbed.
"""

import logging
import sys
import types
import unittest
from unittest import mock

import strategybook


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()

ORDERS = {"Ana": "nc +grind", "Bo": "co -flee"}


class _World:
    """The memo store, the uptime table, the snapshot and the command table."""

    def __init__(self, start, saved_start):
        self.start = start
        self.in_world = []
        self.events = []
        self.refuse = set()
        self.memo = {strategybook.MEMO_KIND: {}, strategybook.START_MEMO_KIND: {}}
        for name, command in ORDERS.items():
            for subject, sign in strategybook.rows(name, command):
                self.memo[strategybook.MEMO_KIND][subject] = (sign, 0.0)
        self.memo[strategybook.START_MEMO_KIND][strategybook.START_SUBJECT] = (
            saved_start,
            0.0,
        )

    def insert(self, cmd):
        if cmd.target_name in self.refuse:
            # Raise whatever bridge catches at call time: another module in a
            # shared run can swap pymysql.err for a stub with no OperationalError.
            raise bridge.pymysql.err.MySQLError(1205, "lock wait timeout")
        self.events.append(("row", cmd.target_name, cmd.command, cmd.source))
        return 1

    def upsert(self, kind, subject, value, since, expires):
        self.memo.setdefault(kind, {})[subject] = (value, since)

    def saved_start(self):
        return self.memo[strategybook.START_MEMO_KIND][strategybook.START_SUBJECT][0]

    def patch(self, test):
        for name, value in {
            "_worldserver_start": lambda: self.start,
            "_memo_read": lambda kind: dict(self.memo.get(kind, {})),
            "_memo_upsert": self.upsert,
            "_bot_held_names": lambda names: [n for n in names if n in self.in_world],
            "_roster_leads": lambda: set(),
            "_insert_command": self.insert,
        }.items():
            patcher = mock.patch.object(bridge, name, value)
            patcher.start()
            test.addCleanup(patcher.stop)


def _fresh_bridge():
    """A just-started bridge: the replayer it builds from the memo store."""
    return strategybook.Reapplier(bridge._strategy_start_seen())


def _rows(world):
    return [(e[1], e[2]) for e in world.events if e[0] == "row"]


class ReapplyPass(unittest.TestCase):
    def setUp(self):
        # The worldserver rolled (start 2000) after the last saved start (1000).
        self.world = _World(start=2000, saved_start=1000)
        self.world.patch(self)

    def test_a_bridge_restart_before_a_member_is_back_still_replays_it(self):
        self.world.in_world = ["Ana"]
        bridge._reapply_strategies(_fresh_bridge())
        self.assertEqual([("Ana", "nc +grind")], _rows(self.world))
        self.assertEqual(1000, self.world.saved_start())

        # The bridge ships and restarts; Bo logs in only now.
        self.world.in_world = ["Ana", "Bo"]
        reapplier = _fresh_bridge()
        bridge._reapply_strategies(reapplier)
        self.assertIn(("Bo", "co -flee"), _rows(self.world))
        self.assertEqual(2000, self.world.saved_start())

        # Paid in full and saved: the next restart owes nobody.
        self.world.events.clear()
        bridge._reapply_strategies(_fresh_bridge())
        self.assertEqual([], _rows(self.world))

    def test_a_refused_row_is_sent_again_on_a_later_pass(self):
        self.world.in_world = ["Ana", "Bo"]
        self.world.refuse = {"Bo"}
        reapplier = _fresh_bridge()
        with self.assertLogs(bridge.log, logging.ERROR):
            bridge._reapply_strategies(reapplier)
        self.assertEqual([("Ana", "nc +grind")], _rows(self.world))
        self.assertEqual({"Bo"}, reapplier.owed())
        self.assertEqual(1000, self.world.saved_start())

        self.world.refuse = set()
        self.world.events.clear()
        self.assertEqual(1, bridge._reapply_strategies(reapplier))
        self.assertEqual([("Bo", "co -flee")], _rows(self.world))
        self.assertEqual(2000, self.world.saved_start())

        self.world.events.clear()
        self.assertEqual(0, bridge._reapply_strategies(reapplier))
        self.assertEqual([], _rows(self.world))

    def test_the_sent_line_prints_only_after_the_rows_are_written(self):
        self.world.in_world = ["Ana", "Bo"]
        events = self.world.events

        class _Tap(logging.Handler):
            def emit(self, record):
                events.append(("log", record.getMessage()))

        tap = _Tap(logging.INFO)
        bridge.log.addHandler(tap)
        self.addCleanup(bridge.log.removeHandler, tap)
        previous = bridge.log.level
        bridge.log.setLevel(logging.INFO)
        self.addCleanup(bridge.log.setLevel, previous)

        bridge._reapply_strategies(_fresh_bridge())
        sent = [
            i
            for i, e in enumerate(events)
            if e[0] == "log" and "command(s) sent to" in e[1]
        ]
        rows = [i for i, e in enumerate(events) if e[0] == "row"]
        self.assertEqual(1, len(sent))
        self.assertEqual(2, len(rows))
        self.assertLess(max(rows), sent[0])
        self.assertIn("2 command(s) sent to Ana, Bo", events[sent[0]][1])


if __name__ == "__main__":
    unittest.main()
