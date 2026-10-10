"""families.py: who the families are, their guilds, and who the site may
answer about.

Tested through the module's interface (families, names, default, guilds,
may_answer, request) over the in-memory store, and the SQL store against a
fake connection that records every statement, so the binding rule (no value
in the statement text) is pinned where the SQL is written.
"""

import pathlib
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import families  # noqa: E402

GRUG = ["Grug", "Bork", "Ugga"]
ZUG = ["Zug", "Oz"]
GUILDS = {
    "Cave": GRUG + ["Mukk"],
    "Bonkers": ZUG + ["Bigzug"],
    "Argentum": ["Alianora"],
}


def realm(fams=None, guilds=None, fallback=("Grug", "Bork", "Ugga")):
    store = families.MemoryStore(
        {"Grug": GRUG, "Zug": ZUG} if fams is None else fams,
        GUILDS if guilds is None else guilds,
    )
    return families.Families(store, fallback=lambda: list(fallback))


class TheFamilies(unittest.TestCase):
    def test_every_family_the_roster_names_with_the_default_first(self):
        self.assertEqual(realm().families(), {"Grug": GRUG, "Zug": ZUG})
        self.assertEqual(list(realm().families()), ["Grug", "Zug"])

    def test_the_default_is_bonds_leader_even_when_it_sorts_last(self):
        fams = {"Ard": ["Ard"], "Grug": GRUG, "Zug": ZUG}
        self.assertEqual(realm(fams).default(), "Grug")
        self.assertEqual(list(realm(fams).families()), ["Grug", "Ard", "Zug"])

    def test_without_bonds_leader_the_first_alphabetically_is_the_default(self):
        fams = {"Zug": ZUG, "Ard": ["Ard"]}
        self.assertEqual(realm(fams).default(), "Ard")
        self.assertEqual(list(realm(fams).families()), ["Ard", "Zug"])

    def test_names_are_every_family_in_family_order(self):
        self.assertEqual(realm().names(), GRUG + ZUG)

    def test_the_one_fallback_is_bonds_family_keyed_by_its_head(self):
        bare = realm({}, {})
        self.assertEqual(bare.families(), {"Grug": ["Grug", "Bork", "Ugga"]})
        self.assertEqual(bare.default(), "Grug")
        self.assertEqual(bare.names(), ["Grug", "Bork", "Ugga"])

    def test_no_roster_and_no_bonds_is_no_family_at_all(self):
        bare = realm({}, {}, fallback=())
        self.assertEqual(bare.families(), {})
        self.assertEqual(bare.default(), "")
        self.assertEqual(bare.names(), [])
        self.assertEqual(bare.guilds(), [])

    def test_a_caller_cannot_change_the_reading(self):
        r = realm()
        with r.request():
            r.families()["Grug"].append("Intruder")
            r.names().append("Intruder")
            self.assertNotIn("Intruder", r.names())


class TheGuilds(unittest.TestCase):
    def test_each_guild_a_family_plays_in_with_that_family_in_family_order(self):
        self.assertEqual(
            realm().guilds(),
            [{"name": "Cave", "family": "Grug"}, {"name": "Bonkers", "family": "Zug"}],
        )

    def test_a_guild_belongs_to_the_family_with_most_members_in_it(self):
        guilds = {"Cave": ["Grug", "Bork", "Zug"], "Bonkers": ["Oz", "Zug", "Ugga"]}
        self.assertEqual(
            realm(guilds=guilds).guilds(),
            [{"name": "Cave", "family": "Grug"}, {"name": "Bonkers", "family": "Zug"}],
        )

    def test_a_guild_no_family_member_is_in_is_not_a_family_guild(self):
        names = [g["name"] for g in realm().guilds()]
        self.assertNotIn("Argentum", names)


class MayAnswer(unittest.TestCase):
    def test_a_family_member_and_a_family_guild_member(self):
        r = realm()
        for name in ("Grug", "Oz", "Mukk", "Bigzug"):
            self.assertTrue(r.may_answer(name), name)

    def test_anyone_else_is_refused(self):
        r = realm()
        for name in (
            "Alianora",
            "Nobody",
            "",
            "A",
            "Grug1",
            "Grug Bork",
            "x" * 13,
            None,
        ):
            self.assertFalse(r.may_answer(name), name)

    def test_a_name_is_matched_exactly(self):
        self.assertFalse(realm().may_answer("grug"))

    def test_without_any_family_nobody_may_be_answered_about(self):
        bare = realm({}, GUILDS, fallback=())
        self.assertFalse(bare.may_answer("Mukk"))


class OneReadingPerRequest(unittest.TestCase):
    def counting(self):
        store = families.MemoryStore({"Grug": GRUG, "Zug": ZUG}, GUILDS)
        calls = {"roster": 0, "guilds": 0}
        roster, guilds_of = store.roster, store.guilds_of

        def count_roster():
            calls["roster"] += 1
            return roster()

        def count_guilds(names):
            calls["guilds"] += 1
            return guilds_of(names)

        store.roster, store.guilds_of = count_roster, count_guilds
        return families.Families(store, fallback=lambda: []), calls

    def test_inside_a_request_the_roster_and_the_guilds_are_read_once(self):
        r, calls = self.counting()
        with r.request():
            r.families(), r.names(), r.default(), r.guilds()
            r.may_answer("Mukk"), r.may_answer("Alianora")
        self.assertEqual(calls, {"roster": 1, "guilds": 1})

    def test_the_guilds_are_not_read_by_a_request_that_needs_only_names(self):
        r, calls = self.counting()
        with r.request():
            r.names(), r.may_answer("Grug")
        self.assertEqual(calls, {"roster": 1, "guilds": 0})

    def test_each_request_reads_afresh(self):
        r, calls = self.counting()
        with r.request():
            r.names()
        with r.request():
            r.names()
        self.assertEqual(calls["roster"], 2)

    def test_outside_a_request_nothing_is_kept(self):
        r, calls = self.counting()
        r.names()
        r.names()
        self.assertEqual(calls["roster"], 2)

    def test_a_nested_request_shares_the_outer_reading(self):
        r, calls = self.counting()
        with r.request():
            r.names()
            with r.request():
                r.names()
            r.names()
        self.assertEqual(calls["roster"], 1)


class FakeCursor:
    def __init__(self, rules, log):
        self.rules, self.log, self.rows = rules, log, []

    def execute(self, sql, params=()):
        self.log.append((sql, tuple(params)))
        self.rows = []
        for words, rows in self.rules:
            if all(w in sql for w in words):
                self.rows = list(rows)
                return

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, rules, log):
        self.rules, self.log, self.closed = rules, log, 0

    def cursor(self):
        return FakeCursor(self.rules, self.log)

    def close(self):
        self.closed += 1


class TheSqlStore(unittest.TestCase):
    ROSTER = [
        {"name": "Grug", "family": "Grug", "lead": 1},
        {"name": "Bork", "family": "Grug", "lead": 0},
        {"name": "Zug", "family": "Zug", "lead": 1},
    ]
    MEMBERS = [
        {"guildid": 23, "name": "Cave", "member": "Grug"},
        {"guildid": 23, "name": "Cave", "member": "Bork"},
        {"guildid": 24, "name": "Bonkers", "member": "Zug"},
    ]

    def realm(self, member_rows=()):
        log, conns = [], []
        rules = [
            (("FROM overseer_roster",), self.ROSTER),
            (("FROM guild g",), self.MEMBERS),
            (("gm.guildid IN",), list(member_rows)),
        ]

        def connect():
            conns.append(FakeConn(rules, log))
            return conns[-1]

        r = families.Families(families.SqlStore(connect), fallback=lambda: [])
        return r, log, conns

    def test_reads_the_roster_families_and_their_guilds(self):
        r, _log, conns = self.realm()
        self.assertEqual(r.families(), {"Grug": ["Grug", "Bork"], "Zug": ["Zug"]})
        self.assertEqual(
            r.guilds(),
            [{"name": "Cave", "family": "Grug"}, {"name": "Bonkers", "family": "Zug"}],
        )
        self.assertTrue(all(c.closed == 1 for c in conns))

    def test_a_guild_member_is_one_bound_query_against_the_family_guilds(self):
        r, log, _conns = self.realm(member_rows=[{"1": 1}])
        self.assertTrue(r.may_answer("Mukk"))
        sql, params = log[-1]
        self.assertNotIn("Mukk", sql)
        self.assertEqual(params, ("Mukk", 23, 24))

    def test_a_stranger_is_refused_by_the_same_query(self):
        r, _log, _conns = self.realm(member_rows=[])
        self.assertFalse(r.may_answer("Alianora"))

    def test_a_badly_shaped_name_never_reaches_the_database(self):
        r, log, _conns = self.realm(member_rows=[{"1": 1}])
        self.assertFalse(r.may_answer("Robert'); DROP"))
        self.assertFalse(any("guildid IN" in sql for sql, _p in log))

    def test_no_value_is_ever_formatted_into_a_statement(self):
        r, log, _conns = self.realm(member_rows=[])
        r.guilds(), r.may_answer("Alianora")
        for sql, _params in log:
            for name in ("Grug", "Bork", "Zug", "Alianora"):
                self.assertNotIn("'" + name, sql)
                self.assertNotIn(name + ",", sql)


if __name__ == "__main__":
    unittest.main()


# ---- through the map server: /api/realm and the closed set everywhere -------

import map_server  # noqa: E402  (must follow the pymysql stub)
from tests.test_vclient import get  # noqa: E402
from unittest import mock  # noqa: E402

# Every GET that takes a character's name. A stranger (a member of a guild no
# family plays in) must be refused by each one before any realm read.
NAME_ROUTES = (
    "/api/armory/member?name=%s",
    "/api/upgrades?name=%s",
    "/api/client/bags?name=%s",
    "/api/client/bank?name=%s",
    "/api/client/guildbank?name=%s",
    "/api/client/quests?name=%s",
    "/api/v2/classchain?name=%s",
    "/api/v2/activity?name=%s",
    "/api/v2/social?name=%s",
    "/api/v2/training?name=%s",
    "/api/v2/upgrades?name=%s",
    "/api/v2/series?name=%s",
)
GUILD_ROUTES = (
    "/api/v2/guild?guild=%s",
    "/api/v2/chronicle?guild=%s",
    "/api/v2/series?guild=%s",
)


class NoRealmRead(Exception):
    pass


def _no_connect():
    raise NoRealmRead("a refused name opened a connection")


class TheServer(unittest.TestCase):
    def setUp(self):
        err = types.SimpleNamespace(
            MySQLError=NoRealmRead,
            ProgrammingError=NoRealmRead,
            OperationalError=NoRealmRead,
        )
        patches = [
            mock.patch.object(map_server, "FAMILIES", realm()),
            mock.patch.object(map_server, "_connect", _no_connect),
            mock.patch.object(map_server, "pymysql", types.SimpleNamespace(err=err)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_the_realm_read_names_the_families_and_their_guilds(self):
        fetched = {"build_rows": [], "version_rows": [], "realmlist_rows": []}
        with mock.patch.object(map_server, "_fetch_realm", return_value=fetched):
            h = get("/api/realm")
        self.assertEqual(h.code, 200)
        self.assertEqual(
            h.payload["families"],
            [{"key": "Grug", "names": GRUG}, {"key": "Zug", "names": ZUG}],
        )
        self.assertEqual(
            h.payload["guilds"],
            [{"name": "Cave", "family": "Grug"}, {"name": "Bonkers", "family": "Zug"}],
        )
        self.assertIn("realm", h.payload)

    def test_a_failed_families_read_leaves_the_realm_banner_standing(self):
        class Down(OSError):
            pass

        broken = families.Families(families.MemoryStore({}), fallback=lambda: [])
        broken._store.roster = mock.Mock(side_effect=Down("no route"))
        fetched = {"build_rows": [], "version_rows": [], "realmlist_rows": []}
        with (
            mock.patch.object(map_server, "FAMILIES", broken),
            mock.patch.object(map_server, "_fetch_realm", return_value=fetched),
            self.assertLogs(map_server.log, "ERROR"),
        ):
            h = get("/api/realm")
        self.assertEqual(h.code, 200)
        self.assertIsNone(h.payload["families"])
        self.assertIsNone(h.payload["guilds"])

    def test_a_stranger_is_refused_by_every_read_that_takes_a_name(self):
        for route in NAME_ROUTES:
            for stranger in ("Alianora", "Nobody", "Grug'--"):
                h = get(route % stranger)
                self.assertIn(h.code, (400, 404), (route, stranger))
                self.assertNotIn(b"world unreachable", h.sent[-1][2], (route, stranger))

    def test_a_guild_no_family_plays_in_is_refused_by_every_guild_read(self):
        for route in GUILD_ROUTES:
            for guild in ("Argentum", "zzz"):
                h = get(route % guild)
                self.assertEqual(h.code, 404, (route, guild))
                self.assertEqual(
                    h.payload, {"error": "no such guild", "guilds": ["bonkers", "cave"]}
                )

    def test_a_family_guild_member_gets_past_the_gate(self):
        # Past the gate the read opens a connection, which this test refuses:
        # the 503 is the proof the name was let through.
        for route in NAME_ROUTES:
            h = get(route % "Mukk")
            self.assertEqual(h.code, 503, route)
