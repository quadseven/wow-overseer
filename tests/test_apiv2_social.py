"""GET /api/v2/social: the Social panel's read, back after #717 removed
/api/client/social with the classic page.

The handler runs against the in-memory realm reader and a fake map server, so
the gate (a family guild member, or a 404) and the reads are exercised with no
database. It only ever reads.
"""

import pathlib
import re
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import apiv2  # noqa: E402
import realmread  # noqa: E402
import vclient  # noqa: E402
from apiv2 import social  # noqa: E402
from apiv2._context import Context  # noqa: E402


def server(families, guildmates=()):
    return types.SimpleNamespace(
        _NAME_RE=re.compile(r"^[A-Za-z]{2,12}$"),
        _fetch_family_groups=lambda: list(families.items()),
        _is_family_guildmate=lambda name, names: name in guildmates,
    )


def ctx_for(answers, srv):
    """The handler's context over a reader that knows `answers` and no other
    statement: a renamed read fails here instead of reading as empty."""
    rd = realmread.Memory(answers)
    return Context(read=rd, server=srv), rd.asked


def family_sql(n):
    return social.FAMILY_SQL + "(" + ", ".join(["%s"] * n) + ")"


FAMILY = [
    {"name": "Grug", "level": 43, "class": 1, "race": 1, "online": 1},
    {"name": "Ugga", "level": 39, "class": 5, "race": 1, "online": 0},
]
GUILD = [{"guild_id": 7, "guild_name": "Cave"}]
ROSTER = [
    {
        "name": "Ugga",
        "level": 39,
        "class": 5,
        "race": 1,
        "online": 0,
        "rank": 1,
        "rank_name": "Officer",
    },
    {
        "name": "Grug",
        "level": 43,
        "class": 1,
        "race": 1,
        "online": 1,
        "rank": 0,
        "rank_name": "Guild Master",
    },
]
FRIENDS = [
    {
        "name": "Zug",
        "level": 29,
        "class": 1,
        "race": 2,
        "online": 1,
        "flags": 1,
        "note": "cousin",
    },
    {
        "name": "Pest",
        "level": 9,
        "class": 4,
        "race": 2,
        "online": 0,
        "flags": 2,
        "note": "",
    },
]
RULES = {
    family_sql(2): FAMILY,
    family_sql(1): FAMILY[1:],
    social.GUILD_SQL: GUILD,
    social.ROSTER_SQL: ROSTER,
    social.FRIENDS_SQL: FRIENDS,
}


class TheRoute(unittest.TestCase):
    def test_social_is_a_v2_read(self):
        self.assertIs(apiv2.ROUTES["/api/v2/social"], social.social)

    def test_a_name_off_the_family_guilds_is_a_404_and_reaches_no_sql(self):
        ctx, log = ctx_for(RULES, server({"Grug": ["Grug", "Ugga"]}))
        for name in ("Stranger", "", "x'; DROP", "a" * 20):
            code, payload = social.social({"name": [name]}, ctx)
            self.assertEqual(code, 404, name)
            self.assertEqual(payload, {"error": "not a guild member"})
        self.assertEqual(log, [])

    def test_every_statement_is_a_select(self):
        ctx, log = ctx_for(RULES, server({"Grug": ["Grug", "Ugga"]}))
        social.social({"name": ["Grug"]}, ctx)
        self.assertTrue(log)
        for sql, _params in log:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)


class TheFrame(unittest.TestCase):
    def test_family_guild_and_friends(self):
        ctx, log = ctx_for(RULES, server({"Grug": ["Grug", "Ugga"]}))
        code, p = social.social({"name": ["Grug"]}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(p["family_key"], "Grug")
        self.assertEqual([m["name"] for m in p["family"]["members"]], ["Grug", "Ugga"])
        self.assertEqual(p["family"]["members"][0]["class"], "Warrior")
        self.assertEqual(p["guild"]["name"], "Cave")
        # Online first.
        self.assertEqual([m["name"] for m in p["guild"]["members"]], ["Grug", "Ugga"])
        self.assertEqual((p["guild"]["online"], p["guild"]["total"]), (1, 2))
        self.assertEqual(p["guild"]["members"][0]["rank"], "Guild Master")
        self.assertEqual([f["name"] for f in p["friends"]], ["Zug"])
        self.assertEqual(p["friends"][0]["note"], "cousin")
        self.assertEqual(p["ignored"], ["Pest"])
        # The family's names are bound, one placeholder each.
        fam = [x for x in log if "WHERE name IN" in x[0]][0]
        self.assertEqual(fam[1], ("Grug", "Ugga"))
        self.assertIn("(%s, %s)", fam[0])

    def test_a_guildmate_in_no_family_is_a_family_of_one(self):
        ctx, _log = ctx_for(RULES, server({"Grug": ["Grug"]}, guildmates=("Ugga",)))
        code, p = social.social({"name": ["Ugga"]}, ctx)
        self.assertEqual(code, 200)
        self.assertEqual(p["family_key"], "")
        self.assertEqual([m["name"] for m in p["family"]["members"]], ["Ugga"])

    def test_no_guild_and_no_friends_say_so(self):
        rules = {
            family_sql(1): FAMILY[:1],
            social.GUILD_SQL: [],
            social.FRIENDS_SQL: [],
        }
        ctx, log = ctx_for(rules, server({"Grug": ["Grug"]}))
        code, p = social.social({"name": ["Grug"]}, ctx)
        self.assertEqual(code, 200)
        self.assertIsNone(p["guild"]["name"])
        self.assertEqual(p["guild"]["note"], vclient.NO_GUILD_NOTE)
        self.assertEqual(p["friends_note"], vclient.NO_FRIENDS_NOTE)
        self.assertFalse([x for x in log if x[0] == social.ROSTER_SQL])


if __name__ == "__main__":
    unittest.main()
