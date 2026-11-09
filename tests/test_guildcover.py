"""A gem or glyph ask is answered by an online guildmate (#1989)."""

import unittest

import craftpleas
import guildcover
import professions
from guildcover import GuildMember


def _guild():
    return [
        GuildMember("Cutty", "Cave", True, {"jewelcrafting": 300}),
        GuildMember("Sleepy", "Cave", False, {"jewelcrafting": 375}),
        GuildMember("Novice", "Cave", True, {"jewelcrafting": 100}),
        GuildMember("Ugga", "Cave", True, {}),
        GuildMember("Rival", "Bonkers", True, {"jewelcrafting": 375}),
        GuildMember("Scribe", "Bonkers", True, {"inscription": 300}),
        GuildMember("Grug", "Bonkers", True, {}),
    ]


class GuildAskTest(unittest.TestCase):
    def test_a_gem_ask_names_the_online_jewelcrafter(self):
        ask = craftpleas.parse_guild_ask("Ugga", "we need a gem")
        self.assertIsNotNone(ask)
        named, line = craftpleas.guild_answer(ask, _guild(), "Cave")
        self.assertEqual(named.crafter, "Cutty")
        self.assertIn("Cutty", line)

    def test_a_glyph_ask_with_no_inscriber_gets_nothing(self):
        ask = craftpleas.parse_guild_ask("Ugga", "we need a glyph")
        _named, line = craftpleas.guild_answer(ask, _guild(), "Cave")
        self.assertEqual(line, "")

    def test_an_offline_holder_is_never_named(self):
        members = [GuildMember("Sleepy", "Cave", False, {"jewelcrafting": 375})]
        ask = craftpleas.parse_guild_ask("Ugga", "we need a gem")
        self.assertEqual(craftpleas.guild_answer(ask, members, "Cave")[1], "")

    def test_only_the_askers_own_guild_is_read(self):
        ask = craftpleas.parse_guild_ask("Ugga", "we need a gem")
        named, _ = craftpleas.guild_answer(ask, _guild(), "Cave")
        self.assertNotEqual(named.crafter, "Rival")
        # Bonkers asks name the Bonkers holder, never a Cave one.
        ask = craftpleas.parse_guild_ask("Grug", "we need a gem")
        named, _ = craftpleas.guild_answer(ask, _guild(), "Bonkers")
        self.assertEqual(named.crafter, "Rival")
        ask = craftpleas.parse_guild_ask("Grug", "we need a glyph")
        named, _ = craftpleas.guild_answer(ask, _guild(), "Bonkers")
        self.assertEqual(named.crafter, "Scribe")

    def test_highest_skill_first(self):
        members = _guild() + [GuildMember("Ace", "Cave", True, {"jewelcrafting": 350})]
        ask = craftpleas.parse_guild_ask("Ugga", "we need a gem")
        self.assertEqual(
            craftpleas.guild_answer(ask, members, "Cave")[0].crafter, "Ace"
        )

    def test_no_guild_means_no_answer(self):
        ask = craftpleas.parse_guild_ask("Ugga", "we need a gem")
        self.assertEqual(craftpleas.guild_answer(ask, _guild(), "")[1], "")

    def test_a_family_trade_is_not_a_guild_ask(self):
        self.assertIsNone(craftpleas.parse_guild_ask("Ugga", "we need a bag"))

    def test_rows_fold_into_members(self):
        rows = [
            {"name": "A", "guild": "Cave", "online": 1, "skill": 755, "value": 300},
            {"name": "A", "guild": "Cave", "online": 1, "skill": 773, "value": 10},
            {"name": "B", "guild": "Cave", "online": 0, "skill": None, "value": None},
        ]
        members = guildcover.members_from_rows(rows)
        self.assertEqual(members[0].skills, {"jewelcrafting": 300, "inscription": 10})
        self.assertFalse(members[1].online)


class CoverageLineTest(unittest.TestCase):
    def _notes(self, cover):
        return " ".join(professions._notes([], cover))

    def test_the_line_names_guild_coverage_per_trade(self):
        counts = guildcover.coverage(_guild(), "Cave", professions.UNASSIGNED)
        self.assertEqual(counts, {"inscription": 0, "jewelcrafting": 2})
        notes = self._notes(counts)
        self.assertIn("jewelcrafting (2 at 260+)", notes)
        self.assertIn("inscription (0 at 260+)", notes)
        self.assertNotIn("Deliberately unassigned", notes)

    def test_no_holder_keeps_the_old_line(self):
        self.assertIn("Deliberately unassigned", self._notes({}))


if __name__ == "__main__":
    unittest.main()
