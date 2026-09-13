"""craft_supply.reagent_errand - the one buy decision it makes, and its refusals.

Every fixture below is a fact measured on the live wow-dev roster the night
this module was written, not an invented number - the same discipline
test_towntrip.py's own module docstring states and holds its fixtures to:
"a threshold tested only against numbers chosen to make it fire proves
nothing." Read directly from `characters`/`item_instance` on 2026-09-12
(Ugga/Grug), and again on 2026-09-13 for Grog (infra#3616's Weak Flux slice):

    Ugga   money 1,721,704 copper   0x Empty Vial    13x Peacebloom  20x Silverleaf
    Grug   money 1,658,352 copper   0x Leaded Vial
    Grog   money 1,782,898 copper   0x Weak Flux

Reagent ids and prices (Empty Vial 3371/20cp, Leaded Vial 3372/200cp,
Crystal Vial 8925/2500cp, Weak Flux 2880/100cp) are read from
acore_world.item_template directly - see craft_supply's own docstring for
the verification, including why Moss Agate (Standard Scope's other
reagent) is deliberately NOT here: it carries zero npc_vendor rows on this
world and is a mined gem, not a vendor purchase.
"""
import unittest

import craft_supply
import towntrip
from towntrip import Town

EMPTY_VIAL = 3371
LEADED_VIAL = 3372
CRYSTAL_VIAL = 8925
WEAK_FLUX = 2880
MINOR_HEALING_POTION = 2330  # needs Empty Vial
HEALING_POTION = 3447  # needs Leaded Vial
SUPERIOR_HEALING_POTION = 11457  # needs Crystal Vial
LESSER_HEALING_POTION = 2337  # the one Alchemy recipe with no vial reagent
BRONZE_TUBE = 3938  # needs Weak Flux (Engineering)
STANDARD_SCOPE = 3978  # needs Moss Agate - deliberately unmapped

UGGA_MONEY = 1_721_704
GRUG_MONEY = 1_658_352
GROG_MONEY = 1_782_898


def town(stocks=frozenset()):
    return Town(repairs=False, stocks=frozenset(stocks), vendor=bool(stocks))


class ReagentErrandTests(unittest.TestCase):
    def test_none_for_a_recipe_with_no_known_vendor_reagent(self):
        # Every crafting recipe outside VIAL (e.g. a Tailoring bolt, or
        # Lesser Healing Potion whose second reagent is the previous
        # recipe's own output) must answer (None, None), never a guess.
        errand, note = craft_supply.reagent_errand(
            "Ugga", LESSER_HEALING_POTION, held=0, money=UGGA_MONEY, free_slots=5,
            town=town({EMPTY_VIAL}),
        )
        self.assertIsNone(errand)
        self.assertIsNone(note)

    def test_none_when_already_stocked_to_target(self):
        errand, note = craft_supply.reagent_errand(
            "Ugga", MINOR_HEALING_POTION, held=craft_supply.TARGET, money=UGGA_MONEY,
            free_slots=5, town=town({EMPTY_VIAL}),
        )
        self.assertIsNone(errand)
        self.assertIsNone(note)

    def test_buys_the_shortfall_up_to_target(self):
        # Ugga's own measured holding is 0x Empty Vial - the exact live
        # condition that stalled her Minor Healing Potion errand tonight.
        errand, note = craft_supply.reagent_errand(
            "Ugga", MINOR_HEALING_POTION, held=0, money=UGGA_MONEY, free_slots=5,
            town=town({EMPTY_VIAL}),
        )
        self.assertIsNone(note)
        self.assertIsNotNone(errand)
        self.assertEqual(errand.member, "Ugga")
        self.assertEqual(errand.kind, "buy")
        # short = TARGET(5) - held(0) = 5, price 20/ea -> ceiling 100
        self.assertEqual(errand.command, "entry:3371 count:5 max:100")
        self.assertEqual(errand.spend, 100)

    def test_refuses_when_no_reachable_vendor_stocks_it(self):
        errand, note = craft_supply.reagent_errand(
            "Ugga", MINOR_HEALING_POTION, held=0, money=UGGA_MONEY, free_slots=5,
            town=town(frozenset()),
        )
        self.assertIsNone(errand)
        self.assertIn("no reachable vendor stocks", note)
        self.assertIn("Empty Vial", note)

    def test_refuses_with_no_free_bag_slot(self):
        errand, note = craft_supply.reagent_errand(
            "Ugga", MINOR_HEALING_POTION, held=0, money=UGGA_MONEY, free_slots=0,
            town=town({EMPTY_VIAL}),
        )
        self.assertIsNone(errand)
        self.assertIn("no free bag slot", note)

    def test_refuses_when_too_poor(self):
        # Healing Potion needs a Leaded Vial at 200 copper each; a stack of
        # 5 (TARGET) costs 1000 copper - far below Grug's own measured
        # purse, so this exercises the refusal with an invented shortfall
        # rather than a real one (Grug has never actually been this poor).
        errand, note = craft_supply.reagent_errand(
            "Grug", HEALING_POTION, held=0, money=50, free_slots=5,
            town=town({LEADED_VIAL}),
        )
        self.assertIsNone(errand)
        self.assertIn("cannot afford", note)

    def test_picks_the_right_vial_per_recipe(self):
        errand, _ = craft_supply.reagent_errand(
            "Grug", HEALING_POTION, held=0, money=GRUG_MONEY, free_slots=5,
            town=town({LEADED_VIAL}),
        )
        self.assertIn("entry:3372", errand.command)

    def test_picks_crystal_vial_for_the_top_alchemy_bracket(self):
        # The third and most expensive tier (2500 copper each) - none of the
        # other tests reach it, and it is the one most likely to trip a
        # copy-paste mistake in VIAL's third column.
        errand, note = craft_supply.reagent_errand(
            "Ugga", SUPERIOR_HEALING_POTION, held=1, money=UGGA_MONEY,
            free_slots=5, town=town({CRYSTAL_VIAL}),
        )
        self.assertIsNone(note)
        # short = TARGET(5) - held(1) = 4, price 2500/ea -> ceiling 10000
        self.assertEqual(errand.command, "entry:8925 count:4 max:10000")
        self.assertEqual(errand.spend, 10_000)

    def test_every_vial_recipe_is_a_real_crafting_recipe(self):
        # craft_supply must never name a spell_id craft.py itself has never
        # heard of - the same "second source of truth goes stale" failure
        # mode craft.py's own docstring warns about, checked in reverse here.
        import craft

        for spell_id in craft_supply.REAGENT:
            found = any(
                r.spell_id == spell_id
                for recipes in craft.RECIPES.values()
                for r in recipes
            )
            self.assertTrue(found, f"spell {spell_id} is not in craft.RECIPES")

    def test_buys_weak_flux_for_bronze_tube(self):
        # Grog's own measured holding is 0x Weak Flux (2026-09-13) - the
        # real condition that would otherwise stall Bronze Tube the same
        # way Ugga's Minor Healing Potion stalled on 0x Empty Vial.
        errand, note = craft_supply.reagent_errand(
            "Grog", BRONZE_TUBE, held=0, money=GROG_MONEY, free_slots=5,
            town=town({WEAK_FLUX}),
        )
        self.assertIsNone(note)
        self.assertIsNotNone(errand)
        self.assertEqual(errand.member, "Grog")
        self.assertEqual(errand.kind, "buy")
        # short = TARGET(5) - held(0) = 5, price 100/ea -> ceiling 500
        self.assertEqual(errand.command, "entry:2880 count:5 max:500")
        self.assertEqual(errand.spend, 500)

    def test_refuses_weak_flux_when_no_reachable_vendor_stocks_it(self):
        errand, note = craft_supply.reagent_errand(
            "Grog", BRONZE_TUBE, held=0, money=GROG_MONEY, free_slots=5,
            town=town(frozenset()),
        )
        self.assertIsNone(errand)
        self.assertIn("no reachable vendor stocks", note)
        self.assertIn("Weak Flux", note)

    def test_standard_scope_answers_none_moss_agate_is_not_a_buy(self):
        # Standard Scope needs Moss Agate, which craft_supply.REAGENT
        # deliberately does not name (it is a mined gem with zero
        # npc_vendor rows on this world, not a vendor purchase) - so this
        # must answer (None, None), the same "not this module's problem"
        # shape Lesser Healing Potion already exercises above, never a
        # refusal note that implies a vendor trip would ever help.
        errand, note = craft_supply.reagent_errand(
            "Grog", STANDARD_SCOPE, held=0, money=GROG_MONEY, free_slots=5,
            town=town(frozenset()),
        )
        self.assertIsNone(errand)
        self.assertIsNone(note)


if __name__ == "__main__":
    unittest.main()
