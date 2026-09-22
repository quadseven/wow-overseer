"""The family's bags, measured, against the bags it could have made.

Every fixture here is the realm as it stood on 2026-09-05: the five worn bag
sets out of `character_inventory`, the levels out of `characters`, and Og's
tailoring value 1 of max 75 out of `character_skills`. The point of the module
is that those Netherweave Bags are unreachable and something else is not, so
the tests are written from the real inventories rather than from convenient
ones.
"""

import unittest

from bag_upgrade import Bag, Member

import bag_economy as be
from bag_economy import (
    LADDER,
    TIERS,
    can_train,
    cloth_for,
    coin,
    craftable,
    deficit,
    first_useful_rung,
    gatherers,
    levelling_craft,
    next_step,
    next_tier,
    raw_cost,
    reachable_cap,
    shopping_list,
    tier_for,
    within_reach,
    worth_making,
)

# The worn bags, exactly as `character_inventory` slots 19 to 22 held them.
FAMILY = (
    Member(
        "Bork",
        4,
        worn=(
            Bag("Small Red Pouch", 6),
            Bag("Netherweave Bag", 16),
            Bag("Netherweave Bag", 16),
            Bag("Green Leather Bag", 8),
        ),
    ),
    Member(
        "Grog",
        4,
        worn=(
            Bag("Small Green Pouch", 6),
            Bag("Red Leather Bag", 8),
            Bag("Large Brown Sack", 10),
            Bag("Green Leather Bag", 8),
        ),
    ),
    Member(
        "Grug",
        4,
        worn=(
            Bag("Netherweave Bag", 16),
            Bag("Netherweave Bag", 16),
            Bag("Green Leather Bag", 8),
            Bag("Green Leather Bag", 8),
        ),
    ),
    Member(
        "Og",
        4,
        worn=(
            Bag("Small Red Pouch", 6),
            Bag("Old Blanchy's Feed Pouch", 8),
            Bag("Netherweave Bag", 16),
            Bag("Netherweave Bag", 16),
        ),
    ),
    Member(
        "Ugga",
        4,
        worn=(
            Bag("Small Brown Pouch", 6),
            Bag("Red Leather Bag", 8),
            Bag("Green Leather Bag", 8),
            Bag("Old Blanchy's Feed Pouch", 8),
        ),
    ),
)
LEVELS = {"Grug": 29, "Bork": 26, "Grog": 26, "Og": 26, "Ugga": 24}
OG_PURSE = 1594393


def rung(name):
    return next(r for r in LADDER if r.bag == name)


class TheLadderIsTheRealmsLadder(unittest.TestCase):
    def test_the_ranks_only_ever_go_up(self):
        """The order is the order Og meets them in, so a caller can stop at the
        first one that fits instead of scanning the whole table."""
        ranks = [r.rank for r in LADDER]
        self.assertEqual(ranks, sorted(ranks))

    def test_bigger_bags_are_never_cheaper_in_skill(self):
        best = 0
        for r in LADDER:
            self.assertGreaterEqual(r.slots, best)
            best = r.slots

    def test_every_rung_names_how_it_is_taught(self):
        for r in LADDER:
            self.assertIn(r.taught_by, ("trainer", "pattern"))
            if r.taught_by == "pattern":
                self.assertTrue(r.pattern, f"{r.bag} has no pattern item")
            else:
                self.assertTrue(r.cost, f"{r.bag} has no trainer price")

    def test_every_rung_eats_exactly_one_kind_of_bolt(self):
        """A bag made of two cloths would break `cloth_for`, which returns one
        band. Nothing in 3.3.5a tailoring does, and the test says so out loud."""
        for r in LADDER:
            bolts = [g for g in r.reagents if g.entry in be.BOLTS]
            self.assertEqual(len(bolts), 1, r.bag)

    def test_the_netherweave_bags_they_own_are_the_top_of_the_ladder(self):
        top = LADDER[-1]
        self.assertEqual(top.bag, "Netherweave Bag")
        self.assertEqual((top.slots, top.rank), (16, 315))


class TheTrainingTiersGateEverything(unittest.TestCase):
    def test_each_tier_is_gated_one_hundred_below_the_cap_it_grants(self):
        """This is how the caps were derived at all, `skilltiers_dbc` being
        empty, so it is worth a test rather than a comment."""
        for tier in TIERS[1:]:
            self.assertEqual(tier.rank, tier.cap - 100, tier.name)

    def test_og_measured_cap_reads_as_apprentice(self):
        self.assertEqual(tier_for(75).name, "Apprentice Tailoring")

    def test_the_next_step_above_apprentice_is_journeyman(self):
        self.assertEqual(next_tier(75).name, "Journeyman Tailoring")

    def test_grand_master_has_nothing_above_it(self):
        self.assertIsNone(next_tier(450))

    def test_a_level_twenty_six_tailor_is_capped_at_two_twenty_five(self):
        """Artisan needs character level 35. This is the ceiling that puts the
        family's own Netherweave Bags out of reach of the family's own tailor."""
        self.assertEqual(reachable_cap(26), 225)

    def test_netherweave_is_not_within_reach_at_twenty_six(self):
        self.assertNotIn("Netherweave Bag", [r.bag for r in within_reach(26)])

    def test_netherweave_needs_level_fifty(self):
        self.assertIn("Netherweave Bag", [r.bag for r in within_reach(50)])

    def test_training_needs_skill_and_level_and_money_together(self):
        journeyman = next_tier(75)
        self.assertTrue(can_train(journeyman, 50, 26, OG_PURSE))
        self.assertFalse(can_train(journeyman, 49, 26, OG_PURSE))
        self.assertFalse(can_train(journeyman, 50, 9, OG_PURSE))
        self.assertFalse(can_train(journeyman, 50, 26, 499))


class WhatOgCanActuallyMake(unittest.TestCase):
    def test_a_skill_one_tailor_can_make_no_bag_at_all(self):
        self.assertEqual(craftable(1), ())

    def test_a_pattern_rung_is_withheld_until_the_pattern_is_found(self):
        red_linen = rung("Red Linen Bag")
        self.assertNotIn(red_linen, craftable(200))
        self.assertIn(red_linen, craftable(200, known=[red_linen.spell]))

    def test_a_trainer_rung_needs_no_pattern(self):
        self.assertIn(rung("Linen Bag"), craftable(45))


class TheFamilysDeficit(unittest.TestCase):
    def test_ugga_is_first_in_line_for_a_ten(self):
        """Fewest worn slots of the five (30) and a 6-slot pouch to displace."""
        self.assertEqual(deficit(FAMILY, 10)[0].who, "Ugga")

    def test_grug_is_last_because_he_wears_two_netherweaves(self):
        self.assertEqual(deficit(FAMILY, 10)[-1].who, "Grug")

    def test_a_ten_beats_an_eight_by_the_gap_not_by_the_size(self):
        gains = {d.who: d.gain for d in deficit(FAMILY, 10)}
        self.assertEqual(gains["Ugga"], 4)
        self.assertEqual(gains["Grug"], 2)

    def test_a_bag_no_bigger_than_the_weakest_worn_helps_nobody(self):
        self.assertEqual(worth_making(FAMILY, 6), ())

    def test_an_empty_bag_position_is_worth_the_whole_bag(self):
        bare = Member("Bork", 4, worn=(Bag("Small Red Pouch", 6),))
        self.assertEqual(deficit([bare], 10)[0].gain, 10)

    def test_ties_are_broken_by_who_carries_less(self):
        """Four characters all displace a 6; the order between them is the one
        thing a stable plan needs and arithmetic alone does not give."""
        order = [d.who for d in deficit(FAMILY, 8)]
        self.assertEqual(order[:4], ["Ugga", "Grog", "Bork", "Og"])

    def test_the_first_useful_rung_skips_the_six_slot_linen_bag(self):
        target = first_useful_rung(FAMILY, 26)
        self.assertEqual(target.bag, "Woolen Bag")

    def test_pattern_rungs_are_skipped_until_the_pattern_is_held(self):
        """Red Linen Bag sits below Woolen Bag and would be chosen first if
        patterns were free. It is 6 slots anyway, so the real proof is that a
        held pattern changes nothing until the bag is bigger."""
        red_woolen = rung("Red Woolen Bag")
        target = first_useful_rung(FAMILY, 26, known=[red_woolen.spell])
        self.assertEqual(target.bag, "Woolen Bag")

    def test_a_family_that_needs_nothing_gets_no_target(self):
        rich = [
            Member("Grug", 4, worn=tuple(Bag("Netherweave Bag", 16) for _ in range(4)))
        ]
        self.assertIsNone(first_useful_rung(rich, 26))


class TheGathering(unittest.TestCase):
    def test_a_woolen_bag_costs_nine_wool_cloth(self):
        """Three Bolt of Woolen Cloth at three Wool Cloth each. The family
        loots cloth and never bolts, so the plan has to be in cloth."""
        self.assertEqual(raw_cost(rung("Woolen Bag")), {2592: 9, 2321: 1})

    def test_the_cost_scales_with_the_number_of_bags(self):
        self.assertEqual(raw_cost(rung("Woolen Bag"), 3), {2592: 27, 2321: 3})

    def test_threads_are_bought_and_cloth_is_fought(self):
        rows = {name: how for _, name, _, how in shopping_list(rung("Woolen Bag"))}
        self.assertEqual(rows["Fine Thread"], "buy")
        self.assertEqual(rows["Wool Cloth"], "gather")

    def test_what_is_already_held_drops_off_the_list(self):
        rows = shopping_list(rung("Woolen Bag"), 1, {2592: 9})
        self.assertEqual([name for _, name, _, _ in rows], ["Fine Thread"])

    def test_nothing_is_asked_for_when_everything_is_held(self):
        self.assertEqual(shopping_list(rung("Woolen Bag"), 1, {2592: 9, 2321: 1}), ())

    def test_wool_is_the_cloth_the_whole_family_is_the_right_level_for(self):
        band = cloth_for(rung("Woolen Bag"))
        self.assertEqual(band.cloth, "Wool Cloth")
        self.assertEqual(
            gatherers(band, LEVELS), ("Grug", "Bork", "Grog", "Og", "Ugga")
        )

    def test_grug_has_outgrown_the_humanoids_that_drop_linen(self):
        """Linen tops out at level 26 on this realm and Grug is 29. Sending the
        highest-level character is the intuitive answer and the wrong one."""
        self.assertNotIn("Grug", gatherers(be.CLOTH_BANDS[2589], LEVELS))

    def test_nobody_can_farm_runecloth_yet(self):
        self.assertEqual(gatherers(be.CLOTH_BANDS[14047], LEVELS), ())


class TheLevellingCraft(unittest.TestCase):
    def test_linen_bolts_are_the_only_thing_a_skill_one_tailor_can_make(self):
        bolt = levelling_craft(1)
        self.assertEqual(bolt.name, "Bolt of Linen Cloth")

    def test_the_linen_bolt_greys_exactly_on_the_journeyman_gate(self):
        """50 is both where the bolt stops teaching and where Journeyman is
        gated, which is why this one craft covers the whole first tier."""
        self.assertEqual(levelling_craft(1).grey, next_tier(75).rank)

    def test_there_is_a_gap_between_the_linen_and_woolen_bolts(self):
        """Nothing in the bolt chain pays between 50 and 75. The planner must
        say so rather than send Og to grind a grey recipe."""
        self.assertIsNone(levelling_craft(50))
        self.assertIsNone(levelling_craft(74))
        self.assertEqual(levelling_craft(75).name, "Bolt of Woolen Cloth")


class TheNextConcreteStep(unittest.TestCase):
    def step(self, skill, cap, held=None, money=OG_PURSE, level=26):
        return next_step(
            tailor="Og",
            skill=skill,
            cap=cap,
            level=level,
            money=money,
            members=FAMILY,
            levels=LEVELS,
            held=held,
        )

    def test_the_measured_family_is_told_to_raise_tailoring_to_fifty(self):
        step = self.step(1, 75)
        self.assertEqual(step.kind, "train")
        self.assertIn("raise tailoring from 1 to 50", step.said)
        self.assertIn("Bolt of Linen Cloth", step.said)
        self.assertEqual(step.rung.bag, "Woolen Bag")

    def test_at_the_gate_the_step_becomes_the_purchase(self):
        step = self.step(50, 75)
        self.assertEqual(step.tier.name, "Journeyman Tailoring")
        self.assertIn("5s", step.said)

    def test_a_tailor_who_cannot_pay_is_told_so_rather_than_sent(self):
        self.assertIn("cannot afford", self.step(50, 75, money=0).said)

    def test_above_the_cap_but_below_the_rank_the_skill_is_the_blocker(self):
        step = self.step(60, 150)
        self.assertEqual(step.kind, "train")
        self.assertIn("needs 80", step.said)

    def test_with_the_skill_the_step_becomes_the_cloth(self):
        step = self.step(80, 150)
        self.assertEqual((step.kind, step.item, step.count), ("gather", 2592, 9))
        self.assertIn("humanoids level 10 to 32", step.said)

    def test_cloth_comes_before_thread_because_it_is_the_hard_half(self):
        self.assertEqual(self.step(80, 150, {2321: 1}).item, 2592)

    def test_only_the_thread_left_is_a_trip_to_a_trade_supplier(self):
        step = self.step(80, 150, {2592: 9})
        self.assertIn("trade supplier", step.said)
        self.assertEqual(step.item, 2321)

    def test_with_everything_in_hand_the_step_is_the_craft(self):
        step = self.step(80, 150, {2592: 9, 2321: 1})
        self.assertEqual(step.kind, "craft")
        self.assertEqual(step.rung.bag, "Woolen Bag")

    def test_a_level_too_low_to_train_is_reported_as_a_level_problem(self):
        """A family already in 12s can only be helped by a Runecloth Bag, and
        that is behind Artisan Tailoring, which is behind character level 35.
        Naming the wall is the answer; "nothing to do" would not be."""
        kitted = [
            Member("Ugga", 4, worn=tuple(Bag("Mageweave Bag", 12) for _ in range(4)))
        ]
        step = next_step(
            tailor="Og",
            skill=200,
            cap=225,
            level=26,
            money=OG_PURSE,
            members=kitted,
            levels=LEVELS,
            known=[rung("Runecloth Bag").spell],
        )
        self.assertEqual(step.rung.bag, "Runecloth Bag")
        self.assertIn("level 26", step.said)
        self.assertIn("Artisan Tailoring", step.said)

    def test_a_family_needing_nothing_gets_told_that_and_not_a_craft(self):
        rich = [
            Member("Grug", 4, worn=tuple(Bag("Netherweave Bag", 16) for _ in range(4)))
        ]
        step = next_step(
            tailor="Og",
            skill=225,
            cap=225,
            level=26,
            money=OG_PURSE,
            members=rich,
            levels=LEVELS,
        )
        self.assertIn("no bag worth making", step.said)
        self.assertIsNone(step.rung)


class TheSentencesAreReadable(unittest.TestCase):
    def test_copper_is_spoken_the_way_the_game_shows_it(self):
        self.assertEqual(coin(500), "5s")
        self.assertEqual(coin(15000), "1g 50s")
        self.assertEqual(coin(0), "0c")
        self.assertEqual(coin(1594393), "159g 43s 93c")

    def test_no_step_carries_an_em_dash(self):
        for skill, cap in ((1, 75), (50, 75), (80, 150)):
            said = next_step(
                tailor="Og",
                skill=skill,
                cap=cap,
                level=26,
                money=OG_PURSE,
                members=FAMILY,
                levels=LEVELS,
            ).said
            self.assertNotIn(chr(0x2014), said)


if __name__ == "__main__":
    unittest.main()
