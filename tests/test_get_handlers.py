"""The GET handler shape (Refs #733): handler(query, ctx) -> (status, payload).

A moved route returns its status and payload and sends nothing itself; the one
shared _answer gives it the request's context, sends its payload as JSON and
turns a raise into the 503 every read had copied for itself. /api/v2's
dispatch goes through the same function.
"""

import datetime
import json
import pathlib
import sys
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402
import realmread  # noqa: E402
import test_app_shell as shell  # noqa: E402

UNREACHABLE = {"error": "world unreachable"}


def answer(handler, query=None):
    """What _answer sends for `handler`, on a handler with its socket cut off."""
    h = shell.FakeHandler("/api/x")
    map_server._answer(h, handler, query or {}, "x query failed")
    return h


class TheSharedAnswer(unittest.TestCase):
    def test_a_payload_goes_out_as_json_with_its_status(self):
        h = answer(
            lambda query, ctx: (404, {"error": "no such thing", "q": query}),
            {"id": ["7"]},
        )
        self.assertEqual(h.status(), 404)
        self.assertEqual(
            json.loads(h.body()), {"error": "no such thing", "q": {"id": ["7"]}}
        )
        self.assertEqual(h.header("Content-Type"), "application/json")

    def test_a_200_carries_the_etag_every_get_does(self):
        h = answer(lambda query, ctx: (200, {"ok": True}))
        self.assertEqual(h.status(), 200)
        self.assertEqual(h.header("Cache-Control"), "no-cache")
        self.assertRegex(h.header("ETag"), r'^"[0-9a-f]{24}"$')

    def test_a_handler_that_raises_is_a_logged_503(self):
        def broken(query, ctx):
            raise OSError("connection reset")

        with self.assertLogs(map_server.log, "ERROR") as logs:
            h = answer(broken)
        self.assertEqual(h.status(), 503)
        self.assertEqual(json.loads(h.body()), UNREACHABLE)
        self.assertIn("x query failed", logs.output[0])

    def test_a_payload_that_is_not_json_is_a_503_too(self):
        with self.assertLogs(map_server.log, "ERROR"):
            h = answer(lambda query, ctx: (200, {"bad": object()}))
        self.assertEqual(h.status(), 503)

    def test_the_context_is_the_reader_families_and_presence(self):
        seen = {}

        def look(query, ctx):
            seen["ctx"] = ctx
            return 200, {}

        answer(look)
        ctx = seen["ctx"]
        self.assertIsInstance(ctx.read, realmread.Reader)
        self.assertIs(ctx.families, map_server.FAMILIES)
        self.assertTrue(callable(ctx.presence))

    def test_the_v2_dispatch_answers_through_it(self):
        with mock.patch.object(map_server, "_answer") as shared:
            shell.get("/api/v2/roll")
        shared.assert_called_once()
        self.assertEqual(shared.call_args.args[3], "v2 read failed: /api/v2/roll")


class TheMovedRoutesReturnStatusAndPayload(unittest.TestCase):
    """Each moved route is a (query, ctx) handler behind its GET_ROUTES row."""

    def test_the_map_returns_its_dots(self):
        with (
            mock.patch.object(map_server, "_fetch_rows", return_value=[]),
            mock.patch.object(
                map_server, "build_payload", return_value={"dots": []}
            ) as build,
        ):
            got = map_server.Handler._map.__wrapped__({}, None)
        self.assertEqual(got, (200, {"dots": []}))
        build.assert_called_once_with([], map_server.GEO)

    def test_the_realm_returns_its_banner(self):
        with (
            mock.patch.object(map_server, "_fetch_realm", return_value={}),
            mock.patch.object(
                map_server.realm, "build_realm", return_value={"name": "R"}
            ),
            mock.patch.object(map_server, "_bridge_started", return_value=None),
            mock.patch.object(
                map_server,
                "_realm_families",
                return_value={"families": [], "guilds": []},
            ),
        ):
            code, payload = map_server.Handler._realm.__wrapped__({}, None)
        self.assertEqual(code, 200)
        self.assertEqual(payload["name"], "R")
        for key in ("page", "app_page", "app_build", "deploy", "families", "guilds"):
            self.assertIn(key, payload)

    def test_a_failed_map_read_is_the_shared_503(self):
        map_server.SHARED_READS.clear()
        self.addCleanup(map_server.SHARED_READS.clear)
        with (
            mock.patch.object(map_server, "_fetch_rows", side_effect=OSError("down")),
            self.assertLogs(map_server.log, "ERROR") as logs,
        ):
            h = shell.get("/api/map")
        self.assertEqual(h.status(), 503)
        self.assertEqual(json.loads(h.body()), UNREACHABLE)
        self.assertIn("map query failed", logs.output[0])

    def test_a_failed_realm_read_is_the_shared_503(self):
        with (
            mock.patch.object(map_server, "_fetch_realm", side_effect=OSError("down")),
            self.assertLogs(map_server.log, "ERROR") as logs,
        ):
            h = shell.get("/api/realm")
        self.assertEqual(h.status(), 503)
        self.assertEqual(json.loads(h.body()), UNREACHABLE)
        self.assertIn("realm query failed", logs.output[0])


# Each moved read: (route, handler, the read it starts with, its failure's log line).
FAMILY_READS = (
    ("/api/raidgoals", "_raidgoals", "_fetch_raidgoals", "raid goals query failed"),
    ("/api/loot", "_loot", "_fetch_loot", "loot query failed"),
    ("/api/council", "_council", "_fetch_achievements", "council query failed"),
    ("/api/eye", "_eye", "_fetch_eye", "eye query failed"),
    ("/api/wealth", "_wealth", "_fetch_wealth", "wealth query failed"),
)


class TheFamilyReadsAreHandlers(unittest.TestCase):
    """The raid, loot, council, eye and wealth reads return (status, payload)
    and leave a failed read to _answer, which answers it with the same 503."""

    def setUp(self):
        map_server.SHARED_READS.clear()
        self.addCleanup(map_server.SHARED_READS.clear)
        families = mock.patch.object(map_server, "FAMILIES")
        families.start().families.return_value = {"a": ["Grug"]}
        self.addCleanup(families.stop)

    def test_a_failed_read_leaves_the_handler(self):
        for path, name, fetch, _what in FAMILY_READS:
            with (
                self.subTest(path),
                mock.patch.object(map_server, fetch, side_effect=OSError("down")),
            ):
                with self.assertRaises(OSError):
                    getattr(map_server.Handler, name).__wrapped__({}, None)

    def test_a_failed_read_is_the_shared_503(self):
        for path, _name, fetch, what in FAMILY_READS:
            with (
                self.subTest(path),
                mock.patch.object(map_server, fetch, side_effect=OSError("down")),
                self.assertLogs(map_server.log, "ERROR") as logs,
            ):
                h = shell.get(path)
            self.assertEqual(h.status(), 503, path)
            self.assertEqual(json.loads(h.body()), UNREACHABLE, path)
            self.assertIn(what, logs.output[0], path)

    def test_the_eye_returns_its_rollup(self):
        with (
            mock.patch.object(map_server, "_fetch_eye", return_value={"x": 1}),
            mock.patch.object(
                map_server.eye, "build_eye", return_value={"tiers": []}
            ) as build,
        ):
            got = map_server.Handler._eye.__wrapped__({}, None)
        self.assertEqual(got, (200, {"tiers": []}))
        build.assert_called_once_with(x=1)


class TheThoughtsAreAHandler(unittest.TestCase):
    def thoughts(self, query, ctx):
        return map_server.Handler._thoughts.__wrapped__(query, ctx)

    def test_a_bad_name_or_cursor_is_a_400(self):
        self.assertEqual(
            self.thoughts({"name": ["x1"]}, None),
            (400, {"error": "not a character name"}),
        )
        self.assertEqual(
            self.thoughts({"name": ["Grug"], "before": ["z"]}, None),
            (400, {"error": "bad cursor"}),
        )

    def test_an_unknown_character_is_a_404(self):
        with mock.patch.object(map_server, "_fetch_thoughts", return_value=None):
            got = self.thoughts({"name": ["Grug"]}, None)
        self.assertEqual(got, (404, {"error": "no such character"}))

    def test_a_page_is_the_timeline(self):
        with (
            mock.patch.object(map_server, "_fetch_thoughts", return_value=([], "now")),
            mock.patch.object(
                map_server.chat, "build_timeline", return_value={"t": []}
            ),
        ):
            got = self.thoughts({"name": ["Grug"], "before": ["5"]}, None)
        self.assertEqual(got, (200, {"t": []}))

    def test_the_400_bytes_are_unchanged(self):
        h = shell.get("/api/thoughts?name=x1")
        self.assertEqual(h.status(), 400)
        self.assertEqual(h.body(), b'{"error": "not a character name"}')


class TheGuildReadsAreHandlers(unittest.TestCase):
    """The guild gear, runs, seats and chat reads return (status, payload);
    the runs and seats read through the request's reader, and the payloads
    that carry database values still encode them with default=str."""

    def setUp(self):
        map_server.SHARED_READS.clear()
        self.addCleanup(map_server.SHARED_READS.clear)

    def test_a_failed_gear_read_leaves_the_handler_and_is_the_shared_503(self):
        with mock.patch.object(
            map_server, "_fetch_guild_gear", side_effect=OSError("down")
        ):
            with self.assertRaises(OSError):
                map_server.Handler._guild_gear.__wrapped__({}, None)
            with self.assertLogs(map_server.log, "ERROR") as logs:
                h = shell.get("/api/guildgear")
        self.assertEqual(h.status(), 503)
        self.assertIn("guild gear query failed", logs.output[0])

    def test_the_runs_read_through_the_request_reader(self):
        ctx = types.SimpleNamespace(read=realmread.Memory({}))
        with (
            mock.patch.object(
                map_server.guildrun, "recent", return_value=["r"]
            ) as recent,
            mock.patch.object(map_server.guildrun, "page", return_value={"recent": []}),
            mock.patch.object(map_server.guildrun, "with_stories") as stories,
        ):
            got = map_server.Handler._guild_runs.__wrapped__({}, ctx)
        self.assertEqual(got, (200, {"recent": []}))
        self.assertIs(recent.call_args.args[0], ctx.read)
        self.assertIs(stories.call_args.args[0], ctx.read)

    def test_the_seats_read_through_the_request_reader(self):
        rows = [{"subject": "g"}]
        ctx = types.SimpleNamespace(
            read=realmread.Memory({map_server.seatmeter.BENCH_READ_SQL: rows})
        )
        with mock.patch.object(
            map_server.seatmeter, "page", return_value={"p": 1}
        ) as page:
            got = map_server.Handler._guild_seats.__wrapped__({}, ctx)
        self.assertEqual(got, (200, {"p": 1}))
        page.assert_called_once_with(rows)

    def test_a_database_value_still_encodes_as_text(self):
        when = datetime.datetime(2026, 1, 2, 3, 4, 5)
        with mock.patch.object(map_server.seatmeter, "page", return_value={"at": when}):
            with mock.patch.object(
                map_server.realmread,
                "Session",
                lambda _connect: realmread.Memory(
                    {map_server.seatmeter.BENCH_READ_SQL: []}
                ),
            ):
                h = shell.get("/api/guildseats")
        self.assertEqual(h.status(), 200)
        self.assertEqual(json.loads(h.body()), {"at": str(when)})

    def test_the_shared_answer_takes_the_encoder_default(self):
        h = shell.FakeHandler("/api/x")
        map_server._answer(
            h,
            lambda q, c: (200, {"at": datetime.date(2026, 1, 2)}),
            {},
            "x",
            default=str,
        )
        self.assertEqual(json.loads(h.body()), {"at": "2026-01-02"})

    def test_the_chat_refuses_a_guild_outside_the_set(self):
        limits = types.SimpleNamespace(guilds=("Cave",))
        with mock.patch.object(map_server.guildrun, "limits", return_value=limits):
            got = map_server.Handler._guild_chat.__wrapped__({"guild": ["Other"]}, None)
        self.assertEqual(got, (400, {"error": "not a guild"}))

    def test_the_chat_without_its_tables_is_not_ready(self):
        limits = types.SimpleNamespace(guilds=("Cave",))
        gap = realmread.Gap(realmread.MISSING_TABLE)
        with (
            mock.patch.object(map_server.guildrun, "limits", return_value=limits),
            mock.patch.object(map_server, "_fetch_guild_chat", side_effect=gap),
        ):
            got = map_server.Handler._guild_chat.__wrapped__({}, None)
        self.assertEqual(
            got,
            (200, {"guild": "Cave", "guilds": ["Cave"], "ready": False, "asks": []}),
        )


if __name__ == "__main__":
    unittest.main()
