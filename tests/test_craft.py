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
        # Blacksmithing is assigned in professions.py's own ROSTER but has no
        # verified recipe in craft.RECIPES yet - see the module docstring on
        # why an unverified id is never guessed in rather than left absent.
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["blacksmithing"], 1))

    def test_finds_the_bracket_a_skill_value_falls_in(self):
        recipe = craft.recipe_for(goals.SKILL_IDS["tailoring"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, 3910)

    def test_bracket_boundaries_are_inclusive(self):
        self.assertIsNotNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 60))
        self.assertIsNone(craft.recipe_for(goals.SKILL_IDS["tailoring"], 0))


class CraftErrandTests(unittest.TestCase):
    def test_zero_for_a_character_with_no_crafting_trade(self):
        # Ugga holds herbalism + alchemy (professions.ROSTER) - a GATHERING
        # trade and one with no craft.RECIPES entry, so this must be 0, never
        # a guessed spell id for either.
        self.assertEqual(craft.craft_errand("Ugga", {"herbalism": 132, "alchemy": 1}), 0)

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

    def test_never_answers_for_a_trade_this_character_does_not_hold(self):
        # Grug is assigned mining + blacksmithing (a GATHERING trade and a
        # CRAFTING one with no recipe entry yet). Even if `skills` claimed a
        # tailoring value (bad data from a stale row, say), craft_errand must
        # not answer with a tailoring recipe for a character professions.py
        # never assigned it - the same permission discipline professions.py
        # itself holds for `wanted`.
        spell_id = craft.craft_errand("Grug", {"mining": 8, "tailoring": 50})
        self.assertEqual(spell_id, 0)


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
