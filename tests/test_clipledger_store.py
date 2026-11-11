"""The map server's side of the clip ledger: the table, the scan, the timer.

The realm reads are patched out and `_connect` is a fake that records every
statement, so a test sees exactly what would reach overseer_clip. No database.
"""

import logging
import pathlib
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
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

    rowcount = 1

    def __init__(self, ready=(), keys=(), fail_first_with=None, inflight=()):
        self.inflight = list(inflight)
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
        if "state IN ('pending', 'cutting')" in self._last:
            return list(self.inflight)
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


# The columns _fetch_achievements selects from overseer_event. There is no id.
HISTORY_COLUMNS = (
    "character_name",
    "kind",
    "subject_id",
    "subject_name",
    "detail",
    "level",
    "map",
    "zone",
    "first_seen",
    "last_seen",
    "occurrences",
    "item_guid",
    "via",
    "source",
)


def history_row(event):
    """An event as the history read returns it: the real columns, no id."""
    return {c: event.get(c) for c in HISTORY_COLUMNS}


class Realm:
    """The realm reads, patched: narrow candidates and the history read."""

    def __init__(
        self, loot=(), events=(), runs=(), history_events=(), cleared=(), open_runs=()
    ):
        self.candidates = {
            "loot_rows": list(loot),
            "event_rows": list(events),
            "run_rows": list(runs),
            "open_run_rows": list(open_runs),
            "now": NOW,
        }
        self.history = {
            "event_rows": [history_row(e) for e in history_events],
            "cleared_runs": list(cleared),
        }
        self.history_reads = 0
        self.candidate_reads = 0
        self.minutes = []
        self.fail_next = False

    def read_candidates(self, roster, minutes=20):
        self.candidate_reads += 1
        self.minutes.append(minutes)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("the realm read failed")
        return self.candidates

    def read_history(self, roster):
        self.history_reads += 1
        return self.history


def scan(store, realm, roster=("Alder",), path_of=lambda name: "wd" + name):
    with (
        mock.patch.object(map_server, "_connect", store.connect),
        mock.patch.object(map_server, "_read_clip_candidates", realm.read_candidates),
        mock.patch.object(map_server, "_read_clip_history", realm.read_history),
        mock.patch.object(
            map_server,
            "_clip_who",
            lambda: (list(roster), ["Lantern Wardens"], {"one": list(roster)}),
        ),
        mock.patch.object(map_server, "_clip_path", path_of),
    ):
        return map_server.scan_clips()


def key_read_minutes(store):
    reads = [s for s in store.reads() if "created_at >=" in s[0]]
    return reads[-1][1][0]


class TheScanGap(unittest.TestCase):
    """The late horizon follows the gap since the last completed scan."""

    def setUp(self):
        last = mock.patch.object(map_server, "_clip_last_scan", None)
        last.start()
        self.addCleanup(last.stop)
        self.clock = [datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)]
        clock = mock.patch.object(map_server, "_clip_now", lambda: self.clock[0])
        clock.start()
        self.addCleanup(clock.stop)

    def later(self, **delta):
        self.clock[0] += timedelta(**delta)

    def test_the_first_scan_after_a_start_reads_a_day_back_on_both_reads(self):
        store, realm = FakeStore(), Realm()
        scan(store, realm)
        self.assertEqual([1440], realm.minutes)
        self.assertEqual(1440, key_read_minutes(store))

    def test_a_scan_after_a_completed_scan_keeps_the_steady_spans(self):
        realm = Realm()
        scan(FakeStore(), realm)
        self.later(minutes=1)
        store = FakeStore()
        scan(store, realm)
        self.assertEqual([1440, 20], realm.minutes)
        self.assertEqual(30, key_read_minutes(store))

    def test_a_scan_after_a_long_gap_reads_back_to_the_last_scan_on_both_reads(self):
        realm = Realm()
        scan(FakeStore(), realm)
        self.later(minutes=90)
        store = FakeStore()
        scan(store, realm)
        self.assertEqual([1440, 90], realm.minutes)
        self.assertEqual(90, key_read_minutes(store))

    def test_a_scan_that_failed_does_not_move_the_last_scan(self):
        realm = Realm()
        scan(FakeStore(), realm)
        self.later(minutes=60)
        realm.fail_next = True
        with self.assertRaises(RuntimeError):
            scan(FakeStore(), realm)
        self.later(minutes=1)
        scan(FakeStore(), realm)
        self.assertEqual([1440, 60, 61], realm.minutes)

    def test_a_late_event_in_the_gap_is_written_once_and_a_second_scan_writes_nothing(
        self,
    ):
        late = dict(loot_row(), first_seen=NOW - timedelta(minutes=60))
        realm = Realm(loot=[late])
        first = FakeStore()
        scan(first, realm)
        (write,) = first.writes()
        self.assertEqual("loot:7", write[1][3])
        self.assertEqual("failed", write[1][7])
        self.later(minutes=1)
        second = FakeStore(keys=["loot:7"])
        scan(second, realm)
        self.assertEqual([], second.writes())


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

    def test_a_quiet_minute_costs_three_small_ledger_reads_and_no_writes(self):
        store = FakeStore()
        result = scan(store, Realm())
        self.assertEqual(3, len(store.reads()))
        self.assertTrue(any("state = 'ready'" in s[0] for s in store.reads()))
        self.assertTrue(
            any("state IN ('pending', 'cutting')" in s[0] for s in store.reads())
        )
        self.assertEqual([], store.writes())
        self.assertEqual(
            {"written": 0, "expired": 0, "timed_out": {"no_view": 0, "failed": 0}},
            result,
        )

    def test_the_scan_times_out_stale_rows_with_conditional_updates(self):
        store = FakeStore(
            inflight=[
                {
                    "id": 5,
                    "state": "pending",
                    "window_end": NOW - timedelta(minutes=20),
                    "updated_at": NOW,
                },
                {
                    "id": 6,
                    "state": "cutting",
                    "window_end": NOW,
                    "updated_at": NOW - timedelta(hours=2),
                },
            ]
        )
        result = scan(store, Realm())
        self.assertEqual({"no_view": 0, "failed": 2}, result["timed_out"])
        writes = store.writes()
        self.assertEqual(2, len(writes))
        for sql, _params in writes:
            self.assertIn("AND state = %s", sql)
        self.assertEqual(
            ("failed", clipledger.PENDING_FAILED_DETAIL, 5, "pending"), writes[0][1]
        )

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

    def test_history_rows_without_an_id_merge_with_candidates_on_the_natural_key(self):
        recent = kill(9, 5, NOW - timedelta(minutes=3))
        realm = Realm(events=[recent], history_events=[recent])
        self.assertNotIn("id", realm.history["event_rows"][0])
        result = scan(FakeStore(), realm)
        self.assertEqual(1, result["written"])

    def test_an_empty_roster_reads_nothing_and_writes_nothing(self):
        realm = Realm(events=[kill(9, 5, NOW - timedelta(minutes=3))])
        store = FakeStore()
        result = scan(store, realm, roster=())
        self.assertEqual(0, realm.candidate_reads)
        self.assertEqual(0, realm.history_reads)
        self.assertEqual({"written": 0, "expired": 0}, result)
        self.assertEqual([], store.reads())

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
        ended = {
            "id": 1,
            "leader_name": "Alder",
            "map_id": 36,
            "started_at": at - timedelta(minutes=30),
            "ended_at": at,
        }
        realm = Realm(runs=[ended], cleared=[cleared])
        store = FakeStore()
        scan(store, realm)
        self.assertEqual(1, realm.history_reads)
        (write,) = store.writes()
        self.assertIn("clear:36", write[1])


class TheViewRule(unittest.TestCase):
    def test_a_run_still_open_gives_the_scan_its_leader_view(self):
        open_run = {
            "id": 1,
            "leader_name": "Alder",
            "map_id": 33,
            "state": "active",
            "started_at": NOW - timedelta(minutes=40),
            "ended_at": None,
        }
        row = dict(loot_row(), character_name="Birch", map=33)
        store = FakeStore()
        realm = Realm(loot=[row], open_runs=[open_run])
        scan(
            store,
            realm,
            roster=("Alder", "Birch"),
            path_of=lambda name: "wdalder" if name == "Alder" else "",
        )
        self.assertEqual(0, realm.history_reads)
        (write,) = store.writes()
        self.assertIn("view: Alder (leader)", write[1][-1])

    def test_the_clip_reads_carry_the_event_map_and_the_open_run_read_exists(self):
        self.assertIn("e.map", map_server._CLIP_LOOT_SQL)
        self.assertIn(" map,", map_server._CLIP_EVENT_SQL)
        self.assertIn("ended_at IS NULL", map_server._CLIP_OPEN_RUN_SQL)
        self.assertIn("{holes}", map_server._CLIP_OPEN_RUN_SQL)


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


class TheRunCardRead(unittest.TestCase):
    def test_the_run_clips_read_carries_what_the_card_matches_on(self):
        sql = map_server._RUN_CLIPS_SQL
        for column in ("event_key", "kind", "`character`", "stream_path", "detail"):
            self.assertIn(column, sql)
        for kind in ("'clear'", "'boss_kill'", "'loot'"):
            self.assertIn(kind, sql)
        self.assertIn("'failed'", sql)
        self.assertIn("INTERVAL %s HOUR", sql)


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
