"""The Lineup tab's gear table, and the game frames it opens for a guildmate.

The operator could not see how the guild's members were geared: the Armory
draws one character at a time and its guild sections are a list of names.
guildgear.py turns one read of every family-guild member's worn items into a
row each; the page draws them as one sortable table, and a row opens the same
frames (bags, bank, guild bank, character, social, quest log) a Watch tile
does. The frames' endpoints now answer for a member of a family guild, and
still for nobody else.
"""

import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildgear  # noqa: E402
import map_server  # noqa: E402  (must follow the pymysql stub)
from tests.test_vclient import FAMILIES, get  # noqa: E402

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent


def worn(name, slot, ilvl, item="", **kw):
    row = {
        "guild_name": "Cave",
        "name": name,
        "level": 35,
        "class_id": 8,
        "money": 99342,
        "online": 1,
        "dead": 0,
        "talent_spells": None,
        "slot": slot,
        "item_level": ilvl,
        "item_name": item or "piece",
        "item_entry": 1000 + (slot or 0),
    }
    row.update(kw)
    return row


class TheRows(unittest.TestCase):
    def test_a_mage_with_no_main_hand_is_flagged_and_sorted_first(self):
        rows = [worn("Mage", s, 20 + s) for s in (3, 4, 7, 9, 10, 11, 14, 16)]
        rows += [worn("Warrior", s, 30, class_id=1) for s in range(19)]
        out = guildgear.members_from_rows(rows)
        self.assertEqual([m["name"] for m in out], ["Mage", "Warrior"])
        mage = out[0]
        # The shirt (slot 3) is cosmetic: 7 of 17 worn, 10 empty.
        self.assertEqual((mage["worn"], mage["of"], mage["empty"]), (7, 17, 10))
        self.assertFalse(mage["weapon"])
        self.assertEqual(mage["flags"], ["no weapon", "10 empty"])
        self.assertIn("main hand", mage["empty_slots"])
        self.assertEqual(mage["weakest"]["slot"], "chest")
        # The entry rides along, so the page's tooltip can read the item.
        self.assertEqual(mage["weakest"]["entry"], 1004)
        self.assertEqual(
            mage["avg_item_level"],
            round(sum(20 + s for s in (4, 7, 9, 10, 11, 14, 16)) / 7, 1),
        )
        self.assertEqual(mage["gold"]["text"], "9g 93s 42c")
        self.assertEqual(mage["class"], "Mage")
        warrior = out[1]
        self.assertTrue(warrior["weapon"])
        self.assertEqual(
            (warrior["worn"], warrior["empty"], warrior["flags"]), (17, 0, [])
        )

    def test_a_flagged_level_thirty_five_sorts_above_a_bare_level_four(self):
        rows = [worn("Low", 15, 2, level=4)]
        rows += [worn("Og", s, 20) for s in (4, 7, 9, 10, 11, 14, 16)]
        out = guildgear.members_from_rows(rows)
        self.assertEqual([m["name"] for m in out], ["Og", "Low"])

    def test_empty_slots_are_flagged_only_from_level_twenty(self):
        low = [worn("Low", 15, 5, level=12)]
        (m,) = guildgear.members_from_rows(low)
        self.assertEqual((m["empty"], m["flags"]), (16, []))

    def test_a_member_wearing_nothing_still_has_a_row_and_death_shows(self):
        rows = [worn("Naked", None, None, dead=1)]
        (m,) = guildgear.members_from_rows(rows)
        self.assertEqual((m["worn"], m["empty"], m["presence"]), (0, 17, "dead"))
        self.assertIsNone(m["weakest"])
        self.assertEqual(m["avg_item_level"], 0.0)

    def test_both_guilds_come_back_in_name_order(self):
        rows = [worn("A", 15, 10), worn("B", 15, 10, guild_name="Bonkers")]
        p = guildgear.build(rows)
        self.assertEqual([g["name"] for g in p["guilds"]], ["Bonkers", "Cave"])
        self.assertEqual(p["slots"], 17)


@mock.patch.object(map_server, "_fetch_family_groups", return_value=FAMILIES)
class TheEndpoints(unittest.TestCase):
    def test_the_gear_table_endpoint(self, _groups):
        rows = [worn("Og", 4, 16)]
        with mock.patch.object(map_server, "_fetch_guild_gear", return_value=rows):
            h = get("/api/guildgear")
        self.assertEqual(h.code, 200)
        self.assertEqual(h.payload["guilds"][0]["members"][0]["name"], "Og")

    def test_a_guildmate_gets_every_frame(self, _groups):
        inv = {"rows": [], "money": 100}
        gb = {"guild": None, "tab_rows": [], "item_rows": []}
        soc = {"family_rows": [], "guild": None, "guild_rows": [], "social_rows": []}
        with (
            mock.patch.object(
                map_server, "_is_family_guildmate", return_value=True
            ) as mate,
            mock.patch.object(map_server, "_fetch_client_inventory", return_value=inv),
            mock.patch.object(map_server, "_fetch_client_guild_bank", return_value=gb),
            mock.patch.object(map_server, "_fetch_client_social", return_value=soc),
            mock.patch.object(map_server, "_fetch_questlog", return_value={}),
            mock.patch.object(
                map_server.questlog,
                "build_questlog",
                return_value={"members": [{"name": "Guildie"}]},
            ),
        ):
            for frame in ("bags", "bank", "guildbank", "social", "quests"):
                h = get("/api/client/%s?name=Guildie" % frame)
                self.assertEqual(h.code, 200, frame)
                self.assertEqual(h.payload["name"], "Guildie")
                self.assertEqual(h.payload["family_key"], "")
            self.assertEqual(
                get("/api/client/quests?name=Guildie").payload["member"],
                {"name": "Guildie"},
            )
            # Checked against every family's names, never trusted.
            self.assertEqual(mate.call_args.args[0], "Guildie")
            self.assertEqual(
                sorted(mate.call_args.args[1]),
                sorted(n for _k, ns in FAMILIES for n in ns),
            )

    def test_a_stranger_still_gets_nothing(self, _groups):
        with (
            mock.patch.object(map_server, "_is_family_guildmate", return_value=False),
            mock.patch.object(map_server, "_fetch_client_inventory") as inv,
        ):
            for frame in ("bags", "quests"):
                self.assertEqual(get("/api/client/%s?name=Stranger" % frame).code, 404)
            inv.assert_not_called()


class ThePage(unittest.TestCase):
    def test_the_read_carries_each_worn_items_entry(self):
        self.assertIn("it.entry AS item_entry", map_server._GUILD_GEAR)


if __name__ == "__main__":
    unittest.main()
