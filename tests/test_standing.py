"""The standing builder: rows in, a readable ledger of what was LEARNED out.

Most of these are rules about NOT LYING, and every one of them describes a
page that would look entirely plausible while being wrong:

  a proficiency compared against a level cap invents a 114-point shortfall
  a reputation read without its base is a whole RANK out
  a faction nobody has met still has a row, so an unfiltered panel is 105
      lines of nothing per character
  a profession rank spell listed under "what they can make" answers the
      question with its own premise
  a trade nobody holds does not appear anywhere in the per-member rows, so
      the one fact worth knowing is the one a per-member view cannot show

Run against the COMMITTED standing.json and talents.json rather than stubs,
deliberately and for the reason test_armory.py gives: the whole point of
those files is that they turn real ids into real names, and a test that
mocked them would pass just as happily with an empty book - which is exactly
the failure mode this service already has, since every `*_dbc` table in the
world database IS empty.

Tickets: quadseven/mod-overseer#88, quadseven/mod-overseer#160.
"""
import json
import pathlib
import unittest

import armory
import family
import goals
import professions
import standing

BOOK = standing.StandingBook.load(".")
TALENTS = armory.TalentBook.load(".")

HERE = pathlib.Path(__file__).resolve().parent.parent

# Taken from bonds rather than retyped, for the reason test_armory.py gives:
# WHO the family is belongs there, and a second list here can disagree.
ROSTER = family.roster()
FIRST = ROSTER[0]

# Real skill ids, from the module that owns them rather than retyped.
ALCHEMY = goals.SKILL_IDS["alchemy"]
HERBALISM = goals.SKILL_IDS["herbalism"]
ENCHANTING = goals.SKILL_IDS["enchanting"]
FIRST_AID = goals.SKILL_IDS["first aid"]
COOKING = goals.SKILL_IDS["cooking"]
FISHING = goals.SKILL_IDS["fishing"]
SWORDS, DEFENCE, CLOTH = 43, 95, 415

# Real factions out of the committed book. Stormwind is the one the family
# has actually worked at; its base rep differs by race, which is the whole
# reason base_reputation exists.
STORMWIND, IRONFORGE = 72, 47

HUMAN, DWARF, GNOME = 1, 3, 7
WARRIOR, PALADIN, ROGUE, PRIEST, MAGE = 1, 2, 4, 5, 8
# Warrior Protection, three ranks; spell 12810 is rank 2 of Puncture, which
# is the difference between counting talents and counting POINTS.
PUNCTURE_R1, PUNCTURE_R2 = 12308, 12810

# The reputation ladder's floors, spelled out here rather than computed, so
# a change to the walk in standing.py has to disagree with a written number
# rather than merely with itself.
NEUTRAL_FLOOR, FRIENDLY_FLOOR, HONORED_FLOOR = 0, 3000, 9000
REVERED_FLOOR, EXALTED_FLOOR = 21000, 42000


def skill(skill_id, value, maximum, name=FIRST):
    return {"name": name, "skill": skill_id, "value": value, "max": maximum}


def rep(faction, value, flags=standing.FLAG_VISIBLE, name=FIRST):
    return {"name": name, "faction": faction, "standing": value, "flags": flags}


def char(name=FIRST, level=27, race=HUMAN, class_id=WARRIOR, group=0):
    return {"name": name, "level": level, "race": race, "class": class_id,
            "activeTalentGroup": group}


class TheWowheadLink(unittest.TestCase):
    def test_it_is_the_one_format_this_service_already_uses(self):
        """achievements.py builds the same link for items. Two spellings of
        one URL is two things to fix when wowhead moves."""
        self.assertEqual(standing.wowhead("skill", 171),
                         "https://www.wowhead.com/wotlk/skill=171")
        self.assertEqual(standing.wowhead("faction", 72),
                         "https://www.wowhead.com/wotlk/faction=72")


class WhichSkillIsATrade(unittest.TestCase):
    def test_the_ids_come_from_the_module_that_owns_them(self):
        """professions/goals already answer 'which number is tailoring'. A
        second table here is a second thing to get wrong."""
        ids = standing.profession_ids()
        self.assertEqual(ids[ALCHEMY], "alchemy")
        self.assertEqual(ids[ENCHANTING], "enchanting")
        self.assertEqual(set(ids.values()),
                         professions.PRIMARY | professions.SECONDARY)

    def test_a_primary_trade_is_grouped_as_one(self):
        self.assertEqual(standing.skill_group(ALCHEMY, standing.CATEGORY_PROFESSION),
                         standing.GROUP_PROFESSION)

    def test_a_secondary_trade_is_told_from_a_racial_passive(self):
        """THE TRAP THIS FUNCTION EXISTS FOR. SkillLine files first aid,
        cooking and fishing in the SAME category as `Racial - Gnome` and
        `Riding`, so a category rule reports a gnome's racial as a trade."""
        self.assertEqual(standing.skill_group(FIRST_AID, standing.CATEGORY_SECONDARY),
                         standing.GROUP_SECONDARY)
        gnome_racial = 753
        self.assertEqual(standing.skill_group(gnome_racial, standing.CATEGORY_SECONDARY),
                         standing.GROUP_OTHER)

    def test_defence_is_pulled_out_of_the_weapon_pile(self):
        """It is the one defensive number in the table, and fifteen weapon
        rows is where it goes to stop being read."""
        self.assertEqual(standing.skill_group(DEFENCE, standing.CATEGORY_WEAPON),
                         standing.GROUP_DEFENCE)
        self.assertEqual(standing.skill_group(SWORDS, standing.CATEGORY_WEAPON),
                         standing.GROUP_WEAPON)

    def test_an_unknown_category_still_lands_somewhere(self):
        self.assertEqual(standing.skill_group(999999, 4242), standing.GROUP_OTHER)


class TheLevelCap(unittest.TestCase):
    def test_five_per_level(self):
        self.assertEqual(standing.level_cap(27), 135)
        self.assertEqual(standing.level_cap(1), 5)

    def test_a_nonsense_level_does_not_produce_a_negative_cap(self):
        self.assertEqual(standing.level_cap(-3), 0)


class WhatCountsAsGraded(unittest.TestCase):
    def test_an_armour_proficiency_is_not_graded(self):
        self.assertTrue(standing.is_proficiency(CLOTH, 1))

    def test_a_weapon_skill_is(self):
        self.assertFalse(standing.is_proficiency(SWORDS, 135))

    def test_the_three_counters_that_wear_a_graded_shape_are_not(self):
        """Mounts and Companions count what the character OWNS against a
        ceiling that tracks level; GENERIC (DND) is a client placeholder.
        All three would otherwise print a large invented shortfall."""
        for counter in standing.UNGRADED:
            self.assertTrue(standing.is_proficiency(counter, 135), counter)


class PercentOf(unittest.TestCase):
    def test_it_rounds_to_one_place(self):
        self.assertEqual(standing.percent(1, 3), 33.3)

    def test_no_scale_means_no_percentage_rather_than_a_crash(self):
        self.assertIsNone(standing.percent(5, 0))
        self.assertIsNone(standing.percent(5, -1))


class OneSkillRow(unittest.TestCase):
    def test_a_weapon_at_the_cap_is_short_by_nothing(self):
        entry = standing.skill_entry(skill(SWORDS, 135, 135), 27, BOOK)
        self.assertEqual(entry["name"], "Swords")
        self.assertEqual(entry["cap"], 135)
        self.assertEqual(entry["short_by"], 0)
        self.assertEqual(entry["percent"], 100.0)
        self.assertFalse(entry["stale_max"])

    def test_a_weapon_below_the_cap_says_how_far(self):
        entry = standing.skill_entry(skill(SWORDS, 100, 135), 27, BOOK)
        self.assertEqual(entry["short_by"], 35)

    def test_the_cap_comes_from_the_level_not_the_stored_maximum(self):
        """The core writes `max` when the skill is next USED, so a character
        who has levelled since carries yesterday's ceiling. The level is the
        authority; the disagreement is reported, not smoothed away."""
        entry = standing.skill_entry(skill(SWORDS, 115, 115), 27, BOOK)
        self.assertEqual(entry["cap"], 135)
        self.assertEqual(entry["short_by"], 20)
        self.assertTrue(entry["stale_max"])

    def test_a_proficiency_gets_no_cap_and_no_invented_shortfall(self):
        """MEASURED LIVE: Bork's Leather is 1/1 at level 23. Against a cap of
        115 that reads '114 short', which would be the loudest number on his
        card and entirely made up - he knows how to wear leather."""
        entry = standing.skill_entry(skill(CLOTH, 1, 1), 23, BOOK)
        self.assertTrue(entry["proficiency"])
        self.assertIsNone(entry["cap"])
        self.assertIsNone(entry["short_by"])
        self.assertIsNone(entry["percent"])

    def test_a_trade_caps_at_its_current_tier_not_the_level(self):
        """Apprentice alchemy is 75 whatever the character's level is."""
        entry = standing.skill_entry(skill(ALCHEMY, 1, 75), 27, BOOK)
        self.assertEqual(entry["cap"], 75)
        self.assertEqual(entry["short_by"], 74)
        self.assertFalse(entry["stale_max"])

    def test_an_unknown_skill_id_names_itself_rather_than_going_blank(self):
        """A blank cell reads as 'this character has an unnamed skill'. The
        number says which row to go and look at."""
        entry = standing.skill_entry(skill(999999, 3, 10), 27, BOOK)
        self.assertEqual(entry["name"], "skill 999999")


class WhatATradeCanMake(unittest.TestCase):
    def setUp(self):
        self.entry = standing.skill_entry(skill(ALCHEMY, 1, 75), 27, BOOK)

    def test_it_counts_what_is_known_against_what_exists(self):
        """'knows 0' and 'knows 0 of 254' are the same fact at two very
        different volumes, and the second is the one that makes the point."""
        built = standing.trade_entry(self.entry, "alchemy", BOOK, frozenset())
        self.assertEqual(built["recipes"]["known"], 0)
        self.assertGreater(built["recipes"]["total"], 100)
        self.assertEqual(built["recipes"]["makes"], [])
        self.assertFalse(built["recipes"]["gathers"])

    def test_a_known_recipe_is_named_and_linked_to_what_it_makes(self):
        spice_bread = 37836
        entry = standing.skill_entry(skill(COOKING, 1, 75), 27, BOOK)
        built = standing.trade_entry(entry, "cooking", BOOK, frozenset({spice_bread}))
        self.assertEqual(built["recipes"]["known"], 1)
        made = built["recipes"]["makes"][0]
        self.assertEqual(made["name"], "Spice Bread")
        # The link goes to the ITEM, because that is the thing a person
        # wants the tooltip for.
        self.assertEqual(made["wowhead"], standing.wowhead("item", 30816))

    def test_a_gathering_trade_says_it_makes_nothing_by_design(self):
        """Herbalism has no recipes at all. '0 of 0' reads as a fault where
        the truth is that gathering is what the trade is for."""
        entry = standing.skill_entry(skill(HERBALISM, 15, 75), 27, BOOK)
        built = standing.trade_entry(entry, "herbalism", BOOK, frozenset())
        self.assertTrue(built["recipes"]["gathers"])
        self.assertEqual(built["recipes"]["total"], 0)

    def test_a_spell_the_character_knows_from_another_trade_is_not_counted(self):
        spice_bread = 37836
        built = standing.trade_entry(self.entry, "alchemy", BOOK,
                                     frozenset({spice_bread}))
        self.assertEqual(built["recipes"]["known"], 0)


class TheReputationLadder(unittest.TestCase):
    def test_every_rank_boundary(self):
        """The floors are the core's own (ReputationMgr::PointsInRank). One
        off by a point puts a character in the wrong rank at the boundary,
        which is exactly where anybody would be looking."""
        for total, expected in ((EXALTED_FLOOR, "Exalted"),
                                (EXALTED_FLOOR - 1, "Revered"),
                                (REVERED_FLOOR, "Revered"),
                                (REVERED_FLOOR - 1, "Honored"),
                                (HONORED_FLOOR, "Honored"),
                                (HONORED_FLOOR - 1, "Friendly"),
                                (FRIENDLY_FLOOR, "Friendly"),
                                (FRIENDLY_FLOOR - 1, "Neutral"),
                                (NEUTRAL_FLOOR, "Neutral"),
                                (-1, "Unfriendly"),
                                (-3000, "Unfriendly"),
                                (-3001, "Hostile"),
                                (-6000, "Hostile"),
                                (-6001, "Hated"),
                                (standing.REPUTATION_BOTTOM, "Hated")):
            self.assertEqual(standing.RANK_NAMES[standing.reputation_rank(total)],
                             expected, total)

    def test_the_floor_of_a_rank_is_where_the_rank_starts(self):
        for index, floor in ((3, NEUTRAL_FLOOR), (4, FRIENDLY_FLOOR),
                             (5, HONORED_FLOOR), (6, REVERED_FLOOR),
                             (7, EXALTED_FLOOR)):
            self.assertEqual(standing.rank_floor(index), floor, index)
            self.assertEqual(standing.reputation_rank(floor), index)


class TheBaseReputation(unittest.TestCase):
    """The single most consequential number on the reputation panel.

    `character_reputation.standing` is stored RELATIVE to it and the core
    adds them back together on load. It is 3000 or 4000 for an Alliance
    character's own capitals, so leaving it out is not a rounding error - it
    moves a character a whole rank.
    """

    def test_a_human_and_a_gnome_do_not_start_level_with_stormwind(self):
        entry = BOOK.factions[STORMWIND]
        human = standing.base_reputation(entry, HUMAN, WARRIOR)
        gnome = standing.base_reputation(entry, GNOME, ROGUE)
        self.assertEqual(human, 4000)
        self.assertEqual(gnome, 3100)

    def test_leaving_it_out_would_move_grug_a_whole_rank(self):
        """MEASURED LIVE 2026-09-02: Grug's stored Stormwind standing is
        7186. With his base that is 11186, which is Honored. Without it he
        reads Friendly, and the panel would be confidently wrong."""
        entry = BOOK.factions[STORMWIND]
        stored = 7186
        with_base = stored + standing.base_reputation(entry, HUMAN, WARRIOR)
        self.assertEqual(standing.RANK_NAMES[standing.reputation_rank(with_base)],
                         "Honored")
        self.assertEqual(standing.RANK_NAMES[standing.reputation_rank(stored)],
                         "Friendly")

    def test_a_faction_with_no_base_table_is_simply_zero(self):
        self.assertEqual(standing.base_reputation({}, HUMAN, WARRIOR), 0)

    def test_an_entry_with_no_race_mask_but_a_class_mask_matches_any_race(self):
        """That is how Faction.dbc spells 'every warrior', and reading the
        condition the other way round silently skips those entries."""
        every_race = 0xFFFF
        entry = {"base": [[0, 1 << (WARRIOR - 1), 500], [every_race, 0, 7]]}
        self.assertEqual(standing.base_reputation(entry, HUMAN, WARRIOR), 500)
        self.assertEqual(standing.base_reputation(entry, HUMAN, PRIEST), 7)

    def test_an_all_zero_entry_matches_nothing_exactly_as_the_core_says(self):
        """Faction.dbc pads its four slots with [0, 0, 0], and the core's
        own condition cannot match one: a zero race mask only qualifies when
        the CLASS mask is non-zero. Treating the padding as a catch-all
        would hand every unmatched character a base of zero by a route that
        also swallows the real entries below it - Stormwind's fourth slot is
        exactly this shape."""
        self.assertEqual(standing.base_reputation({"base": [[0, 0, 7]]},
                                                  HUMAN, WARRIOR), 0)

    def test_the_first_matching_entry_wins(self):
        entry = {"base": [[1 << (HUMAN - 1), 0, 11], [0, 0, 22]]}
        self.assertEqual(standing.base_reputation(entry, HUMAN, WARRIOR), 11)


class WhichFactionsHaveBeenMet(unittest.TestCase):
    """Every character carries a row for every faction in the game. This
    predicate is the difference between a reputation panel and a dump."""

    def test_visible_is_met(self):
        self.assertTrue(standing.met(standing.FLAG_VISIBLE))

    def test_a_row_with_no_visible_flag_is_not(self):
        self.assertFalse(standing.met(0))
        self.assertFalse(standing.met(0x40))

    def test_either_hiding_flag_overrides_visible(self):
        self.assertFalse(standing.met(standing.FLAG_VISIBLE | standing.FLAG_HIDDEN))
        self.assertFalse(standing.met(standing.FLAG_VISIBLE
                                      | standing.FLAG_INVISIBLE_FORCED))

    def test_the_flag_combination_the_family_actually_carries_is_met(self):
        """MEASURED LIVE: all twenty-five of the family's real standings are
        flags=17, which is VISIBLE plus PEACE_FORCED. A predicate that
        tested equality rather than the bit would drop every one of them."""
        self.assertTrue(standing.met(17))


class OneReputationRow(unittest.TestCase):
    def test_it_names_the_faction_and_places_it_in_its_rank(self):
        entry = standing.reputation_entry(rep(STORMWIND, 7186), BOOK, HUMAN, WARRIOR)
        self.assertEqual(entry["name"], "Stormwind")
        self.assertEqual(entry["standing"], "Honored")
        self.assertEqual(entry["total"], 11186)
        self.assertEqual(entry["into"], 11186 - HONORED_FLOOR)
        self.assertEqual(entry["span"], 12000)
        self.assertTrue(entry["friendly"])

    def test_a_hostile_standing_is_flagged_for_the_page(self):
        """The page should not have to know which rank number is neutral."""
        entry = standing.reputation_entry(rep(STORMWIND, -20000), BOOK, GNOME, ROGUE)
        self.assertFalse(entry["friendly"])

    def test_the_total_cannot_leave_the_ladder(self):
        """A base of -42000 plus a stored negative would otherwise index off
        the bottom of the rank table."""
        entry = standing.reputation_entry(rep(STORMWIND, -60000), BOOK, GNOME, ROGUE)
        self.assertEqual(entry["total"], standing.REPUTATION_BOTTOM)
        self.assertEqual(entry["standing"], "Hated")

    def test_an_unknown_faction_names_itself_rather_than_going_blank(self):
        entry = standing.reputation_entry(rep(999999, 10), BOOK, HUMAN, WARRIOR)
        self.assertEqual(entry["name"], "faction 999999")


class TheSpecSummary(unittest.TestCase):
    """THE PANEL THAT WAS SUPPOSED TO BE IMPOSSIBLE.

    acore_world's talent_dbc and talenttab_dbc are both empty, so the join
    a reader reaches for first yields nothing without erroring. The frozen
    book armory.py already ships is the route, and these prove it works
    rather than merely not crashing.
    """

    def test_a_learned_rank_is_named_placed_and_counted_as_points(self):
        spec = standing.spec_summary(
            WARRIOR, 27, [{"spell": PUNCTURE_R2, "specMask": 1}], TALENTS)
        self.assertEqual(spec["primary"], "Protection")
        self.assertEqual(spec["spent"], 2, "rank 2 is TWO points, not one talent")
        self.assertEqual(spec["distribution"], "0/0/2")
        protection = [t for t in spec["trees"] if t["name"] == "Protection"][0]
        self.assertEqual(protection["talents"][0]["name"], "Puncture")
        self.assertEqual(protection["talents"][0]["rank"], 2)
        self.assertEqual(protection["talents"][0]["max_rank"], 3)

    def test_the_talent_links_to_the_rank_actually_held(self):
        spec = standing.spec_summary(
            WARRIOR, 27, [{"spell": PUNCTURE_R2, "specMask": 1}], TALENTS)
        protection = [t for t in spec["trees"] if t["name"] == "Protection"][0]
        self.assertEqual(protection["talents"][0]["wowhead"],
                         standing.wowhead("spell", PUNCTURE_R2))

    def test_unspent_points_are_the_budget_minus_what_is_spent(self):
        spec = standing.spec_summary(
            WARRIOR, 27, [{"spell": PUNCTURE_R1, "specMask": 1}], TALENTS)
        self.assertEqual(spec["available"], armory.talent_points_at(27, WARRIOR))
        self.assertEqual(spec["unspent"], spec["available"] - 1)

    def test_nothing_spent_says_so_rather_than_naming_a_tree(self):
        spec = standing.spec_summary(WARRIOR, 27, [], TALENTS)
        self.assertIsNone(spec["primary"])
        self.assertEqual(spec["spent"], 0)

    def test_a_talent_the_book_cannot_name_is_still_counted(self):
        """A build that silently reads a point short is worse than one that
        admits which point it cannot explain."""
        spec = standing.spec_summary(
            WARRIOR, 27, [{"spell": 999999, "specMask": 1}], TALENTS)
        self.assertEqual(spec["spent"], 1)
        self.assertEqual(spec["unknown"], ["spell 999999"])

    def test_rows_arriving_as_strings_still_resolve(self):
        """Belt and braces: the driver returns ints, but a lookup that is
        silently type-sensitive fails by producing an EMPTY spec, which is
        indistinguishable from a character who has spent nothing."""
        spec = standing.spec_summary(
            WARRIOR, 27, [{"spell": str(PUNCTURE_R2), "specMask": 1}], TALENTS)
        self.assertEqual(spec["spent"], 2)
        self.assertEqual(spec["unknown"], [])

    def test_a_death_knight_budget_is_unknown_rather_than_guessed(self):
        spec = standing.spec_summary(6, 60, [], TALENTS)
        self.assertIsNone(spec["available"])
        self.assertIsNone(spec["unspent"])


class TheFamilyWideGap(unittest.TestCase):
    """The finding this whole view exists to surface (mod-overseer#160)."""

    def test_a_trade_nobody_holds_is_listed_with_what_it_would_have_made(self):
        gap = standing.trade_gap({"alchemy", "herbalism"}, BOOK)
        missing = {m["trade"]: m for m in gap["missing"]}
        self.assertIn("enchanting", missing)
        self.assertEqual(missing["enchanting"]["name"], "Enchanting")
        self.assertGreater(missing["enchanting"]["recipes"], 100)

    def test_enchanting_is_called_out_by_name_with_its_reason(self):
        """It is not one absent trade among ten. It is the one whose absence
        costs the family something on every dungeon run."""
        gap = standing.trade_gap({"alchemy", "herbalism"}, BOOK)
        self.assertTrue(gap["enchanting"])
        self.assertIn("vendor trash", gap["enchanting_why"])
        self.assertIn("mod-overseer#160", gap["enchanting_why"])
        enchanting = [m for m in gap["missing"] if m["trade"] == "enchanting"][0]
        self.assertEqual(enchanting["why"], gap["enchanting_why"])
        others = [m for m in gap["missing"] if m["trade"] != "enchanting"]
        self.assertTrue(all(not m["why"] for m in others))

    def test_a_family_that_had_everything_reports_no_gap(self):
        gap = standing.trade_gap(set(professions.PRIMARY), BOOK)
        self.assertEqual(gap["missing"], [])
        self.assertFalse(gap["enchanting"])

    def test_what_is_held_is_reported_beside_what_is_not(self):
        gap = standing.trade_gap({"alchemy", "herbalism", "not a trade"}, BOOK)
        self.assertEqual(gap["held"], ["alchemy", "herbalism"])


class TheFourPanels(unittest.TestCase):
    """The seams `_member` assembles, each reachable on its own."""

    def entries(self, *rows, level=27):
        return sorted((standing.skill_entry(r, level, BOOK) for r in rows),
                      key=lambda e: (-e["value"], e["name"]))

    def test_the_trade_panel_splits_primary_from_secondary(self):
        panel = standing.trade_panel(
            self.entries(skill(HERBALISM, 15, 75), skill(ALCHEMY, 1, 75),
                         skill(FIRST_AID, 1, 75), skill(SWORDS, 135, 135)),
            BOOK, frozenset())
        self.assertEqual([t["trade"] for t in panel["primary"]],
                         ["herbalism", "alchemy"])
        self.assertEqual([t["trade"] for t in panel["secondary"]], ["first aid"])

    def test_the_trade_panel_reports_the_ceiling_that_blocks_a_new_trade(self):
        panel = standing.trade_panel(
            self.entries(skill(HERBALISM, 15, 75), skill(ALCHEMY, 1, 75)),
            BOOK, frozenset())
        self.assertEqual(panel["slots_free"], 0)
        self.assertEqual(panel["max_primary"], professions.MAX_PRIMARY)

    def test_a_character_with_one_primary_has_a_slot_free(self):
        panel = standing.trade_panel(
            self.entries(skill(HERBALISM, 15, 75)), BOOK, frozenset())
        self.assertEqual(panel["slots_free"], 1)
        self.assertEqual(panel["blocking"], ["herbalism"])

    def test_the_skill_panel_leaves_the_trades_out(self):
        panel = standing.skill_panel(
            self.entries(skill(ALCHEMY, 1, 75), skill(SWORDS, 135, 135)), 27)
        groups = {g["group"] for g in panel["groups"]}
        self.assertEqual(groups, {standing.GROUP_WEAPON})

    def test_the_skill_panel_totals_only_the_graded_combat_skills(self):
        """A proficiency in the pile would poison this number by 134."""
        panel = standing.skill_panel(
            self.entries(skill(SWORDS, 100, 135), skill(DEFENCE, 135, 135),
                         skill(CLOTH, 1, 1)), 27)
        self.assertEqual(panel["short_by"], 35)
        self.assertFalse(panel["at_cap"])

    def test_a_character_with_no_graded_combat_skill_is_not_reported_short(self):
        panel = standing.skill_panel(self.entries(skill(CLOTH, 1, 1)), 27)
        self.assertEqual(panel["short_by"], 0)
        self.assertTrue(panel["at_cap"])

    def test_the_reputation_panel_filters_then_sorts(self):
        rows = [rep(IRONFORGE, 100), rep(STORMWIND, 7186),
                rep(999998, 9999, flags=0)]
        panel = standing.reputation_panel(rows, BOOK, HUMAN, WARRIOR)
        self.assertEqual([r["name"] for r in panel], ["Stormwind", "Ironforge"])

    def test_only_the_build_being_played_is_returned(self):
        rows = [{"spell": PUNCTURE_R1, "specMask": 1},
                {"spell": 12282, "specMask": 2}]
        self.assertEqual(standing.active_talents(char(group=0), rows), rows[:1])
        self.assertEqual(standing.active_talents(char(group=1), rows), rows[1:])

    def test_a_missing_active_group_falls_back_to_the_first(self):
        rows = [{"spell": PUNCTURE_R1, "specMask": 1}]
        self.assertEqual(standing.active_talents({}, rows), rows)


class TheWholePayload(unittest.TestCase):
    def build(self, **kw):
        rows = {
            "char_rows": [char()],
            "skill_rows": [skill(HERBALISM, 15, 75), skill(ALCHEMY, 1, 75),
                           skill(FIRST_AID, 1, 75), skill(SWORDS, 135, 135),
                           skill(DEFENCE, 135, 135), skill(CLOTH, 1, 1)],
            "reputation_rows": [rep(STORMWIND, 7186), rep(IRONFORGE, 1889),
                                rep(999998, 500, flags=0)],
            "talent_rows": [{"name": FIRST, "spell": PUNCTURE_R2, "specMask": 1}],
            "spell_rows": [{"name": FIRST, "spell": 37836}],
        }
        rows.update(kw)
        return standing.build_standing(book=BOOK, talents=TALENTS, **rows)

    def test_every_member_gets_a_card_even_with_no_rows(self):
        """A family view that quietly drops somebody is the failure the
        Armory tab was built to stop, and this is the same rule."""
        payload = self.build()
        self.assertEqual([m["name"] for m in payload["members"]], ROSTER)
        self.assertEqual(payload["expected"], len(ROSTER))
        absent = [m for m in payload["members"] if m["name"] != FIRST]
        self.assertTrue(all(not m["present"] for m in absent))
        self.assertTrue(all("role" in m for m in absent))

    def test_the_member_with_rows_is_fully_built(self):
        member = self.build()["members"][0]
        self.assertTrue(member["present"])
        self.assertEqual(member["class"], "Warrior")
        self.assertEqual([t["trade"] for t in member["professions"]["primary"]],
                         ["herbalism", "alchemy"])
        self.assertEqual([t["trade"] for t in member["professions"]["secondary"]],
                         ["first aid"])
        self.assertEqual(member["spec"]["primary"], "Protection")

    def test_only_factions_that_have_been_met_appear(self):
        member = self.build()["members"][0]
        self.assertEqual([r["name"] for r in member["reputations"]],
                         ["Stormwind", "Ironforge"])

    def test_reputations_are_deepest_first(self):
        member = self.build()["members"][0]
        totals = [r["total"] for r in member["reputations"]]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_the_trades_are_not_also_sent_as_plain_skill_rows(self):
        """Two homes for one fact is two things to keep in step, and the
        page would have to name a group to know which copy to skip."""
        member = self.build()["members"][0]
        groups = {g["group"] for g in member["skills"]["groups"]}
        self.assertNotIn(standing.GROUP_PROFESSION, groups)
        self.assertNotIn(standing.GROUP_SECONDARY, groups)
        self.assertIn(standing.GROUP_WEAPON, groups)
        self.assertIn(standing.GROUP_DEFENCE, groups)

    def test_the_group_order_is_sent_so_the_page_never_names_one(self):
        payload = self.build()
        self.assertEqual(payload["groups"], list(standing.GROUP_ORDER))
        member = payload["members"][0]
        order = [g["group"] for g in member["skills"]["groups"]]
        self.assertEqual(order, [g for g in standing.GROUP_ORDER if g in order])

    def test_a_character_at_the_cap_says_so_in_one_number(self):
        member = self.build()["members"][0]
        self.assertEqual(member["skills"]["short_by"], 0)
        self.assertTrue(member["skills"]["at_cap"])
        self.assertEqual(member["skills"]["cap"], 135)

    def test_a_proficiency_never_contributes_to_the_shortfall(self):
        """The one number on the card that a proficiency could quietly
        poison: cloth at 1/1 against a cap of 135 would read as 134 short."""
        member = self.build()["members"][0]
        self.assertEqual(member["skills"]["short_by"], 0)

    def test_both_primary_slots_taken_is_reported_as_the_blocker_it_is(self):
        """'nobody has enchanting' and 'nobody CAN have it without losing a
        trade' are different problems with different fixes."""
        pro = self.build()["members"][0]["professions"]
        self.assertEqual(pro["slots_free"], 0)
        self.assertEqual(pro["max_primary"], professions.MAX_PRIMARY)
        self.assertEqual(sorted(pro["blocking"]), ["alchemy", "herbalism"])

    def test_the_gap_is_the_union_across_the_family_not_one_member(self):
        payload = self.build()
        self.assertEqual(payload["gap"]["held"], ["alchemy", "herbalism"])
        self.assertTrue(payload["gap"]["enchanting"])

    def test_the_second_talent_build_is_not_summed_into_the_first(self):
        """character_talent holds BOTH specs, told apart by specMask.
        Summing them reports twice the points actually spent."""
        payload = self.build(talent_rows=[
            {"name": FIRST, "spell": PUNCTURE_R2, "specMask": 1},
            {"name": FIRST, "spell": 12282, "specMask": 2},
        ])
        self.assertEqual(payload["members"][0]["spec"]["spent"], 2)

    def test_the_payload_is_json(self):
        """It goes down the wire as JSON, so a set or a frozenset anywhere
        in it is a 500 that no unit test above would notice."""
        json.dumps(self.build())


class TheStandingBookItself(unittest.TestCase):
    """Guards the committed file. If these fail, standing.json is wrong or
    was regenerated from different client data - and the tests above would
    otherwise fail in a way that pointed at the builder instead."""

    def test_the_book_is_not_empty(self):
        """A generator that silently produced an EMPTY book is exactly the
        failure this whole module exists to route around, and it would pass
        every test that only checks a shape."""
        self.assertGreater(len(BOOK.skills), 100)
        self.assertGreater(len(BOOK.factions), 50)
        self.assertGreater(len(BOOK.recipes), 1000)

    def test_it_names_the_skills_the_family_actually_hold(self):
        for skill_id, name in ((ALCHEMY, "Alchemy"), (HERBALISM, "Herbalism"),
                               (FIRST_AID, "First Aid"), (COOKING, "Cooking"),
                               (FISHING, "Fishing"), (ENCHANTING, "Enchanting"),
                               (SWORDS, "Swords"), (DEFENCE, "Defense")):
            self.assertEqual(BOOK.skill_name(skill_id), name)

    def test_every_trade_this_service_knows_about_is_in_the_book(self):
        """professions.py can assign any of these; a trade the book cannot
        name would draw a blank row on the day somebody trained it."""
        for name in professions.PRIMARY | professions.SECONDARY:
            skill_id = goals.SKILL_IDS[name]
            self.assertIn(skill_id, BOOK.skills, name)
            self.assertFalse(BOOK.skill_name(skill_id).startswith("skill "), name)

    def test_the_profession_rank_spells_are_not_listed_as_recipes(self):
        """MEASURED LIVE: these are the only trade spells the family knows.
        Listing `Alchemy` under 'what they can make' answers the question
        with its own premise."""
        for rank_spell in (2259, 2366, 2368, 2550, 3273, 7620):
            self.assertNotIn(rank_spell, BOOK.recipes, rank_spell)

    def test_a_real_recipe_is_in_the_book_with_what_it_makes(self):
        self.assertEqual(BOOK.recipes[3275]["name"], "Linen Bandage")
        self.assertEqual(BOOK.recipes[3275]["skill"], FIRST_AID)
        self.assertEqual(BOOK.recipes[3275]["creates"], 1251)

    def test_the_gathering_trades_carry_no_recipes_and_the_crafts_do(self):
        for name in ("herbalism", "skinning", "fishing"):
            self.assertEqual(BOOK.by_skill.get(goals.SKILL_IDS[name], []), [], name)
        for name in ("alchemy", "enchanting", "tailoring", "blacksmithing"):
            self.assertGreater(len(BOOK.by_skill[goals.SKILL_IDS[name]]), 100, name)

    def test_every_recipe_is_named(self):
        """A nameless recipe would draw a blank link."""
        blank = [s for s, r in BOOK.recipes.items() if not r["name"]]
        self.assertEqual(blank, [])

    def test_every_faction_in_the_book_can_hold_a_reputation(self):
        """The core creates a reputation row only for factions with an
        index, so one without is dead weight in a committed file."""
        self.assertTrue(all(f["index"] >= 0 for f in BOOK.factions.values()))

    def test_it_names_the_factions_the_family_have_actually_met(self):
        for faction_id, name in ((STORMWIND, "Stormwind"), (IRONFORGE, "Ironforge"),
                                 (54, "Gnomeregan Exiles"), (69, "Darnassus"),
                                 (930, "Exodar")):
            self.assertEqual(BOOK.faction_name(faction_id), name)

    def test_every_faction_carries_four_base_entries(self):
        """The core walks all four in order; a short list would silently
        stop matching partway down."""
        for faction_id, entry in BOOK.factions.items():
            self.assertEqual(len(entry["base"]), 4, faction_id)
            for row in entry["base"]:
                self.assertEqual(len(row), 3, faction_id)


class WhatMustShip(unittest.TestCase):
    """The book is useless in the image if it is not IN the image, and that
    failure lands at pod start long after CI has gone green."""

    def test_the_book_is_copied_into_the_image(self):
        dockerfile = (HERE / "Dockerfile").read_text()
        self.assertIn("standing.json", dockerfile)
        self.assertIn("standing.py", dockerfile)

    def test_the_generator_that_wrote_it_is_kept_beside_it(self):
        """A frozen book with no generator is a file nobody can ever
        regenerate or check."""
        self.assertTrue((HERE / "tools" / "gen_standing.py").exists())


class ThePagePanel(unittest.TestCase):
    """The page contract, asserted against index.html as source - the same
    seam test_armory_tab.py uses, and for the same reason: map_server
    imports pymysql and the page has no other."""

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text()
        cls.server = (HERE / "map_server.py").read_text()
        start = cls.page.index("// --- the standing panel (mod-overseer#88")
        cls.js = cls.page[start:cls.page.index("// --- the front door", start)]

    def test_the_panel_lives_inside_the_armory_tab(self):
        """It is the same question about the same five. A sixth tab button
        is one more thing to find on a phone."""
        armory_section = self.page[self.page.index('<section id="armory">'):]
        armory_section = armory_section[:armory_section.index("</section>")]
        self.assertIn('<div id="standing">', armory_section)

    def test_opening_the_tab_does_not_wait_for_the_timer(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertIn("pollStanding();", arm[:arm.index("return;")])

    def test_the_poll_is_gated_on_the_tab_being_open(self):
        poll = self.js[self.js.index("async function pollStanding"):]
        self.assertIn("if (view !== ARMORY_VIEW) return;", poll)

    def test_a_failed_poll_keeps_the_cards_it_has_already_drawn(self):
        """A blank panel reads as 'they have learned nothing'."""
        poll = self.js[self.js.index("async function pollStanding"):]
        self.assertIn("may be stale", poll)
        self.assertNotIn("stcards.textContent", poll)

    def test_nothing_reaches_the_page_as_markup(self):
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("insertAdjacentHTML", self.js)

    def test_it_borrows_the_tabs_icon_host_rather_than_naming_a_second(self):
        """The Armory's own test counts the page's outbound hosts and finds
        exactly two. Every link here arrives already built in the payload."""
        self.assertNotIn("https://", self.js)
        self.assertIn("iconImg(", self.js)

    def test_the_roster_is_not_retyped_into_the_page(self):
        for name in ROSTER:
            self.assertNotIn('"' + name + '"', self.js)

    def test_the_group_names_are_not_retyped_into_the_page(self):
        """The payload carries the groups and their order, exactly as it
        carries the doll layout, so the two ends cannot disagree.

        `class` is exempt and only `class`: it is also the name of a
        MEMBER field, and `class` is a reserved word in JavaScript, so
        `m["class"]` is the only way to read a character's class at all -
        the Armory tab spells it the same way. The exemption is for that
        one string, not for the rule."""
        for group in standing.GROUP_ORDER:
            if group == standing.GROUP_CLASS:
                continue
            self.assertNotIn('"' + group + '"', self.js, group)

    def test_the_group_list_is_taken_from_the_payload(self):
        """The other half of the rule above: the page draws whatever groups
        it is sent, in the order it is sent them."""
        self.assertIn("for (const g of m.skills.groups)", self.js)
        self.assertIn("g.group", self.js)

    def test_the_gap_is_drawn_before_any_card(self):
        """Five cards each listing two trades look complete. Only the union
        shows that nobody can disenchant."""
        render = self.js[self.js.index("function renderStanding"):]
        render = render[:render.index("async function pollStanding")]
        self.assertLess(render.index("renderGap(p.gap)"),
                        render.index("for (const m of p.members)"))

    def test_the_endpoint_is_routed(self):
        self.assertIn('"/api/standing": _standing,', self.server)
        self.assertIn("def _standing(self, query: dict)", self.server)

    def test_the_endpoint_takes_no_name(self):
        """WHO the family is belongs to bonds. Accepting a roster here would
        turn it into a general character query wearing a friendly name."""
        handler = self.server[self.server.index("def _standing"):]
        handler = handler[:handler.index("def _questlog")]
        self.assertNotIn("query.get", handler)
        self.assertIn("family.roster()", self.server)

    def test_a_failed_query_keeps_the_contract_the_other_endpoints_hold(self):
        handler = self.server[self.server.index("def _standing"):]
        handler = handler[:handler.index("def _questlog")]
        self.assertIn("503", handler)
        self.assertIn("world unreachable", handler)

    def test_the_fetch_joins_no_dbc_table(self):
        """Every one of them is EMPTY on this realm, and an empty table
        joins to nothing WITHOUT erroring - which is how a panel ends up
        blank and confident. The names come from the frozen book."""
        fetch = self.server[self.server.index("def _fetch_standing"):]
        fetch = fetch[:fetch.index("# The quest log query")]
        for table in ("faction_dbc", "skillline_dbc", "talent_dbc",
                      "talenttab_dbc", "skilllineability_dbc"):
            self.assertNotIn(table, fetch, table)


if __name__ == "__main__":
    unittest.main()
