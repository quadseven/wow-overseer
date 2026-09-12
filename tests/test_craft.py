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
        # 61-124 is a deliberate gap: the recipe worth casting there needs
        # vendor-bought thread (Linen Belt), which this pass explicitly
        # deferred rather than guess a spell id for. recipe_for must not
        # fall back to the Woolen bolt just because it is close by.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 101))
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 124))

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
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3910)

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

    def test_leatherworking_gap_between_45_and_150_answers_none(self):
        # The guide's own bracket table has no zero-purchased-reagent recipe
        # between Light Armor Kit (ends 45) and Heavy Leather (starts 150) -
        # everything in between needs vendor-bought thread or dye, deferred
        # per this pass's scoping (see the RECIPES table comment). A gap must
        # answer None, never a stale or wrong-bracket recipe.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["leatherworking"], 100))


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

    def test_a_deliberately_deferred_gap_answers_none(self):
        # 106-124: Bronze Tube / Standard Scope need a vendor-bought reagent
        # (Weak Flux / Moss Agate) this pass does not reach - see craft.py's
        # module-level comment. None is the honest answer here, not a guess.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["engineering"], 115))

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
        self.assertEqual(spell_id, 3910)

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

    def test_finds_heavy_linen_bandage_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["first aid"], 74)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3276)

    def test_nothing_past_apprentice_first_aid_cap(self):
        # 75 is Apprentice's own live-verified cap (character_skills.max) -
        # a character sitting there needs a Journeyman trainer visit before
        # anything else is worth casting, not a wasted recipe that grants no
        # skill-up.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["first aid"], 75))

    def test_finds_charred_wolf_meat_bracket(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["cooking"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 2538)

    def test_nothing_past_the_one_verified_cooking_bracket(self):
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["cooking"], 51))

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
        self.assertEqual(spell_id, 3910)

    def test_craft_errand_zero_for_first_aid_not_yet_learned(self):
        # A value of 0 means the trainer errand has not landed yet, the same
        # rule craft_errand already holds for a primary trade - never invent
        # a recipe for a skill nobody has actually trained.
        spell_id = craft.craft_errand("Grug", {"mining": 8, "first aid": 0})
        self.assertEqual(spell_id, 0)

    def test_craft_errand_falls_through_to_cooking_when_first_aid_is_capped(self):
        spell_id = craft.craft_errand(
            "Grug", {"mining": 8, "first aid": 75, "cooking": 1}
        )
        self.assertEqual(spell_id, 2538)


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


if __name__ == "__main__":
    unittest.main()
