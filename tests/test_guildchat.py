"""The Guild chat feed (#570): /api/guildchat and the view that draws it."""

import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402  (must follow the pymysql stub)
from tests.test_vclient import get  # noqa: E402

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent


class MySQLError(Exception):
    """Stands in for pymysql.err.MySQLError, which the stub module lacks."""


class FakeCursor:
    """Answers each query by the table it names; records what it was asked."""

    def __init__(self, tables, missing=()):
        self.tables, self.missing, self.calls, self._rows = tables, missing, [], []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        for name in self.missing:
            if name in sql:
                raise MySQLError(1146, "no table")
        self._rows = next((r for n, r in self.tables.items() if n in sql), [])

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


ASKS = [
    {
        "id": 7,
        "guild": "Cave",
        "asker": "Tanka",
        "kind": "dungeon",
        "target": "36",
        "target_label": "Deadmines",
        "roles_needed": "healer,dps",
        "reason": "gear",
        "said": "LFM Deadmines need healer",
        "created_at": "2026-10-04 12:00:00",
        "expires_at": "2026-10-04 12:30:00",
        "state": "ran",
        "run_id": 3,
    },
    {
        "id": 6,
        "guild": "Cave",
        "asker": "Bolt",
        "kind": "quest",
        "target": "99",
        "target_label": "A quest",
        "roles_needed": "dps",
        "reason": "",
        "said": "anyone for a quest",
        "created_at": "2026-10-04 11:00:00",
        "expires_at": "2026-10-04 11:30:00",
        "state": "open",
        "run_id": None,
    },
]
ANSWERS = [
    {
        "id": 1,
        "ask_id": 7,
        "member": "Pip",
        "role": "healer",
        "stance": "help",
        "said": "omw",
        "created_at": "2026-10-04 12:01:00",
        "state": "seated",
    },
]
RUNS = [
    {
        "id": 3,
        "state": "ended",
        "outcome": "cleared",
        "bosses_done": 5,
        "bosses_total": 5,
        "deaths": 1,
        "ended_at": "2026-10-04 12:40:00",
    }
]


class _Both:
    def __init__(self, conn, err):
        self.conn, self.err = conn, err

    def __enter__(self):
        self.err.__enter__()
        return self.conn.__enter__()

    def __exit__(self, *a):
        self.conn.__exit__(*a)
        return self.err.__exit__(*a)


def serve(missing=()):
    cur = FakeCursor(
        {
            "overseer_guild_ask": ASKS,
            "overseer_guild_answer": ANSWERS,
            "overseer_guild_run": RUNS,
        },
        missing,
    )
    return cur, _Both(
        mock.patch.object(map_server, "_connect", return_value=FakeConn(cur)),
        mock.patch.object(
            map_server.pymysql,
            "err",
            types.SimpleNamespace(MySQLError=MySQLError),
            create=True,
        ),
    )


class APugInTheFeed(unittest.TestCase):
    """#591: the asker's call in LookingForGroup and the pug who joined."""

    def test_the_call_rides_on_its_ask(self):
        calls = [
            {
                "ask_id": 7,
                "asker": "Tanka",
                "seats": "healer",
                "channel": "lfg",
                "said": "LF healer for Deadmines, 4/5",
                "created_at": "2026-10-04 12:05:00",
            }
        ]
        cur = FakeCursor(
            {
                "overseer_guild_ask": ASKS,
                "overseer_guild_answer": ANSWERS,
                "overseer_guild_run": RUNS,
                "overseer_guild_pug_call": calls,
            }
        )
        with mock.patch.object(map_server, "_connect", return_value=FakeConn(cur)):
            out = map_server._fetch_guild_chat("Cave", 30)
        self.assertEqual(
            out["asks"][0]["pug_call"]["said"], "LF healer for Deadmines, 4/5"
        )
        self.assertIsNone(out["asks"][1]["pug_call"])

    def test_a_world_without_the_call_table_still_answers(self):
        cur, patch = serve(missing=("overseer_guild_pug_call",))
        with patch:
            h = get("/api/guildchat?guild=Cave")
        self.assertEqual(h.code, 200)
        self.assertIsNone(h.payload["asks"][0]["pug_call"])


class TheEndpoint(unittest.TestCase):
    def test_asks_come_back_with_answers_and_the_run(self):
        cur, patch = serve()
        with patch:
            h = get("/api/guildchat?guild=Cave")
        self.assertEqual(h.code, 200)
        body = h.payload
        self.assertEqual([a["id"] for a in body["asks"]], [7, 6])
        self.assertEqual(body["asks"][0]["answers"][0]["member"], "Pip")
        self.assertEqual(body["asks"][0]["run"]["outcome"], "cleared")
        self.assertIsNone(body["asks"][1]["run"])
        self.assertEqual(body["asks"][1]["answers"], [])
        self.assertTrue(body["ready"])
        self.assertEqual(body["guilds"], ["Cave", "Bonkers"])

    def test_no_guild_means_the_first_configured_one(self):
        cur, patch = serve()
        with patch:
            h = get("/api/guildchat")
        self.assertEqual(cur.calls[0][1][0], "Cave")
        self.assertEqual(h.payload["guild"], "Cave")

    def test_the_guild_and_limit_are_bound_never_interpolated(self):
        cur, patch = serve()
        with patch:
            get("/api/guildchat?guild=Bonkers&limit=500")
        sql, params = cur.calls[0]
        self.assertEqual(params, ("Bonkers", 100))
        self.assertNotIn("Bonkers", sql)

    def test_limit_defaults_to_30_and_floors_at_1(self):
        for raw, want in (("", 30), ("x", 30), ("0", 1), ("-4", 1), ("12", 12)):
            cur, patch = serve()
            with patch:
                get("/api/guildchat?guild=Cave&limit=" + raw)
            self.assertEqual(cur.calls[0][1], ("Cave", want), raw)

    def test_a_guild_that_is_not_configured_is_a_400_and_never_reaches_sql(self):
        cur, patch = serve()
        with patch as conn:
            h = get("/api/guildchat?guild=Evil%27%3B--")
        self.assertEqual(h.code, 400)
        conn.assert_not_called()

    def test_missing_tables_answer_an_empty_list_with_a_flag(self):
        cur, patch = serve(missing=("overseer_guild_ask",))
        with patch:
            h = get("/api/guildchat?guild=Cave")
        self.assertEqual(h.code, 200)
        self.assertEqual(
            h.payload,
            {
                "guild": "Cave",
                "guilds": ["Cave", "Bonkers"],
                "ready": False,
                "asks": [],
            },
        )

    def test_an_unreachable_world_is_a_503(self):
        with mock.patch.object(map_server, "_connect", side_effect=OSError("down")):
            h = get("/api/guildchat?guild=Cave")
        self.assertEqual(h.code, 503)


if __name__ == "__main__":
    unittest.main()
