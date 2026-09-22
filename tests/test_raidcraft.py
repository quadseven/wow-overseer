"""Which craft spells make what a raid night eats, and how far off each one is.

WHY THIS SUITE EXISTS. raidcraft.py is the join between a LEVELING table
(craft.RECIPES, which asks only which recipe raises a skill fastest) and a
RAID PLAN (raidgoals.RECIPES, which asks only what a Molten Core night wants).
Everything it claims is a fact about the running worldserver, and every one of
those facts was typed in by hand from a measurement - so every one of them
needs a second copy that a pull request can be gated on, exactly as
test_craft.py's MEASURED_FOCUS and MEASURED_BANDS already are for craft.py.

THE PROJECTIONS BELOW ARE THAT SECOND COPY, and MEASURED_RANKS is the first
one in this repo for the SECOND source. See raidcraft.py's docstring: reading
`SkillLineAbility.MinSkillLineRank` alone says Flask of the Titans is castable
at Alchemy 1, because for a recipe that is TAUGHT the rank lives in
`acore_world.trainer_spell` or on the teaching item's `item_template` row
instead. test_craft.py's MEASURED_BANDS reads 1 for seventeen of craft.py's
entries for exactly that reason and cannot catch a bracket that starts below a
trainer's rank; this is the projection that can.
"""

import unittest

import craft
import goals
import professions
import raidcraft
import raidgoals
import test_craft

# ---------------------------------------------------------------------------
# THE REALM'S OWN RANK FOR EVERY CONSUMABLE, AND WHICH TABLE SAID SO.
# spell id -> (rank, source), where source is the table the number came out of.
#
# Read 2026-09-14 against the live `acore_world` in the wow-dev namespace:
#
#   SELECT SpellId, ReqSkillLine, ReqSkillRank FROM trainer_spell
#    WHERE SpellId IN (...) GROUP BY SpellId, ReqSkillLine, ReqSkillRank;
#
#   SELECT entry, name, RequiredSkill, RequiredSkillRank, spellid_2
#     FROM item_template WHERE spellid_2 IN (...);
#
# EVERY TRAINER ROW CAME BACK WITH THREE TRAINERS, which is worth recording
# because it is the same number for all twelve and a differing count would have
# meant a faction-split or a rank-split this projection flattens.
#
# FOUR SPELLS HAVE BOTH A TRAINER ROW AND A TEACHING ITEM at the same rank
# (3450, 7929, 10840, 17556); the trainer is recorded because a trainer visit
# is machinery this repo has and a pattern purchase is not. The other five
# trainer entries (11467, 17551, 9918, 16641, 18630) have no teaching item at
# all, and the thirteen pattern entries have no trainer row at all - so the two
# routes are very nearly a partition, with four overlaps.
MEASURED_RANKS = {
    # ALCHEMY (171)
    6624: (150, "item_template 5642 Recipe: Free Action Potion"),
    3450: (175, "trainer_spell (also item_template 3830)"),
    11467: (240, "trainer_spell"),
    17551: (250, "trainer_spell"),
    26277: (250, "item_template 21547 Recipe: Elixir of Greater Firepower"),
    17556: (275, "trainer_spell (also item_template 13480)"),
    17571: (280, "item_template 13491 Recipe: Elixir of the Mongoose"),
    17574: (290, "item_template 13494 Recipe: Greater Fire Protection Potion"),
    17576: (290, "item_template 13496 Recipe: Greater Nature Protection Potion"),
    17580: (295, "item_template 13501 Recipe: Major Mana Potion"),
    17635: (300, "item_template 13519 Recipe: Flask of the Titans"),
    17636: (300, "item_template 13520 Recipe: Flask of Distilled Wisdom"),
    17637: (300, "item_template 13521 Recipe: Flask of Supreme Power"),
    17638: (300, "item_template 13522 Recipe: Flask of Chromatic Resistance"),
    # BLACKSMITHING (164)
    9918: (200, "trainer_spell"),
    16641: (250, "trainer_spell"),
    22757: (300, "item_template 18264 Plans: Elemental Sharpening Stone"),
    # ENCHANTING (333)
    25129: (300, "item_template 20756 Formula: Brilliant Wizard Oil"),
    25130: (300, "item_template 20757 Formula: Brilliant Mana Oil"),
    # FIRST AID (129)
    7929: (180, "trainer_spell (also item_template 16112)"),
    10840: (210, "trainer_spell (also item_template 16113)"),
    18630: (290, "trainer_spell"),
}

# ---------------------------------------------------------------------------
# THE DBC HALF, same three files and the same md5s test_craft.py's own
# projections name, read on 2026-09-14 with test_craft.py's own two anchors
# asserted first (2963 -> Reagent[0]=2589/ReagentCount[0]=2, and
# 2657 -> RequiresSpellFocus=3):
#
#     Spell.dbc             543b9fe61355b6a77a01714d52fea2e5   49839 x 234
#     SkillLineAbility.dbc  d8c11abfcfe70596cb9068c0e97a1d9a   10219 x 14
#     SpellFocusObject.dbc  797c65a49ae1e6336c9d851eb18011e0
#
# spell id -> (skill line, created item, TrivialSkillLineRankLow,
#              TrivialSkillLineRankHigh, RequiresSpellFocus)
#
# THE CREATED ITEM IS IN HERE AND IT IS THE FIELD THAT CAUGHT THE BRIEF'S OWN
# ERROR. The issue that asked for this work listed "Brilliant Wizard Oil 20749
# Enchanting-adjacent" - 20749 is the ITEM, and the spell that makes it is
# 25129. Three of its spell-column entries were item ids in the same way. The
# whole table was resolved the other way round instead: for every one of the
# brief's item names, `item_template` gave the entry, and then every record in
# Spell.dbc was scanned for a SPELL_EFFECT_CREATE_ITEM (Effect == 24) whose
# EffectItemType is that entry.
MEASURED_CONSUMABLES = {
    # ALCHEMY
    6624: (171, 5634, 175, 215, 0),
    3450: (171, 3825, 195, 235, 0),
    11467: (171, 9187, 255, 295, 0),
    17551: (171, 13423, 250, 260, 0),
    26277: (171, 21546, 265, 305, 0),
    17556: (171, 13446, 290, 330, 0),
    17571: (171, 13452, 295, 335, 0),
    17574: (171, 13457, 305, 345, 0),
    17576: (171, 13458, 305, 345, 0),
    17580: (171, 13444, 310, 350, 0),
    17635: (171, 13510, 315, 330, 0),
    17636: (171, 13511, 315, 330, 0),
    17637: (171, 13512, 315, 330, 0),
    17638: (171, 13513, 315, 330, 0),
    # BLACKSMITHING
    9918: (164, 7964, 200, 210, 0),
    16641: (164, 12404, 255, 260, 0),
    22757: (164, 18262, 300, 320, 0),
    # ENCHANTING
    25129: (333, 20749, 310, 330, 0),
    25130: (333, 20748, 310, 330, 0),
    # FIRST AID
    7929: (129, 6451, 180, 240, 0),
    10840: (129, 8544, 210, 270, 0),
    18630: (129, 14530, 290, 350, 0),
}

# The one non-zero SpellFocusObject id in Alchemy, and the six spells that want
# it. Recorded because the brief asked for the flasks to be checked against an
# "Alchemy Lab" requirement and the answer is that they have none - this is the
# measurement that makes that a fact rather than an omission.
ALCHEMY_LAB_FOCUS = 663
ALCHEMY_LAB_SPELLS = {17632, 38070, 47046, 47048, 47049, 47050}


class TheTableIsTheServersAnswer(unittest.TestCase):
    """Every field of every entry, against the projection above. A hand-typed
    table needs a second hand-typed copy or it is a claim nothing checks - the
    same argument test_craft.MEASURED_BANDS makes for craft.py."""

    def test_every_consumable_is_in_the_projection(self):
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id, name=c.name):
                self.assertIn(c.spell_id, MEASURED_CONSUMABLES)
                self.assertIn(c.spell_id, MEASURED_RANKS)

    def test_the_projection_names_nothing_the_table_does_not(self):
        """Both directions, so a consumable removed from the table leaves a
        stale measurement behind rather than passing silently."""
        spells = {c.spell_id for c in raidcraft.CONSUMABLES}
        self.assertEqual(set(MEASURED_CONSUMABLES), spells)
        self.assertEqual(set(MEASURED_RANKS), spells)

    def test_every_skill_line_matches(self):
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertEqual(
                    goals.SKILL_IDS[c.skill], MEASURED_CONSUMABLES[c.spell_id][0]
                )

    def test_every_created_item_matches(self):
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertEqual(c.item, MEASURED_CONSUMABLES[c.spell_id][1])

    def test_every_colour_band_matches(self):
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                _s, _i, yellow, grey, _f = MEASURED_CONSUMABLES[c.spell_id]
                self.assertEqual((c.yellow, c.grey), (yellow, grey))

    def test_every_floor_is_the_realms_own_rank_and_not_the_dbcs(self):
        """THE POINT OF MEASURED_RANKS. `SkillLineAbility.MinSkillLineRank` is
        1 for every one of these, so a floor taken from the DBC would say a
        flask is castable at Alchemy 1."""
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertEqual(c.floor, MEASURED_RANKS[c.spell_id][0])

    def test_no_consumable_needs_a_focus_nothing_walks_to(self):
        """The brief stated that Alchemy's high-tier flasks need an "Alchemy
        Lab" spell focus. On this realm that is false for every entry here, and
        the field is held to the server's answer rather than to the claim."""
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertEqual(c.focus, MEASURED_CONSUMABLES[c.spell_id][4])
                self.assertTrue(c.focus == 0 or c.focus in craft.FOCUS_AIMS)

    def test_no_consumable_is_one_of_the_six_alchemy_lab_spells(self):
        """Alchemy Lab (focus 663) is real and six spells want it - all of them
        Alchemist's Stones, none of them a flask. Pinned by id so the claim
        cannot be re-proposed without the measurement being redone."""
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertNotIn(c.spell_id, ALCHEMY_LAB_SPELLS)

    def test_a_floor_is_never_at_or_past_its_own_grey(self):
        """A recipe the realm teaches at or past its own grey value can never
        grant a skill point to anybody, which would make it a pure production
        recipe and not something `preferred` may ever hand to a leveling
        bracket. None is today; this is what keeps that true."""
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertLess(c.floor, c.grey)

    def test_every_taught_value_is_one_of_the_three(self):
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertIn(
                    c.taught, (raidcraft.TRAINER, raidcraft.RECIPE_ITEM, raidcraft.AUTO)
                )

    def test_the_source_column_agrees_with_how_it_is_taught(self):
        """A RECIPE_ITEM entry whose rank came out of `trainer_spell` would be
        a contradiction between the two halves of the projection, and it is
        the shape a copy-paste error takes."""
        for c in raidcraft.CONSUMABLES:
            _rank, source = MEASURED_RANKS[c.spell_id]
            with self.subTest(spell=c.spell_id, taught=c.taught):
                if c.taught == raidcraft.TRAINER:
                    self.assertTrue(source.startswith("trainer_spell"), source)
                elif c.taught == raidcraft.RECIPE_ITEM:
                    self.assertTrue(source.startswith("item_template"), source)

    def test_every_skill_named_is_a_real_profession(self):
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertIn(c.skill, goals.SKILL_IDS)
                self.assertTrue(
                    c.skill in professions.CRAFTING or c.skill in professions.SECONDARY
                )

    def test_every_entry_says_something(self):
        """`note` is never empty, the same rule craft.Recipe's own table keeps:
        a row that cannot say why it is here is a row nobody can act on."""
        for c in raidcraft.CONSUMABLES:
            with self.subTest(spell=c.spell_id):
                self.assertTrue(c.note.strip())

    def test_no_spell_is_listed_twice(self):
        spells = [c.spell_id for c in raidcraft.CONSUMABLES]
        self.assertEqual(len(spells), len(set(spells)))

    def test_no_item_is_listed_twice(self):
        items = [c.item for c in raidcraft.CONSUMABLES]
        self.assertEqual(len(items), len(set(items)))


class ThePatternTaughtMajorityIsCountedRatherThanAssumed(unittest.TestCase):
    """THIRTEEN of the twenty-two need a pattern item nothing here buys, which
    is the single most load-bearing fact in this module: it is why the raid's
    list is not a farming problem, and it names the concurrent change that
    unblocks it rather than duplicating it."""

    def test_the_majority_of_the_list_is_pattern_taught(self):
        pattern = [
            c for c in raidcraft.CONSUMABLES if c.taught == raidcraft.RECIPE_ITEM
        ]
        self.assertEqual(len(raidcraft.CONSUMABLES), 22)
        self.assertEqual(len(pattern), 13)

    def test_every_flask_is_pattern_taught(self):
        """All four, at rank 300, with no trainer_spell row anywhere. This is
        the reason "Ugga should craft flasks" is not a skill problem."""
        for spell in (17635, 17636, 17637, 17638):
            with self.subTest(spell=spell):
                self.assertEqual(
                    raidcraft.by_spell(spell).taught, raidcraft.RECIPE_ITEM
                )
                self.assertEqual(raidcraft.by_spell(spell).floor, 300)

    def test_both_weapon_oils_are_enchanting_and_pattern_taught(self):
        """The brief filed these as "Enchanting-adjacent" with the ITEM id in
        the spell column. They are Enchanting proper, at rank 300."""
        for spell in (25129, 25130):
            with self.subTest(spell=spell):
                self.assertEqual(raidcraft.by_spell(spell).skill, "enchanting")
                self.assertEqual(
                    raidcraft.by_spell(spell).taught, raidcraft.RECIPE_ITEM
                )

    def test_elemental_sharpening_stone_is_blacksmithing_and_pattern_taught(self):
        stone = raidcraft.by_spell(22757)
        self.assertEqual(stone.skill, "blacksmithing")
        self.assertEqual(stone.taught, raidcraft.RECIPE_ITEM)


class TheBriefsListWasCheckedAndNineOfItWasWrong(unittest.TestCase):
    """A list that silently dropped the entries it could not confirm would read
    as a list that had confirmed all of them. Both refusals are data."""

    def test_the_six_jujus_are_recorded_as_uncraftable(self):
        for entry in (12451, 12460, 12457, 12455, 12450, 12459):
            with self.subTest(entry=entry):
                self.assertIn(entry, raidcraft.NOT_CRAFTED)

    def test_no_uncraftable_item_leaked_into_the_table(self):
        items = {c.item for c in raidcraft.CONSUMABLES}
        for entry in raidcraft.NOT_CRAFTED:
            with self.subTest(entry=entry):
                self.assertNotIn(entry, items)

    def test_every_refusal_says_why(self):
        for entry, why in sorted(raidcraft.NOT_CRAFTED.items()):
            with self.subTest(entry=entry):
                self.assertTrue(why.strip())

    def test_the_jujus_are_recorded_as_not_horde_only(self):
        """The brief asked for `AllowableRace` to be checked before including
        them. It was: -1 on all six, which is every race. What rules them out
        is that they are quest items nothing crafts - so the conclusion was
        right and the stated reason was not, and both are written down."""
        self.assertIn("AllowableRace -1", raidcraft.NOT_CRAFTED[12451])

    def test_the_three_the_brief_called_absent_are_answered_individually(self):
        """Two of the three exist under a different name and one does not, and
        recording all three as "not found" would have lost that."""
        for name in ("Flask of Petrification", "Shadowoil", "Dreamshard Elixir"):
            with self.subTest(name=name):
                self.assertIn(name, raidcraft.MISNAMED)

    def test_the_two_that_do_exist_name_the_realms_own_spelling(self):
        self.assertIn(
            "Potion of Petrification", raidcraft.MISNAMED["Flask of Petrification"]
        )
        self.assertIn("Shadow Oil", raidcraft.MISNAMED["Shadowoil"])

    def test_the_one_that_is_genuinely_absent_says_so(self):
        self.assertIn("genuinely absent", raidcraft.MISNAMED["Dreamshard Elixir"])


class ThePreferenceIsTakenWhereItIsFree(unittest.TestCase):
    """THE GUARD THE WHOLE MODULE EXISTS FOR.

    `craft.RECIPES` is a partition - one recipe per skill point - so the choice
    between a leveling recipe and a raid consumable is made when a bracket is
    WRITTEN, once, by hand, and until this test nothing recorded that a choice
    had even been available. Dense Sharpening Stone had been picked over its
    identical twin Dense Weightstone for its whole life with nothing saying so,
    which means the next edit could have flipped it for free.

    The rule: at every skill value in every bracket, if a raid consumable is
    LEGAL there (past the realm's rank, below its own grey) and TEACHABLE by
    something this repo has, then the table must have named it - unless naming
    it would have cost skill, which is `yellow` being lower than the
    incumbent's."""

    def _skill_name(self, skill_id):
        for name, value in goals.SKILL_IDS.items():
            if value == skill_id:
                return name
        raise AssertionError("no profession for skill id %d" % skill_id)

    def test_no_bracket_passes_over_a_free_raid_consumable(self):
        for skill_id, recipes in sorted(craft.RECIPES.items()):
            skill = self._skill_name(skill_id)
            if not raidcraft.for_skill(skill):
                continue
            for recipe in recipes:
                incumbent = test_craft.MEASURED_BANDS[recipe.spell_id][1]
                for value in range(recipe.min_skill, recipe.max_skill + 1):
                    want = raidcraft.preferred(skill, value)
                    if want is None or want.spell_id == recipe.spell_id:
                        continue
                    with self.subTest(
                        skill=skill, value=value, named=recipe.name, wanted=want.name
                    ):
                        self.assertLess(
                            want.yellow,
                            incumbent,
                            "%s is legal at %s %d and is not worse for skill "
                            "(yellow %d against %s's %d), so the bracket "
                            "should name it"
                            % (
                                want.name,
                                skill,
                                value,
                                want.yellow,
                                recipe.name,
                                incumbent,
                            ),
                        )

    def test_the_four_brackets_this_rule_moved_are_pinned_by_name(self):
        """Named individually so a later edit that quietly reverts one fails
        with the recipe in the message rather than as an arithmetic sweep."""
        alchemy = goals.SKILL_IDS["alchemy"]
        smithing = goals.SKILL_IDS["blacksmithing"]
        self.assertEqual(craft.recipe_for(alchemy, 175).spell_id, 3450)
        self.assertEqual(craft.recipe_for(alchemy, 240).spell_id, 11467)
        self.assertEqual(craft.recipe_for(alchemy, 275).spell_id, 17556)
        self.assertEqual(craft.recipe_for(smithing, 200).spell_id, 9918)

    def test_the_one_that_was_already_right_is_pinned_too(self):
        """Dense Sharpening Stone over Dense Weightstone - same rank, same
        band, same reagent, and nothing recorded the choice until now."""
        self.assertEqual(
            craft.recipe_for(goals.SKILL_IDS["blacksmithing"], 250).spell_id, 16641
        )

    def test_elixir_of_fortitude_does_not_take_185_to_209(self):
        """The clause that keeps this rule honest in the other direction.
        Elixir of Fortitude is LEGAL from 185 to 209 and taking those points
        would cost skill: its yellow is 195 against Elixir of Agility's 205, so
        the raid item is there for the taking and taking it would be wrong."""
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 195).spell_id, 11449)
        self.assertIn(raidcraft.by_spell(3450), raidcraft.castable("alchemy", 195))

    def test_no_pattern_taught_recipe_is_ever_preferred(self):
        """Naming one would buy a `craft_spell` DriveCraft drops with a WARN
        calling it a planner bug on every twenty-second poll - the identical
        trap Heavy Linen Bandage set for First Aid, which craft.py already paid
        for once. Elixir of the Mongoose at Alchemy 280-284 is the bracket this
        clause costs, and it is checked rather than merely described."""
        for skill in sorted({c.skill for c in raidcraft.CONSUMABLES}):
            for value in range(1, 301):
                want = raidcraft.preferred(skill, value)
                if want is None:
                    continue
                with self.subTest(skill=skill, value=value, want=want.name):
                    self.assertNotEqual(want.taught, raidcraft.RECIPE_ITEM)

    def test_elixir_of_the_mongoose_is_the_bracket_that_clause_costs(self):
        """It is legal from Alchemy 280 and its yellow of 295 beats Major
        Healing Potion's 290, so without the pattern clause the rule would
        demand it at 280-284. No bracket names it, and none may until
        something here can learn from a pattern item."""
        mongoose = raidcraft.by_spell(17571)
        self.assertEqual(mongoose.taught, raidcraft.RECIPE_ITEM)
        self.assertGreater(mongoose.yellow, raidcraft.by_spell(17556).yellow)
        named = {r.spell_id for recipes in craft.RECIPES.values() for r in recipes}
        self.assertNotIn(17571, named)


class NothingHereIsCastableTonightAndItSaysSo(unittest.TestCase):
    """The honest half. A table of flasks that did not state the distance would
    read as a plan for this evening, and the distance is 136 points and two
    rank trainings."""

    LIVE = {
        # acore_characters.character_skills, read 2026-09-14.
        "Ugga": {"alchemy": 14, "herbalism": 133, "first aid": 1, "cooking": 1},
        "Og": {"tailoring": 50, "enchanting": 1, "first aid": 1, "cooking": 1},
        "Bork": {"leatherworking": 1, "skinning": 12, "first aid": 1},
        "Grug": {"blacksmithing": 1, "mining": 8, "first aid": 1},
        "Grog": {"engineering": 1, "mining": 1, "first aid": 1},
    }

    def test_not_one_of_the_family_can_cast_anything_on_this_list(self):
        for name, skills in sorted(self.LIVE.items()):
            for skill, value in sorted(skills.items()):
                with self.subTest(name=name, skill=skill):
                    self.assertEqual(raidcraft.castable(skill, value), ())

    def test_uggas_literal_nearest_is_free_action_potion_136_points_up(self):
        """And it is a rung she cannot step on: pattern-taught. The two
        answers are kept apart on purpose - see the next test."""
        want, short = raidcraft.nearest("alchemy", 14)
        self.assertEqual(want.spell_id, 6624)
        self.assertEqual(short, 136)
        self.assertEqual(want.taught, raidcraft.RECIPE_ITEM)

    def test_uggas_nearest_REACHABLE_is_elixir_of_fortitude_161_points_up(self):
        want, short = raidcraft.nearest_teachable("alchemy", 14)
        self.assertEqual(want.spell_id, 3450)
        self.assertEqual(short, 161)
        self.assertEqual(want.taught, raidcraft.TRAINER)

    def test_the_cheapest_thing_on_the_realm_is_free_action_potion(self):
        """Cheapest and first-reachable are different questions, and the answer
        to the second is Elixir of Fortitude twenty-five points higher, because
        Free Action Potion is pattern-taught."""
        cheapest = min(raidcraft.CONSUMABLES, key=lambda c: c.floor)
        self.assertEqual(cheapest.spell_id, 6624)
        self.assertEqual(cheapest.floor, 150)
        self.assertEqual(cheapest.taught, raidcraft.RECIPE_ITEM)

    def test_the_gap_sentence_names_the_rank_ceiling_and_not_only_the_distance(self):
        """161 points reads as an evening's work; 14/75 with a ceiling at 75
        reads as the two rank trainings it actually is."""
        said = raidcraft.gap("Ugga", {"alchemy": 14})
        self.assertIn("14/75", said)
        self.assertIn("Free Action Potion", said)
        self.assertIn("136", said)

    def test_the_gap_sentence_names_the_reachable_rung_too(self):
        """The literal nearest is a pattern item nothing here buys, so a
        sentence built on it alone would point at a rung this family cannot
        step on. Both are printed when they differ."""
        said = raidcraft.gap("Ugga", {"alchemy": 14})
        self.assertIn("Elixir of Fortitude", said)
        self.assertIn("161", said)

    def test_the_gap_sentence_is_never_empty(self):
        for name, skills in sorted(self.LIVE.items()):
            with self.subTest(name=name):
                self.assertTrue(raidcraft.gap(name, skills).strip())

    def test_a_trade_that_makes_no_raid_consumable_says_that_rather_than_nothing(self):
        said = raidcraft.gap("Bork", {"leatherworking": 300, "skinning": 300})
        self.assertIn("no raid consumable exists", said)

    def test_the_gap_sentence_names_whose_problem_the_recipe_is(self):
        trainer = raidcraft.gap("Ugga", {"alchemy": 14})
        self.assertIn("trainer", trainer)
        pattern = raidcraft.gap("Og", {"enchanting": 1})
        self.assertIn("pattern item", pattern)


class TheReachAnswersAreExact(unittest.TestCase):
    def test_castable_is_inclusive_of_the_floor(self):
        at = raidcraft.castable("alchemy", 175)
        self.assertEqual([c.spell_id for c in at], [6624, 3450])

    def test_castable_one_short_of_the_floor_is_empty(self):
        self.assertEqual(raidcraft.castable("alchemy", 149), ())

    def test_castable_still_answers_past_grey(self):
        """Castable and skill-granting are different questions. At 300 a flask
        is makeable; whether making it raises anybody is `preferred`'s."""
        self.assertIn(raidcraft.by_spell(3450), raidcraft.castable("alchemy", 300))

    def test_nearest_answers_none_above_the_last_floor(self):
        want, short = raidcraft.nearest("alchemy", 300)
        self.assertIsNone(want)
        self.assertEqual(short, 0)

    def test_nearest_answers_none_for_a_trade_with_no_consumables(self):
        want, short = raidcraft.nearest("tailoring", 1)
        self.assertIsNone(want)
        self.assertEqual(short, 0)

    def test_for_skill_is_ordered_by_the_realms_rank(self):
        for skill in sorted({c.skill for c in raidcraft.CONSUMABLES}):
            floors = [c.floor for c in raidcraft.for_skill(skill)]
            with self.subTest(skill=skill):
                self.assertEqual(floors, sorted(floors))

    def test_by_spell_answers_none_for_a_leveling_recipe(self):
        """Every craft.RECIPES entry that is not a raid consumable must answer
        None rather than raise - a caller asking "is this one" gets "no"."""
        self.assertIsNone(raidcraft.by_spell(2330))
        self.assertIsNone(raidcraft.by_spell(0))

    def test_by_spell_finds_the_bracket_craft_py_already_shared(self):
        self.assertEqual(raidcraft.by_spell(17556).name, "Major Healing Potion")

    def test_preferred_answers_none_below_every_floor(self):
        self.assertIsNone(raidcraft.preferred("alchemy", 14))
        self.assertIsNone(raidcraft.preferred("first aid", 1))

    def test_preferred_answers_none_for_a_trade_with_no_consumables(self):
        self.assertIsNone(raidcraft.preferred("engineering", 300))

    def test_preferred_stops_at_its_own_grey(self):
        """Elixir of Fortitude's grey is 235: at 234 it is still worth casting
        and at 235 the core rolls nothing, so it stops being a candidate - and
        with Elixir of Greater Agility's own rank still five points away, 235
        to 239 is a window with no raid consumable in it at all."""
        self.assertEqual(raidcraft.preferred("alchemy", 234).spell_id, 3450)
        self.assertIsNone(raidcraft.preferred("alchemy", 235))
        self.assertEqual(raidcraft.preferred("alchemy", 240).spell_id, 11467)


class TheStockpileTargetIsDataAndSaysWhatItIs(unittest.TestCase):
    """The target the Trades view could read. Every number is a CONVENTION and
    the four that raidgoals already states are imported from it, so the Raid
    page and this module cannot come to disagree about how many flasks a night
    is."""

    def test_the_shared_conventions_are_raidgoals_own(self):
        self.assertEqual(raidcraft.FLASKS_PER_RAIDER, raidgoals.PER_MEMBER_PER_NIGHT)
        self.assertEqual(
            raidcraft.PROTECTION_POTIONS_PER_RAIDER,
            raidgoals.FIRE_PROTECTION_PER_MEMBER,
        )
        self.assertEqual(
            raidcraft.HEALING_POTIONS_PER_RAIDER, raidgoals.HEALING_POTIONS_PER_MEMBER
        )
        self.assertEqual(
            raidcraft.MANA_POTIONS_PER_RAIDER, raidgoals.MANA_POTIONS_PER_MEMBER
        )

    def test_a_forty_man_night_is_forty_flasks_and_two_hundred_fire_potions(self):
        want = dict(raidcraft.stockpile(40))
        titans = raidcraft.by_spell(17635)
        fire = raidcraft.by_spell(17574)
        self.assertEqual(want[titans], 40)
        self.assertEqual(want[fire], 200)

    def test_the_raider_count_is_a_parameter_and_not_a_forty(self):
        """A guild of five is five flasks, and nothing here has to be edited on
        the day it is forty - the same rule raidgoals.roster_from_guild keeps."""
        five = dict(raidcraft.stockpile(5))
        self.assertEqual(five[raidcraft.by_spell(17635)], 5)

    def test_more_nights_multiply(self):
        one = dict(raidcraft.stockpile(40, 1))
        four = dict(raidcraft.stockpile(40, 4))
        titans = raidcraft.by_spell(17635)
        self.assertEqual(four[titans], one[titans] * 4)

    def test_nobody_to_count_is_a_zero_target_rather_than_a_crash(self):
        self.assertTrue(all(count == 0 for _c, count in raidcraft.stockpile(0)))

    def test_stonescale_oil_is_not_in_the_target(self):
        """Nobody drinks it - it is three of Flask of the Titans' reagents, and
        counting it separately would double it."""
        oil = raidcraft.by_spell(17551)
        self.assertEqual(oil.per_raider, 0)
        self.assertNotIn(oil, dict(raidcraft.stockpile(40)))

    def test_every_other_entry_states_a_per_raider_number(self):
        for c in raidcraft.CONSUMABLES:
            if c.spell_id == 17551:
                continue
            with self.subTest(spell=c.spell_id):
                self.assertGreater(c.per_raider, 0)

    def test_a_flask_is_one_and_an_elixir_is_two(self):
        """A flask survives death and lasts two hours; an elixir dies with the
        raider. The difference is a rule about the items, not a preference."""
        self.assertEqual(raidcraft.FLASKS_PER_RAIDER, 1)
        self.assertEqual(raidcraft.ELIXIRS_PER_RAIDER, 2)

    def test_the_default_horizon_is_one_night(self):
        self.assertEqual(raidcraft.NIGHTS_STOCKED, 1)
        self.assertEqual(
            dict(raidcraft.stockpile(40)), dict(raidcraft.stockpile(40, 1))
        )


class TheReportIsNeverSilent(unittest.TestCase):
    """The half that makes the table live rather than a document, and the same
    shape craft_rhythm.report already has for the same reason."""

    def test_it_names_every_crafter_and_the_distance(self):
        said = raidcraft.report(
            ["Ugga", "Grug"], {"Ugga": {"alchemy": 14}, "Grug": {"blacksmithing": 1}}
        )
        self.assertIn("Ugga", said)
        self.assertIn("Grug", said)
        self.assertIn("Elixir of Fortitude", said)
        self.assertIn("Solid Sharpening Stone", said)

    def test_it_counts_the_pattern_taught_blocker_every_pass(self):
        said = raidcraft.report(["Ugga"], {"Ugga": {"alchemy": 14}})
        self.assertIn("pattern item nothing here buys yet", said)

    def test_an_empty_roster_still_says_something(self):
        self.assertTrue(raidcraft.report([], {}).strip())

    def test_a_character_with_no_skills_read_still_says_something(self):
        self.assertTrue(raidcraft.report(["Ugga"], {}).strip())


class TheFirstAidLadderIsRecordedAndBlocked(unittest.TestCase):
    """The brief asked for bandage stockpiling. It is real, it is the cheapest
    raid consumable in the game, and every rung above Linen Bandage is a
    trainer purchase for every class but Death Knight - which this repo had
    already measured and which this table records rather than re-discovering."""

    def test_the_bandages_are_on_the_list(self):
        first_aid = raidcraft.for_skill("first aid")
        self.assertEqual([c.spell_id for c in first_aid], [7929, 10840, 18630])

    def test_every_bandage_needs_a_trainer(self):
        for c in raidcraft.for_skill("first aid"):
            with self.subTest(spell=c.spell_id):
                self.assertEqual(c.taught, raidcraft.TRAINER)

    def test_craft_py_still_carries_only_the_auto_learned_one(self):
        """Linen Bandage (3275) is the sole ClassMask 0 / AcquireMethod 1 rung,
        and craft.RECIPES carrying only it is the correct state, not a gap."""
        spells = {r.spell_id for r in craft.RECIPES[goals.SKILL_IDS["first aid"]]}
        self.assertEqual(spells, {3275})

    def test_the_blocker_is_the_one_professions_py_already_names(self):
        """Not a second opinion about the same wall. If that sentence ever
        stops naming the trainer, this fails and the two are reconciled."""
        self.assertIn("trainer", professions.SECONDARY_BLOCKED["first aid"])

    def test_no_bandage_is_reachable_below_first_aids_ceiling(self):
        """All five are at First Aid 1/75 and the cheapest bandage on this list
        is rank 180, so the ladder is not merely unbuilt - it is 105 points
        past a ceiling nothing can raise."""
        for c in raidcraft.for_skill("first aid"):
            with self.subTest(spell=c.spell_id):
                self.assertGreater(c.floor, 75)


if __name__ == "__main__":
    unittest.main()
