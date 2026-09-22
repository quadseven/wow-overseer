"""The lineup is a selection, and the things it must never get wrong are the
ones a person would act on: who is benched, and what cannot be staffed at all.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import raidlineup  # noqa: E402
from raidlineup import (
    MAGE,
    PALADIN,
    PRIEST,  # noqa: E402
    ROGUE,
    WARLOCK,
    WARRIOR,
)


def _member(name, class_id, level=60):
    return {"name": name, "class_id": class_id, "level": level}


def _roster(**counts):
    """A roster built by class, named predictably: Warrior1, Priest2, ..."""
    out = []
    for class_id, how_many in counts.items():
        cid = getattr(raidlineup, class_id)
        for index in range(how_many):
            out.append(_member("%s%d" % (class_id.title(), index), cid))
    return out


class AFullRosterFillsEveryPlace(unittest.TestCase):
    def setUp(self):
        self.lineup = raidlineup.build_lineup(
            _roster(
                WARRIOR=10,
                PRIEST=12,
                PALADIN=9,
                DRUID=6,
                SHAMAN=6,
                WARLOCK=25,
                MAGE=9,
                HUNTER=8,
                ROGUE=6,
            )
        )

    def test_eight_groups_of_five(self):
        self.assertEqual(len(self.lineup["groups"]), 8)
        for group in self.lineup["groups"]:
            self.assertEqual(len(group["members"]), 5, group["number"])

    def test_every_group_has_exactly_one_tank_and_one_healer(self):
        for group in self.lineup["groups"]:
            roles = [m["role"] for m in group["members"]]
            self.assertEqual(roles.count("tank"), 1, group["number"])
            self.assertEqual(roles.count("healer"), 1, group["number"])

    def test_the_corps_is_twenty_one_and_all_warlocks(self):
        corps = self.lineup["summoners"]
        self.assertEqual(len(corps), 21)
        self.assertTrue(all(m["class_id"] == WARLOCK for m in corps))

    def test_nothing_is_short(self):
        self.assertEqual(set(self.lineup["shortfall"].values()), {0})

    def test_a_character_holds_exactly_one_place(self):
        seen = [m["name"] for g in self.lineup["groups"] for m in g["members"]]
        seen += [m["name"] for m in self.lineup["maintenance"]]
        seen += [m["name"] for m in self.lineup["summoners"]]
        seen += [m["name"] for m in self.lineup["surplus"]]
        self.assertEqual(len(seen), len(set(seen)))


class ASummonerCorpsIsOnlyEverWarlocks(unittest.TestCase):
    """The game's rule, not a preference: Ritual of Summoning is warlock-only.
    A roster short of warlocks must report the gap, never paper over it with
    another class, because a mage in the corps would summon nobody."""

    def test_a_five_warlock_guild_reports_sixteen_missing(self):
        lineup = raidlineup.build_lineup(
            _roster(
                WARLOCK=5,
                WARRIOR=10,
                PRIEST=12,
                PALADIN=9,
                DRUID=6,
                SHAMAN=6,
                MAGE=9,
                HUNTER=8,
                ROGUE=6,
            )
        )
        self.assertEqual(len(lineup["summoners"]), 5)
        self.assertEqual(lineup["shortfall"]["summoners"], 16)
        self.assertTrue(all(m["class_id"] == WARLOCK for m in lineup["summoners"]))

    def test_no_warlocks_at_all_is_a_corps_of_none_not_a_crash(self):
        lineup = raidlineup.build_lineup(_roster(WARRIOR=10, PRIEST=12))
        self.assertEqual(lineup["summoners"], [])
        self.assertEqual(lineup["shortfall"]["summoners"], 21)


class TheFamilyIsNeverBenched(unittest.TestCase):
    def test_guaranteed_names_are_placed_even_from_the_back_of_a_crowd(self):
        crowd = _roster(
            WARRIOR=10,
            PRIEST=12,
            PALADIN=9,
            DRUID=6,
            SHAMAN=6,
            WARLOCK=25,
            MAGE=9,
            HUNTER=8,
            ROGUE=6,
        )
        family = [
            _member("Grug", WARRIOR, 60),
            _member("Ugga", PRIEST, 60),
            _member("Og", MAGE, 60),
            _member("Bork", ROGUE, 60),
            _member("Grog", PALADIN, 60),
        ]
        lineup = raidlineup.build_lineup(
            crowd + family, guaranteed=[m["name"] for m in family]
        )
        raiding = {m["name"] for g in lineup["groups"] for m in g["members"]}
        for member in family:
            self.assertIn(member["name"], raiding, member["name"])
        benched = {m["name"] for m in lineup["surplus"]}
        self.assertFalse(benched & {m["name"] for m in family})

    def test_a_guaranteed_warlock_raids_rather_than_joining_the_corps(self):
        """The corps is filled before the raid, so a family warlock would
        otherwise be swallowed by it and never appear in a group."""
        roster = _roster(
            WARLOCK=25,
            WARRIOR=10,
            PRIEST=12,
            PALADIN=9,
            DRUID=6,
            SHAMAN=6,
            MAGE=9,
            HUNTER=8,
            ROGUE=6,
        )
        roster.append(_member("Zrog", WARLOCK, 60))
        lineup = raidlineup.build_lineup(roster, guaranteed=["Zrog"])
        raiding = {m["name"] for g in lineup["groups"] for m in g["members"]}
        self.assertIn("Zrog", raiding)
        self.assertNotIn("Zrog", {m["name"] for m in lineup["summoners"]})


class TheSurplusIsTheKickList(unittest.TestCase):
    """Whoever the lineup cannot place is named, because a person acts on it."""

    def test_a_guild_of_exactly_seventy_one_benches_nobody(self):
        lineup = raidlineup.build_lineup(
            _roster(
                WARLOCK=21,
                WARRIOR=8,
                PRIEST=8,
                PALADIN=6,
                DRUID=4,
                SHAMAN=4,
                MAGE=8,
                HUNTER=7,
                ROGUE=5,
            )
        )
        self.assertEqual(lineup["counts"]["considered"], 71)
        self.assertEqual(lineup["surplus"], [])

    def test_an_oversized_guild_names_every_extra_character(self):
        lineup = raidlineup.build_lineup(
            _roster(
                WARLOCK=25,
                WARRIOR=10,
                PRIEST=12,
                PALADIN=9,
                DRUID=6,
                SHAMAN=6,
                MAGE=9,
                HUNTER=8,
                ROGUE=6,
            )
        )
        self.assertEqual(lineup["counts"]["considered"], 91)
        self.assertEqual(len(lineup["surplus"]), 91 - 71)
        self.assertTrue(all(m.get("name") for m in lineup["surplus"]))


class AThinRosterDegradesHonestly(unittest.TestCase):
    def test_short_on_tanks_reports_it_rather_than_forming_a_tankless_group(self):
        """Two warriors and no hybrids cannot tank eight groups. Six groups go
        without, and the number six is the recruiting ask - it must appear,
        not be smoothed away by promoting a mage."""
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=2, PRIEST=12, MAGE=30, WARLOCK=21)
        )
        self.assertEqual(lineup["shortfall"]["tanks"], 6)
        tanks = [
            m for g in lineup["groups"] for m in g["members"] if m["role"] == "tank"
        ]
        self.assertEqual(len(tanks), 2)
        self.assertTrue(all(m["class_id"] in raidlineup.TANKS for m in tanks))

    def test_dps_are_dealt_round_robin_so_groups_stay_even(self):
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=8, PRIEST=8, MAGE=8, WARLOCK=21)
        )
        sizes = sorted(len(g["members"]) for g in lineup["groups"])
        self.assertLessEqual(sizes[-1] - sizes[0], 1)

    def test_an_empty_roster_is_empty_groups_and_a_full_shortfall(self):
        lineup = raidlineup.build_lineup([])
        self.assertEqual(lineup["counts"]["raiders"], 0)
        self.assertEqual(lineup["shortfall"]["raiders"], 40)
        self.assertEqual(lineup["surplus"], [])


class TheLineupIsStable(unittest.TestCase):
    """Two runs over the same roster must agree, or the kick list under it
    means nothing."""

    def test_the_same_roster_produces_the_same_lineup_twice(self):
        roster = _roster(
            WARLOCK=25,
            WARRIOR=10,
            PRIEST=12,
            PALADIN=9,
            DRUID=6,
            SHAMAN=6,
            MAGE=9,
            HUNTER=8,
            ROGUE=6,
        )
        first = raidlineup.build_lineup(roster, guaranteed=["Warrior0"])
        second = raidlineup.build_lineup(
            list(reversed(roster)), guaranteed=["Warrior0"]
        )
        self.assertEqual(
            [m["name"] for m in first["surplus"]],
            [m["name"] for m in second["surplus"]],
        )


if __name__ == "__main__":
    unittest.main()
