"""GET /api/v2/chat (#2159): bounded, read-only recent party and guild lines.

The handler runs against the in-memory realm reader, which raises on any
statement it was not given, so the SQL a handler sends is pinned too.
"""

import datetime
import pathlib
import re
import sys
import types
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import apiv2
    import families
    import realmread
    from apiv2 import chat

FAMILIES = families.Families(
    families.MemoryStore(
        {"Grug": ["Grug", "Og"], "Zug": ["Zug", "Oz"]},
        {"Cave": ["Grug", "Og", "Bonk"], "Bonkers": ["Zug", "Oz"]},
    ),
    fallback=lambda: [],
)
WRITES = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|ALTER|DROP|CREATE|TRUNCATE)\b", re.I
)
T0 = datetime.datetime(2026, 11, 9, 12, 0, 0)


def row(i, who, channel, text, secs=0):
    return {
        "line_id": i,
        "sender_name": who,
        "channel": channel,
        "text": text,
        "created_at": T0 + datetime.timedelta(seconds=secs),
    }


def run(query, rows=None):
    mem = realmread.Memory({chat.CHAT_SQL: lambda p: list(rows or [])})
    ctx = types.SimpleNamespace(
        read=mem, families=FAMILIES, server=types.SimpleNamespace()
    )
    code, payload = apiv2.handle("/api/v2/chat", query, ctx)
    return code, payload, mem


class TheRoute(unittest.TestCase):
    def test_registered(self):
        self.assertIn("/api/v2/chat", apiv2.ROUTES)

    def test_party_scoped_to_family_names_newest_last(self):
        rows = [row(9, "Og", "party", "later", 5), row(8, "Grug", "party", "first", 1)]
        code, body, mem = run({"channel": ["party"], "family": ["Grug"]}, rows)
        self.assertEqual(code, 200)
        self.assertEqual([m["id"] for m in body["lines"]], [8, 9])
        self.assertEqual(body["lines"][-1]["speaker"], "Og")
        self.assertEqual(body["order"], "newest last")
        self.assertEqual(body["channel"], "party")
        sql, params = mem.asked[0]
        self.assertIn("overseer_chat", sql)
        self.assertEqual(params[0], "party")
        self.assertEqual(list(params[1:3]), ["Grug", "Og"])

    def test_guild_scoped_by_guild_name(self):
        code, body, mem = run({"channel": ["guild"], "guild": ["cave"]})
        self.assertEqual(code, 200)
        self.assertEqual(body["guild"], "Cave")
        self.assertEqual(mem.asked[0][1][0], "guild")
        self.assertIn("Cave", mem.asked[0][1])

    def test_officer_is_rejected_before_any_read(self):
        code, body, mem = run({"channel": ["officer"], "guild": ["Cave"]})
        self.assertEqual(code, 400)
        self.assertNotIn("officer", body["channels"])
        self.assertEqual(mem.asked, [])

    def test_guild_lines_need_speaker_guid_and_listener_in_the_guild(self):
        _c, _b, mem = run({"channel": ["guild"], "guild": ["Cave"]})
        sql, params = mem.asked[0]
        self.assertIn("sender_guid IN", sql)
        self.assertIn("heard_by IN", sql)
        self.assertNotIn("sender_name IN", sql)
        self.assertEqual(list(params[:3]), ["guild", "Cave", "Cave"])

    def test_whisper_and_unknown_channels_refused_before_any_read(self):
        for ch in ("whisper", "yell", "channel", "x"):
            code, _body, mem = run({"channel": [ch], "family": ["Grug"]})
            self.assertEqual(code, 400)
            self.assertEqual(mem.asked, [])

    def test_unknown_scope_refused(self):
        self.assertEqual(run({"channel": ["party"], "family": ["Nope"]})[0], 404)
        self.assertEqual(run({"channel": ["guild"], "guild": ["Nope"]})[0], 404)
        self.assertEqual(run({"channel": ["party"]})[0], 400)
        self.assertEqual(run({"channel": ["guild"]})[0], 400)

    def test_bounds_default_clamp_and_are_in_payload(self):
        _c, body, mem = run({"channel": ["party"], "family": ["Grug"]})
        self.assertEqual(body["limit"], chat.DEFAULT_LIMIT)
        self.assertEqual(body["hours"], chat.DEFAULT_HOURS)
        self.assertEqual(body["max_limit"], chat.MAX_LIMIT)
        self.assertEqual(body["max_hours"], chat.MAX_HOURS)
        _c, body, mem = run(
            {
                "channel": ["party"],
                "family": ["Grug"],
                "limit": ["99999"],
                "hours": ["99999"],
            }
        )
        self.assertEqual(body["limit"], chat.MAX_LIMIT)
        self.assertEqual(body["hours"], chat.MAX_HOURS)
        self.assertEqual(mem.asked[0][1][-2:], (chat.MAX_HOURS, chat.MAX_LIMIT))

    def test_bad_numbers_are_400(self):
        for k, v in (("limit", "abc"), ("limit", "0"), ("hours", "-1"), ("hours", "x")):
            code, _b, mem = run({"channel": ["party"], "family": ["Grug"], k: [v]})
            self.assertEqual(code, 400, (k, v))
            self.assertEqual(mem.asked, [])

    def test_markup_stripped_addon_dropped_only_speaker_and_line_exposed(self):
        rows = [
            row(3, "Og", "party", "nice |cff00ff00|Hitem:1:0|h[Club]|h|r"),
            row(2, "Og", "party", "MBOT\tPING"),
        ]
        _c, body, _m = run({"channel": ["party"], "family": ["Grug"]}, rows)
        self.assertEqual(len(body["lines"]), 1)
        self.assertEqual(body["lines"][0]["text"], "nice [Club]")
        self.assertEqual(
            set(body["lines"][0]), {"id", "speaker", "channel", "text", "at"}
        )
        self.assertEqual(body["markup"], "stripped")

    def test_api_doc_names_the_query_keys(self):
        doc = (HERE / "docs" / "API.md").read_text()
        section = doc.split("## `GET /api/v2/chat`")[1].split("## ")[0]
        for key in ("channel", "family", "guild", "limit", "hours"):
            self.assertIn("`" + key + "`", section)

    def test_read_only(self):
        _c, _b, mem = run({"channel": ["party"], "family": ["Grug"]})
        for sql, _p in mem.asked:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"))
            self.assertIsNone(WRITES.search(sql))
        self.assertNotIn("whisper", chat.CHANNELS)


if __name__ == "__main__":
    unittest.main()
