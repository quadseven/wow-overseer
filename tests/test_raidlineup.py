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

    def test_every_group_is_one_tank_one_healer_and_three_damage(self):
        """The operator's raid (2026-09-26): eight perfect groups of five."""
        for group in self.lineup["groups"]:
            seats = [m["seat"] for m in group["members"]]
            self.assertEqual(seats.count("tank"), 1, group["number"])
            self.assertEqual(seats.count("healer"), 1, group["number"])
            self.assertEqual(seats.count("dps"), 3, group["number"])
        first = self.lineup["groups"][0]["members"]
        self.assertEqual(first[0]["duty"], raidlineup.MAIN_TANK)
        self.assertTrue(
            any(m["class_id"] == PRIEST and m["seat"] == "healer" for m in first),
            "a priest shields the main tank",
        )
        others = [m for g in self.lineup["groups"][1:] for m in g["members"]]
        self.assertEqual(
            [m["duty"] for m in others if m["seat"] == "tank"],
            [raidlineup.OFF_TANK] * 7,
        )
        self.assertEqual(self.lineup["wanted"]["tanks"], 8)
        self.assertEqual(self.lineup["wanted"]["healers"], 8)
        self.assertEqual(self.lineup["wanted"]["damage"], 24)

    def test_every_raider_is_given_the_tree_its_seat_needs(self):
        for group in self.lineup["groups"]:
            for m in group["members"]:
                self.assertTrue(m["target_spec"], m["name"])
                self.assertEqual(
                    m["target_tab"], raidroles.tree_tab(m["class_id"], m["target_spec"])
                )
                self.assertTrue(
                    raidroles.fits_seat(m["class_id"], m["target_spec"], m["seat"]),
                    m["name"],
                )
        tanks = [
            m
            for g in self.lineup["groups"]
            for m in g["members"]
            if m["seat"] == "tank"
        ]
        self.assertTrue(all(m["class_id"] in raidlineup.TANKS for m in tanks))
        self.assertIn(
            ("Warrior", "Protection"),
            {(raidlineup.CLASS_NAMES[m["class_id"]], m["target_spec"]) for m in tanks},
        )

    def test_the_group_buffs_are_spread(self):
        """Nine paladins and six shamans reach every group; twelve priests
        every group; six druids six groups."""
        cover = self.lineup["buff_cover"]
        self.assertEqual(cover[raidlineup.BLESSINGS]["groups"], 8)
        self.assertEqual(cover[raidlineup.FORTITUDE]["groups"], 8)
        self.assertEqual(cover[raidlineup.MARK]["groups"], 6)
        for group in self.lineup["groups"]:
            self.assertEqual(
                group["missing_buffs"],
                [b for b in raidlineup.BUFFS if b not in group["buffs"]],
            )

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
        """Two warriors and no hybrids cannot fill eight tank seats. The six
        missing are the recruiting ask - they must appear, not be smoothed
        away by promoting a mage."""
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=2, PRIEST=12, MAGE=30, WARLOCK=21)
        )
        self.assertEqual(lineup["shortfall"]["tanks"], 6)
        self.assertEqual(lineup["gaps"]["tanks"], 6)
        tanks = [
            m for g in lineup["groups"] for m in g["members"] if m["role"] == "tank"
        ]
        self.assertEqual(len(tanks), 2)
        self.assertTrue(all(m["class_id"] in raidlineup.TANKS for m in tanks))
        self.assertEqual(
            lineup["recruit_classes"][:3], [WARRIOR, PALADIN, raidlineup.DRUID]
        )
        self.assertIn("Short 6 tanks", lineup["gap_line"])
        self.assertIn("Recruiting prefers Warrior, Paladin, Druid", lineup["gap_line"])

    def test_a_group_never_takes_a_fourth_damage_dealer_for_a_missing_seat(self):
        """A group without its tank stays a seat short: a dungeon party of
        four damage dealers and a healer is not a party."""
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=2, PRIEST=12, MAGE=30, WARLOCK=21)
        )
        for group in lineup["groups"]:
            seats = [m["seat"] for m in group["members"]]
            self.assertLessEqual(seats.count("dps"), 3, group["number"])
            self.assertLessEqual(seats.count("healer"), 1, group["number"])
        self.assertEqual(lineup["counts"]["raiders"], 2 + 8 + 24)

    def test_hybrids_split_evenly_when_both_seats_are_short(self):
        """Four warriors, four priests and four paladins: the paladins go two
        to tanking and two to healing, so each seat is two short, not four and
        none."""
        lineup = raidlineup.build_lineup(
            _roster(WARRIOR=4, PRIEST=4, PALADIN=4, MAGE=30, WARLOCK=21)
        )
        self.assertEqual(lineup["gaps"]["tanks"], 2)
        self.assertEqual(lineup["gaps"]["healers"], 2)
        self.assertEqual(lineup["recruit_classes"][:2], [PALADIN, raidlineup.DRUID])

    def test_an_empty_roster_is_empty_groups_and_a_full_shortfall(self):
        lineup = raidlineup.build_lineup([])
        self.assertEqual(lineup["counts"]["raiders"], 0)
        self.assertEqual(lineup["shortfall"]["raiders"], 40)
        self.assertEqual(lineup["surplus"], [])
        self.assertEqual(lineup["gaps"], {"tanks": 8, "healers": 8, "damage": 24})


class TheNaturalGuildsFillEveryGroup(unittest.TestCase):
    """The dev realm's two guilds by class, read 2026-09-26. The Horde guild
    holds seven warriors, two paladins, one shaman, seven priests and one
    druid outside its warlocks: every tank and healer seat still fills, a
    paladin taking the eighth tank seat and one a healer's."""

    def test_the_horde_guild_has_no_seat_gap(self):
        roster = _roster(
            WARRIOR=7,
            PALADIN=2,
            HUNTER=9,
            ROGUE=10,
            PRIEST=7,
            SHAMAN=1,
            MAGE=13,
            WARLOCK=21,
            DRUID=1,
        )
        lineup = raidlineup.build_lineup(roster)
        self.assertEqual(lineup["gaps"], {"tanks": 0, "healers": 0, "damage": 0})
        cover = lineup["buff_cover"]
        self.assertEqual(cover[raidlineup.BLESSINGS]["bearers"], 3)
        self.assertEqual(cover[raidlineup.BLESSINGS]["groups"], 3)
        self.assertEqual(
            lineup["recruit_classes"],
            [PALADIN, raidlineup.SHAMAN, PRIEST, raidlineup.DRUID],
        )
        self.assertIn("No seat gap", lineup["gap_line"])

    def test_a_death_knight_is_never_a_recruit(self):
        lineup = raidlineup.build_lineup(_roster(MAGE=40))
        self.assertNotIn(raidlineup.DEATH_KNIGHT, lineup["recruit_classes"])


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


class SeatsComeFromClassesAndTheFamilyKeepsItsTree(unittest.TestCase):
    """The guild bots start again at level 1, so a tree read today is a
    preference: a raider in a tree that fits a seat keeps it, and anyone
    else is planned the tree its seat needs. The family's tree is the
    operator's decision and is never planned a respec."""

    def setUp(self):
        roster = [
            _spec("Grug", WARRIOR, "Protection"),
            _spec("Grog", PALADIN, "Retribution"),
            _spec("Ugga", PRIEST, "Holy"),
            _spec("Fury1", WARRIOR, "Fury"),
            _spec("Prot1", WARRIOR, "Protection"),
            _spec("Shadow1", PRIEST, "Shadow"),
            _spec("Disc1", PRIEST, "Discipline"),
            _spec("Tree1", raidlineup.DRUID, "Restoration"),
            _spec("Bear1", raidlineup.DRUID, "Feral Combat"),
            _spec("Enh1", raidlineup.SHAMAN, "Enhancement"),
        ]
        roster += _roster(WARRIOR=5, PRIEST=4, ROGUE=8, HUNTER=8, MAGE=8)
        self.lineup = raidlineup.build_lineup(
            roster, guaranteed=["Grug", "Grog", "Ugga"]
        )
        self.by_name = {
            m["name"]: m for g in self.lineup["groups"] for m in g["members"]
        }

    def test_the_family_head_is_the_main_tank_in_its_own_tree(self):
        grug = self.by_name["Grug"]
        self.assertEqual(grug["duty"], raidlineup.MAIN_TANK)
        self.assertEqual(grug["label"], "main tank, Protection")
        self.assertFalse(grug["respec"])

    def test_a_family_damage_tree_stays_a_damage_seat(self):
        grog = self.by_name["Grog"]
        self.assertEqual(grog["seat"], "dps")
        self.assertEqual(grog["target_spec"], "Retribution")
        self.assertFalse(grog["respec"])

    def test_a_fitting_tree_is_kept_and_a_bear_tanks(self):
        self.assertEqual(self.by_name["Prot1"]["seat"], "tank")
        self.assertEqual(self.by_name["Bear1"]["seat"], "tank")
        self.assertEqual(self.by_name["Bear1"]["target_spec"], "Feral Combat")
        self.assertEqual(self.by_name["Disc1"]["target_spec"], "Discipline")
        self.assertEqual(self.by_name["Tree1"]["seat"], "healer")

    def test_a_free_tree_is_seated_before_one_that_would_respec(self):
        """Five warriors with no tree fill the tank seats before the Fury
        warrior, who deals damage in the tree it plays."""
        fury = self.by_name["Fury1"]
        self.assertEqual(fury["seat"], "dps")
        self.assertEqual(fury["label"], "melee, Fury")
        for index in range(5):
            self.assertEqual(
                self.by_name["Warrior%d" % index]["target_spec"], "Protection"
            )

    def test_a_seat_that_needs_another_tree_says_so(self):
        """Eight healer seats, seven healing priests and druids: the Shadow
        priest takes the last and is planned Holy."""
        shadow = self.by_name["Shadow1"]
        self.assertEqual(shadow["seat"], "healer")
        self.assertEqual(shadow["target_spec"], "Holy")
        self.assertTrue(shadow["respec"])
        self.assertEqual(shadow["label"], "healer, Holy (now Shadow)")
        self.assertEqual(self.lineup["counts"]["respec"], 1)
        self.assertIn("1 play another tree now", self.lineup["roles_line"])

    def test_the_roles_line_says_the_make_up(self):
        line = self.lineup["roles_line"]
        self.assertIn(
            "8 of 8 tanks (Grug the main tank), 8 of 8 healers, 24 of 24 damage", line
        )
        self.assertIn(
            "8 of 8 groups are a full tank, healer and three damage dealers", line
        )
        self.assertEqual(self.lineup["composition"]["main tank"], 1)


class TheTargetTreeIsTheSeats(unittest.TestCase):
    def test_each_class_has_a_tree_for_each_seat_it_can_take(self):
        self.assertEqual(
            raidroles.target_tree(WARRIOR, raidroles.SEAT_TANK), "Protection"
        )
        self.assertEqual(
            raidroles.target_tree(raidlineup.DEATH_KNIGHT, raidroles.SEAT_TANK), "Blood"
        )
        self.assertEqual(
            raidroles.target_tree(raidlineup.DRUID, raidroles.SEAT_TANK), "Feral Combat"
        )
        self.assertEqual(raidroles.target_tree(PRIEST, raidroles.SEAT_HEALER), "Holy")
        self.assertEqual(
            raidroles.target_tree(raidlineup.SHAMAN, raidroles.SEAT_HEALER),
            "Restoration",
        )
        self.assertEqual(raidroles.target_tree(PRIEST, raidroles.SEAT_DAMAGE), "Shadow")
        self.assertEqual(raidroles.target_tree(MAGE, raidroles.SEAT_TANK), "")
        self.assertFalse(raidroles.can_seat(ROGUE, raidroles.SEAT_HEALER))

    def test_a_tree_that_fits_is_kept(self):
        self.assertEqual(
            raidroles.target_tree(PRIEST, raidroles.SEAT_HEALER, "Discipline"),
            "Discipline",
        )
        self.assertEqual(
            raidroles.target_tree(MAGE, raidroles.SEAT_DAMAGE, "Arcane"), "Arcane"
        )
        self.assertEqual(
            raidroles.target_tree(WARRIOR, raidroles.SEAT_TANK, "Fury"), "Protection"
        )

    def test_the_tab_is_the_talent_frames_order(self):
        self.assertEqual(raidroles.tree_tab(WARRIOR, "Protection"), 2)
        self.assertEqual(raidroles.tree_tab(PRIEST, "Holy"), 1)
        self.assertEqual(raidroles.tree_tab(raidlineup.DRUID, "Feral Combat"), 1)
        self.assertEqual(raidroles.tree_tab(raidlineup.DEATH_KNIGHT, "Blood"), 0)
        self.assertIsNone(raidroles.tree_tab(WARRIOR, "Holy"))


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
        # bridge.py: the dues read, the corps read and the guild jobs' read
        # (#194), each of which builds the same lineup the page draws.
        for name, count in (("map_server.py", 2), ("bridge.py", 3)):
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
