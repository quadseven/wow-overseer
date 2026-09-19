"""What the guild trades view is allowed to claim, and what it must not.

MOSTLY ABOUT REFUSALS, like the dungeon plan's suite. The easy half of this
view is counting, and counting is not where a page like this goes wrong: it
goes wrong by letting an absence pass for an answer. A recipe with no source
row read is not a recipe with nowhere to come from; a trade nobody holds is
not a trade with no recipes; a trainer craft that cannot be NAMED is not a
trainer craft that does not exist; and a list trimmed to twelve is not a list
of twelve. Each of those is one assertion below, because each of them is a
sentence somebody would act on.

THE FIXTURES ARE THE REAL FAMILY. Five characters, levels 34 to 38, holding
eight of the eleven primaries between them. Grog has not yet learned his new
assignment (mining + engineering, #2831 update), so engineering is a plain
gap - assigned to somebody, not yet held - while inscription and
jewelcrafting, his OLD pair, are the two professions.UNASSIGNED trades a
guild is meant to cover instead. Writing the fixtures out rather than
generating them is what lets a failure read as "Og's tailoring line is wrong"
instead of "member 3 of 5".

Tickets: infra#3507.
"""
import pathlib
import re
import unittest

import goals
import guildcraft
import professions
from transform import Geometry

HERE = pathlib.Path(__file__).resolve().parent.parent
MODULE = (HERE / "guildcraft.py").read_text(encoding="utf-8")
GEO = Geometry.load(str(HERE))

TAILORING = goals.SKILL_IDS["tailoring"]
ENCHANTING = goals.SKILL_IDS["enchanting"]
ALCHEMY = goals.SKILL_IDS["alchemy"]
HERBALISM = goals.SKILL_IDS["herbalism"]
BLACKSMITHING = goals.SKILL_IDS["blacksmithing"]
MINING = goals.SKILL_IDS["mining"]
ENGINEERING = goals.SKILL_IDS["engineering"]

ROSTER = ["Grug", "Grog", "Bork", "Og", "Ugga"]
LEVELS = {"Grug": 38, "Grog": 36, "Bork": 35, "Og": 34, "Ugga": 37}

# A point this realm's own zones.json places in Westfall, worked out from the
# rectangle rather than typed in. A hand-written coordinate is the thing the
# family's own travel rules forbid, and it would also silently stop naming
# Westfall the first time the geometry was regenerated.
WESTFALL = "Westfall"


def _point_in(zone_name: str, map_id: int = 0):
    """The middle of the named zone's rectangle in zones.json."""
    for zone in GEO.continents[str(map_id)]["zones"]:
        if zone["name"] == zone_name:
            return ((zone["top"] + zone["bottom"]) / 2.0,
                    (zone["left"] + zone["right"]) / 2.0)
    raise AssertionError("zones.json does not name %s" % zone_name)


WESTFALL_X, WESTFALL_Y = _point_in(WESTFALL)


def member(name: str) -> dict:
    return {"name": name, "level": LEVELS[name], "class": 1}


def skill(name: str, ident: int, value: int, ceiling: int = 75) -> dict:
    return {"name": name, "skill": ident, "value": value, "max": ceiling}


def recipe(entry: int, name: str, ident: int, rank: int, spell: int,
           level: int = 0, quality: int = 1) -> dict:
    """One `item_template` row of class 9, as the read selects it."""
    return {"entry": entry, "item_name": name, "RequiredSkill": ident,
            "RequiredSkillRank": rank, "required_level": level,
            "spellid_2": spell, "quality": quality, "item_level": rank,
            "displayid": 1, "class": guildcraft.RECIPE_CLASS, "subclass": 2}


def vendor(item: int, name: str, x=WESTFALL_X, y=WESTFALL_Y,
           map_id: int = 0) -> dict:
    return {"item": item, "name": name, "map": map_id,
            "position_x": x, "position_y": y}


def drop(item: int, name: str, low: int = 20, high: int = 21,
         chance: float = 2.5, map_id: int = 0, x=WESTFALL_X,
         y=WESTFALL_Y) -> dict:
    return {"item": item, "name": name, "minlevel": low, "maxlevel": high,
            "Chance": chance, "map": map_id, "position_x": x, "position_y": y}


def quest(item: int, title: str, level: int = 20, ident: int = 1) -> dict:
    return {"item": item, "ID": ident, "LogTitle": title, "QuestLevel": level}


# The family's live skills as the brief measured them: the full spread, every
# trade freshly taken by the four who already have their assignment, and
# nobody holding engineering, inscription or jewelcrafting - Grog is pending
# on his new pair (#2831 update) and has not learned it yet.
FAMILY_SKILLS = [
    skill("Grug", BLACKSMITHING, 1), skill("Grug", MINING, 5),
    skill("Bork", goals.SKILL_IDS["leatherworking"], 1),
    skill("Bork", goals.SKILL_IDS["skinning"], 12),
    skill("Og", TAILORING, 20), skill("Og", ENCHANTING, 1),
    skill("Ugga", ALCHEMY, 30), skill("Ugga", HERBALISM, 34),
]


def build(**over):
    """A payload over the real family, with any input replaced by name."""
    args = {
        "guild_rows": [],
        "member_rows": [member(name) for name in ROSTER],
        "skill_rows": list(FAMILY_SKILLS),
        "spell_rows": [],
        "roster_rows": [],
        "recipe_rows": [],
        "trainer_rows": [],
        "vendor_rows": [],
        "drop_rows": [],
        "quest_rows": [],
        "icons": {},
        "roster": list(ROSTER),
        "names": {36: "The Deadmines"},
        "geo": GEO,
    }
    args.update(over)
    return guildcraft.build_guildcraft(**args)


def trade(payload: dict, word: str) -> dict:
    found = [t for t in payload["trades"] if t["name"] == word]
    assert len(found) == 1, word
    return found[0]


class TheCoveredRoster(unittest.TestCase):
    """Who the page reads, which is the family until a guild exists."""

    def test_with_no_guild_it_is_the_family_and_says_so(self):
        payload = build()
        self.assertIn("not one of them is in a guild", payload["guild_line"])
        self.assertIn("the family rather than a guild", payload["guild_line"])

    def test_a_guild_widens_the_roster_and_is_named(self):
        rows = [{"guild": "The Long Table", "name": name}
                for name in ROSTER + ["Kam", "Viper"]]
        self.assertEqual(guildcraft.covered_names(ROSTER, rows),
                         ROSTER + ["Kam", "Viper"])
        payload = build(guild_rows=rows,
                        member_rows=[member(n) for n in ROSTER])
        self.assertIn("The Long Table", payload["guild_line"])
        self.assertIn("2 more who share it", payload["guild_line"])

    def test_the_family_is_never_cut_by_the_ceiling(self):
        """A guild big enough to push the five off the end would be answering
        somebody else's question."""
        rows = [{"guild": "Horde", "name": "Bot%d" % n} for n in range(200)]
        covered = guildcraft.covered_names(ROSTER, rows, ceiling=8)
        self.assertEqual(covered[:5], ROSTER)
        self.assertEqual(len(covered), 8)

    def test_a_cut_roster_says_it_was_cut(self):
        """A list that is simply SHORT reads exactly like a complete one."""
        rows = [{"guild": "Horde", "name": "Bot%d" % n} for n in range(200)]
        payload = build(guild_rows=rows)
        self.assertIn("were NOT read", payload["coverage"])
        self.assertIn("rather than known to hold nothing", payload["coverage"])

    def test_an_uncut_roster_does_not_warn(self):
        self.assertIn("Every character this page covers was read",
                      build()["coverage"])

    def test_a_family_split_across_guilds_is_reported_as_a_split(self):
        rows = [{"guild": "One", "name": "Og"}, {"guild": "Two", "name": "Ugga"}]
        self.assertIn("split across 2 guilds", build(guild_rows=rows)["guild_line"])


class WhoHoldsWhat(unittest.TestCase):
    """The first half of the request: per trade, per character, how far."""

    def test_every_trade_this_service_names_gets_a_row(self):
        payload = build()
        self.assertEqual({t["name"] for t in payload["trades"]},
                         set(goals.SKILL_IDS))

    def test_the_holder_line_carries_the_ceiling_and_not_just_the_value(self):
        """1 of 75 and 1 of 300 are different characters."""
        self.assertIn("Og holds tailoring at 20 of 75",
                      trade(build(), "tailoring")["line"])

    def test_a_sole_holder_is_not_printed_twice(self):
        """With one holder the trade sentence IS that holder's sentence, and a
        summary stays on screen when the row is opened, so emitting both put
        the same words twice under their own heading."""
        card = trade(build(), "tailoring")
        self.assertEqual(card["holder_lines"], [])
        self.assertIn("Og holds tailoring", card["line"])

    def test_two_holders_each_get_their_own_line_under_the_count(self):
        payload = build(skill_rows=FAMILY_SKILLS + [skill("Grog", TAILORING, 4)])
        card = trade(payload, "tailoring")
        self.assertEqual(len(card["holder_lines"]), 2)
        self.assertIn("Grog holds tailoring at 4 of 75", card["holder_lines"][1])

    def test_a_skill_at_its_ceiling_says_so(self):
        payload = build(skill_rows=[skill("Og", TAILORING, 75)])
        self.assertIn("as far as their training goes",
                      trade(payload, "tailoring")["line"])

    def test_a_trade_with_two_holders_names_both(self):
        payload = build(skill_rows=FAMILY_SKILLS + [skill("Grog", TAILORING, 4)])
        self.assertIn("2 of them hold tailoring", trade(payload, "tailoring")["line"])

    def test_a_known_recipe_names_who_can_make_it(self):
        payload = build(
            recipe_rows=[recipe(1, "Pattern: Linen Bag", TAILORING, 10, 900)],
            spell_rows=[{"name": "Og", "spell": 900}])
        card = trade(payload, "tailoring")
        self.assertEqual(card["known_count"], 1)
        self.assertIn("Og can make this", card["known"][0]["line"])

    def test_a_spell_held_by_somebody_without_the_trade_is_not_knowing_it(self):
        """Grug has no tailoring. A stray spell id on his row must not make the
        guild's tailoring look one recipe better off than it is."""
        payload = build(
            recipe_rows=[recipe(1, "Pattern: Linen Bag", TAILORING, 10, 900)],
            spell_rows=[{"name": "Grug", "spell": 900}])
        self.assertEqual(trade(payload, "tailoring")["known_count"], 0)

    def test_a_gathering_trade_says_it_has_no_recipes_rather_than_none_missing(self):
        card = trade(build(), "herbalism")
        self.assertIn("a gathering trade", card["recipes_line"])
        self.assertEqual(card["missing_count"], 0)


class WhatNobodyHolds(unittest.TestCase):
    """The gaps, which are the useful part."""

    def test_inscription_and_jewelcrafting_are_gaps_reported_as_a_decision(self):
        """professions.UNASSIGNED now names these two (Grog's old pair) as the
        trades left open for a guild. Listing either beside an accident would
        report a decision as a defect."""
        self.assertEqual(professions.UNASSIGNED, ("inscription", "jewelcrafting"))
        payload = build()
        for word in professions.UNASSIGNED:
            with self.subTest(word=word):
                gap = [g for g in payload["gaps"] if g["name"] == word]
                self.assertEqual(len(gap), 1)
                self.assertIn("left open on purpose", gap[0]["line"])
                self.assertIn("a guild is meant to fill", gap[0]["line"])

    def test_engineering_is_now_a_plain_gap_not_a_decision(self):
        """Engineering used to be the UNASSIGNED trade; #2831's update gave it
        to Grog instead. He has not learned it yet in this fixture, so it must
        read as an ordinary unheld gap, not as the deliberate one."""
        self.assertNotIn("engineering", professions.UNASSIGNED)
        payload = build()
        gap = [g for g in payload["gaps"] if g["name"] == "engineering"][0]
        self.assertNotIn("left open on purpose", gap["line"])

    def test_a_trade_nobody_holds_still_counts_its_recipes(self):
        """`known + missing` is zero for a trade nobody holds, and printing
        that as the recipe count would say "0 recipe items exist for
        engineering" over the one trade this page exists to point at."""
        rows = [recipe(n, "Schematic %d" % n, ENGINEERING, 20, 800 + n)
                for n in range(3)]
        card = trade(build(recipe_rows=rows), "engineering")
        self.assertIn("3 recipe items exist for it", card["recipes_line"])
        self.assertIn("until somebody takes the trade", card["recipes_line"])

    def test_a_trade_assigned_and_not_held_is_a_different_gap(self):
        """overseer_roster.professions is what the family DECIDED.
        character_skills is what the world granted, and the gap is the
        finding."""
        payload = build(skill_rows=[],
                        roster_rows=[{"name": "Og",
                                      "professions": "%d,%d" % (TAILORING,
                                                                ENCHANTING)}])
        gap = [g for g in payload["gaps"] if g["name"] == "tailoring"][0]
        self.assertIn("assigned to Og in the roster", gap["line"])
        self.assertIn("not held by anybody in character_skills", gap["line"])

    def test_an_assignment_the_world_agrees_with_is_not_a_complaint(self):
        payload = build(roster_rows=[{"name": "Og",
                                      "professions": str(TAILORING)}])
        self.assertEqual(trade(payload, "tailoring")["assigned_line"],
                         "assigned to Og in the roster, and held")

    def test_a_malformed_roster_column_costs_one_assignment_and_not_the_page(self):
        payload = build(roster_rows=[{"name": "Og", "professions": "wat,,197"}])
        self.assertEqual(trade(payload, "tailoring")["assigned"], ["Og"])

    def test_the_gap_count_never_says_one_trades(self):
        payload = build(skill_rows=FAMILY_SKILLS)
        self.assertNotIn("1 trades", payload["gaps_line"])
        self.assertRegex(payload["gaps_line"], r"^\d+ trades are held by nobody$")

    def test_a_guild_holding_everything_says_so_rather_than_printing_nothing(self):
        rows = [skill("Og", ident, 10) for ident in goals.SKILL_IDS.values()]
        payload = build(skill_rows=rows)
        self.assertEqual(payload["gaps"], [])
        self.assertIn("held by somebody", payload["gaps_line"])


class WhereAMissingRecipeComesFrom(unittest.TestCase):
    """The farm-run half. A source a reader can walk to, or an admission."""

    def setUp(self):
        self.rows = [recipe(70, "Pattern: Red Linen Robe", TAILORING, 10, 900)]

    def test_a_vendor_is_named_and_placed_in_a_real_zone(self):
        payload = build(recipe_rows=self.rows,
                        vendor_rows=[vendor(70, "Jannos Ironwill")])
        card = trade(payload, "tailoring")["missing"][0]
        self.assertEqual(card["sources"][0]["kind"], guildcraft.VENDOR)
        self.assertIn("sold by Jannos Ironwill in %s" % WESTFALL,
                      card["sources"][0]["line"])

    def test_a_drop_carries_the_creature_its_levels_and_where(self):
        payload = build(recipe_rows=self.rows,
                        drop_rows=[drop(70, "Defias Conjurer")])
        line = trade(payload, "tailoring")["missing"][0]["sources"][0]["line"]
        self.assertIn("drops from Defias Conjurer", line)
        self.assertIn("level 20 to 21", line)
        self.assertIn(WESTFALL, line)
        self.assertIn("2.5%", line)

    def test_a_drop_inside_a_dungeon_is_named_by_the_dungeon(self):
        """zones.json holds no rectangles inside an instance, so running an
        instance spawn through the zone lookup gives "an unknown place" where
        "The Deadmines" is the answer."""
        payload = build(recipe_rows=self.rows,
                        drop_rows=[drop(70, "Mr. Smite", map_id=36)])
        line = trade(payload, "tailoring")["missing"][0]["sources"][0]["line"]
        self.assertIn("The Deadmines", line)
        self.assertNotIn("unknown place", line)

    def test_a_quest_is_named_with_the_level_it_is_written_for(self):
        payload = build(recipe_rows=self.rows,
                        quest_rows=[quest(70, "Red Linen Goods")])
        line = trade(payload, "tailoring")["missing"][0]["sources"][0]["line"]
        self.assertIn("rewarded by the quest Red Linen Goods", line)
        self.assertIn("written for level 20", line)

    def test_the_sources_are_ordered_by_what_they_cost_to_reach(self):
        """A vendor is a walk with a known ending; a drop is a number of kills
        nothing here can predict."""
        payload = build(recipe_rows=self.rows,
                        vendor_rows=[vendor(70, "Jannos Ironwill")],
                        drop_rows=[drop(70, "Defias Conjurer")],
                        quest_rows=[quest(70, "Red Linen Goods")])
        kinds = [s["kind"]
                 for s in trade(payload, "tailoring")["missing"][0]["sources"]]
        self.assertEqual(kinds, [guildcraft.VENDOR, guildcraft.QUEST,
                                 guildcraft.DROP])

    def test_no_source_read_is_not_no_source(self):
        """reference_loot_template is not followed, which is where most world
        drops live. "Nowhere" would assert the absence of a thing this page
        declined to look for."""
        card = trade(build(recipe_rows=self.rows), "tailoring")["missing"][0]
        self.assertEqual(card["sources"], [])
        self.assertIn("world drop behind a reference loot table",
                      card["source_line"])

    def test_a_long_source_list_is_trimmed_and_says_how_many_there_were(self):
        drops = [drop(70, "Defias %d" % n) for n in range(9)]
        card = trade(build(recipe_rows=self.rows, drop_rows=drops),
                     "tailoring")["missing"][0]
        self.assertEqual(len(card["sources"]), guildcraft.SOURCES_SHOWN)
        self.assertIn("9 source rows read", card["source_line"])

    def test_a_spawn_with_no_position_says_it_cannot_be_placed(self):
        """A LEFT JOIN on a creature with no spawn row hands back nulls, and a
        blank where a zone should be reads as a missing name rather than as a
        creature nothing here can find."""
        row = vendor(70, "Somebody", x=None, y=None, map_id=None)
        payload = build(recipe_rows=self.rows, vendor_rows=[row])
        self.assertIn("somewhere this page cannot place",
                      trade(payload, "tailoring")["missing"][0]["sources"][0]["line"])

    def test_a_chance_of_zero_is_not_reported_as_a_percentage(self):
        payload = build(recipe_rows=self.rows,
                        drop_rows=[drop(70, "Defias Conjurer", chance=0)])
        line = trade(payload, "tailoring")["missing"][0]["sources"][0]["line"]
        self.assertIn("gives no chance on this row", line)
        self.assertNotIn("0%", line)


class WhatItWouldTakeToLearnIt(unittest.TestCase):
    """The arithmetic that makes an unreachable recipe look unreachable."""

    def test_a_recipe_under_the_skill_held_can_be_used_today(self):
        payload = build(recipe_rows=[recipe(70, "Pattern", TAILORING, 10, 900)])
        card = trade(payload, "tailoring")["missing"][0]
        self.assertEqual(card["reach"], guildcraft.NOW)
        self.assertIn("Og has 20, so it can be used", card["reach_line"])

    def test_a_recipe_above_the_skill_held_says_how_far_short(self):
        payload = build(recipe_rows=[recipe(70, "Pattern", TAILORING, 60, 900)])
        card = trade(payload, "tailoring")["missing"][0]
        self.assertEqual(card["reach"], guildcraft.SHORT)
        self.assertIn("Og has 20, which is 40 short", card["reach_line"])

    def test_a_recipe_above_one_holders_training_names_the_trainer(self):
        """Skill is ground out by crafting; a tier is bought, and no amount of
        cloth substitutes for it. Grog has ground the most and Og has trained
        the furthest, so a recipe at 100 is listed on Og's ceiling and
        measured against Grog's skill, and the sentence must not claim the
        GUILD needs a trainer when one of them is already there."""
        payload = build(
            recipe_rows=[recipe(70, "Pattern", TAILORING, 100, 900)],
            skill_rows=[skill("Og", TAILORING, 20, ceiling=150),
                        skill("Grog", TAILORING, 45, ceiling=75)])
        card = trade(payload, "tailoring")["missing"][0]
        self.assertIn("Grog has 45", card["reach_line"])
        self.assertIn("their own training stops at 75", card["reach_line"])

    def test_a_character_level_gate_is_named_separately_from_skill(self):
        """A recipe behind a level is not made reachable by any amount of
        crafting, so it must not read as "40 short"."""
        payload = build(recipe_rows=[recipe(70, "Pattern", TAILORING, 10, 900,
                                            level=50)])
        card = trade(payload, "tailoring")["missing"][0]
        self.assertEqual(card["reach"], guildcraft.LEVEL_GATED)
        self.assertIn("character level 50 and Og is 34", card["reach_line"])
        self.assertNotIn("short", card["reach_line"])

    def test_recipes_above_the_ceiling_are_counted_and_not_listed(self):
        """A trade showing twelve missing recipes at skill 75 looks like a
        trade with twelve left in it, when it is a trade with hundreds and one
        trainer visit between them."""
        rows = ([recipe(n, "Pattern %d" % n, TAILORING, 10, 900 + n)
                 for n in range(2)] +
                [recipe(50 + n, "Pattern %d" % n, TAILORING, 200, 950 + n)
                 for n in range(7)])
        card = trade(build(recipe_rows=rows), "tailoring")
        self.assertEqual(card["missing_count"], 2)
        self.assertIn("7 more recipe items exist for it above skill 75",
                      card["beyond_line"])

    def test_the_reach_is_measured_against_the_best_ground_skill(self):
        """The question is "could anybody use this today", and that is the
        skill somebody has ground rather than the tier they paid for."""
        payload = build(
            recipe_rows=[recipe(70, "Pattern", TAILORING, 40, 900)],
            skill_rows=[skill("Og", TAILORING, 20, ceiling=150),
                        skill("Grog", TAILORING, 45, ceiling=75)])
        self.assertIn("Grog has 45",
                      trade(payload, "tailoring")["missing"][0]["reach_line"])


class ThingsItRefusesToClaim(unittest.TestCase):
    """Every one of these is a sentence somebody would act on."""

    def test_a_trainer_craft_is_counted_and_never_named(self):
        """skilllineability_dbc is empty on this realm and spell_dbc holds
        custom rows only, so nothing here can turn a trainer spell into a
        name. Inventing them would be inventing the only part a reader acts
        on."""
        trainer = [{"SpellId": 2963 + n, "ReqSkillLine": TAILORING,
                    "ReqSkillRank": 1, "ReqLevel": 5} for n in range(14)]
        card = trade(build(trainer_rows=trainer), "tailoring")
        self.assertIn("a trainer teaches 14 tailoring crafts", card["trainer_line"])
        self.assertIn("can count them and cannot name them", card["trainer_line"])

    def test_a_trainer_craft_already_known_is_counted_as_known(self):
        trainer = [{"SpellId": 2963, "ReqSkillLine": TAILORING,
                    "ReqSkillRank": 1, "ReqLevel": 5}]
        card = trade(build(trainer_rows=trainer,
                           spell_rows=[{"name": "Og", "spell": 2963}]),
                     "tailoring")
        self.assertIn("is already known", card["trainer_line"])

    def test_an_unreadable_trainer_table_is_absent_and_not_zero(self):
        basis = build(trainer_rows=[])["basis"]
        self.assertIn("returned nothing readable", basis)
        self.assertIn("not a trade whose trainer teaches nothing", basis)

    def test_an_unreadable_roster_column_is_not_a_family_with_no_plan(self):
        basis = build(roster_read=False)["basis"]
        self.assertIn("could not be read this time", basis)
        self.assertIn("not a family that has decided nothing", basis)

    def test_a_trimmed_missing_list_says_how_many_there_were(self):
        rows = [recipe(n, "Pattern %d" % n, TAILORING, 10, 900 + n)
                for n in range(30)]
        card = trade(build(recipe_rows=rows), "tailoring")
        self.assertEqual(len(card["missing"]), guildcraft.LISTED_MISSING)
        self.assertEqual(card["missing_count"], 30)
        self.assertIn("30 of them", card["missing_head"])

    def test_the_basis_names_the_loot_it_does_not_follow(self):
        basis = build()["basis"]
        self.assertIn("reference_loot_template is NOT followed", basis)
        self.assertIn("DIRECT ROWS ONLY", basis)

    def test_the_basis_admits_it_cannot_price_a_craft_in_materials(self):
        self.assertIn("reagent list lives in Spell.dbc", build()["basis"])

    def test_the_basis_defers_drop_chance_to_the_loot_board(self):
        """A percentage invented for a grouped row is a number somebody would
        plan a farm run around."""
        self.assertIn("what a shared roll means", build()["basis"])

    def test_the_basis_says_only_one_spawn_is_named(self):
        self.assertIn("ONE of its spawn rows", build()["basis"])

    def test_an_empty_world_says_there_is_nothing_to_compare(self):
        payload = build(member_rows=[], skill_rows=[], roster=[])
        self.assertIn("nothing here knows who the guild are", payload["line"])


class EveryCountCanBeOne(unittest.TestCase):
    """Every number on this page comes from a list the world handed over, so
    every one of them can be one. "1 source rows read" is the class of mistake
    that turns up on the day something has gone wrong, which is the day the
    page is being read closely."""

    def test_a_single_source_row_is_a_row_and_not_rows(self):
        payload = build(recipe_rows=[recipe(70, "Pattern", TAILORING, 10, 900)],
                        vendor_rows=[vendor(70, "Jannos Ironwill")])
        line = trade(payload, "tailoring")["missing"][0]["source_line"]
        self.assertIn("1 source row read", line)
        self.assertNotIn("1 source rows", line)

    def test_a_single_known_trainer_craft_is_singular(self):
        trainer = [{"SpellId": 2963 + n, "ReqSkillLine": TAILORING,
                    "ReqSkillRank": 1, "ReqLevel": 5} for n in range(3)]
        line = trade(build(trainer_rows=trainer,
                           spell_rows=[{"name": "Og", "spell": 2963}]),
                     "tailoring")["trainer_line"]
        self.assertIn("1 of them is known", line)
        self.assertIn("2 are a trainer visit", line)

    def test_a_single_outstanding_trainer_craft_is_singular(self):
        trainer = [{"SpellId": 2963 + n, "ReqSkillLine": TAILORING,
                    "ReqSkillRank": 1, "ReqLevel": 5} for n in range(2)]
        line = trade(build(trainer_rows=trainer,
                           spell_rows=[{"name": "Og", "spell": 2963}]),
                     "tailoring")["trainer_line"]
        self.assertIn("1 is a trainer visit", line)

    def test_the_recipes_line_reads_as_a_sentence_in_all_three_states(self):
        """It read "and 4 more do" over a clause with no verb for "do" to
        stand in for, which is what happens when three branches share a
        suffix."""
        none = trade(build(), "tailoring")["recipes_line"]
        self.assertIn("none of the rest sit under the training", none)
        rows = [recipe(n, "Pattern %d" % n, TAILORING, 10, 900 + n)
                for n in range(4)]
        some = trade(build(recipe_rows=rows), "tailoring")["recipes_line"]
        self.assertIn("4 more sit under the training already held, all listed",
                      some)
        rows = [recipe(n, "Pattern %d" % n, TAILORING, 10, 900 + n)
                for n in range(30)]
        many = trade(build(recipe_rows=rows), "tailoring")["recipes_line"]
        self.assertIn("the %d cheapest to reach are listed"
                      % guildcraft.LISTED_MISSING, many)

    def test_a_single_missing_recipe_takes_a_singular_verb(self):
        """It read "and 1 more sit under the training already held", which is
        the same shared-suffix fault the three branches were split to fix."""
        payload = build(recipe_rows=[recipe(70, "Pattern", TAILORING, 10, 900)])
        line = trade(payload, "tailoring")["recipes_line"]
        self.assertIn("1 more sits under the training already held", line)

    def test_a_secondary_trade_nobody_holds_is_not_a_craft_with_no_supply(self):
        """First aid, cooking and fishing cost nobody a profession slot, so
        "nothing the guild makes can come from it" is the wrong sentence."""
        gap = [g for g in build()["gaps"] if g["name"] == "cooking"][0]
        self.assertIn("costs nobody a profession slot", gap["line"])


class TheOrderAndThePlaces(unittest.TestCase):
    """A list in an order is read as a finding, so the rule is printed."""

    def test_the_order_is_printed_above_the_list(self):
        order = build()["order"]
        self.assertIn("Trades the guild holds first", order)
        self.assertIn("vendor first, then quest, then drop", order)

    def test_a_held_trade_outranks_one_nobody_holds(self):
        payload = build()
        held = [t["rank"] for t in payload["trades"] if t["held"]]
        unheld = [t["rank"] for t in payload["trades"] if not t["held"]]
        self.assertLess(max(held), min(unheld))

    def test_the_place_is_the_modules_and_not_the_pages_loop_index(self):
        ranks = [t["rank"] for t in build()["trades"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))

    def test_a_sourced_recipe_is_listed_before_an_unsourced_one(self):
        rows = [recipe(1, "Aaa Pattern", TAILORING, 10, 901),
                recipe(2, "Zzz Pattern", TAILORING, 10, 902)]
        payload = build(recipe_rows=rows,
                        vendor_rows=[vendor(2, "Jannos Ironwill")])
        self.assertEqual([r["entry"]
                          for r in trade(payload, "tailoring")["missing"]],
                         [2, 1])

    def test_the_headline_counts_and_does_not_recommend(self):
        payload = build(recipe_rows=[recipe(70, "Pattern", TAILORING, 10, 900)])
        self.assertIn("trades held", payload["line"])
        for word in ("should", "recommend", "best", "worth"):
            self.assertNotIn(word, payload["line"], word)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("guildcraft.py", "tests/test_guildcraft.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)

    def test_the_skill_ids_are_not_restated_here(self):
        """goals.SKILL_IDS was verified live against character_skills and
        against the core's own enum. A second copy is a second thing to get
        wrong, and the two would drift the first time one was edited."""
        self.assertIn("goals.SKILL_IDS", MODULE)
        for number in (164, 165, 171, 197, 202, 333, 755, 773):
            # Word bounded, so a date or a row count that happens to contain
            # the digits is not read as a restated skill id.
            self.assertIsNone(re.search(r"%d" % number, MODULE),
                              str(number))

    def test_the_module_reaches_no_database(self):
        for forbidden in ("pymysql", "cursor", "SELECT ", "execute("):
            self.assertNotIn(forbidden, MODULE, forbidden)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("guildcraft.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
