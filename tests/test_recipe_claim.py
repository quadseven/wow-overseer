"""A recipe reaches the character whose trade can learn it (infra#3731).

THE MEASUREMENT THIS SUITE IS WRITTEN AGAINST, read off the live realm on
2026-09-13 by joining character_inventory to item_template rather than a wiki.
The family carries 15 class-9 recipes and THIRTEEN are in a bag whose owner can
never learn them:

    Grog  Pattern: Heavy Woolen Cloak      RequiredSkill 197 tailoring    -> Og
    Grog  Plans: Frost Tiger Blade         164 blacksmithing              -> Grug
    Grog  Recipe: Elixir of Giant Growth   171 alchemy                    -> Ugga
    Grog  Schematic: EZ-Thro Dynamite      202 engineering                -> Grog
    Grug  Pattern: White Leather Jerkin    165 leatherworking             -> Bork
    Grug  Recipe: Elixir of Minor Agility  171 alchemy                    -> Ugga
    Og    Pattern: Dark Leather Tunic      165 leatherworking             -> Bork
    Og    Plans: Copper Chain Vest         164 blacksmithing              -> Grug
    Og    Plans: Green Iron Boots          164 blacksmithing              -> Grug
    Og    Plans: Silvered Bronze Breastpl. 164 blacksmithing              -> Grug
    Ugga  Pattern: Gray Woolen Robe        197 tailoring                  -> Og
    Ugga  Pattern: Hands of Darkness       197 tailoring                  -> Og
    Grug/Og  Manual: Strong Anti-Venom x3  129 first aid                  -> nobody

Every one is `item_template.bonding = 0` with `item_instance.flags & 1 = 0`, so
the hand-off needs no verb that does not already ship.

WHY NOTHING WAS MOVING THEM, which is the part worth pinning rather than the
arithmetic. Both halves of the economy pass skip a recipe for a DIFFERENT
reason, so neither looked broken: `_SURPLUS_GEAR_SQL` selects
`it.class IN (2, 4)` and never asked `decide` about one, while `sellable`
requires `quality <= 1` and every recipe above is Quality 2. They were not
mis-routed, they were unrouted.

AND THE ONE THING THIS SUITE EXISTS TO PROVE ABOVE ALL OTHERS is that the new
branch is REACHABLE. `gear.claimant` answers UNJUDGEABLE about every class-9
row - it judges by equipment slot and a Pattern goes in none - which
`bag_pressure.family_fits` turns into FIT_UNJUDGEABLE, which returns KEEP.
A recipe rule written below that gate could never once have fired, and a live
dry run producing nothing would have looked exactly like a quiet realm. See
`RecipeBranchIsReachable`.
"""
import unittest

import bag_pressure
import disposition
import gear

# The live skill line ids, from goals.SKILL_IDS, which is itself checked
# against the core's own SharedDefines enum. Restated here as literals on
# purpose: a test that imports the mapping it is testing proves only that the
# mapping equals itself.
FIRST_AID = 129
BLACKSMITHING = 164
LEATHERWORKING = 165
ALCHEMY = 171
TAILORING = 197
ENGINEERING = 202

# The family's assigned primaries as professions.ROSTER holds them, measured
# 2026-09-13. Note that Grog is MINING + ENGINEERING and holds no inscription
# at all - disposition.py's own header still said "Grog Inscription 1/75",
# which live `character_skills` and epic infra#3731's table both contradict.
HOLDERS = {
    BLACKSMITHING: "Grug",
    LEATHERWORKING: "Bork",
    ALCHEMY: "Ugga",
    TAILORING: "Og",
    ENGINEERING: "Grog",
}


def _row(holder, guid, name, skill, *, item_class=9, quality=2, bonding=0,
         instance_flags=0, sell_price=100, entry=1234):
    """One carried-recipe row in exactly the shape _SURPLUS_RECIPES_SQL gives."""
    return {
        "holder": holder, "item_guid": guid, "entry": entry, "count": 1,
        "instance_flags": instance_flags, "name": name, "quality": quality,
        "sell_price": sell_price, "bonding": bonding, "item_class": item_class,
        "bag_family": 0, "required_skill": skill, "required_skill_rank": 100,
    }


def _recipe_item(skill, *, name="Plans: Green Iron Boots", item_class=9):
    return disposition.Item(
        name=name, quality=2, known=True, binding=disposition.BIND_NONE,
        quest_item=False, item_class=item_class, required_skill=skill,
        sell_price=500,
    )


class RecipePredicate(unittest.TestCase):
    def test_class_nine_with_a_skill_gate_is_a_recipe(self):
        self.assertTrue(disposition.recipe(_recipe_item(BLACKSMITHING)))

    def test_class_nine_without_a_skill_gate_is_not(self):
        # A handful of class-9 rows gate on nothing. They name no claimant, so
        # they are ordinary goods and every other rule keeps applying to them.
        self.assertFalse(disposition.recipe(_recipe_item(0)))

    def test_a_green_is_not_a_recipe_however_it_is_labelled(self):
        self.assertFalse(
            disposition.recipe(_recipe_item(BLACKSMITHING, item_class=4))
        )


class Learners(unittest.TestCase):
    def test_a_recipe_in_the_wrong_bag_names_its_trades_owner(self):
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        self.assertEqual(disposition.learners(rows, HOLDERS), {1507032: "Grug"})

    def test_a_recipe_in_the_right_bag_answers_holder(self):
        rows = [_row("Grog", 1508070, "Schematic: EZ-Thro Dynamite", ENGINEERING)]
        self.assertEqual(
            disposition.learners(rows, HOLDERS),
            {1508070: disposition.LEARNER_HOLDER},
        )

    def test_a_trade_nobody_is_assigned_answers_nobody(self):
        # First Aid is held by all five and assigned to none, so no single
        # character can claim the three Manuals the family carries.
        rows = [_row("Grug", 1740598, "Manual: Strong Anti-Venom", FIRST_AID)]
        self.assertEqual(
            disposition.learners(rows, HOLDERS),
            {1740598: disposition.LEARNER_NOBODY},
        )

    def test_the_whole_measured_pile_resolves_as_the_banner_says(self):
        rows = [
            _row("Grog", 1, "Pattern: Heavy Woolen Cloak", TAILORING),
            _row("Grog", 2, "Plans: Frost Tiger Blade", BLACKSMITHING),
            _row("Grog", 3, "Recipe: Elixir of Giant Growth", ALCHEMY),
            _row("Grog", 4, "Schematic: EZ-Thro Dynamite", ENGINEERING),
            _row("Grug", 5, "Pattern: White Leather Jerkin", LEATHERWORKING),
            _row("Grug", 6, "Recipe: Elixir of Minor Agility", ALCHEMY),
            _row("Og", 7, "Pattern: Dark Leather Tunic", LEATHERWORKING),
            _row("Og", 8, "Plans: Copper Chain Vest", BLACKSMITHING),
            _row("Ugga", 9, "Pattern: Gray Woolen Robe", TAILORING),
            _row("Grug", 10, "Manual: Strong Anti-Venom", FIRST_AID),
        ]
        self.assertEqual(disposition.learners(rows, HOLDERS), {
            1: "Og", 2: "Grug", 3: "Ugga", 4: disposition.LEARNER_HOLDER,
            5: "Bork", 6: "Ugga", 7: "Bork", 8: "Grug", 9: "Og",
            10: disposition.LEARNER_NOBODY,
        })

    def test_an_unreadable_row_is_absent_rather_than_guessed(self):
        # Absent means LEARNER_UNASKED at the point of use, which keeps it.
        rows = [
            {"holder": "Og"},                                  # no guid
            _row("", 11, "Plans: Copper Chain Vest", BLACKSMITHING),
            _row("Og", 0, "Plans: Copper Chain Vest", BLACKSMITHING),
            _row("Og", 12, "Shadowgem", BLACKSMITHING, item_class=3),
        ]
        self.assertEqual(disposition.learners(rows, HOLDERS), {})

    def test_a_missing_world_column_keeps_everything(self):
        # `required_skill` absent is what an older image gives, and it must
        # not be read as "gates on nothing, therefore disposable".
        rows = [_row("Og", 13, "Plans: Copper Chain Vest", BLACKSMITHING)]
        del rows[0]["required_skill"]
        self.assertEqual(disposition.learners(rows, HOLDERS), {})


class RecipeBranchIsReachable(unittest.TestCase):
    """The control-flow proof, and the reason this file exists.

    Several rules shipped this week whose live dry run produced nothing, which
    is indistinguishable from a quiet realm. These assert the branch fires from
    the state the REAL pass puts it in, not from a state chosen to make it fire.
    """

    def test_it_beats_the_fit_gate_that_would_otherwise_keep_it(self):
        # THE EXACT STATE THE LIVE PASS PRODUCES. gear.claimant returns
        # UNJUDGEABLE for class 9, which family_fits maps to FIT_UNJUDGEABLE,
        # whose branch returns KEEP. If the recipe rule were written below it
        # this assertion would read KEEP and the feature would be inert.
        verdict = disposition.decide(
            _recipe_item(BLACKSMITHING), disposition.Family(),
            available=disposition.EXECUTABLE_TODAY,
            family_fit=disposition.FIT_UNJUDGEABLE, learner="Grug",
        )
        self.assertEqual(verdict.route, disposition.GIVE)

    def test_gear_claimant_really_does_refuse_a_recipe(self):
        # The premise of the test above, asserted rather than assumed, so that
        # a future change to gear.py cannot quietly invalidate it.
        holding = gear.Holding(
            holder="Og", guid=7, entry=3611, name="Plans: Green Iron Boots",
            quality=2, item_level=1, required_level=0, allowable_class=-1,
            inventory_type=0, item_class=9,
        )
        self.assertEqual(
            gear.claimant(holding, []), gear.UNJUDGEABLE,
        )

    def test_it_beats_the_vendor_route(self):
        # CLAIM BEATS DISPOSAL, the ordering the owner asked for out loud.
        # A reachable vendor and a real sell price must not win over a
        # sibling who can learn the thing.
        verdict = disposition.decide(
            _recipe_item(TAILORING), disposition.Family(vendor_reachable=True),
            available=disposition.EXECUTABLE_TODAY,
            family_fit=disposition.FIT_NOBODY, learner="Og",
        )
        self.assertEqual(verdict.route, disposition.GIVE)


class RecipeVerdicts(unittest.TestCase):
    def test_the_holders_own_trade_keeps(self):
        verdict = disposition.decide(
            _recipe_item(ENGINEERING), disposition.Family(vendor_reachable=True),
            available=disposition.EXECUTABLE_TODAY,
            learner=disposition.LEARNER_HOLDER,
        )
        self.assertEqual(verdict.route, disposition.KEEP)

    def test_a_trade_nobody_is_assigned_keeps_rather_than_sells(self):
        verdict = disposition.decide(
            _recipe_item(FIRST_AID), disposition.Family(vendor_reachable=True),
            available=disposition.EXECUTABLE_TODAY,
            learner=disposition.LEARNER_NOBODY,
        )
        self.assertEqual(verdict.route, disposition.KEEP)

    def test_a_trade_nobody_is_assigned_banks_when_a_bank_is_open(self):
        # The same judgement the reagent branch already makes about a material
        # for a profession nobody has taken: not surplus, early.
        verdict = disposition.decide(
            _recipe_item(FIRST_AID),
            disposition.Family(vendor_reachable=True, bank_reachable=True),
            available=disposition.ALL_ROUTES,
            learner=disposition.LEARNER_NOBODY,
        )
        self.assertEqual(verdict.route, disposition.BANK)

    def test_no_handover_route_keeps_rather_than_falling_through(self):
        verdict = disposition.decide(
            _recipe_item(BLACKSMITHING),
            disposition.Family(vendor_reachable=True),
            available=frozenset({disposition.KEEP, disposition.VENDOR}),
            learner="Grug",
        )
        self.assertEqual(verdict.route, disposition.KEEP)

    def test_a_caller_that_never_asked_behaves_exactly_as_before(self):
        # The default must change nothing for every existing call site.
        item = _recipe_item(BLACKSMITHING)
        self.assertEqual(
            disposition.decide(item, disposition.Family(vendor_reachable=True),
                               available=disposition.EXECUTABLE_TODAY).route,
            disposition.decide(item, disposition.Family(vendor_reachable=True),
                               available=disposition.EXECUTABLE_TODAY,
                               learner=disposition.LEARNER_UNASKED).route,
        )

    def test_a_quest_item_is_still_refused_first(self):
        item = disposition.Item(
            name="Plans: Something Questy", quality=2, known=True,
            binding=disposition.BIND_NONE, quest_item=True, item_class=9,
            required_skill=BLACKSMITHING,
        )
        verdict = disposition.decide(
            item, disposition.Family(), available=disposition.EXECUTABLE_TODAY,
            learner="Grug",
        )
        self.assertEqual(verdict.route, disposition.KEEP)

    def test_a_trade_tool_is_still_refused_before_any_recipe_question(self):
        # A Mining Pick is class 2 with a profession bag. The recipe branch
        # must not have been slipped above the gate that infra#3709 exists for.
        item = disposition.Item(
            name="Mining Pick", quality=1, known=True,
            binding=disposition.BIND_NONE, quest_item=False,
            item_class=2, bag_family=1024, required_skill=186,
        )
        verdict = disposition.decide(
            item, disposition.Family(vendor_reachable=True),
            available=disposition.EXECUTABLE_TODAY, learner="Grug",
        )
        self.assertEqual(verdict.route, disposition.KEEP)
        self.assertIn("trade tool", verdict.why)


class RecipeGifts(unittest.TestCase):
    """The adapter, end to end, over rows shaped like the live query's."""

    def _plan(self, rows, **kw):
        kw.setdefault("position_rows", {
            name: {"map_id": 1, "pos_x": 0.0, "pos_y": 0.0}
            for name in ("Grug", "Ugga", "Og", "Grog", "Bork")
        })
        kw.setdefault("free_slots", {
            name: 10 for name in ("Grug", "Ugga", "Og", "Grog", "Bork")
        })
        return bag_pressure.recipe_gifts(rows, HOLDERS, **kw)

    def test_the_misfiled_recipe_becomes_a_grant_to_its_trades_owner(self):
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        plan = self._plan(rows)
        self.assertEqual(len(plan.grants), 1)
        grant = plan.grants[0]
        self.assertEqual((grant.holder, grant.taker), ("Og", "Grug"))
        self.assertEqual(grant.guid, 1507032)
        self.assertEqual(grant.command, "guid:1507032")

    def test_standing_together_trades_and_standing_apart_gives(self):
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        near = self._plan(rows)
        self.assertEqual(near.grants[0].verb, gear.TRADE)
        far = self._plan(rows, position_rows={
            "Og": {"map_id": 1, "pos_x": 0.0, "pos_y": 0.0},
            "Grug": {"map_id": 1, "pos_x": 800.0, "pos_y": 0.0},
        })
        self.assertEqual(far.grants[0].verb, gear.GIVE)

    def test_a_taker_on_another_map_is_still_a_give_not_a_bad_distance(self):
        # Three of the five hearth to Eastern Kingdoms while the dungeon is on
        # Kalimdor; subtracting coordinates across maps yields a number and
        # that number would put an ocean inside eleven yards.
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        plan = self._plan(rows, position_rows={
            "Og": {"map_id": 0, "pos_x": 0.0, "pos_y": 0.0},
            "Grug": {"map_id": 1, "pos_x": 0.0, "pos_y": 0.0},
        })
        self.assertEqual(plan.grants[0].verb, gear.GIVE)

    def test_a_recipe_in_the_right_bag_moves_nothing(self):
        rows = [_row("Grog", 1508070, "Schematic: EZ-Thro Dynamite", ENGINEERING)]
        self.assertEqual(self._plan(rows).grants, ())

    def test_a_manual_nobody_is_assigned_moves_nothing(self):
        rows = [_row("Grug", 1740598, "Manual: Strong Anti-Venom", FIRST_AID)]
        self.assertEqual(self._plan(rows).grants, ())

    def test_a_soulbound_recipe_is_never_offered(self):
        # A recipe that has been used binds on the INSTANCE while its template
        # still reads bonding 0. DoTrade would refuse it, so no row is written.
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING,
                     instance_flags=1)]
        self.assertEqual(self._plan(rows).grants, ())

    def test_an_owner_marked_name_is_left_alone(self):
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        self.assertEqual(
            self._plan(rows, keep_names=("Plans: Green Iron Boots",)).grants, ()
        )

    def test_a_taker_with_no_room_is_withheld_with_a_note(self):
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        plan = self._plan(rows, free_slots={"Og": 10, "Grug": 0})
        self.assertEqual(plan.grants, ())
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("no free bag slot", plan.notes[0])

    def test_a_taker_who_is_not_in_the_world_is_withheld_with_a_note(self):
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        plan = self._plan(rows, position_rows={
            "Og": {"map_id": 1, "pos_x": 0.0, "pos_y": 0.0},
        })
        self.assertEqual(plan.grants, ())
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("not in the world", plan.notes[0])

    def test_room_is_budgeted_across_the_pass_not_per_grant(self):
        # Grug can learn all three, and has one slot. Two doomed rows must not
        # be written; this is the measurement gear.deliverable exists for.
        rows = [
            _row("Og", 1, "Plans: Copper Chain Vest", BLACKSMITHING),
            _row("Og", 2, "Plans: Green Iron Boots", BLACKSMITHING),
            _row("Og", 3, "Plans: Silvered Bronze Breastplate", BLACKSMITHING),
        ]
        plan = self._plan(rows, free_slots={"Og": 10, "Grug": 1})
        self.assertEqual(len(plan.grants), 1)
        self.assertEqual(len(plan.notes), 2)

    def test_the_measured_pile_produces_the_measured_hand_offs(self):
        rows = [
            _row("Grog", 1, "Pattern: Heavy Woolen Cloak", TAILORING),
            _row("Grog", 2, "Plans: Frost Tiger Blade", BLACKSMITHING),
            _row("Grog", 3, "Recipe: Elixir of Giant Growth", ALCHEMY),
            _row("Grog", 4, "Schematic: EZ-Thro Dynamite", ENGINEERING),
            _row("Grug", 5, "Pattern: White Leather Jerkin", LEATHERWORKING),
            _row("Grug", 6, "Recipe: Elixir of Minor Agility", ALCHEMY),
            _row("Og", 7, "Pattern: Dark Leather Tunic", LEATHERWORKING),
            _row("Og", 8, "Plans: Copper Chain Vest", BLACKSMITHING),
            _row("Og", 9, "Plans: Green Iron Boots", BLACKSMITHING),
            _row("Og", 10, "Plans: Silvered Bronze Breastplate", BLACKSMITHING),
            _row("Ugga", 11, "Pattern: Gray Woolen Robe", TAILORING),
            _row("Ugga", 12, "Pattern: Hands of Darkness", TAILORING),
            _row("Grug", 13, "Manual: Strong Anti-Venom", FIRST_AID),
            _row("Og", 14, "Manual: Strong Anti-Venom", FIRST_AID),
            _row("Og", 15, "Manual: Strong Anti-Venom", FIRST_AID),
        ]
        plan = self._plan(rows)
        moved = {g.guid: (g.holder, g.taker) for g in plan.grants}
        self.assertEqual(moved, {
            1: ("Grog", "Og"), 2: ("Grog", "Grug"), 3: ("Grog", "Ugga"),
            5: ("Grug", "Bork"), 6: ("Grug", "Ugga"), 7: ("Og", "Bork"),
            8: ("Og", "Grug"), 9: ("Og", "Grug"), 10: ("Og", "Grug"),
            11: ("Ugga", "Og"), 12: ("Ugga", "Og"),
        })
        # Twelve of fifteen stay: the Schematic is already Grog's, and the
        # three Manuals name no claimant. 11 move, which is the banner's 13
        # less the two that were never movable.
        self.assertEqual(len(plan.grants), 11)

    def test_no_roster_at_all_moves_nothing(self):
        # Fail closed: an empty mapping is "nobody could be named", not
        # "nobody wants any of it".
        rows = [_row("Og", 1507032, "Plans: Green Iron Boots", BLACKSMITHING)]
        self.assertEqual(
            bag_pressure.recipe_gifts(rows, {}).grants, ()
        )


if __name__ == "__main__":
    unittest.main()
