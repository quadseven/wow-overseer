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


SIDES = [{"family": "Grug", "names": ["Grug"], "faction": "Alliance", "heading": "h"}]
CRAFT_READ = {
    "craft_rows": [],
    "families": {"Grug": {"skill_rows": [], "spell_rows": [], "member_rows": []}},
    **{
        k: []
        for k in (
            "recipe_rows",
            "trainer_rows",
            "vendor_rows",
            "drop_rows",
            "quest_rows",
        )
    },
}


class TheRunAndTradeReadsAreHandlers(unittest.TestCase):
    """The run timeline, recap, trades and trade crafts return (status,
    payload); /api/trades picks the crafts handler when `skill` is asked."""

    def setUp(self):
        map_server.SHARED_READS.clear()
        self.addCleanup(map_server.SHARED_READS.clear)

    def test_a_failed_read_leaves_the_handler(self):
        for name, fetch in (
            ("_run_timeline", "_fetch_run_timeline"),
            ("_guild_trades", "_faction_sides"),
            ("_recap", "_faction_sides"),
        ):
            with (
                self.subTest(name),
                mock.patch.object(map_server, fetch, side_effect=OSError("down")),
            ):
                with self.assertRaises(OSError):
                    getattr(map_server.Handler, name).__wrapped__({}, None)

    def test_a_failed_read_is_the_shared_503(self):
        for path, fetch, what in (
            ("/api/runtimeline", "_fetch_run_timeline", "run timeline query failed"),
            ("/api/recap", "_faction_sides", "recap query failed"),
            ("/api/trades", "_faction_sides", "guild trades query failed"),
            (
                "/api/trades?skill=1",
                "_faction_sides",
                "guild trade crafts query failed",
            ),
        ):
            with (
                self.subTest(path),
                mock.patch.object(
                    map_server.tradespec, "parse_skill", return_value=(1, "")
                ),
                mock.patch.object(map_server, fetch, side_effect=OSError("down")),
                self.assertLogs(map_server.log, "ERROR") as logs,
            ):
                h = shell.get(path)
            self.assertEqual(h.status(), 503, path)
            self.assertIn(what, logs.output[0], path)

    def test_the_recap_returns_one_per_family(self):
        with (
            mock.patch.object(map_server, "_faction_sides", return_value=SIDES),
            mock.patch.object(
                map_server.Handler,
                "_recap_for",
                staticmethod(lambda _map, names: {"live": False, "names": names}),
            ),
        ):
            code, payload = map_server.Handler._recap.__wrapped__({"map": ["x"]}, None)
        self.assertEqual(code, 200)
        self.assertEqual(payload["names"], ["Grug"])
        self.assertEqual([f["family"] for f in payload["families"]], ["Grug"])

    def test_a_bad_skill_is_a_400_before_any_read(self):
        with (
            mock.patch.object(
                map_server.tradespec, "parse_skill", return_value=(None, "bad")
            ),
            mock.patch.object(map_server, "_faction_sides") as sides,
        ):
            got = map_server.Handler._trade_crafts.__wrapped__({"skill": ["x"]}, None)
        self.assertEqual(got, (400, {"error": "bad"}))
        sides.assert_not_called()

    def test_the_craft_list_is_still_sent_compact(self):
        with (
            mock.patch.object(
                map_server.tradespec, "parse_skill", return_value=(1, "")
            ),
            mock.patch.object(
                map_server.tradespec, "parse_family", return_value=("", "")
            ),
            mock.patch.object(map_server, "_faction_sides", return_value=SIDES),
            mock.patch.object(map_server, "_fetch_guildcraft", return_value=CRAFT_READ),
            mock.patch.object(
                map_server.tradespec, "build_craft_list", return_value={"a": 1}
            ),
        ):
            h = shell.get("/api/trades?skill=1")
        self.assertEqual(h.status(), 200)
        self.assertEqual(h.body(), b'{"a":1,"family":"Grug"}')


class TheArmoryReadsAreHandlers(unittest.TestCase):
    """The armory, armory member, upgrades and item reads return (status,
    payload); the refusals are payloads with the same bytes as before."""

    def test_a_failed_read_leaves_the_handler(self):
        for name, query, fetch in (
            ("_armory", {}, "_fetch_armory"),
            ("_armory_member", {"name": ["Grug"]}, "_fetch_armory"),
            ("_upgrades", {"name": ["Grug"]}, "_upgrades_payload"),
            ("_item", {"entry": ["5"]}, "_item_payload"),
        ):
            with (
                self.subTest(name),
                mock.patch.object(map_server, "FAMILIES") as families,
                mock.patch.object(map_server, fetch, side_effect=OSError("down")),
            ):
                families.families.return_value = {"a": ["Grug"]}
                families.may_answer.return_value = True
                with self.assertRaises(OSError):
                    getattr(map_server.Handler, name).__wrapped__(query, None)

    def test_the_upgrades_are_the_shared_payload(self):
        with mock.patch.object(
            map_server, "_upgrades_payload", return_value=(404, {"error": "e"})
        ) as built:
            got = map_server.Handler._upgrades.__wrapped__({"name": ["Grug"]}, None)
        self.assertEqual(got, (404, {"error": "e"}))
        built.assert_called_once_with("Grug")

    def test_the_item_refusals_are_payloads(self):
        item = map_server.Handler._item.__wrapped__
        self.assertEqual(
            item({"entry": ["x"]}, None), (400, {"error": "not an item entry"})
        )
        with mock.patch.object(map_server, "_item_payload", return_value=None):
            self.assertEqual(
                item({"entry": ["5"]}, None), (404, {"error": "no such item"})
            )
        with mock.patch.object(map_server, "_item_payload", return_value={"entry": 5}):
            self.assertEqual(item({"entry": ["5"]}, None), (200, {"entry": 5}))

    def test_a_stranger_is_a_404_before_any_read(self):
        with (
            mock.patch.object(map_server, "FAMILIES") as families,
            mock.patch.object(map_server, "_fetch_armory") as fetch,
        ):
            families.may_answer.return_value = False
            got = map_server.Handler._armory_member.__wrapped__(
                {"name": ["Nobody"]}, None
            )
        self.assertEqual(got, (404, {"error": "not a guild member"}))
        fetch.assert_not_called()

    def test_the_refusal_bytes_are_unchanged(self):
        for path, body in (
            ("/api/item?entry=x", b'{"error": "not an item entry"}'),
            ("/api/armory/member?name=Nobody", b'{"error": "not a guild member"}'),
        ):
            with (
                self.subTest(path),
                mock.patch.object(map_server, "FAMILIES") as families,
            ):
                families.may_answer.return_value = False
                h = shell.get(path)
            self.assertEqual(h.body(), body, path)


def fake_driver():
    """A pymysql whose error class exists whether or not the driver does."""
    error = type("MySQLError", (Exception,), {})
    return types.SimpleNamespace(err=types.SimpleNamespace(MySQLError=error))


# Each probe: (route, its cached read, its failure's log line, its 503 body).
PROBES = (
    (
        "/api/auras",
        "_cached_auras_payload",
        "aura probe failed",
        b'{"error": "aura sample unavailable"}',
    ),
    (
        "/api/meter",
        "_cached_meter_payload",
        "meter probe failed",
        b'{"error": "meter unavailable"}',
    ),
)


class TheProbesAnswerThroughTheSharedAnswer(unittest.TestCase):
    """/api/auras and /api/meter keep their own 503 body and their narrow catch
    through _probe_failed; anything that is no outage still goes on up."""

    def setUp(self):
        families = mock.patch.object(map_server, "FAMILIES")
        families.start().families.return_value = {"a": ["Grug"]}
        self.addCleanup(families.stop)
        driver = mock.patch.object(map_server, "pymysql", fake_driver())
        self.driver = driver.start()
        self.addCleanup(driver.stop)

    def test_a_query_is_the_same_400_before_any_read(self):
        for path, read, _what, _body in PROBES:
            with self.subTest(path), mock.patch.object(map_server, read) as sample:
                h = shell.get(path + "?name=Grug")
            self.assertEqual(h.status(), 400, path)
            self.assertEqual(h.body(), b'{"error": "no query parameters accepted"}')
            sample.assert_not_called()

    def test_a_sample_goes_out_with_its_exact_bytes(self):
        for path, read, _what, _body in PROBES:
            with (
                self.subTest(path),
                mock.patch.object(map_server, read, return_value={"a": 1}),
            ):
                h = shell.get(path)
            self.assertEqual(h.status(), 200, path)
            self.assertEqual(h.body(), b'{"a": 1}', path)
            self.assertEqual(h.header("Cache-Control"), "no-cache", path)

    def test_an_outage_is_its_own_503(self):
        for failure in (OSError("down"), self.driver.err.MySQLError("gone")):
            for path, read, what, body in PROBES:
                with (
                    self.subTest(path, failure=failure),
                    mock.patch.object(map_server, read, side_effect=failure),
                    self.assertLogs(map_server.log, "ERROR") as logs,
                ):
                    h = shell.get(path)
                self.assertEqual(h.status(), 503, path)
                self.assertEqual(h.body(), body, path)
                self.assertEqual(h.header("Content-Type"), "application/json")
                self.assertIn(what, logs.output[0], path)

    def test_a_bug_is_no_outage_and_goes_on_up(self):
        for path, read, _what, _body in PROBES:
            h = shell.FakeHandler(path)
            with (
                self.subTest(path),
                mock.patch.object(map_server, read, side_effect=KeyError("bug")),
                self.assertRaises(KeyError),
            ):
                h.do_GET()
            self.assertEqual(h.sent, [], path)

    def test_a_payload_that_is_not_json_goes_on_up_too(self):
        for path, read, _what, _body in PROBES:
            h = shell.FakeHandler(path)
            with (
                self.subTest(path),
                mock.patch.object(map_server, read, return_value={"bad": object()}),
                self.assertRaises(TypeError),
            ):
                h.do_GET()
            self.assertEqual(h.sent, [], path)


class TheWallIsAHandler(unittest.TestCase):
    """/api/wall returns its heads, shares a 200 and keeps its two failures."""

    def setUp(self):
        map_server.SHARED_READS.clear()
        self.addCleanup(map_server.SHARED_READS.clear)
        families = mock.patch.object(map_server, "FAMILIES")
        self.families = families.start()
        self.families.families.return_value = {"a": ["Grug"]}
        self.families.names.return_value = ["Grug"]
        self.addCleanup(families.stop)
        driver = mock.patch.object(map_server, "pymysql", fake_driver())
        driver.start()
        self.addCleanup(driver.stop)
        for name, value in (
            ("_fetch_family", []),
            ("_fetch_profiles", {}),
            ("_fetch_now_facts", {}),
        ):
            patcher = mock.patch.object(map_server, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_the_heads_go_out_and_are_shared(self):
        with mock.patch.object(
            map_server.watchwall, "build_heads", return_value={"heads": []}
        ) as build:
            first = shell.get("/api/wall")
            second = shell.get("/api/wall")
        self.assertEqual(first.status(), 200)
        self.assertEqual(first.body(), b'{"heads": []}')
        self.assertEqual(second.body(), b'{"heads": []}')
        build.assert_called_once()

    def test_a_failed_read_is_the_shared_503(self):
        self._fetch_family.side_effect = OSError("down")
        with self.assertLogs(map_server.log, "ERROR") as logs:
            h = shell.get("/api/wall")
        self.assertEqual(h.status(), 503)
        self.assertEqual(h.body(), b'{"error": "world unreachable"}')
        self.assertIn("wall query failed", logs.output[0])

    def test_a_failed_status_feed_costs_only_the_sentences(self):
        self._fetch_now_facts.side_effect = OSError("down")
        with (
            mock.patch.object(
                map_server.watchwall, "build_heads", return_value={"heads": []}
            ) as build,
            self.assertLogs(map_server.log, "ERROR") as logs,
        ):
            h = shell.get("/api/wall")
        self.assertEqual(h.status(), 200)
        self.assertIs(build.call_args.kwargs["facts"], False)
        self.assertIn("wall status feed failed", logs.output[0])


if __name__ == "__main__":
    unittest.main()
