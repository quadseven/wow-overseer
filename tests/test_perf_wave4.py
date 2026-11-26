"""Wave 4 backend SQL/API performance regressions: batching, caching, and scope."""

import pathlib
import sys
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

ROOT = pathlib.Path(__file__).resolve().parent.parent

with stub_modules(pymysql=PYMYSQL):
    sys.path.insert(0, str(ROOT))

    import guildrun
    import map_server
    import readcache
    import realmread
    import watchwall
    from apiv2 import achievements as v2_achievements
    from apiv2 import guild as v2_guild
    from apiv2 import members as v2_members
    from apiv2 import series as v2_series
    from apiv2._context import Context
    from test_members_v2 import FakeConn


class IdleRereaderBatching(unittest.TestCase):
    def _rules(self):
        return [
            (
                ("FROM characters",),
                [
                    {"name": "Grug", "level": 30},
                    {"name": "Og", "level": 28},
                    {"name": "Ugga", "level": 31},
                ],
            ),
            (
                ("overseer_level",),
                [
                    {"name": "Grug", "at": 1_800_000_000 - 40 * 3600},
                    {"name": "Og", "at": 1_800_000_000 - 30 * 3600},
                ],
            ),
            (("UNIX_TIMESTAMP() AS now_at",), [{"now_at": 1_800_000_000}]),
            (("overseer_guild_run",), []),
        ]

    def test_multiple_idle_tiles_run_one_batched_pass_not_n_plus_one(self):
        seen = []
        with realmread.Session(lambda: FakeConn(self._rules(), seen)) as rd:
            reread = v2_members.idle_rereader(rd, ["Grug", "Og", "Ugga"])
            tiles = [
                {
                    "name": n,
                    "present": True,
                    "broadcast_url": "x",
                    "playable": True,
                }
                for n in ("Grug", "Og", "Ugga")
            ]
            wall = watchwall.build_wall(tiles, facts={}, reread=reread)
        # Exactly 4 batched queries for all 3 idle tiles (characters,
        # overseer_level, clock, overseer_guild_run) instead of 3 * 4 = 12.
        self.assertEqual(len(seen), 4)
        for tile in wall["tiles"]:
            self.assertNotEqual(tile["now"]["doing"], "Idle")

    def test_non_idle_tiles_issue_zero_queries(self):
        seen = []
        with realmread.Session(lambda: FakeConn(self._rules(), seen)) as rd:
            reread = v2_members.idle_rereader(rd, ["Grug", "Og"])
            busy = {"doing": "Fighting", "waiting": "", "line": "Fighting."}
            self.assertEqual(reread("Grug", busy), busy)
            self.assertEqual(reread("Og", busy), busy)
        self.assertEqual(seen, [])

    def test_read_error_degrades_without_raising(self):
        class BrokenReader:
            def rows(self, *_args, **_kwargs):
                raise RuntimeError("db down")

            def must(self, *_args, **_kwargs):
                raise RuntimeError("db down")

        reread = v2_members.idle_rereader(BrokenReader(), ["Grug"])
        idle = {"doing": "Idle", "waiting": "", "line": "Idle."}
        with self.assertLogs(v2_members.log, "ERROR"):
            self.assertEqual(reread("Grug", idle), idle)
        # Second call reuses the degraded state without logging again.
        self.assertEqual(reread("Grug", idle), idle)


class AchievementsSingleRosterRead(unittest.TestCase):
    def setUp(self):
        v2_achievements.clear_cache()
        self.addCleanup(v2_achievements.clear_cache)

    def test_member_view_reads_guild_roster_once(self):
        answers = {
            v2_achievements.MEMBERS_SQL: [{"name": "Grug", "guild": "Cave"}],
            v2_achievements.NOW_SQL: [{"now_at": 1_800_000_000}],
            v2_achievements.DEATHS_SQL: [],
            v2_achievements.DEATH_TIMES_SQL: [],
            v2_achievements.HEARTHS_SQL: [],
            v2_achievements.LEVELS_SQL: [],
            v2_achievements.EVENTS_SQL: [],
            v2_achievements.ASKS_SQL: [],
            v2_achievements.SALES_SQL: [],
            guildrun._RUN_SQL: [],
        }
        rd = realmread.Memory(answers)
        families = mock.Mock()
        families.guilds.return_value = [{"name": "Cave", "family": "grug"}]
        families.names.return_value = ["Grug"]
        server = mock.Mock()
        server.achievements.MAP_NAMES = {}
        ctx = Context(read=rd, server=server, families=families)

        payload = v2_achievements._for_member(ctx, "Grug")
        self.assertEqual(payload["name"], "Grug")
        self.assertEqual(payload["guild"], "Cave")
        roster_calls = [
            sql for sql, _params in rd.asked if "JOIN guild_member gm" in sql
        ]
        self.assertEqual(len(roster_calls), 1)


class GuildAndSeriesSharedCache(unittest.TestCase):
    def _families(self):
        fam = mock.Mock()
        fam.guilds.return_value = [{"name": "Cave", "family": "grug"}]
        fam.names.return_value = ["Grug"]
        fam.may_answer.return_value = True
        return fam

    def test_v2_guild_shares_200_and_never_caches_404(self):
        shared = readcache.ReadCache(5.0)
        rd = realmread.Memory({v2_guild._GUILD_SQL: [{"guildid": 1, "name": "Cave"}]})
        server = mock.Mock()
        server.recap.zone_names.return_value = {}
        server.GEO.continents = {}
        server.achievements.MAP_NAMES = {}
        ctx = Context(read=rd, server=server, families=self._families(), shared=shared)

        with mock.patch.object(v2_guild, "build", return_value={"guild": "Cave"}) as b:
            c1, p1 = v2_guild.guild({"guild": ["cave"]}, ctx)
            c2, p2 = v2_guild.guild({"guild": ["Cave"]}, ctx)
        self.assertEqual((c1, c2), (200, 200))
        self.assertEqual(p1, p2)
        self.assertEqual(b.call_count, 1)

        # A 404 (guild row absent in DB) must not be cached.
        shared.clear()
        rd_miss = realmread.Memory({v2_guild._GUILD_SQL: []})
        ctx_miss = Context(
            read=rd_miss, server=server, families=self._families(), shared=shared
        )
        self.assertEqual(v2_guild.guild({"guild": ["cave"]}, ctx_miss)[0], 404)
        self.assertEqual(v2_guild.guild({"guild": ["cave"]}, ctx_miss)[0], 404)
        self.assertEqual(len(rd_miss.asked), 2)

    def test_v2_series_shares_200_and_never_caches_404(self):
        shared = readcache.ReadCache(5.0)
        rd = realmread.Memory(
            {
                v2_series._NOW_SQL: [{"now": 1_800_000_000}],
                v2_series._XP_TABLE_SQL: [{"level": 1, "xp": 400}],
                v2_series._MEMBER_SQL: [
                    {"guid": 10, "name": "Grug", "level": 2, "xp": 50}
                ],
                v2_series._EVENTS_SQL: [],
            }
        )
        ctx = Context(read=rd, server=None, families=self._families(), shared=shared)

        c1, p1 = v2_series.series({"name": ["Grug"]}, ctx)
        queries_after_first = len(rd.asked)
        c2, p2 = v2_series.series({"name": ["Grug"]}, ctx)
        self.assertEqual((c1, c2), (200, 200))
        self.assertEqual(p1, p2)
        self.assertEqual(len(rd.asked), queries_after_first)

        # A 404 (character row absent in DB) must not be cached.
        shared.clear()
        rd_miss = realmread.Memory(
            {
                v2_series._NOW_SQL: [{"now": 1_800_000_000}],
                v2_series._XP_TABLE_SQL: [{"level": 1, "xp": 400}],
                v2_series._MEMBER_SQL: [],
            }
        )
        ctx_miss = Context(
            read=rd_miss, server=None, families=self._families(), shared=shared
        )
        self.assertEqual(v2_series.series({"name": ["Grug"]}, ctx_miss)[0], 404)
        first_miss_queries = len(rd_miss.asked)
        self.assertEqual(v2_series.series({"name": ["Grug"]}, ctx_miss)[0], 404)
        self.assertEqual(len(rd_miss.asked), first_miss_queries * 2)


class GuildrunCachingAndActiveRuns(unittest.TestCase):
    def setUp(self):
        guildrun._BOSSES.clear()
        self.addCleanup(guildrun._BOSSES.clear)

    def test_bosses_cached_once_and_empty_is_retried(self):
        empty_rd = realmread.Memory({guildrun.BOSSES_SQL: []})
        self.assertEqual(guildrun._bosses(empty_rd), frozenset())
        self.assertEqual(guildrun._bosses(empty_rd), frozenset())
        self.assertEqual(len(empty_rd.asked), 2)

        full_rd = realmread.Memory(
            {guildrun.BOSSES_SQL: [{"creditEntry": 644}, {"creditEntry": 646}]}
        )
        self.assertEqual(guildrun._bosses(full_rd), frozenset({644, 646}))
        self.assertEqual(guildrun._bosses(full_rd), frozenset({644, 646}))
        self.assertEqual(len(full_rd.asked), 1)

    def test_active_runs_filters_to_in_flight_states(self):
        row = {
            "id": 7,
            "guild": "Cave",
            "keyword": "deadmines",
            "band": "18-22",
            "composition": "real",
            "members": "Grug:tank:warrior:20",
            "state": "inside",
            "outcome": "",
            "why": "",
            "created_at": None,
            "ended_at": None,
            "created_unix": 1_800_000_000,
            "ended_unix": None,
            "seconds_inside": 120,
            "deaths": 0,
        }
        rd = realmread.Memory({guildrun._RUN_SQL: [row]})
        runs = guildrun.active_runs(rd)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["id"], 7)
        self.assertIn("state IN ('queued', 'inside')", rd.asked[0][0])


class MapServerWave4Wiring(unittest.TestCase):
    def test_hot_v1_endpoints_are_shared(self):
        for path in ("/api/guildruns", "/api/live", "/api/eye"):
            self.assertIn(path, map_server.SHARED_GET_PATHS)

    def test_wall_reuses_request_reader_instead_of_opening_extra_session(self):
        rd = realmread.Memory({})
        ctx = Context(read=rd, server=map_server)
        with (
            mock.patch.object(map_server, "FAMILIES") as fam,
            mock.patch.object(map_server, "_fetch_family", return_value=[]),
            mock.patch.object(map_server, "_fetch_profiles", return_value={}),
            mock.patch.object(map_server, "fetch_now_facts", return_value={}),
            mock.patch.object(
                map_server.realmread,
                "Session",
                side_effect=AssertionError("extra conn"),
            ),
        ):
            fam.families.return_value = {"a": ["Grug"]}
            fam.names.return_value = ["Grug"]
            code, payload = map_server.Handler._wall.__wrapped__({}, ctx)
        self.assertEqual(code, 200)
        self.assertIn("wall", payload)


if __name__ == "__main__":
    unittest.main()
