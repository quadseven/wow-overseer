"""Wiring tests for /api/thoughts and /api/chat.

The adapter is meant to be thin, but three of its promises are not visible
from chat.py at all and are exactly the kind that rot silently: a bad name
or an unknown character never reaches SQL or an LLM, an oversized body is
refused before it is read, and the Overseer's own words are persisted
BEFORE the model is asked anything, so an LLM outage costs an answer and
never the message.

The handler is driven directly (no socket): _send is captured, and every
IO function is replaced, so this stays a stdlib-only unit suite like the
rest. pymysql is stubbed for import - the module only touches it inside
_connect(), which no test here reaches.

Ticket: infra#2604.
"""

import io
import json
import logging
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import chat  # noqa: E402  (must follow the pymysql stub)
import map_server  # noqa: E402
import voice  # noqa: E402

# The outage and 503 paths log tracebacks on purpose; without a configured
# root handler those reach stderr and make a passing run look like a wall of
# failures. Scoped to this service's logger only.
map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

NOW = datetime(2026, 8, 21, 12, 0, 0)

SNAPSHOT = {
    "name": "Odo",
    "level": 5,
    "race": 2,
    "class": 1,
    "map_id": 1,
    "pos_x": -600.0,
    "pos_y": -4200.0,
    "health": 100,
    "max_health": 146,
    "in_combat": 0,
    "personality": "gruff and loyal",
}


class FakeHandler(map_server.Handler):
    """A Handler with the socket amputated: routes in, (code, body) out."""

    def __init__(self, path, body=b""):
        self.path = path
        self.rfile = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))} if body else {}
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, ctype, body))

    @property
    def code(self):
        return self.sent[-1][0]

    @property
    def payload(self):
        return json.loads(self.sent[-1][2])


def post(name="Odo", text="hello", raw=None):
    body = raw if raw is not None else json.dumps({"name": name, "text": text}).encode()
    handler = FakeHandler("/api/chat", body)
    handler.do_POST()
    return handler


class ThoughtsEndpointTest(unittest.TestCase):
    def get(self, path):
        handler = FakeHandler(path)
        handler.do_GET()
        return handler

    def test_a_name_that_is_not_a_name_is_refused_before_any_query(self):
        with mock.patch.object(map_server, "_fetch_thoughts") as fetch:
            handler = self.get("/api/thoughts?name=Robert%27);DROP")
        self.assertEqual(handler.code, 400)
        fetch.assert_not_called()

    def test_a_malformed_cursor_is_refused_rather_than_silently_ignored(self):
        # Ignoring it would restart the page at the newest thought, which
        # reads as "history ends here" - a silent lie about the past.
        with mock.patch.object(map_server, "_fetch_thoughts") as fetch:
            handler = self.get("/api/thoughts?name=Odo&before=yesterday")
        self.assertEqual(handler.code, 400)
        fetch.assert_not_called()

    def test_an_unknown_character_is_a_clean_404(self):
        with mock.patch.object(map_server, "_fetch_thoughts", return_value=None):
            handler = self.get("/api/thoughts?name=Nobody")
        self.assertEqual(handler.code, 404)

    def test_a_page_is_fetched_with_a_clamped_limit_and_the_cursor(self):
        rows = [
            {
                "id": 4,
                "source": "event",
                "text": "Odo entered combat.",
                "created_at": NOW,
            }
        ]
        with mock.patch.object(
            map_server, "_fetch_thoughts", return_value=(rows, NOW)
        ) as fetch:
            handler = self.get("/api/thoughts?name=Odo&before=9&limit=99999")
        fetch.assert_called_once_with("Odo", 9, chat.MAX_PAGE)
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["thoughts"][0]["id"], 4)

    def test_a_dead_database_is_a_503_not_a_hang_or_a_blank(self):
        with mock.patch.object(
            map_server, "_fetch_thoughts", side_effect=OSError("gone")
        ):
            handler = self.get("/api/thoughts?name=Odo")
        self.assertEqual(handler.code, 503)


class ChatEndpointTest(unittest.TestCase):
    def setUp(self):
        self.thoughts = []
        self.commands = []
        patches = {
            "_fetch_chat_grounding": mock.DEFAULT,
            "_insert_thought": mock.DEFAULT,
            "_insert_command": mock.DEFAULT,
            "_ask_llm": mock.DEFAULT,
        }
        self.patcher = mock.patch.multiple(map_server, **patches)
        self.mocks = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.mocks["_fetch_chat_grounding"].return_value = {
            "snapshot_row": dict(SNAPSHOT),
            "recent": [],
        }
        self.mocks["_insert_thought"].side_effect = lambda name, source, text: (
            self.thoughts.append((name, source, text))
        )
        self.mocks["_insert_command"].side_effect = lambda name, command, source: (
            self.commands.append((name, command, source)) or 1
        )
        self.mocks[
            "_ask_llm"
        ].return_value = '{"command": "grind", "say": "I will hunt, Overseer."}'

    def test_a_reply_persists_both_sides_of_the_exchange(self):
        handler = post(text="go get stronger")
        self.assertEqual(handler.code, 200)
        self.assertEqual(handler.payload["say"], "I will hunt, Overseer.")
        self.assertEqual(
            self.thoughts,
            [
                ("Odo", "chat", chat.overseer_line("go get stronger")),
                ("Odo", "chat", "I will hunt, Overseer."),
            ],
        )

    def test_a_sanctioned_command_travels_the_discord_path(self):
        # Same table, same worldserver poller: a directive typed on the web
        # page must not reach the game by a second, divergent road.
        handler = post(text="go get stronger")
        self.assertEqual(self.commands, [("Odo", "grind", "web:overseer")])
        self.assertEqual(handler.payload["command"], "grind")

    def test_an_invented_command_never_reaches_the_queue(self):
        self.mocks[
            "_ask_llm"
        ].return_value = '{"command": "delete azeroth", "say": "As you wish."}'
        handler = post()
        self.assertEqual(self.commands, [])
        self.assertIsNone(handler.payload["command"])

    def test_an_llm_outage_keeps_the_message_and_answers_honestly(self):
        self.mocks["_ask_llm"].side_effect = TimeoutError("spark is asleep")
        handler = post(text="are you well?")
        self.assertEqual(handler.code, 200)
        self.assertTrue(handler.payload["degraded"])
        self.assertEqual(
            self.thoughts,
            [
                ("Odo", "chat", chat.overseer_line("are you well?")),
                ("Odo", "chat", chat.outage_line("Odo")),
            ],
        )

    def test_the_overseer_line_is_written_before_the_model_is_asked(self):
        # The ordering IS the guarantee: whatever the model does next, the
        # message is already in the stream.
        order = []
        self.mocks["_insert_thought"].side_effect = lambda *a: order.append("thought")
        self.mocks["_ask_llm"].side_effect = lambda prompt: order.append("llm") or "hi"
        post()
        self.assertEqual(order[:2], ["thought", "llm"])

    def test_the_prompt_carries_the_grounding_the_page_promised(self):
        self.mocks["_fetch_chat_grounding"].return_value = {
            "snapshot_row": dict(SNAPSHOT),
            "recent": [
                {
                    "id": 3,
                    "source": "event",
                    "text": "Odo entered combat.",
                    "created_at": NOW,
                }
            ],
        }
        post(text="what happened?")
        prompt = self.mocks["_ask_llm"].call_args[0][0]
        for fragment in (
            "Odo",
            "Orc",
            "Warrior",
            "gruff and loyal",
            "Odo entered combat.",
            "what happened?",
        ):
            self.assertIn(fragment, prompt)

    def test_a_logged_out_character_is_told_plainly_not_ventriloquized(self):
        self.mocks["_fetch_chat_grounding"].return_value = {
            "snapshot_row": None,
            "recent": [],
        }
        handler = post(text="where are you?")
        self.assertEqual(handler.code, 200)
        self.assertFalse(handler.payload["present"])
        self.mocks["_ask_llm"].assert_not_called()
        # The message still persists: the Overseer spoke, and that belongs
        # in the stream even though nobody was home to answer.
        self.assertEqual(
            self.thoughts, [("Odo", "chat", chat.overseer_line("where are you?"))]
        )

    def test_an_unknown_character_is_a_clean_404_with_nothing_written(self):
        self.mocks["_fetch_chat_grounding"].return_value = None
        handler = post(name="Nobody")
        self.assertEqual(handler.code, 404)
        self.assertEqual(self.thoughts, [])

    def test_a_name_that_is_not_a_name_never_reaches_the_database(self):
        handler = post(name="; DROP TABLE")
        self.assertEqual(handler.code, 400)
        self.mocks["_fetch_chat_grounding"].assert_not_called()

    def test_an_empty_message_is_refused(self):
        handler = post(text="   ")
        self.assertEqual(handler.code, 400)
        self.mocks["_fetch_chat_grounding"].assert_not_called()

    def test_an_oversized_body_is_refused_before_it_is_read(self):
        handler = post(raw=b"x" * (map_server.MAX_BODY + 1))
        self.assertEqual(handler.code, 413)
        # Nothing was consumed from the socket: the bound is the point.
        self.assertEqual(handler.rfile.tell(), 0)

    def test_a_body_that_is_not_json_is_refused(self):
        self.assertEqual(post(raw=b"hello there").code, 400)

    def test_a_json_body_that_is_not_an_object_is_refused(self):
        self.assertEqual(post(raw=b'["Odo", "hi"]').code, 400)

    def test_an_empty_body_is_refused(self):
        self.assertEqual(post(raw=b"").code, 400)

    def test_a_dead_database_is_a_503(self):
        self.mocks["_fetch_chat_grounding"].side_effect = OSError("gone")
        self.assertEqual(post().code, 503)

    def test_posting_anywhere_else_is_a_404(self):
        handler = FakeHandler("/api/map", b"{}")
        handler.do_POST()
        self.assertEqual(handler.code, 404)

    def test_a_long_message_is_bounded_before_it_is_stored(self):
        post(text="y" * 4000)
        self.assertLessEqual(
            len(self.thoughts[0][2]), len(chat.OVERSEER_PREFIX) + chat.MAX_MESSAGE
        )


def said(i, sender="Grug", text="Aye.", at="2026-08-23 12:00:00", ch="party"):
    return {
        "id": i,
        "sender_name": sender,
        "channel": ch,
        "text": text,
        "created_at": at,
        "age_s": 3,
    }


class PartyEndpointTest(unittest.TestCase):
    """GET /api/chat/party?family=<key>&after=<id>."""

    def setUp(self):
        rosters = {"Grug": ["Grug", "Ugga"], "Zug": ["Zug", "Oz"]}
        for name, value in (("families", rosters), ("default", "Grug")):
            patcher = mock.patch.object(map_server.FAMILIES, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, path, rows=(), cursor=0):
        handler = FakeHandler(path)
        with mock.patch.object(
            map_server, "_fetch_chat_party", return_value=(list(rows), cursor)
        ) as fetch:
            handler.do_GET()
        return handler, fetch

    def test_a_line_heard_by_three_is_one_voiced_line(self):
        rows = [said(1), said(2), said(3), said(4, sender="Ugga", ch="raid")]
        handler, _ = self.get("/api/chat/party?family=Grug&after=0", rows)
        self.assertEqual(handler.code, 200)
        lines = handler.payload["rows"]
        self.assertEqual([line["id"] for line in lines], [1, 4])
        self.assertEqual(lines[0]["voice"]["pitch"], 0.70)
        self.assertEqual(lines[1]["voice"]["engine_voice_hint"]["gender"], "female")
        self.assertEqual(handler.payload["cursor"], 4)

    def test_the_requested_familys_roster_and_cursor_reach_the_read(self):
        _, fetch = self.get("/api/chat/party?family=Zug&after=17", cursor=17)
        fetch.assert_called_once_with(["Zug", "Oz"], 17)

    def test_an_unknown_family_is_refused_before_any_query(self):
        # Falling back to the default family would read its lines aloud to a
        # page that asked for another, and twice where it polls both.
        handler, fetch = self.get("/api/chat/party?family=Nobody&after=1", cursor=1)
        self.assertEqual(handler.code, 400)
        fetch.assert_not_called()

    def test_no_family_reads_the_default_one(self):
        _, fetch = self.get("/api/chat/party?after=1", cursor=1)
        fetch.assert_called_once_with(["Grug", "Ugga"], 1)

    def test_no_cursor_asks_for_the_newest_row(self):
        handler, fetch = self.get("/api/chat/party?family=Grug", cursor=90)
        fetch.assert_called_once_with(["Grug", "Ugga"], None)
        self.assertEqual(handler.payload, {"rows": [], "cursor": 90})

    def test_a_bad_cursor_is_refused_before_any_query(self):
        handler, fetch = self.get("/api/chat/party?family=Grug&after=-1")
        self.assertEqual(handler.code, 400)
        fetch.assert_not_called()

    def test_a_database_outage_is_a_503(self):
        handler = FakeHandler("/api/chat/party?family=Grug&after=1")
        with mock.patch.object(
            map_server, "_fetch_chat_party", side_effect=OSError("down")
        ):
            handler.do_GET()
        self.assertEqual(handler.code, 503)


class ChatReadCursor:
    def __init__(self, rows=(), top=0):
        self.rows = list(rows)
        self.top = top
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def fetchone(self):
        return {"top": self.top}

    def fetchall(self):
        return self.rows


class ChatReadConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


class PartyReadTest(unittest.TestCase):
    """_fetch_chat_party: what it asks overseer_chat for."""

    def fetch(self, names, after, cur):
        with mock.patch.object(map_server, "_connect", return_value=ChatReadConn(cur)):
            return map_server._fetch_chat_party(names, after)

    def test_party_and_raid_bot_lines_from_the_roster_after_the_cursor(self):
        cur = ChatReadCursor([said(8)])
        rows, cursor = self.fetch(["Grug", "Ugga"], 7, cur)
        self.assertEqual((rows, cursor), ([said(8)], 7))
        ((sql, params),) = cur.calls
        self.assertIn("channel IN (%s, %s)", sql)
        self.assertIn("sender_is_bot = 1", sql)
        self.assertIn("ORDER BY id LIMIT %s", sql)
        self.assertEqual(params, (7, "party", "raid", "Grug", "Ugga", 20))

    def test_no_cursor_starts_at_the_newest_row_and_reads_no_lines(self):
        cur = ChatReadCursor([said(8)], top=55)
        self.assertEqual(self.fetch(["Grug"], None, cur), ([], 55))
        ((sql, _params),) = cur.calls
        self.assertIn("MAX(id)", sql)

    def test_an_empty_roster_reads_nothing(self):
        cur = ChatReadCursor([said(8)])
        self.assertEqual(self.fetch([], 3, cur), ([], 3))
        self.assertEqual(cur.calls, [])


class ParseGateTest(unittest.TestCase):
    def test_the_endpoint_and_the_bridge_share_one_command_gate(self):
        # Not a duplicate of the chat.py suite: this pins that the web
        # surface delegates to voice.py rather than growing its own rule.
        self.assertIs(
            chat.parse_reply('{"command": "grind", "say": "ok"}').__class__,
            voice.Decision,
        )


if __name__ == "__main__":
    unittest.main()
