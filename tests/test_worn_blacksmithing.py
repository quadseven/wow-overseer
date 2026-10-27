"""The Blacksmith Hammer buy, Green Dye and the worn Blacksmithing recipes.

Item facts below were read from acore_world.item_template on the dev realm:
Blacksmith Hammer 5956 (BuyPrice 18, 206 vendor rows, all unlimited) and
Green Dye 2605 (BuyPrice 100, 87 vendor rows, all unlimited). Spell ids, bar
counts and output items were checked against wowhead.com/wotlk and
classicdb.ch.
"""

import typing
import unittest
from unittest import mock

import craft
import craft_supply
import goals
from towntrip import Town

BLACKSMITHING = goals.SKILL_IDS["blacksmithing"]
HAMMER = 5956
GREEN_DYE = 2605
BELT = 2666  # Runed Copper Belt, a hammer recipe
STONE = 3337  # Heavy Grinding Stone, no hammer


def town(*stocks):
    return Town(repairs=False, stocks=frozenset(stocks), vendor=bool(stocks))


class HammerBuyTests(unittest.TestCase):
    def buy(self, spell=BELT, held=False, money=1000, slots=5, at=(HAMMER,)):
        return craft_supply.hammer_errand("Og", spell, held, money, slots, town(*at))

    def test_a_smith_with_no_hammer_gets_one_buy_row(self):
        errand, note = self.buy()
        self.assertIsNone(note)
        self.assertEqual(errand.kind, "buy")
        self.assertEqual(errand.member, "Og")
        self.assertEqual(errand.command, "entry:5956 count:1 max:18")

    def test_no_second_buy_while_one_is_held(self):
        self.assertEqual(self.buy(held=True), (None, None))

    def test_a_recipe_without_the_tool_buys_nothing(self):
        self.assertEqual(self.buy(spell=STONE), (None, None))

    def test_no_vendor_in_reach_is_a_note(self):
        errand, note = self.buy(at=())
        self.assertIsNone(errand)
        self.assertIn("no reachable vendor", note)

    def test_a_full_bag_is_a_note(self):
        errand, note = self.buy(slots=0)
        self.assertIsNone(errand)
        self.assertIn("no free bag slot", note)

    def test_a_short_purse_is_a_note(self):
        errand, note = self.buy(money=17)
        self.assertIsNone(errand)
        self.assertIn("cannot afford", note)

    def test_the_need_walks_only_when_nothing_in_reach_sells_one(self):
        need = craft_supply.hammer_need("Og", BELT, False, town())
        self.assertEqual((need.shopper, need.entry), ("Og", HAMMER))
        self.assertIsNone(craft_supply.hammer_need("Og", BELT, False, town(HAMMER)))
        self.assertIsNone(craft_supply.hammer_need("Og", BELT, True, town()))
        self.assertIsNone(craft_supply.hammer_need("Og", STONE, False, town()))

    def test_the_need_says_it_may_be_none(self):
        # The contract is spoken in the signature, not only the docstring: a
        # caller (bridge._buy_blacksmith_hammers) must handle None.
        hints = typing.get_type_hints(craft_supply.hammer_need)
        self.assertEqual(hints.get("return"), craft_supply.Need | None)


class GreenDyeTests(unittest.TestCase):
    def test_both_green_iron_recipes_buy_one_dye_per_cast(self):
        for spell in (3506, 3501):
            with self.subTest(spell=spell):
                self.assertEqual(
                    craft_supply.REAGENTS[spell], ((GREEN_DYE, "Green Dye", 100, 1),)
                )

    def test_dye_is_bought_up_to_five_casts(self):
        errands, notes = craft_supply.craft_reagent_errands(
            "Og", 3501, {GREEN_DYE: 0}, 10_000, 5, town(GREEN_DYE)
        )
        self.assertEqual(notes, [])
        self.assertEqual(errands[0].command, "entry:2605 count:5 max:500")


# spell, name, min_skill, max_skill
WORN = (
    (7818, "Silver Rod", 100, 109),
    (2666, "Runed Copper Belt", 110, 124),
    (14379, "Golden Rod", 150, 159),
    (2668, "Rough Bronze Leggings", 160, 174),
    (2672, "Patterned Bronze Bracers", 175, 179),
    (3506, "Green Iron Leggings", 180, 189),
    (3501, "Green Iron Bracers", 190, 199),
    (7223, "Golden Scale Bracers", 210, 224),
    (9928, "Heavy Mithril Gauntlet", 225, 234),
    (9935, "Steel Plate Helm", 235, 249),
    (9964, "Mithril Spurs", 260, 274),
    (16649, "Imperial Plate Bracers", 275, 299),
    (16657, "Imperial Plate Boots", 300, 300),
)


def hammer_walked():
    """The world after the Anvil walk is live: the hammer is a walked tool."""
    return mock.patch.object(craft, "TOOL_WALKS", frozenset({HAMMER}))


class TheHammerRecipesWaitForTheAnvilWalk(unittest.TestCase):
    """Until craft.TOOL_WALKS names the hammer, nothing walks a smith to an
    Anvil, so no hammer recipe is handed out and the Anvil gaps stay None."""

    def test_the_gate_is_shut_today(self):
        self.assertNotIn(HAMMER, craft.TOOL_WALKS)

    def test_recipe_for_never_returns_a_hammer_recipe(self):
        for _spell, name, low, high in WORN:
            for value in (low, high):
                with self.subTest(name=name, value=value):
                    recipe = craft.recipe_for(BLACKSMITHING, value)
                    self.assertTrue(recipe is None or not recipe.tool)

    def test_a_smith_in_an_anvil_gap_gets_no_hammer_errand(self):
        spell = craft.craft_errand("Grug", {"blacksmithing": 110}, ("blacksmithing",))
        self.assertNotEqual(craft.tool_for(spell), HAMMER)

    def test_a_hammer_recipe_is_not_walked(self):
        belt = next(r for r in craft.RECIPES[BLACKSMITHING] if r.spell_id == BELT)
        self.assertFalse(craft.walked(belt))
        with hammer_walked():
            self.assertTrue(craft.walked(belt))


class WornRecipeTests(unittest.TestCase):
    def setUp(self):
        patcher = hammer_walked()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_worn_recipe_is_pinned(self):
        for spell, name, low, high in WORN:
            with self.subTest(name=name):
                for value in (low, high):
                    recipe = craft.recipe_for(BLACKSMITHING, value)
                    self.assertEqual(recipe.spell_id, spell)
                    self.assertEqual(recipe.name, name)
                self.assertEqual(craft.focus_for(spell), 1)
                self.assertEqual(craft.tool_for(spell), HAMMER)

    def test_the_output_items_are_named_in_the_notes(self):
        items = {
            7818: 6338, 2666: 2857, 14379: 11128, 2668: 2865, 2672: 2868,
            3506: 3842, 3501: 3835, 7223: 6040, 9928: 7919, 9935: 7922,
            9964: 7969, 16649: 12425, 16657: 12426,
        }  # fmt: skip
        notes = {r.spell_id: r.note for r in craft.RECIPES[BLACKSMITHING]}
        for spell, item in items.items():
            with self.subTest(spell=spell):
                self.assertIn(f"item {item}", notes[spell])

    def test_the_stones_carry_no_tool(self):
        for recipe in craft.RECIPES[BLACKSMITHING]:
            if recipe.spell_id not in {w[0] for w in WORN}:
                self.assertEqual((recipe.focus, recipe.tool), (0, 0))

    def test_a_smith_is_handed_a_worn_recipe(self):
        spell = craft.craft_errand("Grug", {"blacksmithing": 110}, ("blacksmithing",))
        self.assertEqual(spell, BELT)


if __name__ == "__main__":
    unittest.main()
