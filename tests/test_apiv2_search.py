"""GET /api/v2/search: the app's global search (apiv2/search.py).

The in-memory realm reader answers each statement by the constant it is built
from, and raises on any other, so these run with no database. They hold the contract the app's search provider
(app/searchv2.js) reads: five capped groups, bound LIKE patterns, and an
in-process cache.
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

import apiv2  # noqa: E402
import guildrun  # noqa: E402
import realmread  # noqa: E402
from apiv2 import search  # noqa: E402

ROSTER = ["Grug", "Bork", "Zug"]


class Lost(Exception):
    """A database error that is not a missing table."""


LIMIT_SQL = "SET SESSION MAX_EXECUTION_TIME = %s"


class Wire:
    """The database end of the map server's own reader, answering from an
    in-memory reader: for the one test that goes through the server."""

    def __init__(self, rd):
        self.rd = rd
        self.rows = []
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.rows = self.rd.must(sql, params)

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


def answers(n=1):
    return {
        LIMIT_SQL: [],
        search._MEMBERS_SQL: [
            {
                "name": "Grug%d" % i,
                "level": 40,
                "class_id": 1,
                "online": 1,
                "guild": "Cave",
            }
            for i in range(n)
        ],
        search._ITEMS_SQL: [
            {"entry": 2589 + i, "name": "Linen Cloth", "quality": 1, "item_level": 5}
            for i in range(n)
        ],
        search._QUESTS_SQL: [
            {"quest": 83, "title": "Red Linen Goods", "level": 9, "name": "Grug"},
            {"quest": 83, "title": "Red Linen Goods", "level": 9, "name": "Bork"},
        ]
        + [
            {"quest": 100 + i, "title": "Quest %d" % i, "level": 9, "name": "Zug"}
            for i in range(n)
        ],
        guildrun._RUN_SQL: [
            {
                "id": 400 + i,
                "guild": "Bonkers",
                "keyword": "deadmines",
                "state": "ended",
                "outcome": "cleared",
                "bosses_done": 7,
                "bosses_total": 7,
                "created_at": "2026-10-09 19:00:00",
            }
            for i in range(n)
        ],
    }


def server():
    return types.SimpleNamespace(
        _all_roster_names=lambda: list(ROSTER),
        _MAP_CLASS_NAMES={1: "Warrior"},
        ITEMS=types.SimpleNamespace(icons={2589: "inv_fabric_linen_01"}),
        council=types.SimpleNamespace(
            DUNGEON_KEYWORDS={"deadmines": (36, ""), "wailing": (43, "")},
            keyword_place=lambda k: {
                "deadmines": "The Deadmines",
                "wailing": "Wailing Caverns",
            }.get(k, k),
        ),
        guildrun=types.SimpleNamespace(
            limits=lambda: types.SimpleNamespace(guilds=("Cave", "Bonkers"))
        ),
        achievements=types.SimpleNamespace(
            MAP_NAMES={36: "The Deadmines", 43: "Wailing Caverns"}
        ),
    )


def reader(answered):
    return realmread.Memory(answered)


def ctx_for(rd):
    return types.SimpleNamespace(read=rd, server=server())


def statements(rd):
    return [(sql, tuple(args or ())) for sql, args in rd.asked]


class TheSearch(unittest.TestCase):
    def setUp(self):
        search._cache.clear()

    def run_q(self, q, rd=None):
        rd = rd or reader(answers())
        status, payload = search.search({"q": [q]}, ctx_for(rd))
        return status, payload, rd

    def test_it_is_a_v2_route(self):
        self.assertIs(apiv2.ROUTES["/api/v2/search"], search.search)

    def test_five_groups_come_back_shaped_for_the_app(self):
        status, p, conn = self.run_q("Dead")
        self.assertEqual(status, 200)
        self.assertEqual(p["q"], "dead")
        for group in search.GROUPS:
            self.assertIn(group, p)
        self.assertEqual(
            p["members"][0],
            {
                "name": "Grug0",
                "level": 40,
                "class": "Warrior",
                "guild": "Cave",
                "online": True,
            },
        )
        self.assertEqual(p["items"][0]["icon"], "inv_fabric_linen_01")
        self.assertEqual(p["quests"][0]["holders"], ["Grug", "Bork"])
        # The dungeon links to the runs page of the guild that ran it last.
        self.assertEqual(
            p["dungeons"], [{"map": 36, "name": "The Deadmines", "guild": "Bonkers"}]
        )
        self.assertEqual(p["runs"][0]["id"], 400)
        self.assertEqual(p["runs"][0]["place"], "The Deadmines")

    def test_every_group_is_capped(self):
        _s, p, _c = self.run_q("grug", reader(answers(20)))
        for group in search.GROUPS:
            self.assertLessEqual(len(p[group]), search.CAP, group)
        self.assertEqual(len(p["quests"]), search.CAP)
        self.assertEqual(len(p["runs"]), search.CAP)

    def test_every_statement_is_bounded_and_the_text_is_bound_not_formatted(self):
        _s, _p, rd = self.run_q("50%_off'")
        selects = [
            (sql, args) for sql, args in statements(rd) if sql.startswith("SELECT")
        ]
        self.assertEqual(len(selects), 4)
        for sql, args in selects:
            self.assertIn("LIMIT %s", sql)
            self.assertNotIn("50", sql)
            self.assertIn("%50\\%\\_off'%", args)

    def test_a_short_query_reads_nothing(self):
        rd = reader(answers())
        status, p = search.search({"q": [" g "]}, ctx_for(rd))
        self.assertEqual(status, 200)
        self.assertEqual(p, search.empty("g"))
        self.assertEqual(rd.asked, [])
        status, p = search.search({}, ctx_for(rd))
        self.assertEqual(p["members"], [])

    def test_the_same_text_is_answered_from_the_cache(self):
        rd = reader(answers())
        search.search({"q": ["Linen"]}, ctx_for(rd))
        seen = len(rd.asked)
        search.search({"q": ["  linen "]}, ctx_for(rd))
        self.assertEqual(len(rd.asked), seen)
        with mock.patch.object(
            search.time,
            "monotonic",
            return_value=search.time.monotonic() + search.TTL + 1,
        ):
            search.search({"q": ["linen"]}, ctx_for(rd))
        self.assertGreater(len(rd.asked), seen)

    def test_the_cache_is_bounded(self):
        for i in range(search.CACHE_MAX + 5):
            search._keep("q%d" % i, 0.0, {})
        self.assertEqual(len(search._cache), search.CACHE_MAX)
        self.assertNotIn("q0", search._cache)

    def test_a_world_without_the_runs_table_still_answers(self):
        missing = realmread.MISSING_TABLE
        rd = reader(
            dict(
                answers(),
                **{guildrun._RUN_SQL: missing, guildrun._RUN_SQL_THIN: missing},
            )
        )
        status, p, _c = self.run_q("dead", rd)
        self.assertEqual(status, 200)
        self.assertEqual(p["runs"], [])
        self.assertEqual(p["dungeons"][0]["guild"], "Cave")

    def test_any_other_failure_is_the_namespaces_503(self):
        rd = reader(
            dict(answers(), **{search._ITEMS_SQL: Lost(2013, "lost connection")})
        )
        with self.assertRaises(Lost):
            self.run_q("linen", rd)

    def test_the_text_is_trimmed_and_capped(self):
        self.assertEqual(search.normalise("  Big   Zug "), "big zug")
        self.assertEqual(len(search.normalise("x" * 500)), search.MAX_CHARS)
        self.assertEqual(search.like("a_b"), "%a\\_b%")
        self.assertEqual(search.like("ab", prefix=True), "ab%")


class TheServerRoute(unittest.TestCase):
    def test_the_map_server_serves_it(self):
        from test_app_shell import get

        search._cache.clear()
        wire = Wire(reader(answers()))
        with (
            mock.patch("map_server._connect", lambda: wire),
            mock.patch("map_server._v2_context", ctx_for),
        ):
            h = get("/api/v2/search?q=linen")
        self.assertEqual(h.status(), 200)
        self.assertEqual(json.loads(h.body())["items"][0]["name"], "Linen Cloth")
        self.assertTrue(wire.closed)


if __name__ == "__main__":
    unittest.main()
