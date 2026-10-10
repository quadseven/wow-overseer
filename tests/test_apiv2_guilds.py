"""The /api/v2 reads behind the Guilds section: series, dungeonups, guild and
chronicle. The shaping is tested on rows written here; the handlers are run
against a fake connection that answers each query by a piece of its SQL, so
what a handler reads and what it sends back are both checked without a realm.
"""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import apiv2  # noqa: E402
import guildrun  # noqa: E402
import recap  # noqa: E402
from apiv2 import chronicle, dungeonups, guild, series  # noqa: E402

# Half past an hour, so a minute either side stays in the same hour.
NOW = 1_800_001_800
H = 3600


class FakeCursor:
    def __init__(self, answers):
        self.answers = answers
        self.seen = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        self.seen.append((sql, args))
        for needle, rows in self.answers:
            if needle in sql:
                self.rows = rows(args) if callable(rows) else rows
                return
        self.rows = []

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, answers):
        self.cursor_ = FakeCursor(answers)
        self.closed = False

    def cursor(self):
        return self.cursor_

    def close(self):
        self.closed = True


class Ctx:
    def __init__(self, answers=(), server=None):
        self.conn = FakeConn(list(answers))
        self.server = server
        self.connects = 0

    def connect(self):
        self.connects += 1
        return self.conn


XP = [{"level": lvl, "xp": 1000} for lvl in range(1, 60)]


class TheRoutes(unittest.TestCase):
    def test_every_guilds_read_is_registered(self):
        for path in (
            "/api/v2/series",
            "/api/v2/dungeonups",
            "/api/v2/guild",
            "/api/v2/chronicle",
        ):
            self.assertIn(path, apiv2.ROUTES)


class TheSeries(unittest.TestCase):
    TABLE = {lvl: 1000 for lvl in range(1, 60)}

    def test_total_experience_is_the_levels_below_plus_what_is_held(self):
        self.assertEqual(series.total_xp(3, 250, self.TABLE), 2250)
        self.assertIsNone(series.total_xp(3, 0, {1: 1000}))

    def test_an_hour_is_the_straight_line_between_dings(self):
        # Level 10 at now-10h, level 11 at now-5h, 500 into 11 now: 1000 XP
        # over the five hours between the dings, then 500 over the last five.
        events = [
            {"guid": 1, "old_level": 9, "new_level": 10, "at": NOW - 10 * H},
            {"guid": 1, "old_level": 10, "new_level": 11, "at": NOW - 5 * H},
        ]
        points = series.anchors(events, 11, 500, NOW, self.TABLE)
        hours = series.hourly(points, NOW)
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[-1], [NOW, 100])
        self.assertEqual(hours[-6][1], 200)
        # Before the first ding nothing is known: null, never 0.
        self.assertIsNone(hours[0][1])

    def test_one_instant_is_no_rate(self):
        points = series.anchors([], 20, 500, NOW, self.TABLE)
        self.assertEqual(series.measured_or_empty(series.hourly(points, NOW)), [])

    def test_a_total_that_goes_backwards_is_dropped(self):
        events = [{"guid": 1, "old_level": 30, "new_level": 31, "at": NOW - H}]
        points = series.anchors(events, 5, 0, NOW, self.TABLE)
        self.assertEqual(points, [(float(NOW - H), 30000)])

    def test_the_level_line_starts_where_the_window_starts(self):
        events = [{"guid": 1, "old_level": 9, "new_level": 10, "at": NOW - 2 * H}]
        line = series.level_line(events, 10, NOW)
        self.assertEqual(line[0], [NOW - 7 * 86400, 9])
        self.assertEqual(line[1], [NOW - 2 * H, 10])
        self.assertEqual(line[-1], [NOW, 10])

    def test_a_guild_sums_the_measured_hours_and_says_how_many(self):
        chars = [
            {"guid": 1, "name": "A", "level": 11, "xp": 500},
            {"guid": 2, "name": "B", "level": 20, "xp": 0},
        ]
        events = [
            {"guid": 1, "old_level": 9, "new_level": 10, "at": NOW - 30 * H},
            {"guid": 1, "old_level": 10, "new_level": 11, "at": NOW - 5 * H},
        ]
        out = series.guild_series("Cave", chars, events, self.TABLE, NOW)
        self.assertEqual(out["members"], 2)
        self.assertEqual(out["measured"], 1)
        self.assertEqual(len(out["xp_per_hour"]), 24)
        self.assertEqual(out["xp_per_hour"][-1], [NOW, 100])
        self.assertEqual(out["level"][-1][1], 15.5)

    def _answers(self):
        return [
            ("UNIX_TIMESTAMP() AS now", [{"now": NOW}]),
            ("player_xp_for_level", XP),
            (
                # Only a member of a managed guild: the query carries the list.
                "WHERE c.name = %s AND g.name IN",
                lambda a: (
                    [{"guid": 7, "name": "Grug", "level": 11, "xp": 500}]
                    if a == ("Grug", "Cave", "Bonkers")
                    else []
                ),
            ),
            (
                "FROM guild WHERE name",
                lambda a: [{"guildid": 23, "name": "Cave"}] if a == ("Cave",) else [],
            ),
            (
                "JOIN guild_member",
                [{"guid": 7, "name": "Grug", "level": 11, "xp": 500}],
            ),
            (
                "FROM overseer_level",
                [
                    {"guid": 7, "old_level": 9, "new_level": 10, "at": NOW - 10 * H},
                    {"guid": 7, "old_level": 10, "new_level": 11, "at": NOW - 5 * H},
                ],
            ),
        ]

    def test_the_handler_answers_a_member_and_a_guild(self):
        ctx = Ctx(self._answers())
        code, body = series.series({"name": ["Grug"]}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(body["name"], "Grug")
        self.assertEqual(body["xp_per_hour"][-1], [NOW, 100])
        self.assertTrue(ctx.conn.closed)
        code, body = series.series({"guild": ["cave"]}, Ctx(self._answers()))
        self.assertEqual((code, body["guild"], body["measured"]), (200, "Cave", 1))

    def test_the_handler_refuses_what_it_cannot_answer(self):
        self.assertEqual(series.series({}, Ctx())[0], 400)
        self.assertEqual(
            series.series({"name": ["Nobody"]}, Ctx(self._answers()))[0], 404
        )
        self.assertEqual(
            series.series({"guild": ["nowhere"]}, Ctx(self._answers()))[0], 404
        )


NECK = 2  # inventory type: neck


def drop(entry, ilvl, req, creature=100):
    return {
        "Item": entry,
        "creature": creature,
        "inventory_type": NECK,
        "item_level": ilvl,
        "required_level": req,
        "name": "Neck %d" % entry,
        "quality": 3,
        "displayid": None,
    }


def fetched(drops, level=20, worn_ilvl=10):
    neck = recap.slots_for(NECK)[0]
    return {
        "families": {"Grug": ["Grug"]},
        "char_rows": [{"name": "Grug", "level": level, "class": 1}],
        "equipped_rows": [
            {
                "name": "Grug",
                "slot": neck,
                "item_level": worn_ilvl,
                "item_name": "Old Neck",
            }
        ],
        "skill_rows": [],
        "encounter_rows": [{"creature": 100, "name": "Boss One", "map_id": 36}],
        "loot_rows": drops,
    }


class TheDungeonUps(unittest.TestCase):
    def test_a_drop_that_beats_what_is_worn_is_listed_with_its_gain(self):
        rows = dungeonups.build(
            fetched([drop(1, 18, 15)]), "Grug", 36, {}, {36: "The Deadmines"}
        )
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(
            (r["member"], r["boss"], r["gain"], r["now"], r["req"]),
            ("Grug", "Boss One", 8, True, 15),
        )
        self.assertEqual(
            (r["dungeon"], r["item"]["entry"], r["worn"]),
            ("The Deadmines", 1, "Old Neck"),
        )

    def test_a_drop_a_few_levels_ahead_is_listed_at_its_level(self):
        rows = dungeonups.build(fetched([drop(2, 30, 23)]), "Grug", 36, {}, {})
        self.assertEqual((rows[0]["now"], rows[0]["req"]), (False, 23))
        far = dungeonups.build(
            fetched([drop(3, 40, 20 + dungeonups.LOOKAHEAD + 1)]), "Grug", 36, {}, {}
        )
        self.assertEqual(far, [])

    def test_one_row_per_member_and_slot_the_biggest_gain(self):
        rows = dungeonups.build(
            fetched([drop(1, 12, 10), drop(2, 19, 10), drop(3, 8, 10)]),
            "Grug",
            None,
            {},
            {},
        )
        self.assertEqual([(r["item"]["entry"], r["gain"]) for r in rows], [(2, 9)])

    def test_the_handler_checks_its_arguments(self):
        class Server:
            ITEMS = types.SimpleNamespace(icons={})
            achievements = types.SimpleNamespace(MAP_NAMES={36: "The Deadmines"})

            @staticmethod
            def _fetch_dungeonplan():
                return fetched([drop(1, 18, 15)])

        ctx = Ctx(server=Server)
        self.assertEqual(dungeonups.dungeonups({}, ctx)[0], 400)
        self.assertEqual(
            dungeonups.dungeonups({"family": ["grug"], "dungeon": ["x"]}, ctx)[0], 400
        )
        self.assertEqual(dungeonups.dungeonups({"family": ["nobody"]}, ctx)[0], 404)
        code, body = dungeonups.dungeonups({"family": ["grug"], "dungeon": ["36"]}, ctx)
        self.assertEqual((code, len(body)), (200, 1))


class TheGuild(unittest.TestCase):
    def test_faction_and_family_come_from_the_members(self):
        self.assertEqual(guild.faction_of([1, 3, 1]), "Alliance")
        self.assertEqual(guild.faction_of([2, 5]), "Horde")
        self.assertEqual(guild.faction_of([1, 2]), "")
        rows = [
            {"name": "Grug", "family": "Grug"},
            {"name": "Zug", "family": "Zug"},
            {"name": "Og", "family": "Grug"},
        ]
        self.assertEqual(guild.family_of({"Grug", "Og", "Bonk"}, rows), "Grug")

    def test_a_corpse_and_a_spirit_are_both_ghosts_on_this_page(self):
        # Online and life are presence.of's reading (tests/test_presence.py);
        # this page shows a corpse and a released spirit alike as a ghost.
        def row(name):
            return {"name": name, "level": 20, "class": 1}

        def reading(online, life):
            return {"online": online, "life": life, "fresh_at": None}

        readings = {
            "Ghosty": reading(True, "ghost"),
            "Corpse": reading(True, "dead"),
            "Fine": reading(True, "alive"),
            "Saved": reading(False, "ghost"),
            "Away": reading(False, None),
        }
        out = {
            m["name"]: m
            for m in guild.member_rows([row(n) for n in readings], readings)
        }
        self.assertEqual(
            sorted(n for n, m in out.items() if m["ghost"]),
            ["Corpse", "Ghosty", "Saved"],
        )
        self.assertEqual(
            sorted(n for n, m in out.items() if m["online"]),
            ["Corpse", "Fine", "Ghosty"],
        )

    def test_a_member_is_blocked_when_its_latest_class_step_failed(self):
        steps = [
            {
                "name": "Bonk",
                "command": "take quest:1",
                "status": "error",
                "detail": "refused",
                "result": '{"reason": "no giver"}',
                "at": NOW - 60,
            },
            {
                "name": "Bonk",
                "command": "take quest:1",
                "status": "applied",
                "detail": "",
                "result": "",
                "at": NOW,
            },
            {
                "name": "Durg",
                "command": "turnin quest:2",
                "status": "error",
                "detail": "refused",
                "result": '{"reason": "not eligible"}',
                "at": NOW,
            },
        ]
        blocked = guild.blocked_steps(steps)
        self.assertEqual(list(blocked), ["Durg"])
        open_rows = [
            {"name": "Durg", "id": 2, "status": 3, "title": "Two"},
            {"name": "Bonk", "id": 1, "status": 1, "title": "One"},
        ]
        rows = guild.class_quest_rows(open_rows, blocked, {}, {"Durg": "Warrior"})
        self.assertEqual(
            [(r["member"], r["state"]) for r in rows],
            [("Durg", "blocked"), ("Bonk", "ready to hand in")],
        )
        self.assertEqual(
            (rows[0]["quest"], rows[0]["note"], rows[0]["class"]),
            ("Two", "not eligible", "Warrior"),
        )

    def test_the_path_is_the_factions_doors_in_level_order_with_their_tally(self):
        runs = [
            {
                "keyword": "deadmines",
                "state": "ended",
                "outcome": "wiped",
                "why": "all dead",
                "deaths": 5,
                "seconds_inside": 900,
                "created": NOW - 2 * H,
                "ended": NOW - H,
            },
            {
                "keyword": "deadmines",
                "state": "ended",
                "outcome": "cleared",
                "why": "",
                "deaths": 1,
                "seconds_inside": 2400,
                "created": NOW - 5 * H,
                "ended": NOW - 4 * H,
            },
            {
                "keyword": "deadmines",
                "state": "ended",
                "outcome": "refused",
                "why": "locked",
                "deaths": 0,
                "seconds_inside": 0,
                "created": NOW - 6 * H,
                "ended": NOW - 6 * H,
            },
        ]
        rows = guild.dungeon_rows(guildrun.doors(), "Alliance", runs)
        floors = [r["floor"] for r in rows]
        self.assertEqual(floors, sorted(floors))
        self.assertNotIn("ragefire", [r["keyword"] for r in rows])
        dm = next(r for r in rows if r["keyword"] == "deadmines")
        self.assertEqual(
            (dm["runs"], dm["started"], dm["cleared"], dm["wiped"], dm["best_seconds"]),
            (2, 3, 1, 1, 2400),
        )
        self.assertEqual(dm["lesson"], {"outcome": "wiped", "n": 1, "why": "all dead"})
        self.assertEqual(dm["last_at"], NOW - H)
        never = next(r for r in rows if r["keyword"] == "wailing")
        self.assertEqual(
            (never["runs"], never["best_seconds"], never["last_at"], never["lesson"]),
            (0, None, None, None),
        )

    def test_the_handler_reads_one_guild(self):
        class Server:
            recap = types.SimpleNamespace(zone_names=lambda c: {40: "Westfall"})
            GEO = types.SimpleNamespace(continents={})
            achievements = types.SimpleNamespace(MAP_NAMES={36: "The Deadmines"})

        answers = [
            (
                "FROM guild WHERE name",
                lambda a: [{"guildid": 23, "name": "Cave"}] if a == ("Cave",) else [],
            ),
            ("UNIX_TIMESTAMP() AS now", [{"now": NOW}]),
            # presence.of's two reads: Grug is in the world, Bonk's save has
            # the ghost flag.
            (
                "FROM overseer_snapshot",
                [{"name": "Grug", "health": 900, "max_health": 900, "at": NOW}],
            ),
            ("playerFlags AS flags FROM characters", [{"name": "Bonk", "flags": 0x10}]),
            (
                "FROM characters c JOIN guild_member",
                [
                    {
                        "guid": 1,
                        "name": "Grug",
                        "level": 42,
                        "class": 1,
                        "race": 1,
                        "zone": 40,
                    },
                    {
                        "guid": 2,
                        "name": "Bonk",
                        "level": 20,
                        "class": 9,
                        "race": 3,
                        "zone": 40,
                    },
                ],
            ),
            ("FROM overseer_roster", [{"name": "Grug", "family": "Grug"}]),
            ("FROM overseer_level", [{"name": "Bonk", "level": 20, "at": NOW - H}]),
            ("GROUP BY killer_name", [{"killer": "Defias Pillager", "n": 7, "who": 2}]),
            (
                "COUNT(DISTINCT character_name) AS who FROM overseer_death",
                [{"n": 9, "who": 2}],
            ),
            (
                "SELECT MAX(id) FROM overseer_death",
                [
                    {
                        "name": "Bonk",
                        "killer": "Defias Pillager",
                        "map": 0,
                        "zone": 40,
                        "at": NOW - 600,
                    }
                ],
            ),
            ("character_queststatus_rewarded", [{"n": 12, "who": 2}]),
            (
                "FROM character_queststatus s",
                [{"name": "Bonk", "id": 5, "status": 3, "title": "Five"}],
            ),
            ("FROM overseer_command", []),
            ("FROM overseer_guild_run", []),
        ]
        code, body = guild.guild({"guild": ["cave"]}, Ctx(answers, Server))
        self.assertEqual(code, 200)
        self.assertEqual(
            (
                body["guild"],
                body["faction"],
                body["family"],
                body["count"],
                body["online"],
            ),
            ("Cave", "Alliance", "Grug", 2, 1),
        )
        self.assertEqual([m["name"] for m in body["members"] if m["ghost"]], ["Bonk"])
        self.assertEqual(
            body["deaths"]["ghosts"],
            [
                {
                    "name": "Bonk",
                    "killer": "Defias Pillager",
                    "where": "Westfall",
                    "at": NOW - 600,
                }
            ],
        )
        self.assertEqual(
            (body["class_quests"]["done"], body["class_quests"]["open"]), (12, 1)
        )
        self.assertEqual(
            body["gaining"], [{"name": "Bonk", "level": 20, "at": NOW - H}]
        )
        self.assertEqual(guild.guild({}, Ctx(answers, Server))[0], 400)
        self.assertEqual(
            guild.guild({"guild": ["nowhere"]}, Ctx(answers, Server))[0], 404
        )


class TheChronicle(unittest.TestCase):
    def test_names_read_as_a_sentence(self):
        self.assertEqual(chronicle.names_line(["A"]), "A")
        self.assertEqual(chronicle.names_line(["A", "B", "A"]), "A and B")
        self.assertEqual(
            chronicle.names_line(["A", "B", "C", "D", "E"]), "A, B, C and 2 more"
        )

    def test_levels_are_one_item_per_guild_and_hour(self):
        rows = [
            {"name": "Bonk", "level": 25, "guild_id": 23, "at": NOW},
            {"name": "Durg", "level": 22, "guild_id": 23, "at": NOW - 60},
            {"name": "Zag", "level": 30, "guild_id": 24, "at": NOW - 60},
            {"name": "Bonk", "level": 24, "guild_id": 23, "at": NOW - 2 * H},
        ]
        items = chronicle.level_items(rows, {23: "Cave", 24: "Bonkers"})
        texts = sorted(i["text"] for i in items)
        self.assertIn("Zag reached level 30.", texts)
        self.assertIn("Bonk reached level 24.", texts)
        self.assertTrue(
            any(t.startswith("Reached a new level: ") and "Bonk 25" in t for t in texts)
        )

    def test_runs_that_went_in_read_as_clears_and_returns(self):
        rows = [
            {
                "id": 9,
                "guild": "Cave",
                "keyword": "deadmines",
                "outcome": "cleared",
                "members": "Crag:tank:warrior:23,Totta:dps:mage:23",
                "deaths": 0,
                "bosses_done": 7,
                "bosses_total": 7,
                "at": NOW,
            },
            {
                "id": 8,
                "guild": "Cave",
                "keyword": "wailing",
                "outcome": "wiped",
                "members": "",
                "deaths": 4,
                "bosses_done": 2,
                "bosses_total": 7,
                "at": NOW - H,
            },
        ]
        a, b = chronicle.run_items(rows)
        self.assertEqual(
            (a["kind"], a["who"], a["run"]), ("clear", ["Crag", "Totta"], 9)
        )
        self.assertEqual(a["text"], "Cave cleared The Deadmines, 7 of 7 bosses.")
        self.assertEqual(b["kind"], "run")
        self.assertIn("wiped, 2 of 7 bosses", b["text"])

    def test_dungeon_deaths_group_by_dungeon_and_hour(self):
        rows = [
            {"name": "Crag", "map": 36, "killer": "Sneed", "guild_id": 23, "at": NOW},
            {
                "name": "Crag",
                "map": 36,
                "killer": "Sneed",
                "guild_id": 23,
                "at": NOW - 60,
            },
            {
                "name": "Totta",
                "map": 36,
                "killer": "Defias Miner",
                "guild_id": 23,
                "at": NOW - 120,
            },
            # A map the site does not name (a class start zone) is not a dungeon.
            {"name": "Brug", "map": 609, "killer": "Kitrik", "guild_id": 23, "at": NOW},
        ]
        (item,) = chronicle.death_items(rows, {23: "Cave"}, {36: "The Deadmines"})
        self.assertEqual(
            item["text"],
            "Crag and Totta died in The Deadmines (3 deaths): Sneed and Defias Miner.",
        )

    def test_the_handler_covers_both_guilds_or_one(self):
        class Server:
            achievements = types.SimpleNamespace(MAP_NAMES={36: "The Deadmines"})

        def guilds(args):
            known = {"Cave": 23, "Bonkers": 24}
            return [{"guildid": known[a], "name": a} for a in args if a in known]

        answers = [
            ("FROM guild WHERE name IN", guilds),
            (
                "FROM overseer_level",
                [{"name": "Bonk", "level": 25, "guild_id": 23, "at": NOW}],
            ),
            ("FROM overseer_guild_run", []),
            ("FROM overseer_death", []),
        ]
        code, body = chronicle.chronicle({}, Ctx(answers, Server))
        self.assertEqual(
            (code, body["guilds"], len(body["items"])), (200, ["Bonkers", "Cave"], 1)
        )
        ctx = Ctx(answers, Server)
        code, body = chronicle.chronicle({"guild": ["Cave"]}, ctx)
        self.assertEqual(body["guilds"], ["Cave"])
        self.assertTrue(ctx.conn.closed)
        self.assertEqual(
            chronicle.chronicle({"guild": ["nowhere"]}, Ctx(answers, Server))[0], 404
        )


class TheAllowlist(unittest.TestCase):
    """A guild outside the managed ones, or a value that is not a name, is
    refused before a connection is opened, so it never reaches the realm."""

    OUTSIDERS = ["Adventurer Union", "x' OR '1'='1", "cave; DROP TABLE guild", ""]

    def _refused(self, handler, query, code):
        ctx = Ctx([("", lambda a: self.fail("a query ran: %r" % (a,)))])
        got, body = handler(query, ctx)
        self.assertEqual(got, code, query)
        self.assertEqual(ctx.connects, 0, query)
        self.assertIn("error", body)

    def test_only_managed_guilds_are_read(self):
        for g in self.OUTSIDERS[:-1]:
            self._refused(guild.guild, {"guild": [g]}, 404)
            self._refused(chronicle.chronicle, {"guild": [g]}, 404)
            self._refused(series.series, {"guild": [g]}, 404)

    def test_a_value_that_is_not_a_name_is_refused(self):
        for n in ["x' OR '1'='1", "Grug1", "A" * 13, "Grug Zug"]:
            self._refused(series.series, {"name": [n]}, 400)

        class Server:
            @staticmethod
            def _fetch_dungeonplan():
                raise AssertionError("the world was read")

        for q in ({"family": ["gr'ug"]}, {"family": ["grug"], "dungeon": ["123456"]}):
            ctx = Ctx(server=Server)
            self.assertEqual(dungeonups.dungeonups(q, ctx)[0], 400)

    def test_a_managed_guild_is_matched_in_any_case(self):
        from apiv2 import _allow

        self.assertEqual(_allow.guild("CAVE"), "Cave")
        self.assertEqual(_allow.guild(" bonkers "), "Bonkers")
        self.assertIsNone(_allow.guild("Adventurer Union"))


if __name__ == "__main__":
    unittest.main()
