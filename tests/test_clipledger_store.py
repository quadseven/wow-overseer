"""The map server's side of the clip ledger: the table, the scan, the timer.

The realm reads are patched out and `_connect` is a fake that records every
statement, so a test sees exactly what would reach overseer_clip. No database.
"""

import logging
import pathlib
import sys
import threading
import unittest
from datetime import datetime, timedelta
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import clipledger
    import map_server

NOW = datetime(2026, 11, 9, 12, 0, 0)


class FakeStore:
    """overseer_clip behind `_connect`. The two ledger reads are told apart by
    their SQL: the retention read asks for ready rows, the key read for keys."""

    def __init__(self, ready=(), keys=(), fail_first_with=None):
        self.ready = list(ready)
        self.keys = [{"event_key": k} for k in keys]
        self.statements = []
        self.many = []
        self.fail_first_with = fail_first_with
        self._last = ""

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
        self._last = sql

    def executemany(self, sql, seq):
        self.many.append((sql, [tuple(p) for p in seq]))

    def fetchall(self):
        if "state = 'ready'" in self._last:
            return list(self.ready)
        return list(self.keys)

    def reads(self):
        return [s for s in self.statements if s[0].lstrip().startswith("SELECT")]

    def writes(self):
        return [
            s
            for s in self.statements
            if not s[0].lstrip().startswith(("SELECT", "CREATE"))
        ]


def loot_row():
    return {
        "id": 7,
        "character_name": "Alder",
        "kind": "item_loot",
        "subject_id": 1,
        "subject_name": "Test Blade",
        "subject_quality": 4,
        "item_guid": 9,
        "guild": "Lantern Wardens",
        "first_seen": NOW - timedelta(minutes=8),
    }


def kill(event_id, boss, at, who="Alder"):
    return {
        "id": event_id,
        "character_name": who,
        "kind": "boss_kill",
        "subject_id": boss,
        "subject_name": "Boss %d" % boss,
        "first_seen": at,
    }


class Realm:
    """The realm reads, patched: narrow candidates and the history read."""

    def __init__(self, loot=(), events=(), runs=(), history_events=(), cleared=()):
        self.candidates = {
            "loot_rows": list(loot),
            "event_rows": list(events),
            "run_rows": list(runs),
            "now": NOW,
        }
        self.history = {
            "event_rows": list(history_events),
            "cleared_runs": list(cleared),
        }
        self.history_reads = 0

    def read_history(self, roster):
        self.history_reads += 1
        return self.history


def scan(store, realm):
    with (
        mock.patch.object(map_server, "_connect", store.connect),
        mock.patch.object(
            map_server, "_read_clip_candidates", lambda roster: realm.candidates
        ),
        mock.patch.object(map_server, "_read_clip_history", realm.read_history),
        mock.patch.object(
            map_server, "_clip_who", lambda: (["Alder"], ["Lantern Wardens"])
        ),
        mock.patch.object(map_server, "_clip_path", lambda name: "wd" + name),
    ):
        return map_server.scan_clips()


class TheTable(unittest.TestCase):
    def test_the_table_is_created_idempotently_with_a_unique_event_key(self):
        store = FakeStore()
        with mock.patch.object(map_server, "_connect", store.connect):
            map_server._ensure_clip_store()
        (create,) = [s for s in store.statements if s[0].startswith("CREATE")]
        sql = create[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS overseer_clip", sql)
        self.assertIn("UNIQUE KEY", sql)
        for column in (
            "id",
            "kind",
            "`character`",
            "stream_path",
            "event_key",
            "event_at",
            "window_start",
            "window_end",
            "state",
            "file_name",
            "detail",
            "created_at",
            "updated_at",
        ):
            self.assertIn(column, sql)
        self.assertEqual(
            ("pending", "cutting", "ready", "no_view", "failed", "expired", "deleted"),
            clipledger.STATES,
        )

    def test_the_scan_creates_the_table_itself_before_anything_else(self):
        store = FakeStore()
        scan(store, Realm(loot=[loot_row()]))
        self.assertTrue(store.statements[0][0].startswith("CREATE TABLE IF NOT EXISTS"))


class TheScan(unittest.TestCase):
    def test_a_trigger_is_inserted_with_insert_ignore_so_the_key_stays_unique(self):
        store = FakeStore()
        result = scan(store, Realm(loot=[loot_row()]))
        (write,) = store.writes()
        self.assertTrue(
            write[0].lstrip().startswith("INSERT IGNORE INTO overseer_clip")
        )
        self.assertIn("loot:7", write[1])
        self.assertIn("pending", write[1])
        self.assertEqual(1, result["written"])

    def test_a_restart_with_the_row_already_stored_writes_nothing(self):
        store = FakeStore(keys=["loot:7"])
        result = scan(store, Realm(loot=[loot_row()]))
        self.assertEqual([], store.writes())
        self.assertEqual(0, result["written"])

    def test_the_key_read_is_bounded_to_recent_rows_and_has_no_in_list(self):
        store = FakeStore()
        scan(store, Realm(loot=[loot_row()]))
        keyreads = [s for s in store.reads() if "created_at >=" in s[0]]
        (read,) = keyreads
        self.assertIn("created_at >= NOW() - INTERVAL %s MINUTE", read[0])
        self.assertNotIn(" IN ", read[0])
        self.assertEqual(1, len(read[1]))

    def test_a_quiet_minute_costs_two_small_ledger_reads_and_no_writes(self):
        store = FakeStore()
        result = scan(store, Realm())
        self.assertEqual(2, len(store.reads()))
        self.assertTrue(any("state = 'ready'" in s[0] for s in store.reads()))
        self.assertEqual([], store.writes())
        self.assertEqual({"written": 0, "expired": 0}, result)

    def test_retention_updates_state_one_id_at_a_time_and_never_deletes(self):
        old = NOW - timedelta(days=45)
        ready = [
            {"id": 3, "event_key": "loot:1", "state": "ready", "created_at": old},
            {"id": 4, "event_key": "loot:2", "state": "ready", "created_at": old},
        ]
        store = FakeStore(ready=ready)
        result = scan(store, Realm())
        (sql, params) = store.many[0]
        self.assertEqual(
            "UPDATE overseer_clip SET state = 'expired' WHERE id = %s AND state = 'ready'",
            sql,
        )
        self.assertEqual([(3,), (4,)], params)
        self.assertEqual(2, result["expired"])
        self.assertFalse(any("DELETE" in s[0].upper() for s in store.statements))


class TheCandidateRead(unittest.TestCase):
    """Candidates come from one narrow read; history is read only for a
    firstness decision, and only when a candidate exists."""

    def test_with_no_recent_candidate_there_is_no_history_read(self):
        realm = Realm(history_events=[kill(1, 5, NOW - timedelta(days=2))])
        store = FakeStore()
        scan(store, realm)
        self.assertEqual(0, realm.history_reads)

    def test_a_recent_first_kill_reads_history_and_writes_the_row(self):
        recent = kill(9, 5, NOW - timedelta(minutes=3))
        realm = Realm(events=[recent], history_events=[recent])
        store = FakeStore()
        result = scan(store, realm)
        self.assertEqual(1, realm.history_reads)
        self.assertEqual(1, result["written"])
        (write,) = store.writes()
        self.assertIn("boss_kill:5", write[1])

    def test_a_candidate_missing_from_a_truncated_history_is_still_judged(self):
        recent = kill(9, 5, NOW - timedelta(minutes=3))
        realm = Realm(events=[recent], history_events=[])
        result = scan(FakeStore(), realm)
        self.assertEqual(1, result["written"])

    def test_a_recent_kill_of_a_boss_with_an_older_kill_writes_nothing(self):
        old = kill(1, 5, NOW - timedelta(days=2))
        recent = kill(9, 5, NOW - timedelta(minutes=3))
        realm = Realm(events=[recent], history_events=[old, recent])
        store = FakeStore()
        result = scan(store, realm)
        self.assertEqual(1, realm.history_reads)
        self.assertEqual(0, result["written"])
        self.assertEqual([], store.writes())

    def test_a_level_sixty_needs_no_history_read(self):
        up = {
            "id": 4,
            "character_name": "Alder",
            "kind": "level_up",
            "level": 60,
            "first_seen": NOW - timedelta(minutes=3),
        }
        realm = Realm(events=[up])
        result = scan(FakeStore(), realm)
        self.assertEqual(0, realm.history_reads)
        self.assertEqual(1, result["written"])

    def test_a_recently_ended_run_triggers_the_history_read_for_clears(self):
        at = NOW - timedelta(minutes=3)
        cleared = {"map_id": 36, "dungeon": "Test Mines", "leader": "Alder", "at": at}
        realm = Realm(runs=[{"id": 1}], cleared=[cleared])
        store = FakeStore()
        scan(store, realm)
        self.assertEqual(1, realm.history_reads)
        (write,) = store.writes()
        self.assertIn("clear:36", write[1])


class TheSql(unittest.TestCase):
    def test_the_loot_interval_is_a_bound_parameter_not_formatted_in(self):
        self.assertIn("INTERVAL %s MINUTE", map_server._CLIP_LOOT_SQL)
        self.assertNotIn("INTERVAL 20", map_server._CLIP_LOOT_SQL)

    def test_the_candidate_event_read_is_bounded_and_narrow(self):
        sql = map_server._CLIP_EVENT_SQL
        self.assertIn("INTERVAL %s MINUTE", sql)
        self.assertIn("boss_kill", sql)
        self.assertIn("level_up", sql)
        self.assertIn("{holes}", sql)


class TheTimer(unittest.TestCase):
    def test_the_scanner_thread_runs_the_scan_on_its_timer(self):
        ran = threading.Event()
        stop = threading.Event()
        thread = map_server.start_clip_scanner(every=0.01, scan=ran.set, stop=stop)
        self.assertTrue(ran.wait(2))
        stop.set()
        thread.join(2)

    def test_a_failed_scan_is_logged_as_the_clip_scan_not_the_stream_sweep(self):
        stop = threading.Event()

        def boom():
            stop.set()
            raise RuntimeError("x")

        with self.assertLogs("wow-map", level=logging.ERROR) as logs:
            map_server._sweep_until(stop, 0, boom, "clip scan failed")
        text = " ".join(logs.output)
        self.assertIn("clip scan failed", text)
        self.assertNotIn("stream sweep failed", text)


if __name__ == "__main__":
    unittest.main()
