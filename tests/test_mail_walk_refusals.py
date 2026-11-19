"""A mailbox walk the module refused is not written again at once (#2895).

Eight hours on the dev realm read 17 "character is held by another verb" and 9
"the road to the mailbox crosses ground far above its level" refusals of
`walk-to-mailbox` rows. The pure judgement lives in guildroute; the writers
ask it over their own cursor before inserting.
"""

import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import

import guildroute

HELD = "character is held by another verb"
ABOVE = "the road to the mailbox crosses ground far above its level"


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()


class _Cursor:
    def __init__(self, log, refusal):
        self.log, self.refusal, self.lastrowid, self._last = log, refusal, 0, ""

    def execute(self, sql, args=()):
        self._last = sql
        self.log.append((sql, tuple(args)))
        if sql.startswith("INSERT"):
            self.lastrowid = 41

    def fetchone(self):
        if "status = 'error'" in self._last:
            return self.refusal
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, log, refusal):
        self.log, self.refusal = log, refusal

    def cursor(self):
        return _Cursor(self.log, self.refusal)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run():
    return types.SimpleNamespace(
        holder="Blingz", walk_command="walk-to-mailbox max:600", taker="Grug", gain=5
    )


def _write(fn, *args, refusal=None):
    log = []
    with mock.patch.object(bridge, "_connect", lambda: _Conn(log, refusal)):
        with mock.patch.object(bridge, "_held_as_follower", lambda *a, **k: False):
            row_id = fn(*args)
    inserts = [a for sql, a in log if sql.startswith("INSERT INTO overseer_command")]
    return row_id, inserts


class TheJudgement(unittest.TestCase):
    def test_a_held_refusal_waits_twelve_minutes(self):
        self.assertTrue(guildroute.walk_waits(HELD, 11 * 60))
        self.assertFalse(guildroute.walk_waits(HELD, 12 * 60))

    def test_an_above_level_road_passes_the_holder_over_for_an_hour(self):
        self.assertTrue(guildroute.walk_waits(ABOVE, 59 * 60))
        self.assertFalse(guildroute.walk_waits(ABOVE, 61 * 60))

    def test_any_other_refusal_waits_for_nothing(self):
        self.assertFalse(guildroute.walk_waits("entered combat on the way", 5))
        self.assertFalse(guildroute.walk_waits(HELD, None))


class TheWritersAskFirst(unittest.TestCase):
    def test_a_held_member_is_not_written_a_second_mail_walk(self):
        with self.assertLogs(bridge.log, "INFO") as said:
            row_id, inserts = _write(
                bridge._insert_mail_walk, _run(), refusal={"detail": HELD, "age": 90}
            )
        self.assertEqual((row_id, inserts), (0, []))
        self.assertIn(HELD, "\n".join(said.output))

    def test_an_above_level_refusal_blocks_the_next_walk_for_that_member(self):
        row_id, inserts = _write(
            bridge._insert_mail_walk, _run(), refusal={"detail": ABOVE, "age": 1800}
        )
        self.assertEqual((row_id, inserts), (0, []))

    def test_a_lapsed_refusal_lets_the_walk_through(self):
        row_id, inserts = _write(
            bridge._insert_mail_walk, _run(), refusal={"detail": HELD, "age": 900}
        )
        self.assertEqual(row_id, 41)
        self.assertEqual([a[1] for a in inserts], ["walk-to-mailbox max:600"])

    def test_the_dues_walk_is_held_and_its_letter_is_not(self):
        held, inserts = _write(
            bridge._insert_dues_row,
            "Blingz",
            "walk-to-mailbox max:600",
            "Grug",
            "guildwork:dues",
            refusal={"detail": HELD, "age": 60},
        )
        self.assertEqual((held, inserts), (0, []))
        written, inserts = _write(
            bridge._insert_dues_row,
            "Blingz",
            "send Grug money:5",
            "Grug",
            "guildwork:dues",
            refusal={"detail": HELD, "age": 60},
        )
        self.assertEqual(written, 41)
        self.assertEqual(len(inserts), 1)


if __name__ == "__main__":
    unittest.main()
