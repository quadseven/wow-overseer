"""The GET handler shape (Refs #733): handler(query, ctx) -> (status, payload).

A moved route returns its status and payload and sends nothing itself; the one
shared _answer gives it the request's context, sends its payload as JSON and
turns a raise into the 503 every read had copied for itself. /api/v2's
dispatch goes through the same function.
"""

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


if __name__ == "__main__":
    unittest.main()
