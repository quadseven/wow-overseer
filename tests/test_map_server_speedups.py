"""Unit tests for map_server.py performance speedups.

Covers:
- runreport.read_many batched SQL reads (eliminating N+1 queries)
- 304 Not Modified responses skipping gzip.compress()
- HTTP/1.1 persistent connections on map_server.Handler
- appbuild.fingerprint monotonic TTL caching
"""

from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules
import sandbox_caps

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import appbuild
    import map_server
    import realmread
    import runreport

from test_app_shell import FakeHandler  # noqa: E402


def _make_run(run_id: int, start_hour: int, members: str = "Ugga,Og") -> dict:
    return {
        "id": run_id,
        "leader_name": "Ugga",
        "members": members,
        "map_id": 36,
        "run_number": run_id,
        "state": "ended",
        "outcome": "wipe",
        "ended_reason": "test",
        "started_at": datetime(2026, 10, 20, start_hour, 0, 0),
        "ended_at": datetime(2026, 10, 20, start_hour, 30, 0),
        "duration_seconds": 1800,
    }


def _make_event(run_id: int, name: str, entry: int, subject: str) -> dict:
    return {
        "run_id": run_id,
        "character_name": name,
        "kind": "loot_won",
        "subject_id": entry,
        "subject_name": subject,
        "detail": "loot x1",
        "occurrences": 1,
        "quality": 3,
    }


class RunReportReadManyTests(unittest.TestCase):
    def test_empty_run_ids_makes_zero_queries(self):
        calls: list[str] = []

        def fetch(sql, params):
            calls.append(sql)
            return []

        self.assertEqual(runreport.read_many(fetch, []), {})
        self.assertEqual(calls, [])

    def test_missing_run_ids_stops_after_runs_query(self):
        calls: list[str] = []

        def fetch(sql, params):
            calls.append(sql)
            return []

        self.assertEqual(runreport.read_many(fetch, [101, 102]), {})
        self.assertEqual(len(calls), 1)
        self.assertIn("FROM overseer_dungeon_run WHERE id IN", calls[0])

    def test_batches_many_runs_into_three_queries_with_per_run_death_windows(self):
        runs = {10: _make_run(10, 12), 20: _make_run(20, 14), 30: _make_run(30, 16)}
        events = [
            _make_event(10, "Ugga", 5191, "Cruel Barb"),
            _make_event(20, "Og", 5193, "Cape of the Brotherhood"),
        ]
        deaths = [
            {
                "character_name": "Ugga",
                "killer_name": "Mr. Smite",
                "created_at": datetime(2026, 10, 20, 12, 15, 0),
            },
            # Between run 10 and run 20: must not match either run.
            {
                "character_name": "Ugga",
                "killer_name": "Stray Mob",
                "created_at": datetime(2026, 10, 20, 13, 15, 0),
            },
            {
                "character_name": "Og",
                "killer_name": "Edwin VanCleef",
                "created_at": datetime(2026, 10, 20, 14, 10, 0),
            },
        ]
        calls: list[tuple[str, tuple]] = []

        def fetch(sql, params):
            calls.append((sql, params))
            if "FROM overseer_dungeon_run WHERE id IN" in sql:
                return [runs[i] for i in params if i in runs]
            if "FROM overseer_dungeon_run_summary s" in sql:
                return [e for e in events if e["run_id"] in params]
            if "FROM overseer_death" in sql:
                return list(deaths)
            raise AssertionError(sql)

        result = runreport.read_many(fetch, [10, 20, 30, 999, 10])
        self.assertEqual(len(calls), 3)
        self.assertEqual(list(result.keys()), [10, 20, 30])
        self.assertEqual(result[10]["loot_count"], 1)
        self.assertEqual(result[10]["death_count"], 1)
        self.assertEqual(result[10]["deaths"][0]["items"][0]["item"], "Mr. Smite")
        self.assertEqual(result[20]["loot_count"], 1)
        self.assertEqual(result[20]["death_count"], 1)
        self.assertEqual(result[20]["deaths"][0]["items"][0]["item"], "Edwin VanCleef")
        self.assertEqual(result[30]["loot_count"], 0)
        self.assertEqual(result[30]["death_count"], 0)

    def test_skips_deaths_query_when_no_run_has_started_at(self):
        run = dict(_make_run(11, 12), started_at=None, ended_at=None)
        calls: list[str] = []

        def fetch(sql, params):
            calls.append(sql)
            if "FROM overseer_dungeon_run WHERE id IN" in sql:
                return [run]
            if "FROM overseer_dungeon_run_summary s" in sql:
                return []
            raise AssertionError("unexpected query: " + sql)

        result = runreport.read_many(fetch, [11])
        self.assertEqual(len(calls), 2)
        self.assertIn(11, result)
        self.assertEqual(result[11]["death_count"], 0)

    def test_map_server_run_reports_handles_gap(self):
        class StubReader:
            def must(self, sql, params=()):
                raise realmread.Gap(1146, sql)

        rows = [{"run_id": 10}, {"run_id": 20}]
        self.assertEqual(map_server._run_reports(StubReader(), rows, 5), {})


class NotModifiedSkipsGzipTests(unittest.TestCase):
    def test_304_does_not_call_gzip_compress(self):
        body = json.dumps({"items": ["x" * 100 for _ in range(80)]}).encode()
        self.assertGreaterEqual(len(body), map_server.GZIP_MIN_BYTES)

        first = FakeHandler("/api/test", {"Accept-Encoding": "gzip"})
        with mock.patch.object(
            map_server.gzip, "compress", wraps=map_server.gzip.compress
        ) as compress:
            first._send(200, "application/json", body)
            self.assertEqual(first.status(), 200)
            self.assertEqual(first.header("Content-Encoding"), "gzip")
            self.assertEqual(compress.call_count, 1)
            etag = first.header("ETag")
            self.assertTrue(etag and etag.endswith('-gz"'))

        second = FakeHandler(
            "/api/test", {"Accept-Encoding": "gzip", "If-None-Match": etag}
        )
        with mock.patch.object(
            map_server.gzip, "compress", side_effect=AssertionError("should not gzip")
        ):
            second._send(200, "application/json", body)
        self.assertEqual(second.status(), 304)
        self.assertEqual(second.header("ETag"), etag)
        self.assertEqual(second.header("Vary"), "Accept-Encoding")
        self.assertEqual(second.body(), b"")


class HttpKeepAliveTests(unittest.TestCase):
    def test_handler_uses_http_1_1_and_keeps_timeout(self):
        self.assertEqual(map_server.Handler.protocol_version, "HTTP/1.1")
        self.assertEqual(map_server.Handler.timeout, 30)

    @unittest.skipUnless(sandbox_caps.LOCALHOST, sandbox_caps.NO_LOCALHOST)
    def test_single_connection_serves_multiple_requests(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), map_server.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/healthz")
            r1 = conn.getresponse()
            body1 = r1.read()
            self.assertEqual(r1.status, 200)
            self.assertEqual(r1.version, 11)
            self.assertEqual(body1, b"ok")
            etag = r1.getheader("ETag")
            self.assertIsNotNone(etag)
            sock1 = conn.sock
            self.assertIsNotNone(sock1)

            conn.request("GET", "/healthz", headers={"If-None-Match": etag})
            r2 = conn.getresponse()
            body2 = r2.read()
            self.assertEqual(r2.status, 304)
            self.assertEqual(r2.version, 11)
            self.assertEqual(body2, b"")
            self.assertIs(conn.sock, sock1)
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class FingerprintTtlTests(unittest.TestCase):
    def test_fingerprint_reuses_cached_value_within_ttl_without_walking_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "app").mkdir()
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            script = root / "app" / "main.js"
            script.write_text("const a = 1;\n", encoding="utf-8")
            self.addCleanup(appbuild.clear_cache, tmp)

            now = [100.0]
            with (
                mock.patch.object(appbuild, "_clock", side_effect=lambda: now[0]),
                mock.patch.object(
                    appbuild, "_app_files", wraps=appbuild._app_files
                ) as walk,
            ):
                first = appbuild.fingerprint(tmp)
                self.assertEqual(walk.call_count, 1)

                # Within TTL: disk is not walked, even if a file changes.
                script.write_text("const a = 2;\n", encoding="utf-8")
                os.utime(script, ns=(1, 1))
                now[0] += appbuild.FINGERPRINT_TTL_SECONDS - 0.5
                self.assertEqual(appbuild.fingerprint(tmp), first)
                self.assertEqual(walk.call_count, 1)

                # Past TTL: disk is walked and the new build is returned.
                now[0] += 1.0
                second = appbuild.fingerprint(tmp)
                self.assertEqual(walk.call_count, 2)
                self.assertNotEqual(second, first)

                # ttl=0 bypasses the TTL immediately.
                script.write_text("const a = 3;\n", encoding="utf-8")
                os.utime(script, ns=(2, 2))
                third = appbuild.fingerprint(tmp, ttl=0)
                self.assertEqual(walk.call_count, 3)
                self.assertNotEqual(third, second)


if __name__ == "__main__":
    unittest.main()
