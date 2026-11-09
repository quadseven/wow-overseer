"""Profession name, skill and cap on the Armory, and the guild-wide read.

The Armory could say what a member wears and how they are specced but not what
they craft, so "who makes the flasks, and how close are they" had no data.
A member's card now carries `professions` (name, skill, cap) and
/api/guildprofessions lists every member of every family guild in one read.
Both are read-only: the rows come from character_skills through the same
fetch the rest of the profile uses.

Ticket: quadseven/wow-overseer#2157.
"""

import logging
import pathlib
import sys
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import map_server
    from tests.test_vclient import get, realm_of

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

ALCHEMY, HERBALISM, LANGUAGE = 171, 182, 98
CHAR = {"level": 40, "race": 1, "class": 1, "online": 0, "activeTalentGroup": 0}


def skill(name, skill_id, value, cap):
    return {"name": name, "skill": skill_id, "value": value, "max": cap}


def fetched(names, skill_rows):
    return {
        "equip_event_rows": [],
        "char_rows": [dict(CHAR, name=n) for n in names],
        "equipment_rows": [],
        "talent_rows": [],
        "stats_rows": [],
        "base_rows": [],
        "set_rows": [],
        "skill_rows": skill_rows,
    }


class TheMemberCard(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(map_server, "FAMILIES", realm_of())
        patch.start()
        self.addCleanup(patch.stop)
        self.names = map_server.FAMILIES.names()

    def armory(self, rows):
        with (
            mock.patch.object(
                map_server, "_fetch_armory", return_value=fetched(self.names, rows)
            ),
            mock.patch.object(map_server, "_fetch_guild_sizes", return_value={}),
        ):
            h = get("/api/armory")
        self.assertEqual(h.code, 200)
        return {m["name"]: m for m in h.payload["members"]}

    def test_a_member_with_trades_shows_name_skill_and_cap(self):
        who = self.names[0]
        rows = [
            skill(who, HERBALISM, 150, 225),
            skill(who, ALCHEMY, 75, 150),
        ]
        member = self.armory(rows)[who]
        self.assertEqual(
            member["professions"],
            [
                {"name": "Alchemy", "skill": 75, "cap": 150},
                {"name": "Herbalism", "skill": 150, "cap": 225},
            ],
        )

    def test_a_member_with_none_has_an_empty_list_not_an_error(self):
        members = self.armory([])
        for m in members.values():
            self.assertEqual(m["professions"], [])

    def test_a_skill_that_is_not_a_profession_is_left_out(self):
        who = self.names[0]
        member = self.armory([skill(who, LANGUAGE, 300, 300)])[who]
        self.assertEqual(member["professions"], [])

    def test_one_members_trades_do_not_leak_to_another(self):
        a, b = self.names[:2]
        members = self.armory([skill(a, ALCHEMY, 10, 75)])
        self.assertEqual(len(members[a]["professions"]), 1)
        self.assertEqual(members[b]["professions"], [])


class TheGuildRead(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(
            map_server, "FAMILIES", realm_of(guildmates=["Guildie"])
        )
        patch.start()
        self.addCleanup(patch.stop)

    def read(self, rows):
        with mock.patch.object(
            map_server, "_fetch_guild_professions", return_value=rows
        ):
            h = get("/api/guildprofessions")
        self.assertEqual(h.code, 200)
        return h.payload

    def test_every_member_of_both_guilds_is_listed_trades_or_not(self):
        rows = [
            {
                "guild_name": "Cave",
                "name": "Og",
                "skill": ALCHEMY,
                "value": 5,
                "max": 75,
            },
            {
                "guild_name": "Cave",
                "name": "Bare",
                "skill": None,
                "value": None,
                "max": None,
            },
            {
                "guild_name": "Bonkers",
                "name": "Zed",
                "skill": None,
                "value": None,
                "max": None,
            },
        ]
        guilds = {g["name"]: g for g in self.read(rows)["guilds"]}
        self.assertEqual(sorted(guilds), ["Bonkers", "Cave"])
        cave = {m["name"]: m for m in guilds["Cave"]["members"]}
        self.assertEqual(
            cave["Og"]["professions"], [{"name": "Alchemy", "skill": 5, "cap": 75}]
        )
        self.assertEqual(cave["Bare"]["professions"], [])
        self.assertEqual(guilds["Cave"]["count"], 2)
        self.assertEqual(guilds["Bonkers"]["members"][0]["professions"], [])

    def test_a_trade_is_listed_by_who_holds_it(self):
        rows = [
            {
                "guild_name": "Cave",
                "name": "Og",
                "skill": ALCHEMY,
                "value": 5,
                "max": 75,
            },
            {
                "guild_name": "Cave",
                "name": "Ug",
                "skill": ALCHEMY,
                "value": 60,
                "max": 75,
            },
        ]
        by_trade = self.read(rows)["guilds"][0]["by_profession"]
        self.assertEqual([m["name"] for m in by_trade["Alchemy"]], ["Ug", "Og"])

    def test_the_route_takes_no_name_and_is_read_only(self):
        src = pathlib.Path(HERE / "map_server.py").read_text()
        sql = src[src.index("_GUILD_PROFESSIONS = (") :]
        sql = sql[: sql.index("def _fetch_guild_professions")]
        self.assertTrue(sql.lstrip().split('"')[1].startswith("SELECT"))
        for word in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
            self.assertNotIn(word, sql)
        self.assertNotIn("/api/guildprofessions", map_server.Handler.POST_ROUTES)

    def test_a_failed_read_is_the_shared_503(self):
        with (
            mock.patch.object(
                map_server, "_fetch_guild_professions", side_effect=OSError("down")
            ),
            self.assertLogs(map_server.log, "ERROR"),
        ):
            h = get("/api/guildprofessions")
        self.assertEqual(h.code, 503)


if __name__ == "__main__":
    unittest.main()
