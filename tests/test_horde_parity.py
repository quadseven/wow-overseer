"""Every tab shows the Horde family as fully as the Alliance one (#198).

Two families live on the dev realm: Grug's five (Alliance, guild Cave) and
Zug's five (Horde, guild Bonkers). Most tabs had already learned that. Five
places still read bonds' one family, or one guild, and so drew the Alliance
alone or drew the Horde wrongly:

  * the Armory's standing panel listed Grug's five only;
  * the Eye counted "One family" over Grug's five;
  * the Chronicle's live recap drew a Horde run with the Alliance party;
  * the Trades tab was Cave's alone;
  * the Bags tab's guild bank said "the guild has 1 tab" over two guilds.

This suite holds each fix, plus the two rules the page itself has to keep: no
view names a family or a guild in its own code, and an open tab finds out
when it is an older copy than the server now serves.
"""

import json
import logging
import pathlib
import re
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    _err = types.ModuleType("pymysql.err")

    class _MySQLError(Exception):
        pass

    _err.MySQLError = _MySQLError
    sys.modules["pymysql"].err = _err

import armory  # noqa: E402
import basepath  # noqa: E402
import bonds  # noqa: E402
import eye  # noqa: E402
import map_server  # noqa: E402  (must follow the pymysql stub)
import standing  # noqa: E402
import wealth  # noqa: E402

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SCRIPT = PAGE[PAGE.index("<script>") :]

ALLIANCE = ["Grug", "Bork", "Grog", "Og", "Ugga"]
HORDE = ["Zug", "Oz", "Uzza", "Zork", "Zrog"]
GROUPS = [("Grug", ALLIANCE), ("Zug", HORDE)]
SIDES = [
    {
        "family": "Grug",
        "names": ALLIANCE,
        "faction": "alliance",
        "heading": "Grug's family, Alliance",
    },
    {
        "family": "Zug",
        "names": HORDE,
        "faction": "horde",
        "heading": "Zug's family, Horde",
    },
]


def handler():
    """A Handler with no socket: _send records what would have gone out."""
    h = map_server.Handler.__new__(map_server.Handler)
    h.sent = []
    h._send = lambda code, ctype, body, *a: h.sent.append((code, body))
    return h


def body(h):
    code, raw = h.sent[-1]
    return code, json.loads(raw)


class TheEyeCountsEveryFamily(unittest.TestCase):
    ROWS = [{"name": n, "family": "Grug"} for n in ALLIANCE] + [
        {"name": n, "family": "Zug"} for n in HORDE
    ]

    def test_two_families_are_counted_as_two_and_both_named(self):
        rung = eye.family_tier(self.ROWS)
        self.assertEqual(eye.ON, rung["state"])
        self.assertEqual("2", rung["value"])
        for name in ALLIANCE + HORDE:
            self.assertIn(name, rung["headline"])

    def test_the_strip_counts_both(self):
        payload = eye.build_eye([], self.ROWS, [{"characters": 10}], [{"guilds": 2}])
        strip = {s["label"]: s["value"] for s in payload["strip"]}
        self.assertEqual("2", strip["FAMILIES"])

    def test_one_leader_per_family_is_two_parties_not_a_split(self):
        """Two families behind two leaders used to read as one split family."""
        snap = [
            {"name": "Grug", "group_leader": "Grug"},
            {"name": "Bork", "group_leader": "Grug"},
            {"name": "Zug", "group_leader": "Zug"},
            {"name": "Oz", "group_leader": "Zug"},
        ]
        family_of = {r["name"]: r["family"] for r in self.ROWS}
        rung = eye.party_tier(snap, set(family_of), family_of)
        self.assertEqual(eye.ON, rung["state"])
        self.assertEqual("2", rung["value"])

    def test_a_split_inside_one_family_is_still_a_split(self):
        snap = [
            {"name": "Zug", "group_leader": "Zug"},
            {"name": "Oz", "group_leader": "Oz"},
        ]
        family_of = {r["name"]: r["family"] for r in self.ROWS}
        rung = eye.party_tier(snap, set(family_of), family_of)
        self.assertEqual(eye.PARTIAL, rung["state"])
        self.assertIn("Zug's family", rung["headline"])

    def test_the_fetch_labels_each_row_with_its_family(self):
        cur = mock.MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [{"name": "Grug"}, {"name": "Zug"}]
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        with (
            mock.patch.object(map_server, "_fetch_family_groups", return_value=GROUPS),
            mock.patch.object(map_server, "_connect", return_value=conn),
        ):
            rows = map_server._fetch_eye()["family_rows"]
        self.assertEqual(
            {"Grug": "Grug", "Zug": "Zug"}, {r["name"]: r["family"] for r in rows}
        )


class TheStandingPanelHasASidePerFamily(unittest.TestCase):
    BOOK = standing.StandingBook.load(".")
    TALENTS = armory.TalentBook.load(".")

    def build(self):
        chars = [
            {
                "name": "Grug",
                "level": 60,
                "race": 1,
                "class": 1,
                "activeTalentGroup": 0,
            },
            {"name": "Zug", "level": 25, "race": 2, "class": 1, "activeTalentGroup": 0},
        ]
        return standing.build_standing(
            chars, [], [], [], [], self.BOOK, self.TALENTS, families=GROUPS
        )

    def test_both_families_are_drawn_alliance_first(self):
        p = self.build()
        self.assertEqual(["alliance", "horde"], [s["faction"] for s in p["sides"]])
        self.assertEqual(ALLIANCE + HORDE, [m["name"] for m in p["members"]])

    def test_each_family_has_its_own_gap(self):
        for side in self.build()["sides"]:
            self.assertIn("missing", side["gap"])

    def test_a_horde_member_gets_the_horde_bond(self):
        """bonds.FAMILY is only the driven family; a Horde card had no role."""
        zug = next(m for m in self.build()["members"] if m["name"] == "Zug")
        self.assertEqual(bonds.bond_of("Zug").role, zug["role"])

    def test_the_handler_reads_every_family(self):
        h = handler()
        fetched = {
            "char_rows": [],
            "skill_rows": [],
            "reputation_rows": [],
            "talent_rows": [],
            "spell_rows": [],
        }
        with (
            mock.patch.object(map_server, "_fetch_family_groups", return_value=GROUPS),
            mock.patch.object(
                map_server, "_fetch_standing", return_value=fetched
            ) as fetch,
        ):
            h._standing({})
        fetch.assert_called_once_with(ALLIANCE + HORDE)
        code, p = body(h)
        self.assertEqual(200, code)
        self.assertEqual(2, len(p["sides"]))


class TheRecapIsOnePerFamily(unittest.TestCase):
    def test_each_family_gets_its_own_recap_and_the_live_one_leads(self):
        def recap_for(_map, names):
            return {"live": names == HORDE, "headline": names[0], "board": {}}

        h = handler()
        with (
            mock.patch.object(map_server, "_faction_sides", return_value=SIDES),
            mock.patch.object(
                map_server.Handler, "_recap_for", staticmethod(recap_for)
            ),
        ):
            h._recap({})
        code, p = body(h)
        self.assertEqual(200, code)
        self.assertEqual(["Grug", "Zug"], [f["family"] for f in p["families"]])
        self.assertEqual("Zug", p["family"])
        self.assertEqual("Zug's family, Horde", p["families"][1]["heading"])

    def test_the_runs_are_the_ones_the_family_led(self):
        """Unfiltered, a Horde run was drawn with the Alliance party."""
        at = datetime(2026, 9, 23, 12, 0)
        runs = [
            {
                "id": 2,
                "leader_name": "Zug",
                "map_id": 389,
                "state": "ended",
                "started_at": at,
                "ended_at": at,
            },
            {
                "id": 1,
                "leader_name": "Grug",
                "map_id": 43,
                "state": "ended",
                "started_at": at,
                "ended_at": at,
            },
        ]

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                self.sql = sql

            def fetchall(self):
                return list(runs) if "overseer_dungeon_run" in self.sql else []

        conn = mock.MagicMock()
        conn.cursor.return_value = Cur()
        with mock.patch.object(map_server, "_connect", return_value=conn):
            fetched = map_server._fetch_recap(None, HORDE)
        self.assertEqual([2], [r["id"] for r in fetched["run_rows"]])


class TheTradesTabHasAGuildPerFamily(unittest.TestCase):
    def test_each_family_is_built_from_its_own_rows_alliance_first(self):
        seen = []

        def build(**kw):
            seen.append(
                (kw["roster"], [r["name"] for r in kw["roster_rows"]], kw["guild_rows"])
            )
            return {"line": kw["roster"][0]}

        per = {
            "Grug": {
                "guild_rows": ["cave"],
                "member_rows": [],
                "skill_rows": [],
                "spell_rows": [],
            },
            "Zug": {
                "guild_rows": ["bonkers"],
                "member_rows": [],
                "skill_rows": [],
                "spell_rows": [],
            },
        }
        fetched = {
            "families": per,
            "craft_rows": [],
            "recipe_rows": [],
            "trainer_rows": [],
            "vendor_rows": [],
            "drop_rows": [],
            "quest_rows": [],
            "roster_read": True,
            "roster_rows": [
                {"name": "Og", "professions": "x"},
                {"name": "Uzza", "professions": "y"},
            ],
        }
        h = handler()
        with (
            mock.patch.object(map_server, "_faction_sides", return_value=SIDES),
            mock.patch.object(map_server, "_fetch_guildcraft", return_value=fetched),
            mock.patch.object(map_server.guildcraft, "build_guildcraft", build),
            mock.patch.object(map_server.tradespec, "build_tradespec", return_value={}),
        ):
            h._trades({})
        code, p = body(h)
        self.assertEqual(200, code)
        self.assertEqual(["Grug", "Zug"], [f["family"] for f in p["families"]])
        self.assertEqual((ALLIANCE, ["Og"], ["cave"]), seen[0])
        self.assertEqual((HORDE, ["Uzza"], ["bonkers"]), seen[1])


class TheGuildBankSpeaksForEachGuild(unittest.TestCase):
    def test_two_guilds_each_say_their_own_tabs(self):
        guild_rows = [
            {"name": "Grug", "guild_id": 23, "guild_name": "Cave"},
            {"name": "Zug", "guild_id": 24, "guild_name": "Bonkers"},
        ]
        tabs = [{"guild_id": 23, "tab_id": 0, "tab_name": "", "item_count": 3}]
        sides = [
            {"guild": "Cave", "faction": "alliance"},
            {"guild": "Bonkers", "faction": "horde"},
        ]
        g = wealth.build_guild_bank(guild_rows, tabs, [], sides)
        self.assertEqual(["Cave", "Bonkers"], [b["guild"] for b in g["by_guild"]])
        self.assertIn(
            "Cave has 1 purchased bank tab holding 3", g["by_guild"][0]["line"]
        )
        self.assertEqual("Bonkers has no purchased bank tab.", g["by_guild"][1]["line"])
        self.assertEqual(
            "The families are in Cave (Alliance) and Bonkers (Horde).", g["lead"]
        )

    def test_one_guild_keeps_the_old_sentence(self):
        guild_rows = [{"name": "Grug", "guild_id": 23, "guild_name": "Cave"}]
        g = wealth.build_guild_bank(guild_rows, [], [])
        self.assertEqual("The family is in Cave.", g["lead"])
        self.assertTrue(g["body"])


class TheLineupPutsTheAllianceFirst(unittest.TestCase):
    def test_a_tie_no_longer_puts_the_horde_guild_first(self):
        rows = [
            {
                "guildid": 24,
                "guild_name": "Bonkers",
                "name": "Zug",
                "class_id": 1,
                "level": 25,
                "race": 2,
            },
            {
                "guildid": 23,
                "guild_name": "Cave",
                "name": "Grug",
                "class_id": 1,
                "level": 60,
                "race": 1,
            },
        ]
        h = handler()
        with mock.patch.object(
            map_server,
            "_fetch_lineup",
            return_value={"roster": ["Grug", "Zug"], "rows": rows},
        ):
            h._lineup({})
        code, p = body(h)
        self.assertEqual(200, code)
        self.assertEqual(["Cave", "Bonkers"], [g["guild"] for g in p["guilds"]])


class AnOpenTabLearnsItIsStale(unittest.TestCase):
    def test_the_page_is_stamped_with_the_version_it_was_served_as(self):
        raw = (HERE / "index.html").read_bytes()
        served = basepath.apply(raw, "/dev")
        self.assertIn(basepath.page_version(raw).encode(), served)
        self.assertNotIn(basepath.PAGE_PLACEHOLDER.encode(), served)

    def test_realm_reports_the_version_the_server_would_serve_now(self):
        h = handler()
        with (
            mock.patch.object(map_server, "_fetch_realm", return_value={}),
            mock.patch.object(map_server.realm, "build_realm", return_value={}),
        ):
            h._realm({})
        _code, p = body(h)
        raw = (HERE / "index.html").read_bytes()
        self.assertEqual(basepath.page_version(raw), p["page"])

    def test_the_page_compares_and_offers_a_reload(self):
        self.assertIn('const PAGE_BUILT = "__OVERSEER_PAGE__";', SCRIPT)
        self.assertIn("checkPage(d.page);", SCRIPT)
        self.assertIn('id="pagestale"', PAGE)


class NoTabHardCodesOneFamily(unittest.TestCase):
    """The page draws whatever families the server sends. A family or guild
    name typed into the script is a view that works for one of them."""

    def test_no_family_member_or_guild_is_named_in_the_script(self):
        names = [n for house in bonds.HOUSES.values() for n in house.members]
        for name in names + ["Cave", "Bonkers", "Alliance", "Horde"]:
            self.assertIsNone(
                re.search(r"[\"']%s[\"']" % re.escape(name), SCRIPT), name
            )

    def test_a_first_guild_is_only_ever_a_switch_default(self):
        """guilds[0] alone is a view of one guild; `|| guilds[0]` is a switch
        that opens on the first and offers the rest."""
        for m in re.finditer(r"guilds\[0\]", SCRIPT):
            before = SCRIPT[max(0, m.start() - 4) : m.start()]
            self.assertEqual("|| ", before[-3:], SCRIPT[m.start() - 80 : m.end()])

    def test_the_two_family_views_draw_every_family_they_are_sent(self):
        for fragment in (
            "for (const side of p.sides) {",  # standing
            "const fams = p.families || [p];",  # recap, loot board, trades
            "for (const f of p.families) dgnfamilies",  # dungeons
            "for (const f of p.families || []) cnfamilies",  # council
            "for (const g of guilds) {",  # lineup
            "for (const g of p.guilds) rrlist",  # raid
        ):
            self.assertIn(fragment, SCRIPT, fragment)

    def test_the_per_family_reads_carry_the_family(self):
        for path in ("/api/needs", "/api/questlog", "/api/agenda"):
            self.assertIn('fetch(u("%s" + familyQuery(' % path, SCRIPT, path)


if __name__ == "__main__":
    unittest.main()
