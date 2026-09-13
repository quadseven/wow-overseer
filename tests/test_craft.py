"""Which recipe a character should stand and cast, to level a crafting trade.

WHY THIS SUITE EXISTS (infra#440). craft.py answers exactly one question -
given a character who already holds a crafting skill at some value, which
recipe (if any) is worth aiming them at right now - and nothing else. The
mod_overseer.cpp side (DriveCraft) is what actually casts the spell and reads
the reagents back from the character's real bags; this module never touches
either, which is what these tests hold it to.
"""
import unittest

import craft
import goals
import professions


class RecipeForTests(unittest.TestCase):
    def test_returns_none_in_the_gap_between_two_bolt_brackets(self):
        # 101-124 is a still-deliberate gap: Silk Headband and the rest of
        # the guide's later thread/dye Tailoring recipes are deferred past
        # infra#3609's own minimum ask (Linen Belt, added directly below).
        # recipe_for must not fall back to the Silk bolt just because it is
        # close by.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 101))
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 124))

    def test_finds_linen_belt_bracket(self):
        # infra#3609's own acceptance criteria: the first Tailoring bracket
        # unblocked once craft_supply.REAGENTS could buy its thread.
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 61)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 8776)
        self.assertEqual(craft.recipe_for(goals.SKILL_IDS["tailoring"], 67).spell_id, 8776)

    def test_woolen_cloth_bracket_starts_after_linen_belt(self):
        # Woolen Cloth's own min_skill shifted from the guide's 61 to 68 to
        # make room for Linen Belt (61-67) directly below it.
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 68)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2964)

    def test_returns_none_above_every_bracket(self):
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 301))

    def test_finds_bolt_of_woolen_cloth_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 75)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2964)

    def test_finds_bolt_of_silk_cloth_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 130)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3839)

    def test_finds_bolt_of_mageweave_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 180)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3865)

    def test_finds_bolt_of_runecloth_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 255)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 18401)

    def test_returns_none_for_a_profession_with_no_entry(self):
        # Enchanting is assigned in professions.py's own ROSTER (Og) but has
        # no verified recipe in craft.RECIPES - it is not even a plain
        # SPELL_EFFECT_CREATE_ITEM output (see the module docstring on why an
        # unverified/wrong-shaped id is never guessed in rather than left
        # absent).
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["enchanting"], 1))

    def test_finds_the_bracket_a_skill_value_falls_in(self):
        # 2963, NOT 3910. Spell 3910 is named "Tailoring" in the
        # worldserver's own Spell.dbc - the Expert rank profession spell,
        # no reagents, creates nothing - so this bracket named a non-recipe
        # for its whole life and DriveCraft dropped every errand built from
        # it (infra#3689). 2963 is the real Bolt of Linen Cloth, confirmed
        # by six live casts once the id was corrected.
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2963)

    def test_no_tailoring_bracket_names_a_profession_rank_spell(self):
        # The exact shape of infra#3689: 3908/3909/3910/3911/12180/26790 are
        # the Apprentice/Journeyman/Expert/Artisan/Master/Grand Master
        # Tailoring RANK spells, not recipes. One of them sat in this table
        # labelled "Bolt of Linen Cloth" because nothing asserted the
        # difference, and a rank spell creates no item, so the bracket could
        # never have worked for anyone.
        rank_spells = {3908, 3909, 3910, 3911, 12180, 26790}
        for recipe in craft.RECIPES[goals.SKILL_IDS["tailoring"]]:
            self.assertNotIn(recipe.spell_id, rank_spells)

    def test_bracket_boundaries_are_inclusive(self):
        self.assertIsNotNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 60))
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 0))

    def test_blacksmithing_finds_the_bracket_a_skill_value_falls_in(self):
        # Grug's real starting bracket - Rough Sharpening Stone, 1-29.
        recipe = craft.recipe_for(goals.SKILL_IDS["blacksmithing"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2660)

    def test_blacksmithing_returns_none_in_an_anvil_gated_gap(self):
        # 91-124 is real skill range with real recipes (Runed Copper Belt,
        # Silver Rod, Rough Bronze Leggings) - all require an Anvil +
        # Blacksmith Hammer DriveCraft's v1 cannot satisfy, so this must stay
        # None rather than falling back to a stone recipe that would not
        # actually grant a skill-up there.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["blacksmithing"], 100))

    def test_blacksmithing_finds_the_top_bracket(self):
        # Dense Sharpening Stone, 250-260 - the highest verified entry.
        recipe = craft.recipe_for(goals.SKILL_IDS["blacksmithing"], 260)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 16641)

    def test_blacksmithing_returns_none_past_the_last_verified_bracket(self):
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["blacksmithing"], 261))

    def test_leatherworking_picks_light_leather_at_skill_1(self):
        # 3x Ruined Leather Scraps -> 1x Light Leather, spell 2881, no
        # purchased reagent - the recycle recipe every leatherworker knows.
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2881)

    def test_leatherworking_picks_light_armor_kit_mid_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 30)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2152)

    def test_leatherworking_picks_heavy_leather_at_150(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 150)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 20649)

    def test_leatherworking_1_to_300_is_covered_except_the_verified_gap(self):
        # infra#3611 closed every remaining gap EXCEPT 46-55, once
        # craft_supply.REAGENTS existed to buy thread/dye - 46-55
        # (Handstitched Leather Cloak, spell 9058) stays empty because that
        # spell id could not be confirmed against this world's live
        # database (no trainer_spell row, no pattern item) - see craft.py's
        # own comment beside that bracket. Every OTHER point in 1-300 is
        # covered (checked generally by RecipeTableDisciplineTests.
        # test_brackets_do_not_overlap_within_one_skill).
        for skill_value in range(1, 301):
            if 46 <= skill_value <= 55:
                continue
            with self.subTest(skill_value=skill_value):
                self.assertIsNotNone(
                    craft.recipe_for(goals.SKILL_IDS["leatherworking"], skill_value)
                )

    def test_the_handstitched_leather_cloak_gap_answers_none(self):
        # 46-55: spell 9058 has no trainer_spell row and no pattern item
        # teaching it on this world - unverified, so left out rather than
        # shipped on wiki-only sourcing. See craft.py's own comment.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["leatherworking"], 50))

    def test_leatherworking_picks_embossed_leather_gloves(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 100)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3756)

    def test_leatherworking_picks_fine_leather_belt(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 125)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3763)

    def test_leatherworking_picks_dark_leather_boots(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 126)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2167)

    def test_leatherworking_picks_dark_leather_pants(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 149)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 7135)

    def test_leatherworking_picks_cured_heavy_hide(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 156)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3818)

    def test_leatherworking_picks_heavy_armor_kit(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 180)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3780)

    def test_leatherworking_picks_barbaric_shoulders(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 181)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 7151)

    def test_leatherworking_picks_guardian_gloves(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 200)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 7156)

    def test_leatherworking_picks_thick_armor_kit(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 205)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 10487)

    def test_leatherworking_picks_nightscape_headband(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 235)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 10507)

    def test_leatherworking_picks_nightscape_pants(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 250)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 10548)

    def test_leatherworking_picks_nightscape_boots(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 260)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 10558)

    def test_leatherworking_picks_wicked_leather_gauntlets(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 290)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 19049)

    def test_leatherworking_picks_runic_leather_headband_at_the_top(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["leatherworking"], 300)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 19082)


class EngineeringRecipeForTests(unittest.TestCase):
    """Engineering (infra#440's follow-up) is the first skill with more than
    one bracket, so it is what actually exercises `recipe_for` picking among
    several entries rather than the trivial single-entry case Tailoring
    covers above."""

    def test_first_bracket_covers_skill_one(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3918)  # Rough Blasting Powder

    def test_a_middle_bracket_answers_its_own_value(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 200)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 12589)  # Mithril Tube

    def test_last_bracket_covers_skill_three_hundred(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 300)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 19795)  # Thorium Tube

    def test_bronze_tube_now_fills_the_106_124_bracket(self):
        # infra#3616: Weak Flux is a real, verified vendor purchase (see
        # craft_supply.REAGENT), so Bronze Tube (spell 3938) now fills the
        # bracket that used to answer None here.
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 115)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3938)

    def test_standard_scope_is_still_deliberately_deferred(self):
        # Standard Scope's own reagent, Moss Agate, was checked against
        # acore_world.npc_vendor directly and found NOT vendor-sold (a mined
        # gem, not a general good) - so unlike Bronze Tube it stays out of
        # RECIPES, and skill 125 still answers with Heavy Blasting Powder's
        # own bracket rather than a Standard Scope entry that could never
        # complete. See craft.py's module-level comment.
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 125)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3945)  # Heavy Blasting Powder

    def test_the_explosive_sheep_chain_gap_answers_none(self):
        # 151-174: Whirring Bronze Gizmo / Bronze Framework / Explosive Sheep
        # collide with Heavy Blasting Powder's own skill window and cannot
        # all be stocked by this module's one-recipe-per-bracket model - see
        # craft.py's module-level comment.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["engineering"], 160))


class ToolRecipeTests(unittest.TestCase):
    """The tool-vs-consumable distinction (infra#440's Engineering follow-up):
    a recipe that creates a permanent tool, not something to spam, is marked
    `repeatable=False` and MUST use a single-skill-point bracket - that
    narrow bracket, not an inventory check this module cannot make, is what
    stops DriveCraft from recasting it once the skill-up lands."""

    def test_every_non_repeatable_recipe_has_a_single_point_bracket(self):
        for recipes in craft.RECIPES.values():
            for recipe in recipes:
                if not recipe.repeatable:
                    self.assertEqual(
                        recipe.min_skill, recipe.max_skill,
                        f"{recipe.name} is marked repeatable=False but spans "
                        f"more than one skill point - it would be recast "
                        f"like a consumable"
                    )

    def test_arclight_spanner_is_marked_not_repeatable(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 51)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 7430)
        self.assertFalse(recipe.repeatable)

    def test_gyromatic_micro_adjustor_is_marked_not_repeatable(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["engineering"], 195)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 12590)
        self.assertFalse(recipe.repeatable)

    def test_ordinary_consumable_recipes_default_to_repeatable(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 1)
        self.assertTrue(recipe.repeatable)


class AlchemyRecipeForTests(unittest.TestCase):
    """One assertion per bracket - the full skill 1-300 Alchemy progression,
    verified against real spell/reagent data (see craft.RECIPES's own
    comment). Boundaries checked explicitly since the brackets abut without
    overlapping (RecipeTableDisciplineTests.test_brackets_do_not_overlap
    already holds the general shape; this pins the actual numbers)."""

    def test_minor_healing_potion_covers_1_to_59(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 1).spell_id, 2330)
        self.assertEqual(craft.recipe_for(alchemy, 59).spell_id, 2330)

    def test_lesser_healing_potion_covers_60_to_109(self):
        # THE POTION-AS-REAGENT BRACKET: this recipe's own reagent is the
        # previous recipe's output (1x Minor Healing Potion), not a raw herb.
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 60).spell_id, 2337)
        self.assertEqual(craft.recipe_for(alchemy, 109).spell_id, 2337)

    def test_healing_potion_covers_110_to_139(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 110).spell_id, 3447)
        self.assertEqual(craft.recipe_for(alchemy, 139).spell_id, 3447)

    def test_lesser_mana_potion_covers_140_to_154(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 140).spell_id, 3173)
        self.assertEqual(craft.recipe_for(alchemy, 154).spell_id, 3173)

    def test_greater_healing_potion_covers_155_to_184(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 155).spell_id, 7181)
        self.assertEqual(craft.recipe_for(alchemy, 184).spell_id, 7181)

    def test_elixir_of_agility_covers_185_to_209(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 185).spell_id, 11449)
        self.assertEqual(craft.recipe_for(alchemy, 209).spell_id, 11449)

    def test_elixir_of_greater_defense_covers_210_to_214(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 210).spell_id, 11450)
        self.assertEqual(craft.recipe_for(alchemy, 214).spell_id, 11450)

    def test_superior_healing_potion_covers_215_to_229(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 215).spell_id, 11457)
        self.assertEqual(craft.recipe_for(alchemy, 229).spell_id, 11457)

    def test_elixir_of_detect_undead_covers_230_to_264(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 230).spell_id, 11460)
        self.assertEqual(craft.recipe_for(alchemy, 264).spell_id, 11460)

    def test_superior_mana_potion_covers_265_to_284(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 265).spell_id, 17553)
        self.assertEqual(craft.recipe_for(alchemy, 284).spell_id, 17553)

    def test_major_healing_potion_covers_285_to_300(self):
        alchemy = goals.SKILL_IDS["alchemy"]
        self.assertEqual(craft.recipe_for(alchemy, 285).spell_id, 17556)
        self.assertEqual(craft.recipe_for(alchemy, 300).spell_id, 17556)

    def test_nothing_above_300(self):
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["alchemy"], 301))


class CraftErrandTests(unittest.TestCase):
    def test_zero_for_a_character_with_no_crafting_trade(self):
        # Og holds tailoring + enchanting (professions.ROSTER). Tailoring at
        # 0 means "not learned yet" (professions.py's trainer errand owns
        # that), and enchanting still has no craft.RECIPES entry (a
        # non-CREATE_ITEM output, flagged deferred in the design doc) - so
        # this must fall all the way through to 0, never a guessed spell id.
        # No secondary (First Aid/Cooking) keys are given, so the fallback
        # below this loop also finds nothing learned.
        self.assertEqual(craft.craft_errand("Og", {"tailoring": 0, "enchanting": 1}), 0)

    def test_zero_for_a_trade_not_yet_learned(self):
        # Og is assigned tailoring but a skill value of 0 means the trainer
        # errand has not landed yet - craft.py must never invent a recipe for
        # a trade nobody has learned. professions.assigned("Og") includes
        # "tailoring" per the family's real assignment table.
        self.assertEqual(craft.craft_errand("Og", {"tailoring": 0}), 0)

    def test_finds_the_recipe_for_a_learned_crafting_trade(self):
        # Og: tailoring + enchanting. tailoring has a verified recipe;
        # enchanting does not (it is also a non-CREATE_ITEM output, flagged as
        # deferred in the design doc), so the learned tailoring value must be
        # what answers this.
        spell_id = craft.craft_errand("Og", {"tailoring": 1, "enchanting": 1})
        self.assertEqual(spell_id, 2963)

    def test_finds_the_alchemy_recipe_for_uggas_learned_trade(self):
        # Ugga: herbalism + alchemy (professions.ROSTER) - herbalism is a
        # GATHERING trade with no craft.RECIPES entry (it climbs on its own
        # per the module docstring), so the learned alchemy value must be
        # what answers this.
        spell_id = craft.craft_errand("Ugga", {"herbalism": 132, "alchemy": 60})
        self.assertEqual(spell_id, 2337)  # Lesser Healing Potion's bracket

    def test_finds_the_leatherworking_recipe_for_bork(self):
        # Bork: skinning + leatherworking (professions.ROSTER). Skinning is a
        # GATHERING trade with no craft.RECIPES entry, so the leatherworking
        # value is what must answer this.
        spell_id = craft.craft_errand("Bork", {"skinning": 40, "leatherworking": 1})
        self.assertEqual(spell_id, 2881)

    def test_never_answers_for_a_trade_this_character_does_not_hold(self):
        # Grug is assigned mining + blacksmithing (a GATHERING trade and a
        # CRAFTING one that now has verified recipe entries). Even if
        # `skills` claimed a tailoring value (bad data from a stale row,
        # say), craft_errand must not answer with a tailoring recipe for a
        # character professions.py never assigned it - the same permission
        # discipline professions.py itself holds for `wanted`.
        spell_id = craft.craft_errand("Grug", {"mining": 8, "tailoring": 50})
        self.assertEqual(spell_id, 0)

    def test_finds_grogs_engineering_recipe(self):
        # Grog: mining + engineering (professions.ROSTER). mining is a
        # GATHERING trade with no craft.RECIPES entry; engineering now has a
        # full bracket table, so his engineering value must be what answers
        # this.
        spell_id = craft.craft_errand("Grog", {"mining": 40, "engineering": 1})
        self.assertEqual(spell_id, 3918)  # Rough Blasting Powder

    def test_finds_the_recipe_for_grugs_blacksmithing(self):
        # Grug: mining + blacksmithing. mining is a GATHERING trade with no
        # RECIPES entry (it climbs on its own, per the module docstring);
        # blacksmithing now has Rough Sharpening Stone at 1-29.
        spell_id = craft.craft_errand("Grug", {"mining": 8, "blacksmithing": 1})
        self.assertEqual(spell_id, 2660)


class FirstAidAndCookingTests(unittest.TestCase):
    """infra#2757's Cooking/First Aid slice - the two SECONDARY skills every
    family character already holds, verified independently of the
    per-character CRAFTING assignment `professions.assigned` gates."""

    def test_finds_linen_bandage_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["first aid"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3275)

    def test_linen_bandage_runs_to_its_real_grey_value(self):
        """59, not 39 (infra#3614).

        `SkillLineAbility.dbc` from the running worldserver gives 3275 a grey
        (TrivialSkillLineRankHigh) of 60, so 59 is the last value it can still
        grant a point at. The old 39 was not a measurement of 3275 at all - it
        was where Heavy Linen Bandage used to take over, and that recipe is a
        trainer purchase this family cannot reach.
        """
        first_aid = goals.SKILL_IDS["first aid"]
        for value in (1, 39, 40, 59):
            with self.subTest(value=value):
                recipe = craft.recipe_for(first_aid, value)
                self.assertIsNotNone(recipe)
                self.assertEqual(recipe.spell_id, 3275)

    def test_nothing_past_linen_bandages_grey(self):
        # 60 is 3275's grey value: it stops granting skill-ups there, and no
        # other First Aid recipe is reachable without a Journeyman trainer
        # (infra#3614, mod-overseer#454). Better no errand than a cast that
        # consumes cloth for nothing.
        for value in (60, 74, 75):
            with self.subTest(value=value):
                self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["first aid"], value))

    def test_no_heavy_linen_bandage_bracket_at_any_value(self):
        """3276 is a trainer purchase for every class this family has.

        Its auto-learn SkillLineAbility row is ClassMask 0x20 - Death Knight
        and nothing else. The all-class row (ClassMask 0x5DF) is
        AcquireMethod 0, i.e. `trainer_spell` at ReqSkillRank 40 for 100
        copper, and the nearest Alliance-usable First Aid trainer is 15,513
        yards across an ocean `ResolveTravelTarget` refuses (infra#3732).
        Naming it here produces a `craft_spell` DriveCraft drops as a planner
        bug, which is how First Aid came to stall silently at 39.
        """
        first_aid = goals.SKILL_IDS["first aid"]
        named = {r.spell_id for r in craft.RECIPES[first_aid]}
        self.assertNotIn(3276, named)
        for value in range(1, 76):
            recipe = craft.recipe_for(first_aid, value)
            if recipe is not None:
                self.assertNotEqual(recipe.spell_id, 3276)

    def test_cooking_has_no_reachable_bracket_at_all(self):
        """Every Cooking recipe below the 75 cap needs a Cooking Fire.

        Read off `SkillLineAbility.dbc` joined to `Spell.dbc` from the running
        worldserver: all 181 abilities on skill 185, and every one that
        creates an item and is reachable below 75 carries
        `RequiresSpellFocus = 4`. DriveCraft casts in place, so an entry here
        would sit refused for ever. The table carries none rather than one
        that looks right and produces nothing.
        """
        self.assertEqual(craft.RECIPES[goals.SKILL_IDS["cooking"]], ())
        for value in (1, 50, 51, 75):
            with self.subTest(value=value):
                self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["cooking"], value))

    def test_craft_errand_finds_first_aid_for_a_character_assigned_no_primary_with_recipe(self):
        # Grug: assigned mining + blacksmithing (professions.ROSTER), neither
        # of which has a craft.RECIPES entry, so the primary loop finds
        # nothing - but every character, Grug included, already holds First
        # Aid, so the secondary fallthrough must answer with it.
        spell_id = craft.craft_errand("Grug", {"mining": 8, "first aid": 1})
        self.assertEqual(spell_id, 3275)

    def test_craft_errand_prefers_a_live_primary_recipe_over_a_secondary_one(self):
        # Og: assigned tailoring, which DOES have a verified recipe - that
        # must win over First Aid even though Og also holds First Aid, same
        # "one craft_spell at a time" contract craft_errand always had.
        spell_id = craft.craft_errand(
            "Og", {"tailoring": 1, "first aid": 1, "cooking": 1}
        )
        self.assertEqual(spell_id, 2963)

    def test_craft_errand_zero_for_first_aid_not_yet_learned(self):
        # A value of 0 means the trainer errand has not landed yet, the same
        # rule craft_errand already holds for a primary trade - never invent
        # a recipe for a skill nobody has actually trained.
        spell_id = craft.craft_errand("Grug", {"mining": 8, "first aid": 0})
        self.assertEqual(spell_id, 0)

    def test_craft_errand_is_silent_once_first_aid_is_past_its_grey(self):
        """There is nothing to fall through TO, and that is the honest answer.

        This test used to assert a fall-through to Charred Wolf Meat (2538).
        That recipe needed a Cooking Fire the system cannot light, so the
        fall-through delivered a permanently refused cast dressed as progress.
        0 means "no standing craft errand" - the schema's own sentinel - and a
        caller that wants to know WHY asks
        `professions.SECONDARY_BLOCKED['cooking']`.
        """
        spell_id = craft.craft_errand(
            "Grug", {"mining": 8, "first aid": 60, "cooking": 1}
        )
        self.assertEqual(spell_id, 0)

    def test_cooking_never_shadows_first_aid_in_the_secondary_fallthrough(self):
        """The ordering defect the Cooking entry was hiding (infra#3614).

        `craft_errand` walks `sorted(professions.SECONDARY)`, and "cooking"
        sorts before "first aid". So for as long as Cooking carried a bracket
        at value 1, every character reaching the secondary fall-through got
        the focus-gated Cooking recipe and First Aid was never consulted at
        all - the castable recipe was shadowed by the inert one.
        """
        self.assertLess(
            sorted(professions.SECONDARY).index("cooking"),
            sorted(professions.SECONDARY).index("first aid"),
            "if this ever stops being true the shadowing below changes shape",
        )
        spell_id = craft.craft_errand(
            "Grug", {"mining": 8, "first aid": 1, "cooking": 1}
        )
        self.assertEqual(spell_id, 3275)


class RecipeTableDisciplineTests(unittest.TestCase):
    """The module's own stated rule: one verified entry beats five guessed
    ones. This suite is what keeps a future edit honest about that."""

    def test_every_recipe_has_a_positive_spell_id(self):
        for recipes in craft.RECIPES.values():
            for recipe in recipes:
                self.assertGreater(recipe.spell_id, 0)

    def test_every_recipe_key_is_a_real_crafting_or_secondary_skill(self):
        # CRAFTING (a primary, slot-costing trade) and SECONDARY (First Aid /
        # Cooking / Fishing, free and held by everyone) are the only two
        # kinds of skill craft_errand ever answers for - see its own
        # docstring. A key that is neither is a typo, not a new profession.
        real_ids = {
            goals.SKILL_IDS[name]
            for name in professions.CRAFTING | professions.SECONDARY
            if name in goals.SKILL_IDS
        }
        for skill_id in craft.RECIPES:
            self.assertIn(skill_id, real_ids)

    def test_brackets_do_not_overlap_within_one_skill(self):
        for recipes in craft.RECIPES.values():
            ordered = sorted(recipes, key=lambda r: r.min_skill)
            for a, b in zip(ordered, ordered[1:]):
                self.assertLess(a.max_skill, b.min_skill)


class TheModeConstant(unittest.TestCase):
    def test_it_matches_the_vocabulary(self):
        import jobs
        self.assertEqual(craft.MODE, "craft")
        self.assertIn(craft.MODE, jobs.MODES)
        self.assertIn(craft.MODE, jobs.IMPLEMENTED)


class NoForecastOfTheWorldserversAnswer(unittest.TestCase):
    """infra#3695. This pins an ABSENCE, deliberately, because the thing it
    forbids is the thing two agents reached for on the same afternoon.

    A `craft.readiness()` that asked whether each character knows its recipe -
    reading `character_spell` - was written, tested, and was WRONG: every row
    said nobody knew anything while Ugga was crafting Minor Healing Potions
    (2330) seven times over. mod-playerbots grants recipes at runtime and
    `Player::_SaveSpells` never persists them, so the saved tables are partial
    in exactly the direction that turns a guard into a false refusal.

    `Player::HasSpell` is what DriveCraft gates on and it reads live memory.
    Python cannot see that, so Python must not pretend to predict it. If a
    readiness answer is ever wanted here it has to consume DriveCraft's own
    recorded outcome, not forecast it.
    """

    def test_craft_exposes_no_readiness_predicate(self):
        self.assertFalse(
            hasattr(craft, "readiness"),
            "craft.readiness() forecasts DriveCraft's HasSpell check from "
            "saved tables that omit runtime-granted recipes - see this class's "
            "docstring and craft.py's header before re-adding it",
        )

    def test_the_module_records_why(self):
        import inspect
        source = inspect.getsource(craft)
        self.assertIn("3695", source)
        self.assertIn("_SaveSpells", source)


class SpellFocusTests(unittest.TestCase):
    """No recipe in this table may need a forge, an anvil or a loom.

    WHY THIS IS A TEST AND NOT A COMMENT (infra#3738). DriveCraft casts in
    place: it does not walk anyone to a spell-focus gameobject, and the core's
    own CheckCast refuses a recipe that needs one with
    SPELL_FAILED_REQUIRES_SPELL_FOCUS. mod-overseer does not clear the errand
    on that refusal and does not distinguish it from a cooldown in the log - it
    records a bare numeric SpellCastResult at INFO and retries every twenty
    seconds - so a focus-gated entry added here would not fail loudly. It would
    sit in the table looking correct and produce nothing, for ever, while the
    log said something that reads like a transient.

    craft.py has always asserted "no focus needed" in each entry's `note`, but
    a note is free prose the module's own docstring says is "for a human
    reading this table, not for anything the code checks". infra#3738 then
    proposed adding a smelt recipe, every one of which requires a Forge
    (Spell.dbc RequiresSpellFocus = 3). That is the change this class exists to
    refuse until something can stand a character next to one.
    """

    def test_no_recipe_requires_a_spell_focus(self):
        for skill_id, recipes in craft.RECIPES.items():
            for recipe in recipes:
                with self.subTest(skill=skill_id, recipe=recipe.name):
                    self.assertEqual(
                        recipe.focus, 0,
                        f"{recipe.name} (spell {recipe.spell_id}) declares "
                        f"focus={recipe.focus}, so CheckCast will refuse it "
                        "unless the character is standing next to that "
                        "SpellFocusObject. DriveCraft does not walk anyone "
                        "anywhere. Land the forge/anvil aim first - see "
                        "craft.py's MINING AND SMELTING comment - then teach "
                        "the caller to honour this field.",
                    )

    def test_no_recipe_is_a_smelt_spell(self):
        # The specific ids infra#3738 proposed, plus the whole classic smelt
        # chain around them, read off the running worldserver's Spell.dbc.
        # 2659 is Smelt Bronze, NOT Smelt Copper as that issue states; Smelt
        # Copper is 2657. Both are Forge-gated, as is every other entry here.
        smelt_spells = {
            2657: "Smelt Copper", 2658: "Smelt Silver", 2659: "Smelt Bronze",
            3304: "Smelt Tin", 3307: "Smelt Iron", 3308: "Smelt Gold",
            3569: "Smelt Steel", 10097: "Smelt Mithril",
            10098: "Smelt Truesilver", 16153: "Smelt Thorium",
        }
        named = {
            recipe.spell_id
            for recipes in craft.RECIPES.values()
            for recipe in recipes
        }
        clash = named & set(smelt_spells)
        self.assertFalse(
            clash,
            "RECIPES names %s, which are Forge-gated smelt spells "
            "(RequiresSpellFocus = 3). See craft.py's MINING AND SMELTING "
            "comment." % sorted(
                "%d (%s)" % (spell, smelt_spells[spell]) for spell in clash),
        )

    def test_no_cooking_recipe_needs_a_fire(self):
        """The sibling of the smelt refusal, for focus 4 (infra#3614).

        WHY THIS EXISTS SEPARATELY FROM `test_no_recipe_requires_a_spell_focus`
        ABOVE, and it is the hole that let an inert recipe ship. That test
        compares `recipe.focus` against 0 - which is to say it compares the
        declared field against itself. `Recipe.focus` defaults to 0, so an
        entry written before the field existed, or one added by someone who
        never looked the spell up, declares 0 and passes while the worldserver
        refuses it every twenty seconds. Charred Wolf Meat (2538) sat in this
        table in exactly that state: declared 0, `Spell.dbc` says 4.

        So this test pins ids, the way `test_no_recipe_is_a_smelt_spell` does,
        because an id is a fact a future edit cannot accidentally re-declare.
        Every value below was read off `Spell.dbc` and `SpellFocusObject.dbc`
        pulled from the running worldserver, with the parse proved first
        against this table's own anchor (2963 -> Reagent[0]=2589,
        ReagentCount[0]=2).

        37836 (Spice Bread) is on the list deliberately. infra#3732 called it
        "the cheapest real point of secondary progress available" because the
        family demonstrably owns it - and it is focus 4 like the rest, with a
        yellow/grey of 30/40 that is shorter than the Charred Wolf Meat it
        would have replaced. It is a worse version of the same mistake, and
        this test is what says no to it.
        """
        fire_spells = {
            2538: "Charred Wolf Meat", 2540: "Roasted Boar Meat",
            3370: "Crocolisk Steak", 3371: "Blood Sausage",
            3372: "Murloc Fin Soup", 3373: "Crocolisk Gumbo",
            3376: "Curiously Tasty Omelet", 3377: "Gooey Spider Cake",
            3397: "Big Bear Steak", 3398: "Hot Lion Chops",
            6412: "Kaldorei Spider Kabob", 6413: "Scorpid Surprise",
            6414: "Roasted Kodo Meat", 6415: "Fillet of Frenzy",
            6416: "Strider Stew", 6417: "Dig Rat Stew",
            7751: "Brilliant Smallfish", 7752: "Slitherskin Mackerel",
            37836: "Spice Bread",
        }
        named = {
            recipe.spell_id
            for recipes in craft.RECIPES.values()
            for recipe in recipes
        }
        clash = named & set(fire_spells)
        self.assertFalse(
            clash,
            "RECIPES names %s, which require a Cooking Fire "
            "(RequiresSpellFocus = 4, SpellFocusObject.dbc id 4). Nothing in "
            "this system lights one. See craft.py's COOKING comment for the "
            "single cast (spell 818, gameobject 29784, ten-yard radius) that "
            "would." % sorted(
                "%d (%s)" % (spell, fire_spells[spell]) for spell in clash),
        )

    def test_the_module_records_the_forge_finding(self):
        # The measurements behind the refusal above are the expensive part of
        # infra#3738 and the reason it will not be re-litigated from a wiki.
        import inspect
        source = inspect.getsource(craft)
        self.assertIn("3738", source)
        self.assertIn("RequiresSpellFocus", source)
        self.assertIn("2657", source)

    def test_the_module_records_the_cooking_fire_finding(self):
        # Same reason as the forge finding above: the campfire measurement
        # (spell 818 -> gameobject 29784, type 8 / Data0 4 / Data1 10) is the
        # expensive part of infra#3614, and it is what stops the next reader
        # concluding that Cooking is merely missing a bracket.
        import inspect
        source = inspect.getsource(craft)
        self.assertIn("818", source)
        self.assertIn("29784", source)
        self.assertIn("Cooking Fire", source)


if __name__ == "__main__":
    unittest.main()
