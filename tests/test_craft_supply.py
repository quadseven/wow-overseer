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

WHERE THEY HAVE TO WALK TO BUY IT (infra#3692) is the second half of this
suite, and its fixtures are measured the same way - read off the live world
on 2026-09-13 while all five stood in Gadgetzan. See the table above
`SupplyTripTests` for the four creatures involved and why 5411 in particular
is in it. The bridge half is read as TEXT rather than imported, the way
test_bank_pass.py reads it: bridge.py imports discord and cannot be imported
here, and what is worth pinning there is the seam anyway - that the decision
is the pure module's, the aim goes onto the leader, and it names a creature
entry rather than a role keyword or a coordinate.
"""
import pathlib
import re
import unittest

import craft_supply
import towntrip
import travel
from towntrip import Town

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


def _bridge_source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _bridge_block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent.

    The same helper test_bank_pass.py uses, and deliberately the same shape:
    a structural assertion that reads half a file is an assertion about
    nothing in particular.
    """
    src = _bridge_source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest

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


# WHERE THE FAMILY MUST WALK (infra#3692). Every number below was read off
# the live wow-dev world on 2026-09-13, while all five stood in Gadgetzan at
# roughly (-7116, -3734) on map 1:
#
#     creature  name                  faction  yards  stocks 3371
#     5594      Alchemist Pestlezugg      474     83   yes
#     5411      Krinkle Goodsteel         474     92   NO  (7 npc_vendor rows)
#     4877      Jandia                    104   2071   yes
#     4897      Helenia Olden             894   3361   yes
#
# 5411 is the one the family was actually sent to, by the `vendor` role
# keyword, and it is why these fixtures are these numbers: the nearest vendor
# and the nearest vendor that stocks Empty Vial were nine yards and one whole
# different NPC apart, and the errand went to the wrong one. Map 1 is
# Kalimdor; map 0 below stands for Eastern Kingdoms, which is across an ocean
# MoveFarTo cannot path over.
GADGETZAN_MAP = 1
EASTERN_KINGDOMS_MAP = 0
PESTLEZUGG = craft_supply.VendorSpawn(
    entry=5594, name="Alchemist Pestlezugg", faction=474,
    map_id=GADGETZAN_MAP, yards=83.0,
)
JANDIA = craft_supply.VendorSpawn(
    entry=4877, name="Jandia", faction=104,
    map_id=GADGETZAN_MAP, yards=2071.0,
)
HELENIA = craft_supply.VendorSpawn(
    entry=4897, name="Helenia Olden", faction=894,
    map_id=GADGETZAN_MAP, yards=3361.0,
)


class SupplyTripTests(unittest.TestCase):
    """craft_supply.supply_trip - which vendor, and who walks to it."""

    def test_it_aims_at_a_vendor_that_stocks_it_and_not_at_a_role(self):
        # The whole of infra#3692's first half. The old pass wrote the
        # `vendor` role keyword, mod-overseer resolved that to creature 5411
        # (nearest vendor, no Empty Vial), Ugga arrived and bought nothing.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG, JANDIA]},
            leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "5594")
        self.assertEqual(trip.vendor.entry, 5594)
        self.assertEqual(trip.shopper, "Ugga")
        self.assertEqual(trip.entry, EMPTY_VIAL)

    def test_the_leader_walks_and_not_the_shopper(self):
        # infra#3692's second half: the family carries exactly one `new rpg`
        # and it is the leader's, so an aim written onto a follower moves
        # nobody. The shopper is still named, because the BUY is hers.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.traveller, "Grog")
        self.assertEqual(trip.shopper, "Ugga")
        self.assertNotEqual(trip.traveller, trip.shopper)

    def test_a_vendor_on_another_map_is_never_chosen(self):
        # A hard constraint, not a preference: ResolveTravelTarget refuses a
        # spawn that is not on the character's own map, because MoveFarTo
        # paths through PathGenerator and there is no navmesh across an
        # ocean. A cross-map aim would resolve to nothing, silently.
        across = craft_supply.VendorSpawn(
            entry=1234, name="Somebody in Stormwind", faction=12,
            map_id=EASTERN_KINGDOMS_MAP, yards=1.0,
        )
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [across, PESTLEZUGG]},
            leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "5594")
        self.assertNotIn(across, trip.passed_over)

    def test_nothing_on_this_map_sells_it_is_a_sentence_a_person_can_act_on(self):
        # This was invisible before: "vendor aim taken=True" and then nothing
        # for as long as the errand existed. The sentence has to name the
        # reagent, its entry, the map and whose errand it is, because those
        # are the four things somebody would otherwise have to go and look up.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: []}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "")
        self.assertEqual(len(trip.unreachable), 1)
        said = trip.unreachable[0]
        self.assertIn("Empty Vial", said)
        self.assertIn("3371", said)
        self.assertIn("map 1", said)
        self.assertIn("Ugga", said)
        self.assertTrue(trip.why_not)

    def test_an_unreachable_reagent_does_not_block_a_reachable_one(self):
        # One unsupplyable recipe must not hold up the other four characters,
        # the same reasoning craft_reagent_errands already applies within one
        # recipe's two reagents.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Bork", CRYSTAL_VIAL, "Crystal Vial"),
             craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {CRYSTAL_VIAL: [], EMPTY_VIAL: [PESTLEZUGG]},
            leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "5594")
        self.assertEqual(trip.shopper, "Ugga")
        self.assertEqual(len(trip.unreachable), 1)
        self.assertIn("Crystal Vial", trip.unreachable[0])

    def test_one_trip_per_pass_and_the_nearest_need_wins(self):
        # The family has exactly one traveller; two aims is infra#2812's
        # 937-yard scatter with a fresh reason attached (trainjob.plan states
        # the same restraint). Ranking on the chosen vendor's distance means
        # the shopper who can be served in 83 yards goes before the one who
        # would need 3,361.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Bork", LEADED_VIAL, "Leaded Vial"),
             craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {LEADED_VIAL: [HELENIA], EMPTY_VIAL: [PESTLEZUGG]},
            leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.shopper, "Ugga")
        self.assertEqual(trip.waiting, ("Bork's Leaded Vial",))

    def test_a_second_shopper_at_the_same_counter_is_not_called_waiting(self):
        # Both need Empty Vial and Pestlezugg sells it to both, so one walk
        # answers for both of them - their own DoBuy fires where they stand.
        # Calling the second one "waiting its turn" would send a reader
        # looking for a second trip that is never needed.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Bork", EMPTY_VIAL, "Empty Vial"),
             craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "5594")
        self.assertEqual(trip.waiting, ())
        self.assertEqual(len(trip.also_served), 1)
        self.assertIn("Empty Vial", trip.also_served[0])
        self.assertIn("same counter", craft_supply.report(trip))

    def test_the_answer_never_depends_on_the_order_rows_arrive_in(self):
        # Two shops at an identical distance must not let MySQL's row order
        # decide the aim - a pass that oscillates re-aims the family forever
        # and arrives nowhere. Same tie-break ResolveTravelTarget applies to
        # its own shortlist.
        near = craft_supply.VendorSpawn(
            entry=9001, name="A", faction=35, map_id=GADGETZAN_MAP, yards=40.0)
        also_near = craft_supply.VendorSpawn(
            entry=8001, name="B", faction=35, map_id=GADGETZAN_MAP, yards=40.0)
        first = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [near, also_near]}, leader="Grog",
            map_id=GADGETZAN_MAP,
        )
        second = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [also_near, near]}, leader="Grog",
            map_id=GADGETZAN_MAP,
        )
        self.assertEqual(first.target, second.target)
        self.assertEqual(first.target, "8001")

    def test_two_reagents_on_one_cast_are_resolved_one_pass_at_a_time(self):
        # Dark Leather Boots needs Fine Thread AND Gray Dye, and nothing says
        # one vendor sells both. The one-trip-per-pass shape handles that
        # with no special case: this pass takes the nearer reagent, and the
        # pass after it - by which time that one is carried and no longer a
        # need - takes the other.
        thread_shop = craft_supply.VendorSpawn(
            entry=7001, name="Thread", faction=474, map_id=GADGETZAN_MAP,
            yards=60.0)
        dye_shop = craft_supply.VendorSpawn(
            entry=7002, name="Dye", faction=474, map_id=GADGETZAN_MAP,
            yards=900.0)
        both = [craft_supply.Need("Og", FINE_THREAD, "Fine Thread"),
                craft_supply.Need("Og", GRAY_DYE, "Gray Dye")]
        spawns = {FINE_THREAD: [thread_shop], GRAY_DYE: [dye_shop]}

        first = craft_supply.supply_trip(both, spawns, "Grog", GADGETZAN_MAP)
        self.assertEqual(first.target, "7001")
        self.assertEqual(first.waiting, ("Og's Gray Dye",))

        # Next pass: the thread is carried, so only the dye is still a need.
        second = craft_supply.supply_trip(
            [both[1]], spawns, "Grog", GADGETZAN_MAP)
        self.assertEqual(second.target, "7002")
        self.assertEqual(second.waiting, ())

    def test_no_leader_means_no_trip_and_a_reason(self):
        # _head_now reads the world and can answer nobody. Writing the aim
        # onto '' would update no row and report nothing, which is the exact
        # silent shape this issue is about.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "")
        self.assertIn("follower", trip.why_not)

    def test_nobody_short_is_not_an_error(self):
        trip = craft_supply.supply_trip([], {}, "Grog", GADGETZAN_MAP)
        self.assertEqual(trip.target, "")
        self.assertTrue(trip.why_not)
        self.assertEqual(trip.unreachable, ())

    def test_creature_zero_is_never_written_as_an_aim(self):
        # 0 is the worldserver's own "no creature" sentinel, so an aim at it
        # resolves to nothing and looks exactly like an aim that simply did
        # not work. travel.resolve is what refuses it, and this is the test
        # that craft_supply actually asks travel.resolve rather than
        # formatting the id itself.
        nowhere = craft_supply.VendorSpawn(
            entry=0, name="", faction=0, map_id=GADGETZAN_MAP, yards=1.0)
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [nowhere]}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "")
        self.assertIn("travel_npc", trip.why_not)

    def test_the_aim_fits_the_column_and_is_a_travel_target(self):
        # overseer_roster.travel_npc is VARCHAR(32) and a truncated creature
        # entry is a different creature. Every entry on this world is five or
        # six digits, so this has room to spare - it is asserted anyway.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertLessEqual(len(trip.target), travel.COLUMN_WIDTH)
        self.assertTrue(travel.is_target(trip.target))
        self.assertEqual(travel.describe(trip.target), "creature 5594")

    def test_a_need_with_no_shopper_or_no_entry_is_dropped(self):
        trip = craft_supply.supply_trip(
            [craft_supply.Need("", EMPTY_VIAL, "Empty Vial"),
             craft_supply.Need("Ugga", 0, "nothing")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.unreachable, ())

    def test_a_need_and_an_errand_never_disagree(self):
        """`reagent_need` and `reagent_errand` each carry their own copy of
        "is this character short", and a drift between them is a family
        walked somewhere for a reagent they already have (or left standing
        with none). Checked across every REAGENT recipe, both stocked and
        not, at the boundary and either side of it."""
        for spell_id, (entry, label, _price) in craft_supply.REAGENT.items():
            for held in (0, craft_supply.TARGET - 1, craft_supply.TARGET,
                         craft_supply.TARGET + 1):
                empty = town(frozenset())
                need = craft_supply.reagent_need("Ugga", spell_id, held, empty)
                _errand, note = craft_supply.reagent_errand(
                    "Ugga", spell_id, held, 10_000_000, 5, empty)
                self.assertEqual(
                    bool(need), bool(note),
                    "spell %s held %d: need=%r note=%r"
                    % (spell_id, held, need, note))
                # And a reagent that IS in reach is never a trip, whatever
                # the shortfall - the buy happens where they stand.
                stocked = town({entry})
                self.assertIsNone(
                    craft_supply.reagent_need("Ugga", spell_id, held, stocked),
                    "spell %s held %d was sent travelling to a vendor it is "
                    "already standing at" % (spell_id, held))
                self.assertTrue(label)

    def test_plural_needs_and_plural_errands_never_disagree(self):
        for spell_id, reagents in craft_supply.REAGENTS.items():
            empty = town(frozenset())
            held = {entry: 0 for entry, _l, _p, _q in reagents}
            needs = craft_supply.craft_reagent_needs("Og", spell_id, held, empty)
            _errands, notes = craft_supply.craft_reagent_errands(
                "Og", spell_id, held, 10_000_000, 5, empty)
            self.assertEqual(len(needs), len(reagents), spell_id)
            self.assertEqual(len(needs), len(notes), spell_id)
            # Fully stocked to target: nowhere to go.
            full = {entry: craft_supply.CASTS_PER_TRIP * qty
                    for entry, _l, _p, qty in reagents}
            self.assertEqual(
                craft_supply.craft_reagent_needs("Og", spell_id, full, empty),
                [], spell_id)

    def test_a_reagent_in_reach_is_bought_while_the_other_is_walked_to(self):
        """Dark Leather Boots needs Fine Thread AND Gray Dye. Standing at a
        counter that sells only the dye, the dye should still be bought - and
        only the thread becomes a trip."""
        here = town({GRAY_DYE})
        held = {FINE_THREAD: 0, GRAY_DYE: 0}
        needs = craft_supply.craft_reagent_needs(
            "Og", DARK_LEATHER_BOOTS, held, here)
        self.assertEqual([n.entry for n in needs], [FINE_THREAD])
        errands, _notes = craft_supply.craft_reagent_errands(
            "Og", DARK_LEATHER_BOOTS, held, OG_MONEY, 5, here)
        self.assertEqual(len(errands), 1)
        self.assertTrue(errands[0].command.startswith("entry:4340 "))

    def test_a_shopper_on_another_map_is_not_walked_to(self):
        # Following does not cross a map. This family has been split across
        # an ocean before - three of five bound in Eastern Kingdoms while the
        # work was on Kalimdor - and a leader walking to a Tanaris counter
        # puts nobody in Stormwind in front of it, however well the walk
        # goes. The refusal names both maps, because "why did nothing
        # happen" is the question it exists to answer.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog",
            map_id=GADGETZAN_MAP,
            shopper_maps={"Ugga": EASTERN_KINGDOMS_MAP},
        )
        self.assertEqual(trip.target, "")
        self.assertEqual(len(trip.unreachable), 1)
        self.assertIn("Ugga", trip.unreachable[0])
        self.assertIn("map 0", trip.unreachable[0])
        self.assertIn("map 1", trip.unreachable[0])

    def test_a_shopper_nobody_can_see_is_not_walked_to_either(self):
        # `_fetch_positions` is bounded to snapshots under a minute old, so a
        # missing row means offline or unobserved. Guessing they are with the
        # leader is how a trip gets taken for somebody who is not there.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog",
            map_id=GADGETZAN_MAP, shopper_maps={},
        )
        self.assertEqual(trip.target, "")
        self.assertIn("nowhere visible", trip.unreachable[0])

    def test_a_shopper_standing_with_the_leader_is_served(self):
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG]}, leader="Grog",
            map_id=GADGETZAN_MAP,
            shopper_maps={"Ugga": GADGETZAN_MAP},
        )
        self.assertEqual(trip.target, "5594")
        self.assertEqual(trip.unreachable, ())

    def test_the_vendor_keyword_is_travels_own_and_not_a_fourth_copy(self):
        # The keyword this numeric aim replaces, and the one bridge's write
        # guard lets it refine. A fourth spelling is the one nobody checks.
        self.assertIn(craft_supply.VENDOR_ROLE, travel.ROLES)
        self.assertEqual(craft_supply.VENDOR_ROLE, "vendor")


class SupplyReportTests(unittest.TestCase):
    """craft_supply.report - the line that replaced 'vendor aim taken=True'."""

    def test_it_names_the_entry_the_faction_and_the_runners_up(self):
        # The faction is said because the gate that can refuse this aim lives
        # in the C++ and reads exactly that column (mod-overseer#234); the
        # runners-up are said so "it went to the wrong one" and "it was
        # refused and there was no other" are different sentences.
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: [PESTLEZUGG, JANDIA, HELENIA]},
            leader="Grog", map_id=GADGETZAN_MAP,
        )
        said = craft_supply.report(trip)
        self.assertIn("5594", said)
        self.assertIn("Alchemist Pestlezugg", said)
        self.assertIn("474", said)
        self.assertIn("Ugga", said)
        self.assertIn("Grog", said)
        self.assertIn("Empty Vial", said)
        self.assertIn("3371", said)
        self.assertIn("4877", said)
        self.assertIn("4897", said)

    def test_only_shortlist_runners_up_are_named(self):
        many = [PESTLEZUGG] + [
            craft_supply.VendorSpawn(
                entry=9000 + n, name="Shop %d" % n, faction=35,
                map_id=GADGETZAN_MAP, yards=100.0 + n)
            for n in range(10)
        ]
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: many}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(len(trip.passed_over), craft_supply.SHORTLIST)

    def test_a_trip_that_was_not_taken_reports_why(self):
        trip = craft_supply.supply_trip(
            [craft_supply.Need("Ugga", EMPTY_VIAL, "Empty Vial")],
            {EMPTY_VIAL: []}, leader="Grog", map_id=GADGETZAN_MAP,
        )
        self.assertEqual(craft_supply.report(trip), trip.why_not)


class TheBridgeWalksTheLeaderToTheRightShop(unittest.TestCase):
    """bridge.py imports discord and cannot be imported here, so this reads it
    as text the way test_bank_pass.py does. What is pinned is the seam: the
    aim is decided in the pure module, written onto the LEADER, and names a
    creature entry rather than a role keyword or a coordinate."""

    def test_the_pass_no_longer_aims_the_role_keyword(self):
        # The literal that shipped the bug. If it comes back, so does a
        # family walking to the nearest shop that does not sell the thing.
        body = _bridge_block("    async def _craft_supply_once(")
        self.assertNotIn('travel_npc="vendor"', body)
        self.assertIn("craft_supply.reagent_need(", body)
        self.assertIn("craft_supply.craft_reagent_needs(", body)
        self.assertIn("self._aim_at_reagent_vendor(needs)", body)

    def test_the_bridge_does_no_shortfall_arithmetic_of_its_own(self):
        """Whether a character is short of a reagent - and so whether a walk
        is worth taking - is craft_supply's arithmetic. A TARGET or a
        CASTS_PER_TRIP spelled here would be that decision made twice, and
        the copy nobody would think to check."""
        body = _bridge_block("    async def _craft_supply_once(")
        code = "\n".join(ln.split("#", 1)[0] for ln in body.splitlines())
        self.assertNotIn("craft_supply.TARGET", code)
        self.assertNotIn("craft_supply.CASTS_PER_TRIP", code)
        self.assertNotIn("town.stocks", code)

    def test_the_aim_is_written_onto_the_leader(self):
        body = _bridge_block("    async def _aim_at_reagent_vendor(")
        self.assertIn("_head_now", body)
        self.assertIn("character=trip.traveller", body)
        self.assertIn("travel_npc=trip.target", body)
        # And through the one guarded writer, never a second UPDATE.
        self.assertIn("_write_trade_errand", body)

    def test_the_bridge_reads_where_the_shoppers_are_standing(self):
        """A shopper on another map cannot arrive by following, and the pure
        module can only refuse the trip if it is told."""
        body = _bridge_block("    async def _aim_at_reagent_vendor(")
        self.assertIn("shopper_maps=shopper_maps", body)
        self.assertIn("_fetch_positions", body)

    def test_the_decision_is_the_pure_modules_and_not_the_bridges(self):
        body = _bridge_block("    async def _aim_at_reagent_vendor(")
        self.assertIn("craft_supply.supply_trip(", body)
        self.assertIn("craft_supply.report(trip)", body)
        # No arithmetic about which vendor: a literal distance or a sort here
        # would be the decision being made twice.
        self.assertNotIn("sorted(spawns", body)

    def test_an_unreachable_reagent_is_logged_loudly_every_pass(self):
        body = _bridge_block("    async def _aim_at_reagent_vendor(")
        self.assertIn("trip.unreachable", body)
        self.assertIn("log.warning", body)

    def test_the_vendor_query_is_bounded_to_one_map_and_one_item(self):
        src = _bridge_source()
        sql = src[src.index("_REAGENT_VENDOR_SQL = ("):src.index("REAGENT_VENDOR_ROWS =")]
        self.assertIn("acore_world.npc_vendor", sql)
        self.assertIn("nv.item = %s", sql)
        self.assertIn("cr.map = %s", sql)
        # creature.id, never creature.id1 - the same column _TOWN_COUNTERS_SQL
        # already joins on, checked against SHOW COLUMNS on this world.
        self.assertIn("cr.id = nv.entry", sql)
        self.assertNotIn("cr.id1", sql)
        # A stock list behind no vendor flag is a purchase nobody can make,
        # which towntrip.town_from_rows already refuses to count.
        self.assertIn("ct.npcflag", sql)

    def test_the_log_promises_no_more_vendors_than_the_query_reads(self):
        src = _bridge_source()
        self.assertIn("REAGENT_VENDOR_ROWS = craft_supply.SHORTLIST + 1", src)

    def test_a_bare_creature_entry_is_written_under_the_same_guard(self):
        # A numeric aim must never take _write_trade_errand's unconditional
        # branch: that branch also writes learn_skill/unlearn_skill, so a
        # shopping trip would silently erase an outstanding trainer errand.
        body = _bridge_block("def _retaskable_from(")
        self.assertIn("if aim in ECONOMY_ERRANDS:", body)
        self.assertIn("aim.isdigit()", body)
        self.assertIn("craft_supply.VENDOR_ROLE", body)
        self.assertIn("return ()", body)

    def test_no_coordinate_is_ever_authored_as_a_travel_aim(self):
        # A guessed z has no navmesh under it. The aim names a creature and
        # lets mod-overseer resolve the spawn, which is the whole reason this
        # fix is shaped around an entry id.
        source = pathlib.Path(craft_supply.__file__).read_text(encoding="utf-8")
        code = source.split('"""', 2)[2]
        self.assertNotIn('"at:', code)
        self.assertIn("travel.resolve(", code)


if __name__ == "__main__":
    unittest.main()
