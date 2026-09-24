"""Which dungeon is worth running next, asserted against the module.

TWO THINGS THIS FILE IS FOR. The first is that the page decides nothing: every
sentence a reader sees is built here, so it has to be readable by a Python
test, and test_dungeon_tab.py asserts the other half - that index.html prints
these strings rather than composing its own.

The second is the honesty. This view ranks twenty dungeons, and a ranked list
is read as a finding whether anybody meant it that way or not. So the cases
below are mostly about what the ranking must NOT claim: that an empty slot has
an item level delta, that five chest pieces are five chests, that a level range
of 0 to 0 is a level range, that two dungeons which scored the same are in an
order, and that a weapon nobody can hold is a gain.

Tickets: infra#3500, mod-overseer#411.
"""

import pathlib
import unittest

import armory
import dungeonplan
import recap

HERE = pathlib.Path(__file__).resolve().parent.parent
MODULE = (HERE / "dungeonplan.py").read_text(encoding="utf-8")

ENTRANCES = {"43": {"map": 1}, "36": {"map": 0}, "329": {"map": 0}, "209": {"map": 1}}
CONTINENTS = {"0": {"name": "Eastern Kingdoms"}, "1": {"name": "Kalimdor"}}


def catalogue(map_id, low=15, high=25, comment="A Dungeon", difficulty=0):
    return {
        "map_id": map_id,
        "difficulty": difficulty,
        "min_level": low,
        "max_level": high,
        "comment": comment,
    }


def encounter(map_id, creature, name="A Boss"):
    return {"map_id": map_id, "creature": creature, "name": name}


def drop(creature, item, name, ilvl, inv=5, cls=4, sub=2, req=1, allow=-1):
    """One creature_loot_template row joined to its item_template row.

    Defaults to a leather chest, which is the least interesting case and so
    the one every test that is about something else should not have to spell.
    """
    return {
        "Entry": creature,
        "Item": item,
        "Chance": 20,
        "GroupId": 0,
        "creature": creature,
        "item_name": name,
        "quality": 3,
        "item_level": ilvl,
        "required_level": req,
        "class": cls,
        "subclass": sub,
        "displayid": None,
        "inventory_type": inv,
        "allowable_class": allow,
    }


def worn(name, slot, item, ilvl, cls=4, sub=2, inv=5):
    return {
        "name": name,
        "slot": slot,
        "entry": 900 + slot,
        "item_name": item,
        "quality": 1,
        "item_level": ilvl,
        "class": cls,
        "subclass": sub,
        "inventory_type": inv,
        "displayid": None,
    }


def skills(name, *ids):
    return [{"name": name, "skill": skill, "value": 1} for skill in ids]


# A rogue in leather who holds daggers, and a warrior in mail who holds
# swords. Neither holds a staff, which is the mod-overseer#411 case.
ROGUE_SKILLS = skills("Ugga", 414, 173)
WARRIOR_SKILLS = skills("Bork", 413, 43, 55)


def build(
    catalogue_rows,
    encounter_rows,
    loot_rows,
    char_rows,
    equipped_rows,
    skill_rows,
    roster=None,
    names=None,
    book=None,
):
    return dungeonplan.build_dungeonplan(
        catalogue_rows=catalogue_rows,
        encounter_rows=encounter_rows,
        loot_rows=loot_rows,
        char_rows=char_rows,
        equipped_rows=equipped_rows,
        skill_rows=skill_rows,
        icons={},
        roster=roster if roster is not None else ["Ugga", "Bork"],
        names=names or {},
        entrances=ENTRANCES,
        continents=CONTINENTS,
        book=book,
    )


def one(payload, name):
    for dungeon in payload["dungeons"]:
        if dungeon["name"] == name:
            return dungeon
    raise AssertionError(
        "no dungeon called %r in %r" % (name, [d["name"] for d in payload["dungeons"]])
    )


def gains_for(dungeon, who):
    for found in dungeon["members"]:
        if found["who"] == who:
            return found
    return None


class TheDungeonListIsTheWorldsAndNotAHandWrittenOne(unittest.TestCase):
    """A hand list is what put a boss in the Chronicle the core does not count
    (infra#3189), and it also cannot follow the family into a dungeon nobody
    remembered to add to it."""

    def base(self, rows):
        return build(
            rows,
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )

    def test_every_catalogue_row_becomes_a_dungeon(self):
        payload = self.base(
            [
                catalogue(43, comment="Wailing Caverns"),
                catalogue(36, comment="The Deadmines"),
            ]
        )
        self.assertEqual(
            {d["name"] for d in payload["dungeons"]},
            {"Wailing Caverns", "The Deadmines"},
        )

    def test_a_map_with_two_difficulty_rows_is_one_dungeon(self):
        """dungeon_access_template is keyed per difficulty, so a map arrives
        twice with two level ranges."""
        payload = self.base(
            [
                catalogue(43, 15, 25, "Wailing Caverns", 0),
                catalogue(43, 70, 80, "Wailing Caverns", 1),
            ]
        )
        self.assertEqual(len(payload["dungeons"]), 1)

    def test_the_lowest_difficulty_row_wins_whole(self):
        """Not the lowest minimum with the highest maximum: that is a span
        neither row states, printed as though the table said it."""
        payload = self.base(
            [
                catalogue(43, 70, 80, "Wailing Caverns", 1),
                catalogue(43, 15, 25, "Wailing Caverns", 0),
            ]
        )
        self.assertIn("level 15 to 25", one(payload, "Wailing Caverns")["level_line"])

    def test_the_sites_own_name_beats_the_tables_comment(self):
        """A second spelling of the same place on one site is a place a reader
        has to work out is the same place."""
        payload = build(
            [catalogue(36, comment="Deadmines (normal)")],
            [],
            [],
            [],
            [],
            [],
            roster=[],
            names={36: "The Deadmines"},
        )
        self.assertEqual(payload["dungeons"][0]["name"], "The Deadmines")

    def test_the_tables_comment_is_the_fallback_and_not_a_map_number(self):
        payload = self.base([catalogue(999, comment="Somewhere New")])
        self.assertEqual(payload["dungeons"][0]["name"], "Somewhere New")

    def test_a_map_with_neither_a_name_nor_a_comment_is_still_listed(self):
        payload = self.base([catalogue(999, comment="")])
        self.assertEqual(payload["dungeons"][0]["name"], "map 999")

    def test_no_catalogue_at_all_says_so_instead_of_drawing_nothing(self):
        payload = self.base([])
        self.assertEqual(payload["dungeons"], [])
        self.assertTrue(payload["empty_note"])
        self.assertIn("no dungeons", payload["line"])


class TheLevelRange(unittest.TestCase):
    def line(self, low, high, levels=(20,)):
        chars = [{"name": "Ugga", "level": levels[0], "class": 4, "map": 1}]
        payload = build(
            [catalogue(43, low, high, "Wailing Caverns")],
            [],
            [],
            chars,
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        return one(payload, "Wailing Caverns")["level_line"]

    def test_a_real_range_is_printed_with_both_numbers(self):
        self.assertIn("level 15 to 25", self.line(15, 25))

    def test_zero_and_zero_is_not_a_range(self):
        """THE TRAP. A row nobody filled in carries 0 in both columns, and
        "for levels 0 to 0" reads as "anybody can go"."""
        line = self.line(0, 0)
        self.assertIn("no level range", line)
        self.assertNotIn("0 to 0", line)

    def test_a_minimum_with_no_maximum_says_which_half_is_missing(self):
        self.assertIn("no maximum", self.line(15, 0))

    def test_a_maximum_with_no_minimum_says_which_half_is_missing(self):
        self.assertIn("no minimum", self.line(0, 25))

    def test_the_familys_own_levels_are_on_the_same_line(self):
        """The range is only context if the thing it is context for is beside
        it. A reader should not have to open another tab to use it."""
        self.assertIn("the family is 20", self.line(15, 25))


class WhoIsTooLowToZoneIn(unittest.TestCase):
    def payload(self, low, levels):
        chars = [
            {"name": name, "level": level, "class": 4, "map": 1}
            for name, level in levels.items()
        ]
        return build(
            [catalogue(43, low, 60, "Wailing Caverns")],
            [],
            [],
            chars,
            [],
            ROGUE_SKILLS + WARRIOR_SKILLS,
            roster=sorted(levels),
        )

    def test_nobody_is_named_when_everybody_is_high_enough(self):
        found = one(self.payload(15, {"Ugga": 20, "Bork": 21}), "Wailing Caverns")
        self.assertEqual(found["entry_line"], "")
        self.assertFalse(found["shut"])

    def test_the_ones_who_are_too_low_are_named(self):
        found = one(self.payload(21, {"Ugga": 20, "Bork": 21}), "Wailing Caverns")
        self.assertIn("Ugga", found["entry_line"])
        self.assertNotIn("Bork", found["entry_line"])
        self.assertFalse(found["shut"], "one of them can still go")

    def test_a_dungeon_nobody_can_enter_is_shut_and_says_so_without_a_count(self):
        """The sentence said "not one of the five" over a family of three,
        because five is what the roster happened to be the day it was written.
        Counting fixed that and broke a smaller thing: "not one of the 1 is
        high enough" on a roster of one. The count is already on the level
        line and in the chip, so the sentence carries none."""
        found = one(self.payload(40, {"Ugga": 20, "Bork": 21}), "Wailing Caverns")
        self.assertTrue(found["shut"])
        self.assertIn("nobody here is high enough", found["entry_line"])
        for hardcoded in ("five", "2", "1"):
            self.assertNotIn(hardcoded, found["entry_line"], hardcoded)

    def test_a_partly_blocked_dungeon_still_names_who_cannot_go(self):
        """Dropping the count must not cost the reader WHO, which is the half
        that decides whether the run can happen four-handed."""
        found = one(self.payload(21, {"Ugga": 20, "Bork": 21}), "Wailing Caverns")
        self.assertIn("Ugga", found["entry_line"])
        self.assertNotIn("Bork", found["entry_line"])

    def test_no_count_on_this_page_reads_as_a_plural_when_it_is_one(self):
        """Every count here comes from a list the world handed over, so every
        one of them can be one: a degraded schema leaves a single readable
        map. "1 dungeons read" appears on the day something is already wrong,
        which is the day the page is read closely."""
        chars = [{"name": "Ugga", "level": 20, "class": 4, "map": 1}]
        payload = build(
            [catalogue(43, comment="Only One")],
            [],
            [],
            chars,
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertIn("1 dungeon read", payload["line"])
        self.assertNotIn("1 dungeons", payload["line"])
        self.assertIn("1 dungeon listed", payload["coverage"])
        self.assertNotIn("1 dungeons", payload["coverage"])

    def test_no_minimum_is_not_read_as_everybody_can_go(self):
        found = one(self.payload(0, {"Ugga": 20}), "Wailing Caverns")
        self.assertEqual(found["entry_line"], "")
        self.assertFalse(found["shut"])


class WhereItsEntranceStands(unittest.TestCase):
    """The crossing is the expensive part for this family, so "is it on the
    continent they are already on" is on the card rather than left to the
    map."""

    def payload(self, maps):
        chars = [
            {"name": name, "level": 20, "class": 4, "map": where}
            for name, where in maps.items()
        ]
        return build(
            [
                catalogue(43, comment="Wailing Caverns"),
                catalogue(36, comment="The Deadmines"),
            ],
            [],
            [],
            chars,
            [],
            ROGUE_SKILLS + WARRIOR_SKILLS,
            roster=sorted(maps),
        )

    def test_a_dungeon_on_their_continent_says_all_of_them_are_on_it(self):
        found = one(self.payload({"Ugga": 1, "Bork": 1}), "Wailing Caverns")
        self.assertIn("Kalimdor", found["where_line"])
        self.assertIn("all 2", found["where_line"])

    def test_a_dungeon_across_the_ocean_says_none_of_them_are(self):
        found = one(self.payload({"Ugga": 1, "Bork": 1}), "The Deadmines")
        self.assertIn("Eastern Kingdoms", found["where_line"])
        self.assertIn("not one of them", found["where_line"])

    def test_a_split_family_is_counted_rather_than_rounded(self):
        found = one(self.payload({"Ugga": 1, "Bork": 0}), "Wailing Caverns")
        self.assertIn("1 of the 2", found["where_line"])

    def test_a_character_inside_an_instance_is_placed_by_its_entrance(self):
        """Map 43 is not a continent and tells a reader nothing about how far
        away anything is. The entrance to it stands on Kalimdor, and that is
        the answer to the question actually being asked."""
        found = one(self.payload({"Ugga": 43, "Bork": 43}), "Wailing Caverns")
        self.assertIn("all 2", found["where_line"])

    def test_an_entrance_nothing_can_place_is_admitted_and_not_guessed(self):
        payload = build(
            [catalogue(777, comment="Nowhere")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertIn("cannot place", one(payload, "Nowhere")["where_line"])


class WhatCountsAsAGain(unittest.TestCase):
    """One definition of "upgrade" on this site, and it is recap.verdict's."""

    def payload(self, loot, equipped, skill_rows=None):
        chars = [
            {"name": "Ugga", "level": 30, "class": 4, "map": 1},
            {"name": "Bork", "level": 30, "class": 1, "map": 1},
        ]
        return build(
            [catalogue(43, comment="Wailing Caverns")],
            [encounter(43, 3654, "Mutanus the Devourer")],
            loot,
            chars,
            equipped,
            ROGUE_SKILLS + WARRIOR_SKILLS if skill_rows is None else skill_rows,
        )

    def test_a_higher_item_level_in_a_worn_slot_is_a_gain(self):
        found = one(
            self.payload(
                [drop(3654, 10, "Better Vest", 44)], [worn("Ugga", 4, "Old Vest", 30)]
            ),
            "Wailing Caverns",
        )
        self.assertIn("Ugga", found["gainers"])
        self.assertEqual(gains_for(found, "Ugga")["gains"][0]["delta"], 14)

    def test_a_lower_item_level_is_not_a_gain(self):
        found = one(
            self.payload(
                [drop(3654, 10, "Worse Vest", 20)], [worn("Ugga", 4, "Old Vest", 30)]
            ),
            "Wailing Caverns",
        )
        self.assertNotIn("Ugga", found["gainers"])

    def test_the_same_item_level_is_not_a_gain(self):
        found = one(
            self.payload(
                [drop(3654, 10, "Same Vest", 30)], [worn("Ugga", 4, "Old Vest", 30)]
            ),
            "Wailing Caverns",
        )
        self.assertNotIn("Ugga", found["gainers"])

    def test_what_it_replaces_is_named_and_so_is_the_boss(self):
        found = one(
            self.payload(
                [drop(3654, 10, "Better Vest", 44)], [worn("Ugga", 4, "Old Vest", 30)]
            ),
            "Wailing Caverns",
        )
        gain = gains_for(found, "Ugga")["gains"][0]
        self.assertEqual(gain["worn"], "Old Vest")
        self.assertEqual(gain["worn_ilvl"], 30)
        self.assertEqual(gain["boss"], "Mutanus the Devourer")
        self.assertIn("Mutanus the Devourer", gain["line"])
        self.assertIn("Old Vest", gain["line"])
        self.assertIn("chest", gain["line"])

    def test_a_staff_is_never_offered_to_a_rogue(self):
        """mod-overseer#411. allowable_class is -1 on a staff, so the ITEM
        restricts nobody; whether a character may hold it is a row in their
        own character_skills and is absent from item_template entirely."""
        staff = drop(3654, 2280, "Kam's Walking Stick", 40, inv=17, cls=2, sub=10)
        found = one(
            self.payload(
                [staff], [worn("Ugga", 15, "Dagger", 5, cls=2, sub=15, inv=13)]
            ),
            "Wailing Caverns",
        )
        self.assertNotIn("Ugga", found["gainers"])

    def test_a_weapon_the_character_does_hold_is_still_offered(self):
        sword = drop(3654, 5195, "Cruel Barb", 41, inv=21, cls=2, sub=7)
        found = one(
            self.payload(
                [sword], [worn("Bork", 15, "Rusty Sword", 20, cls=2, sub=7, inv=21)]
            ),
            "Wailing Caverns",
        )
        self.assertIn("Bork", found["gainers"])

    def test_a_level_they_have_not_reached_is_not_a_gain(self):
        found = one(
            self.payload(
                [drop(3654, 10, "Late Vest", 90, req=60)],
                [worn("Ugga", 4, "Old Vest", 30)],
            ),
            "Wailing Caverns",
        )
        self.assertEqual(found["gainers"], [])

    def test_a_bag_is_not_a_gain_because_it_is_not_worn(self):
        bag = drop(3654, 10, "A Bag", 40, inv=0, cls=1, sub=0)
        found = one(self.payload([bag], []), "Wailing Caverns")
        self.assertEqual(found["gainers"], [])
        self.assertEqual(found["pieces"], 0)

    def test_the_caveat_the_verdict_did_not_check_travels_with_the_drop(self):
        """A two-hander also costs the off hand, and this comparison does not
        price that. Printed beside the piece rather than in a footer twenty
        rows down."""
        axe = drop(3654, 11, "Big Axe", 50, inv=17, cls=2, sub=1)
        found = one(
            self.payload(
                [axe],
                [worn("Bork", 15, "Rusty Sword", 20, cls=2, sub=7, inv=21)],
                skill_rows=WARRIOR_SKILLS + skills("Bork", 172),
            ),
            "Wailing Caverns",
        )
        gain = gains_for(found, "Bork")["gains"][0]
        self.assertTrue([c for c in gain["caveats"] if "off hand" in c])


class AnEmptySlotIsAllGainAndHasNoNumber(unittest.TestCase):
    """recap.verdict calls an empty slot all gain, and it is. It is not a
    DELTA: counting the whole item level of a trinket into a slot nobody has
    filled would rank a dungeon full of trinkets above one with a weapon."""

    def payload(self):
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        # A worn chest so the armour ladder has an answer: a character in
        # nothing graded is UNRANKED rather than EMPTY, which is a different
        # case and test_recap.py's.
        return build(
            [catalogue(43, comment="Wailing Caverns")],
            [encounter(43, 3654)],
            [drop(3654, 12, "A Cloak", 39, inv=16, sub=1)],
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )

    def test_it_counts_toward_who_would_gain(self):
        self.assertIn("Ugga", one(self.payload(), "Wailing Caverns")["gainers"])

    def test_it_does_not_count_toward_the_item_level_total(self):
        self.assertEqual(one(self.payload(), "Wailing Caverns")["total"], 0)

    def test_it_carries_no_delta_rather_than_a_zero(self):
        """A zero would be indistinguishable from a gain of nothing."""
        found = gains_for(one(self.payload(), "Wailing Caverns"), "Ugga")
        self.assertIsNone(found["gains"][0]["delta"])

    def test_the_card_says_why_the_total_does_not_count_it(self):
        found = gains_for(one(self.payload(), "Wailing Caverns"), "Ugga")
        self.assertIn("empty slot", found["delta_note"])
        self.assertIn("not in the total", found["delta_note"])


class OneSlotIsWornOnce(unittest.TestCase):
    """The reason `total` is not a sum over the list. A dungeon dropping five
    chest pieces that each beat what a character wears is five entries and ONE
    chest they can put on."""

    def payload(self):
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        loot = [
            drop(3654, 20, "Vest A", 40),
            drop(3654, 21, "Vest B", 44),
            drop(3654, 22, "Vest C", 42),
        ]
        return build(
            [catalogue(43, comment="Wailing Caverns")],
            [encounter(43, 3654)],
            loot,
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )

    def test_every_piece_is_still_listed(self):
        found = gains_for(one(self.payload(), "Wailing Caverns"), "Ugga")
        self.assertEqual(len(found["gains"]), 3)

    def test_the_total_counts_the_best_one_and_not_the_sum(self):
        self.assertEqual(one(self.payload(), "Wailing Caverns")["total"], 14)

    def test_the_best_is_the_one_the_line_names(self):
        found = gains_for(one(self.payload(), "Wailing Caverns"), "Ugga")
        self.assertEqual(found["best"], 14)
        self.assertIn("3 pieces", found["line"])
        self.assertIn("14 item levels", found["line"])

    def test_two_different_slots_do_both_count(self):
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        loot = [drop(3654, 20, "Vest", 40), drop(3654, 21, "Gloves", 40, inv=10)]
        payload = build(
            [catalogue(43, comment="Wailing Caverns")],
            [encounter(43, 3654)],
            loot,
            chars,
            [
                worn("Ugga", 4, "Old Vest", 30),
                worn("Ugga", 9, "Old Gloves", 30, inv=10),
            ],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertEqual(one(payload, "Wailing Caverns")["total"], 20)


class TheOrderAndWhatItIsAllowedToClaim(unittest.TestCase):
    def payload(self):
        chars = [
            {"name": "Ugga", "level": 30, "class": 4, "map": 1},
            {"name": "Bork", "level": 30, "class": 1, "map": 1},
        ]
        equipped = [
            worn("Ugga", 4, "Old Vest", 30),
            worn("Bork", 4, "Old Mail", 30, sub=3),
        ]
        catalogue_rows = [
            catalogue(43, comment="Two Gainers"),
            catalogue(36, comment="One Big Gainer"),
            catalogue(209, comment="One Small Gainer"),
            catalogue(329, 40, 60, comment="Shut To Them"),
        ]
        encounters = [
            encounter(43, 1),
            encounter(36, 2),
            encounter(209, 3),
            encounter(329, 4),
        ]
        loot = [
            drop(1, 30, "Leather Vest", 34),
            drop(1, 31, "Mail Vest", 34, sub=3),
            drop(2, 32, "Great Leather Vest", 60),
            drop(3, 33, "Slight Leather Vest", 31),
            drop(4, 34, "Shut Leather Vest", 99),
        ]
        return build(
            catalogue_rows,
            encounters,
            loot,
            chars,
            equipped,
            ROGUE_SKILLS + WARRIOR_SKILLS,
        )

    def test_more_people_gaining_outranks_a_bigger_gain(self):
        """The headline question is where to take the FAMILY, so two people
        gaining four is above one gaining thirty."""
        order = [d["name"] for d in self.payload()["dungeons"]]
        self.assertLess(order.index("Two Gainers"), order.index("One Big Gainer"))

    def test_item_levels_break_a_tie_on_the_count(self):
        order = [d["name"] for d in self.payload()["dungeons"]]
        self.assertLess(order.index("One Big Gainer"), order.index("One Small Gainer"))

    def test_a_dungeon_nobody_can_enter_is_last_whatever_it_holds(self):
        """It holds the best piece on the page and they cannot get in."""
        self.assertEqual(self.payload()["dungeons"][-1]["name"], "Shut To Them")

    def test_the_rank_is_the_modules_and_starts_at_one(self):
        ranks = [d["rank"] for d in self.payload()["dungeons"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_a_tie_is_reported_as_a_tie_on_both_of_them(self):
        """A ranked list invents an order where there is none, and the one
        printed on top reads as the better answer."""
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        payload = build(
            [catalogue(43, comment="Alpha"), catalogue(36, comment="Beta")],
            [encounter(43, 1), encounter(36, 2)],
            [drop(1, 40, "Vest One", 40), drop(2, 41, "Vest Two", 40)],
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertIn("Beta", one(payload, "Alpha")["tie_line"])
        self.assertIn("Alpha", one(payload, "Beta")["tie_line"])

    def test_a_dungeon_with_nothing_in_it_is_not_tied_with_anything(self):
        """Fifteen empty dungeons each printing a fourteen-name tie line is
        noise standing where a finding should be, and it is also not what
        tied means."""
        for dungeon in self.payload()["dungeons"]:
            if not dungeon["gainers"]:
                self.assertEqual(dungeon["tie_line"], "", dungeon["name"])

    def test_the_rule_it_ranked_by_is_on_the_payload(self):
        order = self.payload()["order"]
        for said in ("how many", "item level", "name", "tie"):
            self.assertIn(said, order, said)


class WhatTheHeadlineMayNotSay(unittest.TestCase):
    def test_no_loot_at_all_is_a_different_answer_from_nothing_better(self):
        """A dungeon whose bosses are all summoned rather than spawned comes
        back with no loot, and saying its drops lost a comparison that never
        ran is the page asserting something nothing here checked."""
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        payload = build(
            [catalogue(43, comment="Empty")],
            [],
            [],
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        line = one(payload, "Empty")["line"]
        self.assertIn("no boss loot", line)
        self.assertNotIn("beats what", line)

    def test_loot_that_beats_nothing_says_that_instead(self):
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        payload = build(
            [catalogue(43, comment="Poor")],
            [encounter(43, 1)],
            [drop(1, 50, "Rag", 5)],
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertIn("beats what", one(payload, "Poor")["line"])

    def test_everybody_gaining_is_counted_and_named(self):
        chars = [
            {"name": "Ugga", "level": 30, "class": 4, "map": 1},
            {"name": "Bork", "level": 30, "class": 1, "map": 1},
        ]
        payload = build(
            [catalogue(43, comment="Good")],
            [encounter(43, 1)],
            [drop(1, 50, "Cloak", 39, inv=16, sub=1)],
            chars,
            [worn("Ugga", 4, "Old Vest", 30), worn("Bork", 4, "Old Mail", 30, sub=3)],
            ROGUE_SKILLS + WARRIOR_SKILLS,
        )
        line = one(payload, "Good")["line"]
        self.assertIn("all 2", line)
        self.assertIn("Ugga", line)
        self.assertIn("Bork", line)

    def test_the_top_line_counts_dungeons_and_recommends_nothing(self):
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        payload = build(
            [catalogue(43, comment="Good"), catalogue(36, comment="Empty")],
            [encounter(43, 1)],
            [drop(1, 50, "Cloak", 39, inv=16, sub=1)],
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertIn("2 dungeons read", payload["line"])
        self.assertIn("1 of them holds", payload["line"])
        for invented in ("should", "best", "go to", "recommend"):
            self.assertNotIn(invented, payload["line"], invented)

    def test_the_family_line_says_who_was_compared_and_where_they_stand(self):
        """Every distance on every card is measured from this, so a reader who
        disagrees with one has to be able to see what it was measured from."""
        chars = [
            {"name": "Ugga", "level": 30, "class": 4, "map": 1},
            {"name": "Bork", "level": 28, "class": 1, "map": 0},
        ]
        payload = build([], [], [], chars, [], ROGUE_SKILLS + WARRIOR_SKILLS)
        self.assertIn("Ugga 30", payload["family_line"])
        self.assertIn("Bork 28", payload["family_line"])
        self.assertIn("Kalimdor", payload["family_line"])
        self.assertIn("Eastern Kingdoms", payload["family_line"])


class TheChipsThatSurviveBeingCollapsed(unittest.TestCase):
    """The list is twenty rows on a phone and a reader is not going to open
    every one. These are cut in the module: a page trimming the level sentence
    to chip length would be writing the short version itself."""

    def chips(self, dungeon):
        return {chip["text"]: chip["tone"] for chip in dungeon["chips"]}

    def test_the_level_range_and_the_continent_are_always_there(self):
        payload = build(
            [catalogue(43, 15, 25, "Wailing Caverns")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        chips = self.chips(one(payload, "Wailing Caverns"))
        self.assertIn("levels 15 to 25", chips)
        self.assertEqual(chips["Kalimdor"], "up")

    def test_a_continent_none_of_them_are_on_is_toned_as_a_cost(self):
        payload = build(
            [catalogue(36, comment="The Deadmines")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertEqual(
            self.chips(one(payload, "The Deadmines"))["Eastern Kingdoms"], "no"
        )

    def test_a_missing_level_range_is_dashed_rather_than_stated(self):
        payload = build(
            [catalogue(43, 0, 0, "Wailing Caverns")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertEqual(
            self.chips(one(payload, "Wailing Caverns"))["no level range"], "unsure"
        )

    def test_a_shut_dungeon_carries_the_chip_that_says_so(self):
        payload = build(
            [catalogue(329, 40, 60, "Stratholme")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertEqual(
            self.chips(one(payload, "Stratholme"))["too low to enter"], "no"
        )

    def test_the_item_level_chip_is_absent_when_there_is_nothing_to_show(self):
        payload = build(
            [catalogue(43, comment="Wailing Caverns")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertNotIn("0 item levels", self.chips(one(payload, "Wailing Caverns")))

    def test_every_tone_is_one_the_stylesheet_knows(self):
        payload = build(
            [
                catalogue(43, 0, 0, "A"),
                catalogue(36, 40, 60, "B"),
                catalogue(777, 15, 25, "C"),
            ],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        for dungeon in payload["dungeons"]:
            for chip in dungeon["chips"]:
                self.assertIn(chip["tone"], ("", "up", "no", "unsure"), chip["text"])


class TheBasisSaysWhatTheListDoesNotCover(unittest.TestCase):
    """The house rule, and the loot board's own footer is the precedent. A
    list that quietly omits this is one a reader will over-trust."""

    def basis(self, skill_rows):
        return build(
            [catalogue(43, comment="Wailing Caverns")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            skill_rows,
            roster=["Ugga"],
        )["basis"]

    def test_it_names_the_tables_it_read(self):
        basis = self.basis(ROGUE_SKILLS)
        for table in (
            "dungeon_access_template",
            "instance_encounters",
            "creature_loot_template",
        ):
            self.assertIn(table, basis, table)

    def test_it_admits_the_loot_it_does_not_follow(self):
        self.assertIn("reference_loot_template", self.basis(ROGUE_SKILLS))

    def test_it_admits_a_summoned_boss_is_missing(self):
        self.assertIn("summoned", self.basis(ROGUE_SKILLS))

    def test_it_says_item_level_only_and_does_not_dress_it_up(self):
        basis = self.basis(ROGUE_SKILLS)
        self.assertIn("item level only", basis)
        self.assertIn("no stat weighting", basis)

    def test_it_admits_the_three_reasons_to_run_a_dungeon_it_ignores(self):
        """A real run also yields trash drops, a quest reward and reputation,
        and a page that counts only boss loot while answering "what can they
        get there" is read as having counted all of it."""
        basis = self.basis(ROGUE_SKILLS)
        for missing in ("trash", "quest", "reputation"):
            self.assertIn(missing, basis, missing)

    def test_it_says_it_does_not_ask_how_likely_a_drop_is(self):
        """The loot board asks that one dungeon at a time, and this page must
        not be read as having asked it."""
        self.assertIn("likely", self.basis(ROGUE_SKILLS))

    def test_proficiency_read_for_everybody_is_said_so(self):
        self.assertIn("character_skills", self.basis(ROGUE_SKILLS))

    def test_one_unknown_member_keeps_the_warning_for_everybody(self):
        """A board where one character's skills are missing is a board where
        that character's verdicts are the old item-level ones."""
        basis = build(
            [catalogue(43, comment="Wailing Caverns")],
            [],
            [],
            [
                {"name": "Ugga", "level": 20, "class": 4, "map": 1},
                {"name": "Bork", "level": 20, "class": 1, "map": 1},
            ],
            [],
            ROGUE_SKILLS,
        )["basis"]
        self.assertIn("could not be read for every character", basis)

    def test_no_skill_rows_at_all_is_the_same_warning(self):
        self.assertIn("could not be read", self.basis([]))


class ItBorrowsTheVerdictRatherThanKeepingASecondOne(unittest.TestCase):
    """A second definition of "upgrade" on a second page is two answers to one
    question that are free to disagree about the same drop on the same
    evening."""

    def test_the_gain_verdicts_are_the_loot_boards_own_constants(self):
        self.assertEqual(set(dungeonplan.GAIN_VERDICTS), {recap.UPGRADE, recap.EMPTY})

    def test_the_sentence_on_a_gain_is_the_verdicts_own_why(self):
        chars = [{"name": "Ugga", "level": 30, "class": 4, "map": 1}]
        member = recap.family_members(
            chars, [worn("Ugga", 4, "Old Vest", 30)], ["Ugga"], ROGUE_SKILLS
        )[0]
        row = drop(3654, 10, "Better Vest", 44)
        payload = build(
            [catalogue(43, comment="Wailing Caverns")],
            [encounter(43, 3654)],
            [row],
            chars,
            [worn("Ugga", 4, "Old Vest", 30)],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        gain = gains_for(one(payload, "Wailing Caverns"), "Ugga")["gains"][0]
        self.assertIn(recap.verdict(row, member)["why"], gain["line"])


# --- the dungeon they are actually running (infra#3500 review) --------------
#
# THE SAMPLE THAT PROMPTED THIS WAS FIXTURE DATA and it did not contain The
# Stockade, which is the dungeon the family are running a hundred times. That
# was a property of the fixture and not of the pipeline, but "the fixture did
# not have it" is not evidence that the pipeline would, so these trace map 34
# end to end with the real credit creatures and a family at the levels they
# are actually at.
#
# The five credit creatures are the world database's own rather than
# remembered: 1716 Bazil Thredd, 1717 Hamhock, 1663 Dextren Ward, 1666 Kam
# Deepfury, 1696 Targorr the Dread. The item rows are shaped, not real: what
# these prove is that a map survives every stage, and a real drop list would
# make them fail the day the world database changed one.
STOCKADE = 34
STOCKADE_BOSSES = [
    encounter(STOCKADE, 1716, "Bazil Thredd"),
    encounter(STOCKADE, 1717, "Hamhock"),
    encounter(STOCKADE, 1663, "Dextren Ward"),
    encounter(STOCKADE, 1666, "Kam Deepfury"),
    encounter(STOCKADE, 1696, "Targorr the Dread"),
]
STOCKADE_LOOT = [
    drop(1716, 2043, "Brass Knuckles", 33, inv=13, cls=2, sub=13),
    drop(1716, 2044, "Warden Belt", 34, inv=6, sub=2),
    drop(1717, 1986, "Heavy Hammer", 35, inv=17, cls=2, sub=5),
    drop(1663, 2045, "Warden Vest", 36, inv=5, sub=2),
    drop(1666, 2046, "Deepfury Shield", 35, inv=14, sub=6),
    drop(1696, 2047, "Dread Blade", 34, inv=13, cls=2, sub=15),
]
# The roster as the family really is: five names, levels 32 to 38.
STOCKADE_FAMILY = [
    {"name": "Bork", "level": 38, "class": 1, "map": 0},
    {"name": "Grog", "level": 36, "class": 4, "map": 0},
    {"name": "Grug", "level": 35, "class": 3, "map": 0},
    {"name": "Og", "level": 33, "class": 5, "map": 0},
    {"name": "Ugga", "level": 32, "class": 8, "map": 0},
]
STOCKADE_ROSTER = ["Bork", "Grog", "Grug", "Og", "Ugga"]
STOCKADE_WORN = [
    worn("Bork", 4, "Worn Mail", 20, sub=3),
    worn("Bork", 5, "Worn Belt", 20, sub=3, inv=6),
    worn("Grog", 4, "Worn Leather", 21),
    worn("Grug", 4, "Worn Hide", 22),
    worn("Og", 4, "Worn Robe", 19, sub=1, inv=20),
    worn("Ugga", 4, "Worn Vestment", 18, sub=1, inv=20),
]
STOCKADE_SKILLS = (
    skills("Bork", 413, 43, 44, 54, 55, 160, 172, 433)
    + skills("Grog", 414, 173, 43, 44, 473)
    + skills("Grug", 414, 43, 173, 45, 229)
    + skills("Og", 415, 136, 173, 228)
    + skills("Ugga", 415, 136, 173, 228)
)


def stockade(catalogue_rows, encounter_rows=None, loot_rows=None, names=None):
    return build(
        catalogue_rows,
        STOCKADE_BOSSES if encounter_rows is None else encounter_rows,
        STOCKADE_LOOT if loot_rows is None else loot_rows,
        STOCKADE_FAMILY,
        STOCKADE_WORN,
        STOCKADE_SKILLS,
        roster=STOCKADE_ROSTER,
        names={STOCKADE: "The Stockade"} if names is None else names,
    )


class TheDungeonTheyAreActuallyRunning(unittest.TestCase):
    """Map 34 end to end. Each of these fails loudly if a stage of the pipeline
    silently drops a map, which is the one failure that cannot be seen by
    reading the page it produces."""

    def listed(self):
        return stockade([catalogue(STOCKADE, 22, 30, "The Stockade")])

    def test_it_comes_out_of_the_access_table_with_its_gains(self):
        found = one(self.listed(), "The Stockade")
        self.assertEqual(found["bosses"], 5)
        self.assertEqual(found["pieces"], 6)
        self.assertTrue(found["gainers"], "nobody gains from six pieces")

    def test_every_boss_credited_is_one_of_the_five_the_world_names(self):
        found = one(self.listed(), "The Stockade")
        named = {gain["boss"] for m in found["members"] for gain in m["gains"]}
        self.assertTrue(named)
        self.assertLessEqual(
            named,
            {
                "Bazil Thredd",
                "Hamhock",
                "Dextren Ward",
                "Kam Deepfury",
                "Targorr the Dread",
            },
        )

    def test_the_shield_reaches_only_whoever_holds_shields(self):
        """mod-overseer#411 reaching this page. The shield is subclass 6 and
        restricts nobody by class, so only the skill row refuses it, and only
        one of these five carries skill 433."""
        found = one(self.listed(), "The Stockade")
        for member in found["members"]:
            for gain in member["gains"]:
                if gain["name"] == "Deepfury Shield":
                    self.assertEqual(member["who"], "Bork")

    def test_it_survives_when_the_access_table_has_never_heard_of_it(self):
        """THE FAILURE THE UNION EXISTS FOR. Before it, a map the access table
        does not list was absent from this page with no row, no sentence and
        no count, which is indistinguishable from a dungeon holding nothing."""
        found = one(stockade([]), "The Stockade")
        self.assertEqual(found["source"], dungeonplan.SITE_LIST)
        self.assertTrue(found["gainers"])
        self.assertIn("does not list this one", found["source_line"])

    def test_a_row_from_the_access_table_is_not_captioned_as_an_oddity(self):
        found = one(self.listed(), "The Stockade")
        self.assertEqual(found["source"], dungeonplan.ACCESS_TABLE)
        self.assertEqual(found["source_line"], "")

    def test_the_access_tables_row_wins_over_the_site_placeholder(self):
        """The union is a floor and never a ceiling: a real row brings a real
        level range with it and must not be shadowed by the placeholder."""
        self.assertIn(
            "level 22 to 30", one(self.listed(), "The Stockade")["level_line"]
        )

    def test_the_reads_are_told_to_cover_every_map_that_gets_a_row(self):
        """A map added to the page but missing from the bound map list comes
        back with no bosses, and would render "no boss loot" over loot that
        was simply never asked for."""
        self.assertIn(STOCKADE, dungeonplan.map_ids([], {STOCKADE: "The Stockade"}))
        self.assertIn(STOCKADE, dungeonplan.map_ids([catalogue(STOCKADE)], {}))
        self.assertEqual(
            dungeonplan.map_ids([catalogue(STOCKADE)], {STOCKADE: "The Stockade"}),
            [STOCKADE],
        )

    def test_nothing_narrows_the_catalogue_beyond_the_two_lists(self):
        """No level filter, no party-size filter, no continent filter. Every
        map either list names gets a row, and the count is the whole answer to
        "is this list short because the pipeline narrowed it"."""
        rows = [catalogue(m, comment="map %d" % m) for m in (34, 43, 36, 209)]
        payload = build(
            rows,
            [],
            [],
            STOCKADE_FAMILY,
            STOCKADE_WORN,
            STOCKADE_SKILLS,
            roster=STOCKADE_ROSTER,
            names={},
        )
        self.assertEqual({d["map_id"] for d in payload["dungeons"]}, {34, 43, 36, 209})


class AnAbsentDungeonCannotPassForAnEmptyOne(unittest.TestCase):
    """Three states, and the third of them has no row of its own to speak
    from, which is why the count above the list is not decoration."""

    def listed_with_gains(self):
        return stockade([catalogue(STOCKADE, 22, 30, "The Stockade")])

    def listed_but_unreadable(self):
        """In the catalogue, but the encounter table has nothing for it. A
        boss that is summoned rather than spawned is the real case."""
        return stockade(
            [catalogue(STOCKADE, 22, 30, "The Stockade")],
            encounter_rows=[],
            loot_rows=[],
        )

    def nothing_better(self):
        return stockade(
            [catalogue(STOCKADE, 22, 30, "The Stockade")],
            loot_rows=[drop(1716, 2043, "Rag", 3, inv=5)],
        )

    def test_a_dungeon_with_nothing_readable_still_gets_a_row(self):
        found = one(self.listed_but_unreadable(), "The Stockade")
        self.assertEqual(found["pieces"], 0)
        self.assertIn("no boss loot", found["line"])

    def test_that_row_is_not_worded_as_a_comparison_that_ran(self):
        self.assertNotIn(
            "beats what", one(self.listed_but_unreadable(), "The Stockade")["line"]
        )

    def test_the_three_states_do_not_share_a_sentence(self):
        gains = one(self.listed_with_gains(), "The Stockade")["line"]
        unreadable = one(self.listed_but_unreadable(), "The Stockade")["line"]
        poor = one(self.nothing_better(), "The Stockade")["line"]
        self.assertEqual(len({gains, unreadable, poor}), 3)
        self.assertIn("no boss loot", unreadable)
        self.assertIn("beats what", poor)

    def test_the_coverage_line_counts_both_lists_and_what_was_readable(self):
        coverage = self.listed_with_gains()["coverage"]
        self.assertIn("1 dungeon listed", coverage)
        self.assertIn("1 of them had boss loot", coverage)

    def test_the_coverage_line_says_a_map_on_neither_list_cannot_appear(self):
        """The ONLY place a reader can learn that their dungeon was never
        offered, because an absent dungeon has no row to say it from."""
        self.assertIn(
            "does not appear here at all", self.listed_with_gains()["coverage"]
        )

    def test_it_counts_what_the_site_added_separately_from_the_table(self):
        self.assertIn("1 more this site names", stockade([])["coverage"])

    def test_it_does_not_invent_an_addition_when_there_was_none(self):
        self.assertNotIn("more this site names", self.listed_with_gains()["coverage"])

    def test_the_unreadable_one_is_counted_out_of_the_readable_tally(self):
        self.assertIn(
            "0 of them had boss loot", self.listed_but_unreadable()["coverage"]
        )

    def test_the_basis_repeats_the_distinction_under_the_list(self):
        basis = self.listed_with_gains()["basis"]
        self.assertIn("neither list", basis)
        self.assertIn("not the same as", basis)

    def test_an_empty_world_says_so_rather_than_counting_to_zero(self):
        payload = build(
            [],
            [],
            [],
            STOCKADE_FAMILY,
            STOCKADE_WORN,
            STOCKADE_SKILLS,
            roster=STOCKADE_ROSTER,
            names={},
        )
        self.assertEqual(payload["coverage"], "")
        self.assertTrue(payload["empty_note"])


# --- how many people the table's comment happens to mention -----------------
#
# The access table on this realm spans classic through Wrath - 74 distinct
# maps, raids among them - and carries NO player-count column. The only signal
# is inside `comment`, which is free text a person wrote. These strings are
# that realm's own rows, copied rather than invented.
REAL_COMMENTS = {
    229: "Blackrock Spire - Both Lower (LBRS) & Upper (UBRS) - 5/10man",
    309: "Zul'Gurub (ZG) - 20man",
    409: "Molten Core - 40man",
    509: "Ahn'Qiraj Ruins (AQ20) - 20man",
    531: "Ahn'Qiraj Temple (AQ40) - 40man",
    532: "Karazhan - 10man",
    544: "Hellfire Citadel: Magtheridon's Lair - 25man",
}
# Real rows that name no size whatsoever. These are the reason this is never a
# filter: a rule built on the marker would have to decide what these are, and
# any answer it gave would be invented.
UNMARKED_COMMENTS = ("Uldaman", "Scholomance", "Mana Tombs", "The Stockade")


class ThePartySizeIsReadToShowAndNeverToFilter(unittest.TestCase):
    """The table's comment is free text, not a schema. Reading it to add a
    chip is additive and reversible; reading it to narrow the list would drop
    a real dungeon the first time somebody edited a string."""

    def test_it_finds_the_marker_in_every_real_row_that_has_one(self):
        for map_id, comment in REAL_COMMENTS.items():
            self.assertTrue(
                dungeonplan.party_size(comment), "%d: %s" % (map_id, comment)
            )

    def test_it_reports_the_tables_own_words_and_does_not_tidy_them(self):
        """ "5/10man" is both, and a module that turned it into a number would
        be asserting which one."""
        self.assertEqual(dungeonplan.party_size(REAL_COMMENTS[229]), "5/10man")
        self.assertEqual(dungeonplan.party_size(REAL_COMMENTS[409]), "40man")
        self.assertEqual(dungeonplan.party_size(REAL_COMMENTS[544]), "25man")

    def test_a_row_that_names_no_size_gets_no_answer_rather_than_five(self):
        for comment in UNMARKED_COMMENTS:
            self.assertEqual(dungeonplan.party_size(comment), "", comment)

    def test_a_missing_comment_is_not_a_crash_and_not_a_guess(self):
        self.assertEqual(dungeonplan.party_size(None), "")
        self.assertEqual(dungeonplan.party_size(""), "")

    def test_it_does_not_match_a_word_that_merely_ends_in_man(self):
        """The false positive that would put a chip on a dungeon nobody said
        anything about."""
        for near in ("10mana potion", "Human Lair", "Mana Tombs", "Shadowfang Keep"):
            self.assertEqual(dungeonplan.party_size(near), "", near)

    def test_the_marker_reaches_the_chips_beside_the_level_range(self):
        payload = build(
            [catalogue(409, 55, 60, REAL_COMMENTS[409])],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        chips = [c["text"] for c in payload["dungeons"][0]["chips"]]
        self.assertIn("40man", chips)
        self.assertLess(chips.index("levels 55 to 60"), chips.index("40man"))

    def test_the_chip_is_a_fact_and_not_painted_as_a_refusal(self):
        """A 40man marker beside a family of five speaks for itself. Painting
        it as a warning would be this module deciding the one thing it went
        out of its way not to decide."""
        payload = build(
            [catalogue(409, 55, 60, REAL_COMMENTS[409])],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        for chip in payload["dungeons"][0]["chips"]:
            if chip["text"] == "40man":
                self.assertEqual(chip["tone"], "")

    def test_an_unmarked_dungeon_carries_no_chip_at_all(self):
        """Not "unknown size" either: an extra chip on most rows is noise, and
        the footer is where the gap is explained."""
        payload = build(
            [catalogue(34, 22, 30, "The Stockade")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        chips = [c["text"] for c in payload["dungeons"][0]["chips"]]
        self.assertFalse([c for c in chips if "man" in c], chips)

    def test_nothing_is_dropped_from_the_list_on_the_strength_of_a_marker(self):
        """THE WHOLE POINT. A 40man raid stays in the list and explains itself
        through its own chips; it is not filtered out by a rule built on free
        text that several dungeons do not carry."""
        rows = [catalogue(m, 55, 60, c) for m, c in REAL_COMMENTS.items()]
        rows += [catalogue(34, 22, 30, "The Stockade")]
        payload = build(
            rows,
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        # Karazhan (532) and Magtheridon's Lair (544) leave for the classic
        # ruleset, not for their marker: see the test below.
        self.assertEqual(
            {d["map_id"] for d in payload["dungeons"]},
            (set(REAL_COMMENTS) - {532, 544}) | {34},
        )

    def test_only_classic_doors_are_listed(self):
        """The classic ruleset: no Outland, Northrend or rebuilt-for-80 door."""
        rows = [
            catalogue(36, 17, 26, "The Deadmines"),
            catalogue(540, 70, 72, "Hellfire Citadel: The Shattered Halls"),
            catalogue(574, 70, 72, "Utgarde Keep"),
            catalogue(249, 80, 80, "Onyxia's Lair"),
        ]
        payload = build(
            rows,
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        self.assertEqual([d["map_id"] for d in payload["dungeons"]], [36])
        self.assertEqual(
            dungeonplan.map_ids(rows, {533: "Naxxramas", 36: "The Deadmines"}), [36]
        )

    def test_the_footer_says_a_row_without_the_chip_is_not_a_claim(self):
        payload = build(
            [catalogue(34, 22, 30, "The Stockade")],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
        )
        basis = payload["basis"]
        self.assertIn("free text", basis)
        self.assertIn("never to narrow", basis)
        self.assertIn("not a claim", basis)

    def test_a_site_listed_row_has_no_comment_to_read_and_says_nothing(self):
        payload = build(
            [],
            [],
            [],
            [{"name": "Ugga", "level": 20, "class": 4, "map": 1}],
            [],
            ROGUE_SKILLS,
            roster=["Ugga"],
            names={34: "The Stockade"},
        )
        chips = [c["text"] for c in payload["dungeons"][0]["chips"]]
        self.assertFalse([c for c in chips if "man" in c], chips)


# --- the tooltip on a drop nobody holds (infra#3501) ------------------------
#
# #3502 built this for exactly this shape of view: an item no character owns,
# named on a page, that a reader wants to know the stats of. It matters MORE
# here than on the loot board, because this page ranks by item level and says
# in its own footer that it applies no stat weighting. The tooltip is how a
# reader does the weighting the page refuses to do, so it is the thing that
# makes the footer's admission survivable rather than merely honest.
BOOK = armory.ItemBook.load(str(HERE))


def tooltip_loot():
    """A drop carrying the columns _ITEM_TEMPLATE_COLUMNS selects. The armour
    value and the stat pair are what a tooltip has to have something to say
    about; without them template_tooltip has nothing to draw."""
    row = drop(1716, 2044, "Warden Belt", 34, inv=6, sub=2)
    row.update(
        armor=56,
        max_durability=45,
        bonding=1,
        sell_price=900,
        stat_type1=4,
        stat_value1=7,
        stat_type2=7,
        stat_value2=5,
        description="",
        itemset=0,
        block=0,
        delay=0,
        dmg_min1=0,
        dmg_max1=0,
    )
    return [row]


class ADropNobodyHoldsStillShowsItsLines(unittest.TestCase):
    def payload(self, book):
        return build(
            [catalogue(34, 22, 30, "The Stockade")],
            [encounter(34, 1716, "Bazil Thredd")],
            tooltip_loot(),
            STOCKADE_FAMILY,
            STOCKADE_WORN,
            STOCKADE_SKILLS,
            roster=STOCKADE_ROSTER,
            names={34: "The Stockade"},
            book=book,
        )

    def gain(self, book):
        found = one(self.payload(book), "The Stockade")
        self.assertTrue(found["members"], "nobody gained, so nothing to read")
        return found["members"][0]["gains"][0]

    def test_a_gain_carries_the_items_own_lines_when_a_book_is_given(self):
        self.assertIsNotNone(self.gain(BOOK)["tooltip"])

    def test_without_a_book_the_row_still_renders_and_says_nothing(self):
        """The book is the one thing a caller can be missing, and a page that
        broke without it would be a page that breaks on a degraded read."""
        gain = self.gain(None)
        self.assertIsNone(gain["tooltip"])
        self.assertEqual(gain["name"], "Warden Belt")
        self.assertTrue(gain["line"])

    def test_the_tooltip_is_the_armorys_and_not_a_second_one(self):
        """A second tooltip builder is a second opinion about what an item
        says, and the two would disagree the first time either was touched."""
        row = dict(tooltip_loot()[0], entry=2044)
        self.assertEqual(self.gain(BOOK)["tooltip"], armory.template_tooltip(row, BOOK))

    def test_it_is_built_from_our_own_tables_and_not_fetched(self):
        """The page already refuses to let a browser reach an outside CDN for
        the 3D model; a tooltip that needed one would be the part of this view
        that stops working off the tailnet."""
        self.assertNotIn("zamimg", MODULE)
        self.assertNotIn("wowhead.com/widgets", MODULE)


if __name__ == "__main__":
    unittest.main()
