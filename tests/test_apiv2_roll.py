"""GET /api/v2/roll: the last roll, read from the realm's own database.

The rule under every case: a field the realm does not report comes back null
with a reason, never a guess. The channel and the shipped list are not in the
realm's database at all, so they are always null and the app says "not
measured".
"""

import json
import pathlib
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
from apiv2 import roll as v2roll  # noqa: E402
from apiv2._context import Context  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, 0)
CORE = (
    "AzerothCore rev. 7f12e89ee5f4+ 2026-09-20 08:10:47 -0700 "
    "(HEAD branch) (Unix, RelWithDebInfo, Static)"
)


def build_rows(reported_at=NOW - timedelta(hours=6)):
    rows = [
        ("module", "0.1.0", "compiled"),
        ("core", CORE, "compiled"),
        ("realm", "wow-dev", "declared"),
        ("realm_kind", "non-production", "derived"),
        ("pins", "match", "derived"),
    ]
    return [
        {"name": n, "value": v, "source": s, "reported_at": reported_at}
        for n, v, s in rows
    ]


class FakeCursor:
    """Answers each of the roll's three reads with rows set per SQL."""

    def __init__(self, answers):
        self.answers = answers
        self.rows = []
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)
        self.rows = self.answers.get(sql, [])

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self.cur = cursor
        self.closed = False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


def guarded(cur, sql, _what):
    cur.execute(sql)
    return list(cur.fetchall())


def context(answers):
    cur = FakeCursor(answers)
    conn = FakeConnection(cur)
    server = types.SimpleNamespace(_realm_guarded=guarded)
    return Context(connect=lambda: conn, server=server), conn, cur


class TheRoll(unittest.TestCase):
    def test_a_realm_that_reported_gives_its_build_and_when(self):
        out = v2roll.build_roll(
            build_rows(), [{"core_version": CORE}], [{"up": 7200}], now=NOW
        )
        self.assertEqual(out["build"], "core 7f12e89ee5f4, module 0.1.0")
        self.assertEqual(out["when"], "2026-10-09 06:00:00")
        self.assertEqual(out["when_seconds"], 6 * 3600)
        self.assertEqual(out["uptime_seconds"], 7200)
        self.assertEqual(out["core_revision"], "7f12e89ee5f4")
        self.assertEqual(out["module_version"], "0.1.0")

    def test_channel_and_shipped_are_never_invented(self):
        out = v2roll.build_roll(build_rows(), [], [{"up": 60}], now=NOW)
        self.assertIsNone(out["channel"])
        self.assertIsNone(out["shipped"])
        self.assertIn("channel", out["unmeasured"])
        self.assertIn("shipped", out["unmeasured"])
        self.assertNotIn("build", out["unmeasured"])

    def test_a_realm_that_reported_nothing_is_all_null_with_reasons(self):
        out = v2roll.build_roll([], [], [], now=NOW)
        for key in ("build", "when", "channel", "shipped", "uptime_seconds"):
            self.assertIsNone(out[key], key)
            self.assertTrue(out["unmeasured"][key], key)

    def test_the_core_alone_still_names_the_build(self):
        out = v2roll.build_roll([], [{"core_version": CORE}], [{"up": None}], now=NOW)
        self.assertEqual(out["build"], "core 7f12e89ee5f4")
        self.assertIsNone(out["when"])
        self.assertIsNone(out["uptime_seconds"])

    def test_a_tuple_uptime_row_is_read_and_an_empty_one_is_not_measured(self):
        self.assertEqual(
            v2roll.build_roll([], [], [(90,)], now=NOW)["uptime_seconds"], 90
        )
        self.assertIsNone(v2roll.build_roll([], [], [()], now=NOW)["uptime_seconds"])

    def test_the_spec_shape_is_present(self):
        out = v2roll.build_roll(build_rows(), [], [], now=NOW)
        for key in ("build", "when", "channel", "shipped"):
            self.assertIn(key, out)
        json.dumps(out)


class TheHandler(unittest.TestCase):
    def test_it_is_registered_under_v2(self):
        self.assertIs(apiv2.ROUTES["/api/v2/roll"], v2roll.roll)

    def test_it_reads_the_three_tables_and_closes_the_connection(self):
        ctx, conn, cur = context(
            {
                v2roll.BUILD_SQL: build_rows(),
                v2roll.VERSION_SQL: [{"core_version": CORE}],
                v2roll.UPTIME_SQL: [{"up": 3600}],
            }
        )
        code, payload = apiv2.handle("/api/v2/roll", {}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(payload["build"], "core 7f12e89ee5f4, module 0.1.0")
        self.assertEqual(payload["uptime_seconds"], 3600)
        self.assertEqual(
            cur.executed, [v2roll.BUILD_SQL, v2roll.VERSION_SQL, v2roll.UPTIME_SQL]
        )
        self.assertTrue(conn.closed)

    def test_every_statement_only_reads(self):
        for sql in (v2roll.BUILD_SQL, v2roll.VERSION_SQL, v2roll.UPTIME_SQL):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)

    def test_the_map_server_serves_it(self):
        import map_server

        sys.path.insert(0, str(HERE / "tests"))
        from test_app_shell import get

        conn = FakeConnection(FakeCursor({v2roll.BUILD_SQL: build_rows()}))
        with mock.patch.object(map_server, "_connect", lambda: conn):
            h = get("/api/v2/roll")
        self.assertEqual(h.status(), 200)
        body = json.loads(h.body())
        self.assertEqual(body["build"], "core 7f12e89ee5f4, module 0.1.0")
        self.assertIsNone(body["shipped"])


if __name__ == "__main__":
    unittest.main()
