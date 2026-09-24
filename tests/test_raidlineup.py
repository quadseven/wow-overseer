"""The lineup is a selection, and the things it must never get wrong are the
ones a person would act on: who is benched, and what cannot be staffed at all.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import raidlineup  # noqa: E402
import raidroles  # noqa: E402
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

    def test_a_classic_raid_four_tanks_in_group_one_and_twelve_healers(self):
        first = self.lineup["groups"][0]["members"]
        self.assertEqual([m["role"] for m in first].count("tank"), 4)
        self.assertEqual(first[0]["duty"], raidlineup.MAIN_TANK)
        self.assertEqual([m["duty"] for m in first[1:4]], [raidlineup.OFF_TANK] * 3)
        self.assertEqual(first[4]["class_id"], PRIEST, "a priest shields the tanks")
        healers = [
            m
            for g in self.lineup["groups"]
            for m in g["members"]
            if m["role"] == "healer"
        ]
        self.assertEqual(len(healers), 12)
        for group in self.lineup["groups"]:
            roles = [m["role"] for m in group["members"]]
            self.assertGreaterEqual(roles.count("healer"), 1, group["number"])

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
        """Two warriors and no hybrids cannot fill a raid's four tank places.
        The two missing are the recruiting ask - they must appear, not be
        smoothed away by promoting a mage."""
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=2, PRIEST=12, MAGE=30, WARLOCK=21)
        )
        self.assertEqual(lineup["shortfall"]["tanks"], 2)
        tanks = [
            m for g in lineup["groups"] for m in g["members"] if m["role"] == "tank"
        ]
        self.assertEqual(len(tanks), 2)
        self.assertTrue(all(m["class_id"] in raidlineup.TANKS for m in tanks))

    def test_a_short_roster_keeps_the_groups_after_the_tanks_even(self):
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=8, PRIEST=8, MAGE=8, WARLOCK=21)
        )
        sizes = sorted(len(g["members"]) for g in lineup["groups"][1:])
        self.assertLessEqual(sizes[-1] - sizes[0], 1)
        self.assertGreater(sizes[0], 0, "no group is left empty")

    def test_an_empty_roster_is_empty_groups_and_a_full_shortfall(self):
        lineup = raidlineup.build_lineup([])
        self.assertEqual(lineup["counts"]["raiders"], 0)
        self.assertEqual(lineup["shortfall"]["raiders"], 40)
        self.assertEqual(lineup["surplus"], [])


def _talents(class_id, tree, points=5):
    """A talent_spells string putting `points` single ranks in one tree."""
    book = raidroles._book()
    spells = sorted(
        spell
        for spell, (cid, name, rank) in book.items()
        if cid == class_id and name == tree and rank == 1
    )
    return ",".join(str(s) for s in spells[:points])


def _spec(name, class_id, tree, level=60):
    return dict(_member(name, class_id, level), talent_spells=_talents(class_id, tree))


class RolesComeFromTheTalentTree(unittest.TestCase):
    """Read on the dev realm, 2026-09-24: packing by class put Fury and Arms
    warriors in tank seats, Shadow priests in healer seats and a Restoration
    druid among the damage dealers. The tree decides the role."""

    def setUp(self):
        roster = [
            _spec("Grug", WARRIOR, "Protection"),
            _spec("Fury1", WARRIOR, "Fury"),
            _spec("Fury2", WARRIOR, "Fury"),
            _spec("Arms1", WARRIOR, "Arms"),
            _spec("Prot1", WARRIOR, "Protection"),
            _spec("Holypal", PALADIN, "Protection"),
            _spec("Shadow1", PRIEST, "Shadow"),
            _spec("Shadow2", PRIEST, "Shadow"),
            _spec("Holy1", PRIEST, "Holy"),
            _spec("Disc1", PRIEST, "Discipline"),
            _spec("Tree1", raidlineup.DRUID, "Restoration"),
            _spec("Cat1", raidlineup.DRUID, "Feral Combat"),
            _spec("Enh1", raidlineup.SHAMAN, "Enhancement"),
            _spec("Resto1", raidlineup.SHAMAN, "Restoration"),
        ]
        roster += _roster(ROGUE=4, HUNTER=4, MAGE=6)
        self.lineup = raidlineup.build_lineup(roster, guaranteed=["Grug"])
        self.by_name = {
            m["name"]: m for g in self.lineup["groups"] for m in g["members"]
        }

    def test_tanks_are_the_protection_trees_the_family_head_first(self):
        tanks = [
            m["name"]
            for m in self.lineup["groups"][0]["members"]
            if m["role"] == "tank"
        ]
        self.assertEqual(tanks, ["Grug", "Holypal", "Prot1"] + ["Arms1"])
        self.assertEqual(self.by_name["Grug"]["duty"], raidlineup.MAIN_TANK)
        self.assertEqual(self.by_name["Grug"]["label"], "main tank, Protection")
        self.assertEqual(
            self.by_name["Arms1"]["duty"],
            raidlineup.OFF_TANK,
            "a warrior in a damage tree fills the fourth tank place",
        )

    def test_healers_are_the_healing_trees_and_a_shadow_priest_never_heals(self):
        healers = sorted(n for n, m in self.by_name.items() if m["role"] == "healer")
        self.assertEqual(healers, ["Disc1", "Holy1", "Resto1", "Tree1"])
        self.assertEqual(self.by_name["Shadow1"]["duty"], "caster")
        self.assertEqual(self.lineup["shortfall"]["healers"], 8)

    def test_damage_dealers_are_named_by_kind_and_stand_together(self):
        self.assertEqual(self.by_name["Fury1"]["duty"], "melee")
        self.assertEqual(self.by_name["Enh1"]["duty"], "melee")
        self.assertEqual(self.by_name["Cat1"]["label"], "melee, Feral Combat")
        self.assertEqual(self.by_name["Hunter0"]["duty"], "ranged")
        melee_groups = {
            g["number"]
            for g in self.lineup["groups"]
            for m in g["members"]
            if m["duty"] == "melee"
        }
        caster_groups = {
            g["number"]
            for g in self.lineup["groups"]
            for m in g["members"]
            if m["duty"] == "caster"
        }
        self.assertLess(max(melee_groups), max(caster_groups))

    def test_the_roles_line_says_the_make_up(self):
        line = self.lineup["roles_line"]
        self.assertIn("4 of 4 tanks (Grug the main tank), 4 of 12 healers", line)
        self.assertIn("talent tree", line)
        self.assertEqual(self.lineup["wanted"]["healers"], 12)
        self.assertEqual(self.lineup["composition"]["main tank"], 1)


class TheTreeIsRead(unittest.TestCase):
    def test_the_tree_with_the_most_points(self):
        spells = _talents(WARRIOR, "Protection", 5) + "," + _talents(WARRIOR, "Fury", 2)
        self.assertEqual(raidroles.tree_of(WARRIOR, spells), "Protection")

    def test_a_tie_or_nothing_is_no_tree(self):
        spells = _talents(WARRIOR, "Protection", 2) + "," + _talents(WARRIOR, "Fury", 2)
        self.assertEqual(raidroles.tree_of(WARRIOR, spells), "")
        self.assertEqual(raidroles.tree_of(WARRIOR, None), "")
        self.assertEqual(raidroles.tree_of(WARRIOR, "junk,,"), "")

    def test_another_classes_spells_are_not_counted(self):
        self.assertEqual(raidroles.tree_of(WARRIOR, _talents(PRIEST, "Holy")), "")

    def test_a_single_role_class_needs_no_talents(self):
        self.assertEqual(raidroles.role_of(_member("M", MAGE)), raidroles.CASTER)
        self.assertEqual(raidroles.role_of(_member("P", PALADIN)), raidroles.UNKNOWN)

    def test_every_guild_read_carries_the_talents(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import raidrun

        with open(os.path.join(root, "raidrun.py")) as f:
            self.assertTrue("raidroles.TALENTS_COLUMN" in f.read())
        self.assertIn(raidroles.KEY, raidrun.GUILD_MEMBERS_SQL)
        for name, count in (("map_server.py", 2), ("bridge.py", 2)):
            with open(os.path.join(root, name)) as f:
                self.assertEqual(
                    f.read().count("raidroles.TALENTS_COLUMN"), count, name
                )


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
