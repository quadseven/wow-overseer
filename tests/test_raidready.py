"""Raid readiness per guild: what stops the first raid, and what only slows it.

The finding the operator needs is the split between HARD blockers (the raid
cannot happen) and SOFT ones (it would go worse). These tests pin that split
and the two-guild grouping, which is what put the Horde guild on the tab.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import raidready  # noqa: E402
from raidlineup import (DRUID, HUNTER, MAGE, PALADIN, PRIEST,  # noqa: E402
                        ROGUE, SHAMAN, WARLOCK, WARRIOR)

NO_GOALS = {"goals": []}


def _guild(name, guildid, spec, level=60, race=1):
    """Guild rows built by class: spec is [(class_id, count), ...]."""
    rows = []
    for class_id, count in spec:
        for index in range(count):
            rows.append({"name": "%s%d_%d" % (name, class_id, index),
                         "level": level, "class_id": class_id, "race": race,
                         "guildid": guildid, "guild_name": name})
    return rows


FULL = [(WARRIOR, 10), (PRIEST, 12), (PALADIN, 9), (DRUID, 6), (SHAMAN, 6),
        (WARLOCK, 25), (MAGE, 9), (HUNTER, 8), (ROGUE, 6)]


def _card(rows, family_names, *, min_level=50, worn=(), attuned=(),
          goals=NO_GOALS, runnable=True):
    group = raidready.group_guilds(rows, {"Head": family_names})[0]
    portals = (frozenset({raidready.RAID_PORTAL}) if runnable
               else frozenset({"deadmines"}))
    with mock.patch.object(raidready.jobs, "PORTAL_KEYWORDS", portals):
        return raidready.build_guild(group, [], list(worn),
                                     [{"name": n} for n in attuned],
                                     min_level, goals)


class TwoFamiliesAreTwoGuilds(unittest.TestCase):
    def test_each_family_gets_its_own_guild_card_in_family_order(self):
        rows = (_guild("Cave", 23, [(WARRIOR, 2)])
                + _guild("Bonkers", 24, [(PRIEST, 2)], level=10, race=2))
        groups = raidready.group_guilds(rows, {
            "Grug": ["Cave1_0"], "Zug": ["Bonkers5_0"]})
        self.assertEqual([g["guild"] for g in groups], ["Cave", "Bonkers"])
        self.assertEqual(groups[1]["family"], "Zug")
        self.assertEqual(len(groups[1]["rows"]), 2)

    def test_a_family_in_no_guild_is_still_drawn(self):
        groups = raidready.group_guilds([], {"Zug": ["Zug", "Oz"]})
        self.assertEqual(groups[0]["guild"], "")
        self.assertEqual(groups[0]["family_names"], ["Zug", "Oz"])

    def test_the_faction_comes_from_the_races(self):
        self.assertEqual(raidready.faction_of([1, 3, 7]), "Alliance")
        self.assertEqual(raidready.faction_of([2, 5]), "Horde")
        self.assertEqual(raidready.faction_of([1, 2]), "")
        self.assertEqual(raidready.faction_of([]), "")


class HardBlockers(unittest.TestCase):
    def test_a_full_staffed_guild_with_a_raid_portal_is_ready(self):
        rows = _guild("Cave", 23, FULL)
        card = _card(rows, [rows[0]["name"]],
                     attuned=[r["name"] for r in rows],
                     worn=[{"name": r["name"], "slot": 0, "item_level": 60}
                           for r in rows])
        self.assertTrue(card["ready"])
        self.assertEqual(card["blockers"], [])
        self.assertIn("is ready", card["headline"])

    def test_without_a_raid_portal_nothing_can_start_the_raid(self):
        rows = _guild("Cave", 23, FULL)
        card = _card(rows, [rows[0]["name"]], runnable=False)
        self.assertFalse(card["ready"])
        first = card["blockers"][0]
        self.assertEqual(first["tone"], raidready.HARD)
        self.assertIn("cannot take a raid in", first["text"])
        self.assertIn("deadmines", first["text"])

    def test_a_small_guild_is_short_raiders_tanks_and_healers(self):
        rows = _guild("Bonkers", 24, [(WARRIOR, 1), (PRIEST, 1), (MAGE, 1),
                                      (SHAMAN, 1), (DRUID, 1)],
                      level=10, race=2)
        card = _card(rows, [r["name"] for r in rows])
        hard = [b["text"] for b in card["blockers"] if b["tone"] == "hard"]
        self.assertTrue(any("35 raiders short" in t for t in hard), hard)
        self.assertTrue(any("tanks short" in t for t in hard), hard)
        self.assertTrue(any("healers short" in t for t in hard), hard)
        self.assertTrue(any("below level 50" in t for t in hard), hard)
        self.assertIn("(Horde)", card["title"])
        self.assertIn("cannot raid Molten Core yet", card["headline"])

    def test_no_access_row_means_no_level_gate_is_invented(self):
        rows = _guild("Bonkers", 24, FULL, level=10, race=2)
        card = _card(rows, [rows[0]["name"]], min_level=None)
        self.assertFalse(any("the instance's own access row" in b["text"]
                             for b in card["blockers"]))


class SoftBlockersStopNothing(unittest.TestCase):
    def setUp(self):
        self.rows = _guild("Cave", 23, [(WARRIOR, 10), (PRIEST, 12),
                                        (PALADIN, 9), (DRUID, 6), (SHAMAN, 6),
                                        (WARLOCK, 5), (MAGE, 9), (HUNTER, 8),
                                        (ROGUE, 6)], level=58)

    def test_below_the_cap_thin_gear_and_few_warlocks_are_soft(self):
        card = _card(self.rows, [self.rows[0]["name"]],
                     worn=[{"name": r["name"], "slot": 0, "item_level": 40}
                           for r in self.rows],
                     goals={"goals": [{"name": "Healing potions",
                                       "status": "short"}]})
        self.assertTrue(card["ready"], card["blockers"])
        tones = {b["tone"] for b in card["blockers"]}
        self.assertEqual(tones, {raidready.SOFT})
        text = " ".join(b["text"] for b in card["blockers"])
        self.assertIn("below level 60", text)
        self.assertIn("below item level 55", text)
        self.assertIn("summoners short", text)
        self.assertIn("Attunement to the Core", text)
        self.assertIn("healing potions", text)
        self.assertIn("could form its first Molten Core raid today",
                      card["headline"])

    def test_the_shirt_and_tabard_do_not_drag_the_gear_average(self):
        worn = [{"name": "A", "slot": 0, "item_level": 60},
                {"name": "A", "slot": 3, "item_level": 1},
                {"name": "A", "slot": 18, "item_level": 1}]
        self.assertEqual(raidready.worn_item_levels(worn), {"A": 60})


class TheTopLine(unittest.TestCase):
    def test_it_counts_the_guilds_that_could_raid(self):
        self.assertEqual(
            raidready.build_readiness([{"ready": True}, {"ready": False}])["line"],
            "1 of 2 guilds could form its first raid today")
        self.assertIn("no family",
                      raidready.build_readiness([])["line"])

    def test_the_goal_line_states_the_operators_numbers(self):
        line = raidready.build_readiness([])["goal_line"]
        for number in ("40 raiders", "8 groups of 5", "10 on maintenance",
                       "21 warlocks"):
            self.assertIn(number, line)


if __name__ == "__main__":
    unittest.main()
