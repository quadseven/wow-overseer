"""The operator routes obey the deployment's switch on the server (#1842).

POST /api/chat, /api/decree and /api/watch queue orders, start a game client
or hold a thread on the model gateway. The app draws them locked unless
OVERSEER_OPERATOR_ACTIONS is on (apiv2/operator.py); before #1842 the server
obeyed a post from anywhere on the network regardless. These tests pin the
server side: off is a 403 that runs nothing, on runs the route, the director
and frame routes keep their own rules, and /api/chat holds at most
CHAT_MAX_CALLS model calls at once.

The handler is driven directly (no socket), as tests/test_chat_endpoints.py
does.
"""

import io
import logging
import os
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import map_server

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

GATED = ("/api/chat", "/api/decree", "/api/watch")
ON = {"OVERSEER_OPERATOR_ACTIONS": "1"}


class FakeHandler(map_server.Handler):
    """A Handler with the socket amputated: routes in, (code, body) out."""

    def __init__(self, path, body=b'{"name": "Odo", "text": "hello"}'):
        self.path = path
        self.rfile = io.BytesIO(body)
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, ctype, body))

    @property
    def code(self):
        return self.sent[-1][0]


def posted(path, routes):
    """POST `path` with POST_ROUTES swapped for `routes`; the handler."""
    handler = FakeHandler(path)
    with mock.patch.dict(map_server.Handler.POST_ROUTES, routes):
        handler.do_POST()
    return handler


class TheSwitchIsOff(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("OVERSEER_OPERATOR_ACTIONS", None)

    def test_each_operator_route_is_a_403_that_runs_nothing(self):
        for path in GATED:
            with self.subTest(path=path):
                route = mock.Mock()
                handler = posted(path, {path: route})
                self.assertEqual(handler.code, 403)
                self.assertIn(b"operator actions are off", handler.sent[-1][2])
                route.assert_not_called()

    def test_a_query_string_does_not_slip_past_the_switch(self):
        route = mock.Mock()
        handler = posted("/api/decree?x=1", {"/api/decree": route})
        self.assertEqual(handler.code, 403)
        route.assert_not_called()

    def test_an_unset_switch_and_a_false_one_both_refuse(self):
        for value in ("", "0", "off", "false"):
            with (
                self.subTest(value=value),
                mock.patch.dict(os.environ, {"OVERSEER_OPERATOR_ACTIONS": value}),
            ):
                route = mock.Mock()
                handler = posted("/api/chat", {"/api/chat": route})
                self.assertEqual(handler.code, 403)
                route.assert_not_called()

    def test_the_director_and_the_frame_routes_keep_their_own_rules(self):
        for path in ("/api/director", "/api/frame"):
            with self.subTest(path=path):
                route = mock.Mock()
                posted(path, {path: route})
                route.assert_called_once()

    def test_an_unknown_route_is_still_a_404(self):
        handler = posted("/api/nothing", {})
        self.assertEqual(handler.code, 404)


class TheSwitchIsOn(unittest.TestCase):
    def test_each_operator_route_runs(self):
        for path in GATED:
            with self.subTest(path=path), mock.patch.dict(os.environ, ON):
                route = mock.Mock()
                posted(path, {path: route})
                route.assert_called_once()


class TheChatHoldsFewModelCalls(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ON)
        patcher.start()
        self.addCleanup(patcher.stop)
        sem = mock.patch.object(
            map_server,
            "_CHAT_CALLS",
            map_server.threading.BoundedSemaphore(map_server.CHAT_MAX_CALLS),
        )
        sem.start()
        self.addCleanup(sem.stop)

    def chat(self):
        handler = FakeHandler("/api/chat")
        handler.do_POST()
        return handler

    def test_the_cap_is_small_and_fixed(self):
        self.assertGreaterEqual(map_server.CHAT_MAX_CALLS, 1)
        self.assertLessEqual(map_server.CHAT_MAX_CALLS, 4)

    def test_past_the_cap_a_chat_is_a_429_that_writes_and_asks_nothing(self):
        for _ in range(map_server.CHAT_MAX_CALLS):
            self.assertTrue(map_server._CHAT_CALLS.acquire(blocking=False))
        with mock.patch.object(map_server.Handler, "_chat") as talk:
            handler = self.chat()
        self.assertEqual(handler.code, 429)
        talk.assert_not_called()

    def test_inside_the_cap_a_chat_runs_and_gives_its_slot_back(self):
        with mock.patch.object(map_server.Handler, "_chat") as talk:
            for _ in range(map_server.CHAT_MAX_CALLS + 2):
                self.chat()
        self.assertEqual(talk.call_count, map_server.CHAT_MAX_CALLS + 2)

    def test_a_chat_that_fails_still_gives_its_slot_back(self):
        with mock.patch.object(
            map_server.Handler, "_chat", side_effect=RuntimeError("world")
        ):
            for _ in range(map_server.CHAT_MAX_CALLS + 1):
                handler = self.chat()
                self.assertEqual(handler.code, 503)
        with mock.patch.object(map_server.Handler, "_chat") as talk:
            self.chat()
        talk.assert_called_once()


if __name__ == "__main__":
    unittest.main()
