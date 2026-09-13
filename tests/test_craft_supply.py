"""craft_supply.reagent_errand - the one buy decision it makes, and its refusals.

Every fixture below is a fact measured on the live wow-dev roster the night
this module was written, not an invented number - the same discipline
test_towntrip.py's own module docstring states and holds its fixtures to:
"a threshold tested only against numbers chosen to make it fire proves
nothing." Read directly from `characters`/`item_instance` on 2026-09-12
(Ugga/Grug), and again on 2026-09-13 for Grog (infra#3616's Weak Flux slice)
and for Bork/Og (infra#3609/#3611's thread/dye slice):

    Ugga   money 1,721,704 copper   0x Empty Vial    13x Peacebloom  20x Silverleaf
    Grug   money 1,658,352 copper   0x Leaded Vial
    Grog   money 1,782,898 copper   0x Weak Flux
    Bork   money 1,555,887 copper   0x Coarse Thread  0x Fine Thread  0x Gray Dye
    Og     money 1,689,767 copper   0x Coarse Thread  0x Fine Thread  0x Gray Dye

Reagent ids and prices (Empty Vial 3371/20cp, Leaded Vial 3372/200cp,
Crystal Vial 8925/2500cp, Weak Flux 2880/100cp, Coarse Thread 2320/10cp,
Fine Thread 2321/100cp, Silken Thread 4291/500cp, Heavy Silken Thread
8343/2000cp, Rune Thread 14341/5000cp, Gray Dye 4340/350cp, Black Dye
2325/1000cp, Salt 4289/50cp) are read from acore_world.item_template
directly - see craft_supply's own docstring for the verification, including
why Moss Agate (Standard Scope's other reagent) is deliberately NOT here: it
carries zero npc_vendor rows on this world and is a mined gem, not a vendor
purchase.
"""
import unittest

import craft_supply
import towntrip
from towntrip import Town

EMPTY_VIAL = 3371
LEADED_VIAL = 3372
CRYSTAL_VIAL = 8925
WEAK_FLUX = 2880
COARSE_THREAD = 2320
FINE_THREAD = 2321
SILKEN_THREAD = 4291
HEAVY_SILKEN_THREAD = 8343
RUNE_THREAD = 14341
GRAY_DYE = 4340
BLACK_DYE = 2325
SALT = 4289
MINOR_HEALING_POTION = 2330  # needs Empty Vial
HEALING_POTION = 3447  # needs Leaded Vial
SUPERIOR_HEALING_POTION = 11457  # needs Crystal Vial
LESSER_HEALING_POTION = 2337  # the one Alchemy recipe with no vial reagent
BRONZE_TUBE = 3938  # needs Weak Flux (Engineering)
STANDARD_SCOPE = 3978  # needs Moss Agate - deliberately unmapped
LIGHT_LEATHER = 2881  # no vendor reagent at all - pure recycle
LINEN_BELT = 8776  # needs Coarse Thread only (Tailoring)
DARK_LEATHER_BOOTS = 2167  # needs Fine Thread AND Gray Dye
NIGHTSCAPE_PANTS = 10548  # needs 4x Silken Thread per cast
RUNIC_LEATHER_HEADBAND = 19082  # needs Rune Thread only

UGGA_MONEY = 1_721_704
GRUG_MONEY = 1_658_352
GROG_MONEY = 1_782_898
BORK_MONEY = 1_555_887
OG_MONEY = 1_689_767


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


class CraftReagentErrandsTests(unittest.TestCase):
    """craft_supply.craft_reagent_errands - the plural sibling that answers
    for REAGENTS, where a recipe may name one or two vendor reagents."""

    def test_empty_for_a_recipe_with_no_reagents_entry(self):
        # Light Leather is a pure Skinning recycle - no vendor reagent at
        # all, the same "not this module's problem" shape LESSER_HEALING_
        # POTION already exercises for REAGENT/reagent_errand.
        errands, notes = craft_supply.craft_reagent_errands(
            "Bork", LIGHT_LEATHER, held={}, money=BORK_MONEY, free_slots=5,
            town=town({COARSE_THREAD}),
        )
        self.assertEqual(errands, [])
        self.assertEqual(notes, [])

    def test_buys_the_shortfall_for_a_single_reagent_recipe(self):
        # Bork's own measured holding is 0x Coarse Thread - the real
        # condition that stalls Linen Belt the same way
        # Ugga's 0x Empty Vial stalled Minor Healing Potion.
        errands, notes = craft_supply.craft_reagent_errands(
            "Bork", LINEN_BELT, held={COARSE_THREAD: 0},
            money=BORK_MONEY, free_slots=5, town=town({COARSE_THREAD}),
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(errands), 1)
        # qty_per_cast=1, CASTS_PER_TRIP=5 -> target=5, short=5, price 10 -> ceiling 50
        self.assertEqual(errands[0].command, "entry:2320 count:5 max:50")
        self.assertEqual(errands[0].spend, 50)

    def test_none_when_already_stocked_to_target(self):
        target = craft_supply.CASTS_PER_TRIP * 1  # Coarse Thread, 1/cast
        errands, notes = craft_supply.craft_reagent_errands(
            "Bork", LINEN_BELT, held={COARSE_THREAD: target},
            money=BORK_MONEY, free_slots=5, town=town({COARSE_THREAD}),
        )
        self.assertEqual(errands, [])
        self.assertEqual(notes, [])

    def test_buys_both_reagents_for_a_two_reagent_recipe(self):
        # Dark Leather Boots needs 2x Fine Thread AND 1x Gray Dye per cast -
        # the exact shape REAGENT's single-tuple values cannot hold, which
        # is why REAGENTS/craft_reagent_errands exist as a plural sibling.
        errands, notes = craft_supply.craft_reagent_errands(
            "Og", DARK_LEATHER_BOOTS, held={FINE_THREAD: 0, GRAY_DYE: 0},
            money=OG_MONEY, free_slots=5, town=town({FINE_THREAD, GRAY_DYE}),
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(errands), 2)
        commands = {e.command for e in errands}
        # Fine Thread: qty_per_cast=2 -> target=10, price 100 -> ceiling 1000
        self.assertIn("entry:2321 count:10 max:1000", commands)
        # Gray Dye: qty_per_cast=1 -> target=5, price 350 -> ceiling 1750
        self.assertIn("entry:4340 count:5 max:1750", commands)

    def test_buys_only_the_reagent_still_short_when_one_is_already_stocked(self):
        errands, notes = craft_supply.craft_reagent_errands(
            "Og", DARK_LEATHER_BOOTS,
            held={FINE_THREAD: 10, GRAY_DYE: 0},
            money=OG_MONEY, free_slots=5, town=town({FINE_THREAD, GRAY_DYE}),
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(errands), 1)
        self.assertEqual(errands[0].command, "entry:4340 count:5 max:1750")

    def test_scales_target_with_quantity_per_cast(self):
        # Nightscape Pants consumes 4x Silken Thread per cast - a flat
        # REAGENT-style TARGET of 5 units would strand this recipe after
        # little more than one cast, which is exactly why REAGENTS carries
        # its own per-recipe quantity instead.
        errands, notes = craft_supply.craft_reagent_errands(
            "Og", NIGHTSCAPE_PANTS, held={SILKEN_THREAD: 0}, money=OG_MONEY,
            free_slots=5, town=town({SILKEN_THREAD}),
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(errands), 1)
        # qty_per_cast=4, CASTS_PER_TRIP=5 -> target=20, price 500 -> ceiling 10000
        self.assertEqual(errands[0].command, "entry:4291 count:20 max:10000")
        self.assertEqual(errands[0].spend, 10_000)

    def test_refuses_a_reagent_with_no_reachable_vendor_but_buys_the_other(self):
        # Only Gray Dye is stocked here - Fine Thread must refuse while Gray
        # Dye still queues, since a recipe with two reagents should not let
        # one missing vendor block the one that IS reachable.
        errands, notes = craft_supply.craft_reagent_errands(
            "Og", DARK_LEATHER_BOOTS, held={FINE_THREAD: 0, GRAY_DYE: 0},
            money=OG_MONEY, free_slots=5, town=town({GRAY_DYE}),
        )
        self.assertEqual(len(errands), 1)
        self.assertEqual(errands[0].command, "entry:4340 count:5 max:1750")
        self.assertEqual(len(notes), 1)
        self.assertIn("no reachable vendor stocks", notes[0])
        self.assertIn("Fine Thread", notes[0])

    def test_refuses_with_no_free_bag_slot(self):
        errands, notes = craft_supply.craft_reagent_errands(
            "Bork", LINEN_BELT, held={COARSE_THREAD: 0},
            money=BORK_MONEY, free_slots=0, town=town({COARSE_THREAD}),
        )
        self.assertEqual(errands, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("no free bag slot", notes[0])

    def test_refuses_when_too_poor(self):
        # Rune Thread is 5000 copper each; a target of 5 (CASTS_PER_TRIP x
        # 1/cast) costs 25000 - far below Og's own measured purse, so this
        # exercises the refusal with an invented shortfall rather than a
        # real one (Og has never actually been this poor).
        errands, notes = craft_supply.craft_reagent_errands(
            "Og", RUNIC_LEATHER_HEADBAND, held={RUNE_THREAD: 0}, money=100,
            free_slots=5, town=town({RUNE_THREAD}),
        )
        self.assertEqual(errands, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("cannot afford", notes[0])

    def test_rune_thread_uses_the_only_sellable_item_id(self):
        # item_template carries a second "Rune Thread" row (entry 24288)
        # that has ZERO npc_vendor rows on this world - REAGENTS must only
        # ever name 14341, the one confirmed sold, never the look-alike.
        errands, _ = craft_supply.craft_reagent_errands(
            "Og", RUNIC_LEATHER_HEADBAND, held={RUNE_THREAD: 0}, money=OG_MONEY,
            free_slots=5, town=town({RUNE_THREAD}),
        )
        self.assertEqual(len(errands), 1)
        self.assertTrue(errands[0].command.startswith("entry:14341 "))

    def test_every_reagents_spell_is_a_real_crafting_recipe(self):
        # The same reverse-lookup discipline
        # test_every_vial_recipe_is_a_real_crafting_recipe already holds
        # REAGENT to: craft_supply must never name a spell_id craft.py
        # itself has never heard of.
        import craft

        for spell_id in craft_supply.REAGENTS:
            found = any(
                r.spell_id == spell_id
                for recipes in craft.RECIPES.values()
                for r in recipes
            )
            self.assertTrue(found, f"spell {spell_id} is not in craft.RECIPES")

    def test_every_reagents_entry_names_a_positive_quantity_per_cast(self):
        for spell_id, needs in craft_supply.REAGENTS.items():
            for entry, label, price, qty_per_cast in needs:
                self.assertGreater(
                    qty_per_cast, 0,
                    f"spell {spell_id}'s {label} ({entry}) has a non-positive "
                    f"per-cast quantity",
                )
                self.assertGreater(price, 0)


if __name__ == "__main__":
    unittest.main()
