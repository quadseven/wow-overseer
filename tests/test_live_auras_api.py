"""The live aura endpoint is a separate, bounded read through probe commands."""

import pathlib
import sys
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

try:
    import pymysql  # noqa: F401
except ModuleNotFoundError:
    # map_server's pure payload helpers need no database driver. Keep this test
    # usable in the stdlib-only local check, where the production image adds it.
    pymysql_stub = types.ModuleType("pymysql")
    pymysql_stub.connections = types.SimpleNamespace(Connection=object)
    mysql_error = type("MySQLError", (Exception,), {})
    pymysql_stub.MySQLError = mysql_error
    pymysql_stub.err = types.SimpleNamespace(MySQLError=mysql_error)
    sys.modules["pymysql"] = pymysql_stub

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import map_server  # noqa: E402


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.lastrowid = 0
        self.current = []
        self.inserted = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("INSERT"):
            self.lastrowid += 1
            self.inserted.append((sql, params))
            self.current = []
        else:
            self.current = list(self.rows)

    def fetchall(self):
        return self.current


class FakeConnection:
    def __init__(self, rows=()):
        self.fake_cursor = FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.fake_cursor

    def close(self):
        self.closed = True


class AuraResponseContract(unittest.TestCase):
    def test_core_family_buffs_have_readable_names(self):
        auras = map_server._normalize_auras(
            [
                {
                    "spell": spell,
                    "stacks": 1,
                    "remaining_ms": 60000,
                    "positive": True,
                    "caster": "Ugga",
                }
                for spell in (976, 1126, 1245, 1461, 14752)
            ]
        )
        self.assertEqual(
            [aura["name"] for aura in auras],
            [
                "Shadow Protection",
                "Mark of the Wild",
                "Power Word: Fortitude",
                "Arcane Intellect",
                "Divine Spirit",
            ],
        )

    def test_shape_and_unknown_spell_id_are_preserved(self):
        payload = map_server._build_auras_payload(
            {"Grug's Family": ["Ugga"]},
            {
                ("Grug's Family", "Ugga"): {
                    "status": "online",
                    "auras": map_server._normalize_auras(
                        [
                            {
                                "spell": 987654321,
                                "stacks": 2,
                                "remaining_ms": 45000,
                                "positive": True,
                                "caster": "Ugga",
                            }
                        ]
                    ),
                }
            },
            sampled_at=123,
        )
        self.assertEqual(set(payload), {"sampled_at", "members"})
        self.assertEqual(payload["sampled_at"], 123)
        member = payload["members"][0]
        self.assertEqual(member["family"], "Grug's Family")
        self.assertEqual(member["name"], "Ugga")
        self.assertEqual(member["status"], "online")
        self.assertEqual(
            member["auras"],
            [
                {
                    "spell": 987654321,
                    "stacks": 2,
                    "remaining_ms": 45000,
                    "positive": True,
                    "caster": "Ugga",
                }
            ],
        )

    def test_permanent_duration_sentinel_is_preserved(self):
        aura = map_server._normalize_auras(
            [
                {
                    "spell": 987654321,
                    "stacks": 1,
                    "remaining_ms": -1,
                    "positive": False,
                    "caster": "",
                }
            ]
        )[0]
        self.assertEqual(aura["remaining_ms"], -1)

    def test_offline_and_error_members_are_explicit(self):
        roster = {"Horde": ["Zug", "Oz"]}
        payload = map_server._build_auras_payload(
            roster,
            {
                ("Horde", "Zug"): {
                    "status": "offline",
                    "error": "target not online",
                    "auras": [],
                },
                ("Horde", "Oz"): {
                    "status": "error",
                    "error": "bad probe JSON",
                    "auras": [],
                },
            },
            sampled_at=456,
        )
        self.assertEqual(
            [m["status"] for m in payload["members"]], ["offline", "error"]
        )
        self.assertEqual([m["auras"] for m in payload["members"]], [[], []])
        self.assertEqual(payload["members"][0]["error"], "target not online")

    def test_probe_command_failures_become_offline_or_error_states(self):
        conn = FakeConnection(
            [
                {
                    "id": 1,
                    "status": "error",
                    "detail": "target not online",
                    "result": None,
                },
                {
                    "id": 2,
                    "status": "error",
                    "detail": "queue rejected",
                    "result": None,
                },
            ]
        )
        with patch.object(map_server, "_connect", return_value=conn):
            responses = map_server._sample_auras({"Horde": ["Zug", "Oz"]})
        self.assertEqual(responses[("Horde", "Zug")]["status"], "offline")
        self.assertEqual(responses[("Horde", "Oz")]["status"], "error")
        self.assertTrue(all("auras" in r for r in responses.values()))
        self.assertTrue(conn.closed)

    def test_worldserver_wait_is_bounded_and_reports_timeout(self):
        conn = FakeConnection()
        with patch.object(map_server, "_connect", return_value=conn):
            responses = map_server._sample_auras({"Alliance": ["Grug"]}, timeout=0)
        self.assertEqual(responses[("Alliance", "Grug")]["status"], "error")
        self.assertIn("timed out", responses[("Alliance", "Grug")]["error"])
        self.assertEqual(len(conn.fake_cursor.inserted), 1)

    def test_short_cache_reuses_aura_sample(self):
        roster = {"Alliance": ["Grug"]}
        previous = map_server._AURA_CACHE
        map_server._AURA_CACHE = None
        try:
            with patch.object(map_server, "_sample_auras", return_value={}) as sample:
                first = map_server._cached_auras_payload(roster)
                second = map_server._cached_auras_payload(roster)
            self.assertIs(first, second)
            sample.assert_called_once_with(roster)
        finally:
            map_server._AURA_CACHE = previous

    def test_concurrent_cold_cache_requests_share_one_sample(self):
        roster = {"Alliance": ["Grug"]}
        previous = map_server._AURA_CACHE
        map_server._AURA_CACHE = None
        entered_sample = threading.Event()
        release_sample = threading.Event()
        try:

            def sample(_roster):
                entered_sample.set()
                self.assertTrue(release_sample.wait(timeout=2))
                return {}

            with patch.object(
                map_server, "_sample_auras", side_effect=sample
            ) as mocked:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(map_server._cached_auras_payload, roster)
                    self.assertTrue(entered_sample.wait(timeout=2))
                    second = pool.submit(map_server._cached_auras_payload, roster)
                    time.sleep(0.02)
                    release_sample.set()
                    self.assertIs(first.result(timeout=2), second.result(timeout=2))
                mocked.assert_called_once_with(roster)
        finally:
            map_server._AURA_CACHE = previous

    def test_endpoint_rejects_character_selectors(self):
        handler = map_server.Handler.__new__(map_server.Handler)
        sent = []
        handler._send = lambda *args, **kwargs: sent.append(args)
        with patch.object(map_server, "_fetch_families") as rosters:
            handler._auras({"name": ["arbitrary character"]})
        self.assertEqual(sent[0][0], 400)
        rosters.assert_not_called()


if __name__ == "__main__":
    unittest.main()
