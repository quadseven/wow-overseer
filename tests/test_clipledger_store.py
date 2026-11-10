"""The map server's side of the clip ledger: the table, the scan, the timer.

The realm reads are patched out and `_connect` is a fake that records every
statement, so a test sees exactly what would reach overseer_clip. No database.
"""

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
    def __init__(self, ledger=()):
        self.ledger = list(ledger)
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
        return list(self.ledger)

    def writes(self):
        return [s for s in self.statements if not s[0].lstrip().startswith("SELECT")]


def inputs(**kw):
    base = dict(
        loot_rows=[
            {
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
        ],
        event_rows=[],
        cleared_runs=[],
        family_guilds=["Lantern Wardens"],
        roster=["Alder"],
        now=NOW,
    )
    base.update(kw)
    return base


class TheTable(unittest.TestCase):
    def test_the_table_is_created_idempotently_with_a_unique_event_key(self):
        store = FakeStore()
        with mock.patch.object(map_server, "_connect", store.connect):
            map_server._ensure_clip_store()
        (create,) = store.writes()
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


class TheScan(unittest.TestCase):
    def scan(self, ledger=(), **kw):
        store = FakeStore(ledger)
        with (
            mock.patch.object(map_server, "_connect", store.connect),
            mock.patch.object(map_server, "_read_clip_inputs", lambda: inputs(**kw)),
            mock.patch.object(map_server, "_clip_path", lambda name: "wd" + name),
        ):
            result = map_server.scan_clips()
        return result, store

    def test_a_trigger_is_inserted_with_insert_ignore_so_the_key_stays_unique(self):
        result, store = self.scan()
        (write,) = store.writes()
        self.assertTrue(
            write[0].lstrip().startswith("INSERT IGNORE INTO overseer_clip")
        )
        self.assertIn("loot:7", write[1])
        self.assertIn("pending", write[1])
        self.assertEqual(1, result["written"])

    def test_a_restart_with_the_row_already_stored_writes_nothing(self):
        ledger = [
            {"id": 1, "event_key": "loot:7", "state": "pending", "created_at": NOW}
        ]
        result, store = self.scan(ledger)
        self.assertEqual([], store.writes())
        self.assertEqual(0, result["written"])

    def test_retention_updates_state_and_never_deletes(self):
        old = NOW - timedelta(days=45)
        ledger = [{"id": 3, "event_key": "loot:1", "state": "ready", "created_at": old}]
        result, store = self.scan(ledger, loot_rows=[])
        (write,) = store.writes()
        self.assertIn("UPDATE overseer_clip SET state = 'expired'", write[0])
        self.assertEqual((3,), write[1])
        self.assertEqual(1, result["expired"])
        self.assertFalse(any("DELETE" in s[0].upper() for s in store.statements))


class TheTimer(unittest.TestCase):
    def test_the_scanner_thread_runs_the_scan_on_its_timer(self):
        ran = threading.Event()
        stop = threading.Event()
        thread = map_server.start_clip_scanner(every=0.01, scan=ran.set, stop=stop)
        self.assertTrue(ran.wait(2))
        stop.set()
        thread.join(2)


if __name__ == "__main__":
    unittest.main()
