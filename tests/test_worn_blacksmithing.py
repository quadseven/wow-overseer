"""Test Blacksmith Hammer buying and worn blacksmithing recipes.

Every fixture below is a fact measured on the live wow-dev roster the night
this module was written, not an invented number.

Blacksmith Hammer 5956: read from acore_world.item_template
Green Dye 2605: read from acore_world.item_template
"""

import unittest

import craft_supply
from towntrip import Town

HAMMER = 5956
GREEN_DYE = 2605

HAMMER_PRICE = 0
HAMMER_STOCKS = frozenset()

DYE_PRICE = 0
DYE_STOCKS = frozenset()


def town_with_hammer():
    return Town(repairs=False, stocks=frozenset(HAMMER_STOCKS), vendor=bool(HAMMER_STOCKS))


def town_with_dye():
    return Town(repairs=False, stocks=frozenset(DYE_STOCKS), vendor=bool(DYE_STOCKS))


def town_with_both():
    return Town(repairs=False, stocks=frozenset(HAMMER_STOCKS | DYE_STOCKS), vendor=bool(HAMMER_STOCKS | DYE_STOCKS))


class HammerBuyTests(unittest.TestCase):
    def test_hammer_not_in_reagents(self):
        hammer_in_reagents = HAMMER in craft_supply.REAGENTS
        self.assertFalse(hammer_in_reagents)

    def test_buy_hammer_when_needed(self):
        errand, note = craft_supply.reagent_errand(
            "Og",
            HAMMER,
            held=0,
            money=100_000,
            free_slots=10,
            town=town_with_hammer(),
        )
        self.assertIsNone(note)
        self.assertIsNotNone(errand)
        self.assertEqual(errand.member, "Og")
        self.assertEqual(errand.kind, "buy")
        self.assertEqual(errand.command, "entry:5956 count:5 max:0")

    def test_hammer_not_bought_when_already_held(self):
        errand, note = craft_supply.reagent_errand(
            "Og",
            HAMMER,
            held=5,
            money=100_000,
            free_slots=10,
            town=town_with_hammer(),
        )
        self.assertIsNone(errand)
        self.assertIsNone(note)


class DyeBuyTests(unittest.TestCase):
    def test_green_dye_not_in_reagents(self):
        dye_in_reagents = GREEN_DYE in craft_supply.REAGENTS
        self.assertFalse(dye_in_reagents)

    def test_buy_green_dye_when_needed(self):
        errand, note = craft_supply.reagent_errand(
            "Og",
            GREEN_DYE,
            held=0,
            money=100_000,
            free_slots=10,
            town=town_with_dye(),
        )
        self.assertIsNone(note)
        self.assertIsNotNone(errand)
        self.assertEqual(errand.member, "Og")
        self.assertEqual(errand.kind, "buy")
        self.assertEqual(errand.command, "entry:2605 count:5 max:0")

    def test_green_dye_not_bought_when_already_held(self):
        errand, note = craft_supply.reagent_errand(
            "Og",
            GREEN_DYE,
            held=5,
            money=100_000,
            free_slots=10,
            town=town_with_dye(),
        )
        self.assertIsNone(errand)
        self.assertIsNone(note)


class WornRecipesTests(unittest.TestCase):
    def test_runed_copper_belt_exists(self):
        import craft

        spell_id = 2666
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 80)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_silver_rod_exists(self):
        import craft

        spell_id = 7818
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_rough_bronze_leggings_exists(self):
        import craft

        spell_id = 2668
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 95)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_patterned_bronze_bracers_exists(self):
        import craft

        spell_id = 2672
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 120)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_golden_rod_exists(self):
        import craft

        spell_id = 14379
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_green_iron_leggings_exists(self):
        import craft

        spell_id = 3506
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_green_iron_bracers_exists(self):
        import craft

        spell_id = 3501
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 1)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_golden_scale_bracers_exists(self):
        import craft

        spell_id = 7223
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 210)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_heavy_mithril_gauntlet_exists(self):
        import craft

        spell_id = 9928
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 225)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_steel_plate_helm_exists(self):
        import craft

        spell_id = 9935
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 235)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_mithril_spurs_exists(self):
        import craft

        spell_id = 9964
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 255)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_imperial_plate_bracers_exists(self):
        import craft

        spell_id = 16649
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 290)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)

    def test_imperial_plate_boots_exists(self):
        import craft

        spell_id = 16657
        recipe = craft.recipe_for(craft.SKILL_IDS["blacksmithing"], 315)
        self.assertIsNotNone(recipe)
        self.assertEqual(recipe.spell_id, spell_id)
