"""One reading of who is in the world and alive, for every page that says so.

Three reads once said "online" three ways: the roster by a fresh snapshot, the
Guild page by a fresh snapshot OR the saved online column, the gear table by
the saved online column alone (and dead by a snapshot with no health, so a
released spirit never showed). The same guild's online count differed between
two pages. apiv2/presence.py is now the one rule, and each of the three
endpoints asks it rather than deciding for itself.

The fake world below answers the two reads the way MySQL would: a snapshot
row comes back only while it is younger than the bound the query names, and
every name is a bound parameter.
"""

import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import guildgear  # noqa: E402
import map_server  # noqa: E402  (must follow the pymysql stub)
from apiv2 import guild, members, presence  # noqa: E402
from tests.test_apiv2_guilds import Ctx as GuildCtx  # noqa: E402
from tests.test_members_v2 import ctx_for, roster_rules, server  # noqa: E402
from tests.test_vclient import get  # noqa: E402

NOW = 1_800_000_000
GHOST_FLAG = 0x10  # PLAYER_FLAGS_GHOST in the saved playerFlags


class World:
    """overseer_snapshot and characters, answering as the database would.

    snaps: name -> (age in seconds, health, max_health)
    flags: name -> saved playerFlags
    """

    def __init__(self, snaps=None, flags=None):
        self.snaps = snaps or {}
        self.flags = flags or {}
        self.seen = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.seen.append((sql, params))
        names = [p for p in params if isinstance(p, str)]
        if "FROM overseer_snapshot" in sql:
            bound = next(p for p in params if isinstance(p, int))
            self.rows = [
                {"name": n, "health": h, "max_health": mx, "at": NOW - age}
                for n, (age, h, mx) in self.snaps.items()
                if n in names and age < bound  # updated_at > NOW() - bound
            ]
        elif "FROM characters" in sql:
            self.rows = [
                {"name": n, "flags": f} for n, f in self.flags.items() if n in names
            ]
        else:
            self.rows = []

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


FRESH, STALE = 5, 61
SET, UNSET = GHOST_FLAG | 0x8, 0x8  # another flag rides along either way

# snapshot age (None: no row at all), health, max_health, saved flags
#   -> online, life
CASES = [
    # A fresh snapshot decides, whatever the save says.
    (FRESH, 0, 300, UNSET, True, "dead"),
    (FRESH, 0, 300, SET, True, "dead"),
    (FRESH, 1, 300, UNSET, True, "ghost"),
    (FRESH, 1, 300, SET, True, "ghost"),
    (FRESH, 300, 300, UNSET, True, "alive"),
    (FRESH, 300, 300, SET, True, "alive"),
    # One point of health out of one is full health, not a spirit.
    (FRESH, 0, 1, UNSET, True, "dead"),
    (FRESH, 0, 1, SET, True, "dead"),
    (FRESH, 1, 1, UNSET, True, "alive"),
    (FRESH, 1, 1, SET, True, "alive"),
    # A snapshot over a minute old is not in the world: the save speaks, and
    # only through the ghost flag.
    (STALE, 0, 300, UNSET, False, None),
    (STALE, 0, 300, SET, False, "ghost"),
    (STALE, 1, 300, UNSET, False, None),
    (STALE, 1, 300, SET, False, "ghost"),
    (STALE, 300, 300, UNSET, False, None),
    (STALE, 300, 300, SET, False, "ghost"),
    (STALE, 0, 1, UNSET, False, None),
    (STALE, 0, 1, SET, False, "ghost"),
    (STALE, 1, 1, UNSET, False, None),
    (STALE, 1, 1, SET, False, "ghost"),
    # No snapshot row at all.
    (None, None, None, UNSET, False, None),
    (None, None, None, SET, False, "ghost"),
]


class OneReading(unittest.TestCase):
    def test_the_case_table(self):
        snaps, flags, want = {}, {}, {}
        for i, (age, health, max_health, flag, online, life) in enumerate(CASES):
            name = "Case%02d" % i
            if age is not None:
                snaps[name] = (age, health, max_health)
            flags[name] = flag
            fresh_at = NOW - age if online else None
            want[name] = {"online": online, "life": life, "fresh_at": fresh_at}
        got = presence.of(World(snaps, flags), sorted(want))
        for name, case in zip(sorted(want), CASES):
            with self.subTest(name=name, case=case):
                self.assertEqual(got[name], want[name])

    def test_a_minute_is_the_edge_of_fresh(self):
        world = World({"Edge": (59, 300, 300), "Over": (60, 300, 300)})
        got = presence.of(world, ["Edge", "Over"])
        self.assertTrue(got["Edge"]["online"])
        self.assertFalse(got["Over"]["online"])

    def test_a_name_nothing_knows_is_offline_with_no_reading(self):
        self.assertEqual(
            presence.of(World(), ["Nobody"]),
            {"Nobody": {"online": False, "life": None, "fresh_at": None}},
        )

    def test_no_names_reads_nothing(self):
        world = World()
        self.assertEqual(presence.of(world, []), {})
        self.assertEqual(world.seen, [])

    def test_the_reads_are_bounded_and_every_name_is_bound(self):
        world = World({"Grug": (FRESH, 9, 9)}, {"Grug": 0, "Ugga": SET})
        presence.of(world, ["Grug", "Ugga"])
        self.assertLessEqual(len(world.seen), 2)
        for sql, params in world.seen:
            self.assertNotIn("Grug", sql)
            self.assertNotIn("Ugga", sql)
            self.assertTrue(
                {"Grug", "Ugga"} >= {p for p in params if isinstance(p, str)}
            )
        # The save is read only for a name the world did not answer for.
        chars = [p for sql, p in world.seen if "FROM characters" in sql]
        self.assertEqual(chars, [("Ugga",)])


# ---- every endpoint asks presence.of and says what it answered -------------------
#
# Each test hands the endpoint a stub reading that contradicts the rows the
# fake database holds (a member online in the save and in a fresh snapshot is
# read as offline, a member nothing says is online is read as online). An
# endpoint that still decided for itself would follow the rows and fail.


def contrary(readings):
    """A stand-in for presence.of that answers `readings` and records the call."""
    calls = []

    def of(cur, names):
        calls.append(list(names))
        nothing = {"online": False, "life": None, "fresh_at": None}
        return {n: readings.get(n, nothing) for n in names}

    return of, calls


def reading(online, life):
    return {"online": online, "life": life, "fresh_at": NOW if online else None}


class EveryEndpointAsks(unittest.TestCase):
    def test_the_roster(self):
        # The rows: Grug fresh at full health, Ugga a fresh ghost, Twinkle saved
        # online with no snapshot.
        stub, calls = contrary(
            {
                "Grug": reading(False, "ghost"),
                "Ugga": reading(True, "alive"),
                "Twinkle": reading(True, "dead"),
            }
        )
        ctx, _log = ctx_for(roster_rules(), server())
        with mock.patch.object(presence, "of", stub):
            code, payload = members.roster({}, ctx)
        self.assertEqual(code, 200)
        by = {m["name"]: (m["online"], m["life"]) for m in payload["members"]}
        self.assertEqual(
            by,
            {
                "Grug": (False, "ghost"),
                "Ugga": (True, "alive"),
                "Twinkle": (True, "dead"),
            },
        )
        self.assertEqual(sorted(calls[0]), ["Grug", "Twinkle", "Ugga"])

    def test_the_guild_page(self):
        class Server:
            recap = types.SimpleNamespace(zone_names=lambda c: {})
            GEO = types.SimpleNamespace(continents={})
            achievements = types.SimpleNamespace(MAP_NAMES={})

        def member(guid, name, online, flags):
            return {
                "guid": guid,
                "name": name,
                "level": 20,
                "class": 1,
                "race": 1,
                "online": online,
                "flags": flags,
                "zone": 12,
            }

        answers = [
            ("FROM guild WHERE name", [{"guildid": 23, "name": "Cave"}]),
            ("UNIX_TIMESTAMP() AS now", [{"now": NOW}]),
            # Grug online in the save, Bonk offline with the ghost flag.
            (
                "FROM characters c JOIN guild_member",
                [
                    member(1, "Grug", 1, 0),
                    member(2, "Bonk", 0, GHOST_FLAG),
                ],
            ),
            (
                "FROM overseer_snapshot",
                [{"name": "Grug", "health": 9, "max_health": 9}],
            ),
            ("GROUP BY killer_name", []),
            ("COUNT(DISTINCT character_name) AS who", [{"n": 0, "who": 0}]),
            ("character_queststatus_rewarded", [{"n": 0, "who": 0}]),
        ]
        stub, calls = contrary(
            {"Grug": reading(False, None), "Bonk": reading(True, "dead")}
        )
        with mock.patch.object(presence, "of", stub):
            code, body = guild.guild({"guild": ["cave"]}, GuildCtx(answers, Server))
        self.assertEqual(code, 200)
        self.assertEqual(body["online"], 1)
        self.assertEqual(
            {m["name"]: (m["online"], m["ghost"]) for m in body["members"]},
            {"Grug": (False, False), "Bonk": (True, True)},
        )
        self.assertEqual(sorted(calls[0]), ["Bonk", "Grug"])

    def test_the_gear_table(self):
        row = {
            "guild_name": "Cave",
            "name": "Og",
            "level": 30,
            "class_id": 1,
            "money": 0,
            "online": 1,
            "dead": 0,
            "talent_spells": None,
            "slot": None,
            "item_level": None,
            "item_name": None,
            "item_entry": None,
            "item_quality": None,
        }

        class Cursor(World):
            def execute(self, sql, params=()):
                self.seen.append((sql, params))
                self.rows = [dict(row)] if "FROM guild g" in sql else []

        class Conn:
            def cursor(self):
                return Cursor()

            def close(self):
                pass

        stub, calls = contrary({"Og": reading(False, "ghost")})
        with (
            mock.patch.object(map_server, "_connect", Conn),
            mock.patch.object(map_server, "_all_roster_names", lambda: ["Og"]),
            mock.patch.object(presence, "of", stub),
        ):
            h = get("/api/guildgear")
        self.assertEqual(h.code, 200)
        (m,) = h.payload["guilds"][0]["members"]
        self.assertEqual(
            (m["presence"], m["online"], m["life"]), ("offline", False, "ghost")
        )
        self.assertEqual(calls, [["Og"]])
        self.assertEqual(guildgear.build([])["guilds"], [])


class TheAppReadsWhatIsServed(unittest.TestCase):
    def test_the_gear_table_states_a_member_from_the_served_reading(self):
        # A member the roster did not list printed the gear row's presence
        # word, which never said ghost. Both rows now carry `online` and
        # `life`, and the state is stateOf's one reading of either.
        src = (HERE / "app" / "views" / "gear.js").read_text(encoding="utf-8")
        self.assertNotIn("m.presence", src)
        self.assertIn("stateOf(r.get(m.name) || m)", src)
        self.assertIn("stateLabel(m._r || m, at)", src)


if __name__ == "__main__":
    unittest.main()
