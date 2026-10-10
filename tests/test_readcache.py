"""The shared reads: a cold page load's expensive GETs built once, not per caller.

A first visit asks for the nav badges' reads and the view's reads together, and
/api/v2/roster and /api/v2/stuck are one build. readcache.ReadCache keeps a
build for a few seconds and lets callers that arrive during a build wait for
it. These pin the cache (on a fake clock), the server's use of it (ETags and
`no-cache` kept, errors never kept), and the two slow reads it was measured
against: the guild-route read behind /api/wealth and the per-member rescoring
behind /api/raidgoals.
"""

import json
import pathlib
import sys
import threading
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import gearscore  # noqa: E402
import map_server  # noqa: E402
import raidgear  # noqa: E402
import readcache  # noqa: E402
from apiv2 import members  # noqa: E402
from apiv2._context import Context  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Counter:
    def __init__(self, value="built"):
        self.calls = 0
        self.value = value

    def __call__(self):
        self.calls += 1
        return "%s %d" % (self.value, self.calls)


class TheCache(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cache = readcache.ReadCache(5.0, clock=self.clock)

    def test_a_second_ask_inside_the_ttl_is_the_first_build(self):
        build = Counter()
        self.assertEqual(self.cache.get("/a", build), "built 1")
        self.clock.now += 4.9
        self.assertEqual(self.cache.get("/a", build), "built 1")
        self.assertEqual(build.calls, 1)

    def test_an_ask_after_the_ttl_builds_again(self):
        build = Counter()
        self.cache.get("/a", build)
        self.clock.now += 5.0
        self.assertEqual(self.cache.get("/a", build), "built 2")

    def test_keys_are_kept_apart(self):
        a, b = Counter("a"), Counter("b")
        self.assertEqual(self.cache.get("/x?guild=cave", a), "a 1")
        self.assertEqual(self.cache.get("/x?guild=bonkers", b), "b 1")
        self.assertEqual(self.cache.get("/x?guild=cave", b), "a 1")

    def test_a_failed_build_is_not_kept(self):
        def broken():
            raise OSError("world unreachable")

        with self.assertRaises(OSError):
            self.cache.get("/a", broken)
        build = Counter()
        self.assertEqual(self.cache.get("/a", build), "built 1")

    def test_a_zero_ttl_keeps_nothing(self):
        cache = readcache.ReadCache(0, clock=self.clock)
        build = Counter()
        cache.get("/a", build)
        cache.get("/a", build)
        self.assertEqual(build.calls, 2)

    def test_old_entries_go_and_the_count_is_capped(self):
        cache = readcache.ReadCache(5.0, max_entries=2, clock=self.clock)
        for key in ("/1", "/2", "/3"):
            cache.get(key, Counter(key))
        self.assertEqual(sorted(cache._entries), ["/2", "/3"])
        self.clock.now += 6
        cache.get("/4", Counter())
        self.assertEqual(sorted(cache._entries), ["/4"])


class OneFlight(unittest.TestCase):
    """Callers that arrive while a build runs wait for it instead of building."""

    def _race(self, build, n=4):
        cache = readcache.ReadCache(5.0)
        results, errors = [], []

        def ask():
            try:
                results.append(cache.get("/roster", build))
            except Exception as exc:  # noqa: BLE001 - the test reports it
                errors.append(exc)

        threads = [threading.Thread(target=ask) for _ in range(n)]
        for t in threads:
            t.start()
        return threads, results, errors

    def test_concurrent_callers_share_one_build(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def slow():
            calls.append(1)
            started.set()
            release.wait(5)
            return "roster"

        threads, results, errors = self._race(slow)
        self.assertTrue(started.wait(5))
        # Let every other caller reach the wait before the build answers.
        for _ in range(50):
            if len(calls) > 1:
                break
            threading.Event().wait(0.01)
        release.set()
        for t in threads:
            t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(results, ["roster"] * 4)
        self.assertEqual(len(calls), 1)

    def test_a_waiter_on_a_failed_build_builds_for_itself(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def first_fails():
            calls.append(1)
            if len(calls) == 1:
                started.set()
                release.wait(5)
                raise OSError("world unreachable")
            return "roster"

        cache = readcache.ReadCache(5.0)
        out = {}

        def leader():
            try:
                cache.get("/roster", first_fails)
            except OSError as exc:
                out["leader"] = exc

        def waiter():
            out["waiter"] = cache.get("/roster", first_fails)

        a = threading.Thread(target=leader)
        a.start()
        self.assertTrue(started.wait(5))
        b = threading.Thread(target=waiter)
        b.start()
        threading.Event().wait(0.05)
        release.set()
        a.join(5)
        b.join(5)
        self.assertIsInstance(out["leader"], OSError)
        self.assertEqual(out["waiter"], "roster")


# ---- the server's half ---------------------------------------------------------


class FakeHandler(map_server.Handler):
    """A Handler with the socket cut off; the real _send runs."""

    def __init__(self, path, headers=None):
        self.path = path
        self.command = "GET"
        self.headers = headers or {}
        self.lines = []
        self.body = b""
        self.wfile = self

    def send_response(self, code, message=None):
        self.lines.append(("status", code))

    def send_header(self, key, value):
        self.lines.append((key, value))

    def end_headers(self):
        pass

    def write(self, body):
        self.body += body

    def status(self):
        return next(v for k, v in self.lines if k == "status")

    def header(self, name):
        return next((v for k, v in self.lines if k == name), None)


def get(path, headers=None):
    h = FakeHandler(path, headers)
    h.do_GET()
    return h


class TheSharedGets(unittest.TestCase):
    def setUp(self):
        map_server.SHARED_READS.clear()
        self.addCleanup(map_server.SHARED_READS.clear)

    def test_the_expensive_reads_are_shared(self):
        for path in (
            "/api/map",
            "/api/wall",
            "/api/guildgear",
            "/api/raidgoals",
            "/api/wealth",
        ):
            self.assertIn(path, map_server.SHARED_GET_PATHS)
            self.assertIn(path, map_server.Handler.GET_ROUTES)

    def test_two_asks_build_once_and_both_carry_the_etag(self):
        with (
            mock.patch.object(
                map_server, "_fetch_guild_gear", return_value=[]
            ) as fetch,
            mock.patch.object(
                map_server.guildgear, "build", return_value={"guilds": []}
            ),
        ):
            first = get("/api/guildgear")
            second = get("/api/guildgear")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first.body, second.body)
        self.assertEqual(json.loads(second.body), {"guilds": []})
        for h in (first, second):
            self.assertEqual(h.status(), 200)
            self.assertEqual(h.header("Cache-Control"), "no-cache")
            self.assertRegex(h.header("ETag"), r'^"[0-9a-f]{24}"$')

    def test_an_unchanged_answer_is_still_a_304(self):
        with (
            mock.patch.object(map_server, "_fetch_guild_gear", return_value=[]),
            mock.patch.object(
                map_server.guildgear, "build", return_value={"guilds": []}
            ),
        ):
            tag = get("/api/guildgear").header("ETag")
            again = get("/api/guildgear", {"If-None-Match": tag})
        self.assertEqual(again.status(), 304)
        self.assertEqual(again.body, b"")

    def test_an_error_is_sent_and_never_kept(self):
        with (
            mock.patch.object(
                map_server, "_fetch_guild_gear", side_effect=[OSError("gone"), []]
            ) as fetch,
            mock.patch.object(
                map_server.guildgear, "build", return_value={"guilds": []}
            ),
            mock.patch.object(map_server.log, "exception"),
        ):
            down = get("/api/guildgear")
            up = get("/api/guildgear")
        self.assertEqual(down.status(), 503)
        self.assertEqual(down.header("Cache-Control"), "no-store")
        self.assertIsNone(down.header("ETag"))
        self.assertEqual(up.status(), 200)
        self.assertEqual(fetch.call_count, 2)

    def test_the_query_is_part_of_the_key(self):
        self.assertNotEqual(
            map_server._shared_key("/api/wall", {"a": ["1"]}),
            map_server._shared_key("/api/wall", {"a": ["2"]}),
        )
        self.assertEqual(
            map_server._shared_key("/api/wall", {"a": ["1"], "b": ["2"]}),
            map_server._shared_key("/api/wall", {"b": ["2"], "a": ["1"]}),
        )

    def test_a_read_that_is_not_shared_builds_every_time(self):
        self.assertNotIn("/api/realm", map_server.SHARED_GET_PATHS)
        self.assertNotIn("/api/item", map_server.SHARED_GET_PATHS)


class RosterAndStuckAreOneBuild(unittest.TestCase):
    PAYLOAD = {"members": [], "checked_at": 1, "basis": "b"}

    def test_stuck_reuses_the_rosters_build(self):
        ctx = Context(read=None, server=None, shared=readcache.ReadCache(5.0))
        with mock.patch.object(
            members, "_build_roster", return_value=self.PAYLOAD
        ) as build:
            self.assertEqual(members.roster({}, ctx)[0], 200)
            self.assertEqual(members.stuck({}, ctx)[1]["members"], [])
        self.assertEqual(build.call_count, 1)

    def test_without_the_shared_reads_each_builds(self):
        ctx = Context(read=None, server=None)
        with mock.patch.object(
            members, "_build_roster", return_value=self.PAYLOAD
        ) as build:
            members.roster({}, ctx)
            members.stuck({}, ctx)
        self.assertEqual(build.call_count, 2)

    def test_the_server_hands_v2_its_shared_reads(self):
        self.assertIs(map_server._v2_context(None).shared, map_server.SHARED_READS)


# ---- the two slow reads ---------------------------------------------------------


class Cursor:
    def __init__(self):
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.sql.append(sql)

    def fetchall(self):
        return []


class Conn:
    def __init__(self):
        self.cur = Cursor()

    def cursor(self):
        return self.cur

    def close(self):
        pass


class TheGuildRouteRead(unittest.TestCase):
    def test_it_walks_the_time_window_not_the_whole_table(self):
        """`ORDER BY id DESC LIMIT n` with fewer than n matches in the window
        scanned every command on the realm (about 15 s for 800k rows)."""
        conn = Conn()
        with mock.patch.object(map_server, "_connect", return_value=conn):
            map_server._fetch_guild_routes()
        sql = " ".join(conn.cur.sql[0].split())
        self.assertIn("ORDER BY created_at DESC, id DESC LIMIT", sql)
        self.assertNotIn("ORDER BY id DESC", sql)


class TheRaidReadiness(unittest.TestCase):
    def test_the_list_items_are_scored_once_for_the_roster(self):
        items = {
            entry: {
                "entry": entry,
                "name": "Item %d" % entry,
                "stat_type1": 4,
                "stat_value1": 10,
            }
            for entry in raidgear.every_list_id()[:40]
        }
        roster = [{"name": "M%d" % i, "class_id": 1, "level": 60} for i in range(6)]
        worn = [
            {"name": m["name"], "slot": 0, "entry": next(iter(items))} for m in roster
        ]
        real = gearscore.stats_from_row
        with mock.patch.object(gearscore, "stats_from_row", side_effect=real) as scored:
            shares = raidgear.readiness_by_name(roster, worn, items)
        self.assertEqual(sorted(shares), sorted(m["name"] for m in roster))
        # Once per list item, plus whatever the worn rows add per member;
        # never once per item per member.
        self.assertLess(scored.call_count, len(items) * 2)


if __name__ == "__main__":
    unittest.main()
