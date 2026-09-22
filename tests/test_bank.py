"""Reading a family's bags and bank, and deciding what crosses the counter.

The pure half of the bank pass (mod-overseer#207 built the executor and
nothing had ever written it a row). Everything here is arithmetic and ordering
over rows written by hand; the routing verdict itself is disposition's and is
tested in test_disposition.py.

Written from the dev family as measured on 2026-09-04: every member with a
bank-side item count of zero, four of five at zero free bag slots, and the
bags full of reagents for crafts nobody in the family has taken.
"""

import pathlib
import unittest

import bank
import disposition


def row(**kw):
    """One joined character_inventory row, as the bridge's SQL names it."""
    base = dict(
        holder="Grug",
        level=20,
        item_guid=1,
        count=1,
        name="Linen Cloth",
        quality=1,
        sell_price=10,
        required_level=0,
        bonding=0,
        item_class=7,
        container_slots=0,
        bag=0,
        slot=23,
    )
    base.update(kw)
    return base


# A family that has taken no trades at all, so every reagent feeds a
# profession nobody has and disposition routes it to the bank.
NOBODY = bank.family_from_skills({})

# The measured family: somebody holds each of these at skill one.
REAL = bank.family_from_skills(
    {
        "Og": {"tailoring": 1, "enchanting": 1},
        "Ugga": {"alchemy": 1, "herbalism": 119},
        "Grug": {"blacksmithing": 1, "mining": 3},
    }
)


class TheRowsBecomeTwoSidesOfACounter(unittest.TestCase):
    def test_the_backpack_is_carried_and_the_bank_slots_are_banked(self):
        members = bank.members_from_rows(
            [row(item_guid=1, slot=23), row(item_guid=2, slot=39)], ["Grug"]
        )
        grug = members[0]
        self.assertEqual([h.guid for h in grug.carried], [1])
        self.assertEqual([h.guid for h in grug.banked], [2])

    def test_an_item_inside_a_worn_bag_is_carried(self):
        rows = [
            row(
                item_guid=50,
                slot=19,
                name="Small Black Pouch",
                item_class=1,
                container_slots=6,
            ),
            row(item_guid=51, bag=50, slot=0),
        ]
        grug = bank.members_from_rows(rows, ["Grug"])[0]
        self.assertEqual([h.guid for h in grug.carried], [51])
        self.assertEqual(grug.banked, ())

    def test_the_same_row_inside_a_bank_bag_is_banked(self):
        """Nothing about an item's own row says which side it is on. Only the
        container it sits in does, which is why this needs two passes."""
        rows = [
            row(
                item_guid=50,
                slot=67,
                name="Small Black Pouch",
                item_class=1,
                container_slots=6,
            ),
            row(item_guid=51, bag=50, slot=0),
        ]
        grug = bank.members_from_rows(rows, ["Grug"])[0]
        self.assertEqual([h.guid for h in grug.banked], [51])
        self.assertEqual(grug.carried, ())

    def test_worn_equipment_is_neither(self):
        grug = bank.members_from_rows([row(item_guid=7, slot=4)], ["Grug"])[0]
        self.assertEqual(grug.carried, ())
        self.assertEqual(grug.banked, ())

    def test_a_container_this_family_does_not_own_is_left_alone(self):
        """A row inside a bag that is not worn and not in the bank - the
        keyring, buyback - is a possession with no verb, not a mystery."""
        grug = bank.members_from_rows([row(item_guid=9, bag=999, slot=0)], ["Grug"])[0]
        self.assertEqual(grug.carried, ())
        self.assertEqual(grug.banked, ())

    def test_a_name_with_no_rows_is_still_a_member(self):
        members = bank.members_from_rows([], ["Bork", "Ugga"])
        self.assertEqual([m.name for m in members], ["Bork", "Ugga"])
        self.assertEqual(members[0].bag_free, bank.BACKPACK_SIZE)
        self.assertEqual(members[0].bank_free, bank.BANK_SIZE)

    def test_rows_for_somebody_else_are_ignored(self):
        members = bank.members_from_rows([row(holder="Stranger")], ["Grug"])
        self.assertEqual([m.name for m in members], ["Grug"])
        self.assertEqual(members[0].carried, ())

    def test_members_come_back_in_a_stable_order(self):
        members = bank.members_from_rows([], ["Ugga", "Bork", "Grug"])
        self.assertEqual([m.name for m in members], ["Bork", "Grug", "Ugga"])


class TheRoomIsCountedHereAndNotInSQL(unittest.TestCase):
    def test_an_empty_character_has_a_backpack_and_a_bank(self):
        grug = bank.members_from_rows([], ["Grug"])[0]
        self.assertEqual(grug.bag_free, 16)
        self.assertEqual(grug.bank_free, 28)

    def test_a_worn_bag_adds_its_slots_and_costs_none(self):
        """It occupies a bag POSITION, which is not an inventory slot."""
        grug = bank.members_from_rows(
            [row(item_guid=50, slot=19, item_class=1, container_slots=6)], ["Grug"]
        )[0]
        self.assertEqual(grug.bag_free, 22)

    def test_a_bank_bag_adds_to_the_bank_and_not_to_the_bags(self):
        grug = bank.members_from_rows(
            [row(item_guid=50, slot=67, item_class=1, container_slots=8)], ["Grug"]
        )[0]
        self.assertEqual(grug.bank_free, 36)
        self.assertEqual(grug.bag_free, 16)

    def test_every_carried_stack_costs_one_slot_whatever_its_size(self):
        rows = [row(item_guid=1, slot=23, count=20), row(item_guid=2, slot=24, count=1)]
        self.assertEqual(bank.members_from_rows(rows, ["Grug"])[0].bag_free, 14)

    def test_a_full_character_has_no_room_rather_than_negative_room(self):
        rows = [row(item_guid=n, slot=n) for n in bank.BACKPACK_SLOTS]
        rows.append(row(item_guid=99, bag=999, slot=0))
        self.assertEqual(bank.members_from_rows(rows, ["Grug"])[0].bag_free, 0)

    def test_an_unreadable_stack_still_occupies_its_slot(self):
        """The slot is full whether or not the item can be identified. Counting
        it as free is how a plan gets written that the world then refuses."""
        grug = bank.members_from_rows([row(item_guid=1, slot=23, name=None)], ["Grug"])[
            0
        ]
        self.assertEqual(grug.bag_free, 15)
        self.assertEqual(grug.carried, ())


class NothingUnreadableIsEverRouted(unittest.TestCase):
    def test_a_row_with_no_name_is_refused_outright(self):
        self.assertIsNone(bank.item_from_row({"quality": 1}))
        self.assertIsNone(bank.item_from_row({"name": ""}))

    def test_an_unreadable_class_reads_as_a_quest_item(self):
        """Which disposition then keeps, because a quest item is never routed
        anywhere at all."""
        item = bank.item_from_row(row(name="???", item_class=None))
        self.assertTrue(item.quest_item)
        self.assertEqual(disposition.decide(item, NOBODY).route, disposition.KEEP)

    def test_an_unreadable_bonding_reads_as_soulbound(self):
        self.assertEqual(
            bank.item_from_row(row(bonding=99)).binding, disposition.BIND_ON_PICKUP
        )
        self.assertEqual(
            bank.item_from_row(row(bonding=None)).binding, disposition.BIND_ON_PICKUP
        )

    def test_a_guid_of_zero_is_not_a_candidate(self):
        """Zero is what every 'not found' path in the core returns, and the
        executor refuses it; planning one would be a guaranteed refusal."""
        grug = bank.members_from_rows([row(item_guid=0, slot=23)], ["Grug"])[0]
        self.assertEqual(grug.carried, ())

    def test_price_and_disenchant_threshold_are_never_guessed(self):
        item = bank.item_from_row(row())
        self.assertIsNone(item.auction_value)
        self.assertIsNone(item.disenchant_skill_required)

    def test_a_reagent_is_recognised_by_the_one_table_that_names_them(self):
        self.assertEqual(
            bank.item_from_row(row(name="Linen Cloth")).reagent_for, "tailoring"
        )
        self.assertIsNone(bank.item_from_row(row(name="Rough Stone")).reagent_for)


class TheFamilyIsWhatItActuallyIsToday(unittest.TestCase):
    def test_a_profession_nobody_has_is_absent_rather_than_zero(self):
        family = bank.family_from_skills({"Og": {"tailoring": 1}})
        self.assertEqual(family.professions.get("tailoring"), 1)
        self.assertIsNone(family.professions.get("jewelcrafting"))

    def test_the_best_skill_anybody_has_is_the_family_answer(self):
        family = bank.family_from_skills(
            {"Og": {"tailoring": 1}, "Ugga": {"tailoring": 60}}
        )
        self.assertEqual(family.professions["tailoring"], 60)

    def test_the_auction_house_is_not_reachable_because_nothing_lists(self):
        self.assertFalse(bank.family_from_skills({}).auction_reachable)

    def test_the_bank_is_reachable_because_this_pass_walks_there(self):
        self.assertTrue(bank.family_from_skills({}).bank_reachable)

    def test_the_enchanter_is_read_off_the_same_skills(self):
        self.assertEqual(
            bank.family_from_skills({"Og": {"enchanting": 1}}).enchanting_skill, 1
        )

    def test_an_empty_or_missing_skill_table_is_a_family_with_no_trades(self):
        for held in (None, {}, {"Og": None}):
            self.assertEqual(bank.family_from_skills(held).professions, {})


class WhatGoesDownAndWhatComesBack(unittest.TestCase):
    def test_a_reagent_nobody_can_use_is_deposited(self):
        members = bank.members_from_rows(
            [row(item_guid=11, name="Malachite", count=12)], ["Grug"]
        )
        plan = bank.plan(members, REAL)
        self.assertEqual(
            [(m.character, m.verb, m.guid) for m in plan.moves],
            [("Grug", bank.DEPOSIT, 11)],
        )

    def test_the_reason_comes_from_disposition_and_is_carried_through(self):
        members = bank.members_from_rows(
            [row(item_guid=11, name="Malachite", count=12)], ["Grug"]
        )
        move = bank.plan(members, REAL).moves[0]
        self.assertIn("jewelcrafting", move.why)

    def test_what_the_family_can_use_is_left_in_the_bags(self):
        members = bank.members_from_rows(
            [row(item_guid=11, name="Linen Cloth", count=5)], ["Grug"]
        )
        self.assertEqual(bank.plan(members, REAL).moves, ())

    def test_a_banked_stack_the_family_can_now_use_comes_back(self):
        members = bank.members_from_rows(
            [row(item_guid=11, name="Linen Cloth", count=5, slot=39)], ["Grug"]
        )
        moves = bank.plan(members, REAL).moves
        self.assertEqual([(m.verb, m.guid) for m in moves], [(bank.WITHDRAW, 11)])

    def test_a_banked_stack_bound_for_a_vendor_is_left_where_it_is(self):
        """Hauling something out of the bank so a different pass can carry
        it to a merchant is a feature with its own travel, not a side
        effect of this one. Where it is, it costs nothing."""
        members = bank.members_from_rows(
            [row(item_guid=11, name="Rough Stone", count=5, slot=39)], ["Grug"]
        )
        self.assertEqual(bank.plan(members, REAL).moves, ())

    def test_only_the_routes_that_want_it_in_the_bags_fetch_it_back(self):
        self.assertEqual(bank.WITHDRAW_ROUTES, (disposition.KEEP, disposition.GIVE))
        self.assertNotIn(disposition.BANK, bank.WITHDRAW_ROUTES)
        self.assertNotIn(disposition.VENDOR, bank.WITHDRAW_ROUTES)

    def test_a_banked_stack_the_family_still_cannot_use_stays_down(self):
        members = bank.members_from_rows(
            [row(item_guid=11, name="Malachite", count=5, slot=39)], ["Grug"]
        )
        self.assertEqual(bank.plan(members, REAL).moves, ())

    def test_a_deposit_is_never_planned_for_something_not_carried(self):
        """The executor's answer to that is `item not carried`, and a queue
        full of those is indistinguishable from a broken bank."""
        members = bank.members_from_rows(
            [row(item_guid=11, name="Malachite", count=12, slot=39)], ["Grug"]
        )
        self.assertNotIn(bank.DEPOSIT, [m.verb for m in bank.plan(members, REAL).moves])

    def test_a_quest_item_never_crosses_the_counter(self):
        members = bank.members_from_rows(
            [row(item_guid=11, name="Gold Pickup Schedule", item_class=12)], ["Grug"]
        )
        self.assertEqual(bank.plan(members, NOBODY).moves, ())

    def test_a_bag_is_not_banked_even_when_it_is_spare(self):
        """An empty one belongs in somebody's empty bag position and a full one
        cannot be moved at all - the executor says so in as many words."""
        members = bank.members_from_rows(
            [
                row(
                    item_guid=11,
                    name="Small Black Pouch",
                    item_class=1,
                    container_slots=6,
                    slot=23,
                )
            ],
            ["Grug"],
        )
        self.assertEqual(bank.plan(members, NOBODY).moves, ())


class TheOrderIsStableAndTheVisitIsBounded(unittest.TestCase):
    def _five_stacks(self):
        return [
            row(item_guid=n, name="Malachite", count=n, slot=23 + n)
            for n in range(1, 6)
        ]

    def test_the_biggest_pile_goes_down_first(self):
        members = bank.members_from_rows(self._five_stacks(), ["Grug"])
        moves = bank.plan(members, REAL).moves
        self.assertEqual([m.guid for m in moves], [5, 4, 3, 2, 1])

    def test_the_same_rows_in_a_different_order_plan_the_same_moves(self):
        rows = self._five_stacks()
        one = bank.plan(bank.members_from_rows(rows, ["Grug"]), REAL)
        two = bank.plan(bank.members_from_rows(list(reversed(rows)), ["Grug"]), REAL)
        self.assertEqual(one.moves, two.moves)

    def test_identical_stacks_are_ordered_by_guid(self):
        rows = [
            row(item_guid=g, name="Malachite", count=4, slot=23 + g) for g in (7, 3, 5)
        ]
        members = bank.members_from_rows(rows, ["Grug"])
        self.assertEqual([m.guid for m in bank.plan(members, REAL).moves], [3, 5, 7])

    def test_one_visit_is_bounded_and_says_so(self):
        rows = [
            row(item_guid=n, name="Malachite", count=n, slot=23 + n)
            for n in range(1, 13)
        ]
        plan = bank.plan(bank.members_from_rows(rows, ["Grug"]), REAL, visit_limit=3)
        self.assertEqual(len(plan.moves), 3)
        self.assertTrue(any("next trip" in note for note in plan.notes))

    def test_characters_are_planned_in_name_order(self):
        rows = [
            row(holder=name, item_guid=n, name="Malachite", count=1)
            for n, name in enumerate(("Ugga", "Bork", "Grug"), start=1)
        ]
        members = bank.members_from_rows(rows, ["Ugga", "Bork", "Grug"])
        self.assertEqual(
            [m.character for m in bank.plan(members, REAL).moves],
            ["Bork", "Grug", "Ugga"],
        )


class TheMoveHasToFitOnBothSides(unittest.TestCase):
    def test_a_full_bank_refuses_the_deposit_and_says_which_item(self):
        rows = [
            row(item_guid=1000 + n, name="Rough Stone", slot=n, item_class=7)
            for n in bank.BANK_ITEM_SLOTS
        ]
        rows.append(row(item_guid=11, name="Malachite", count=9, slot=23))
        plan = bank.plan(bank.members_from_rows(rows, ["Grug"]), REAL)
        self.assertEqual(plan.moves, ())
        self.assertTrue(any("bank is full" in note for note in plan.notes))

    def test_a_withdrawal_needs_a_bag_slot_to_land_in(self):
        rows = [
            row(item_guid=n, name="Rough Stone", slot=n) for n in bank.BACKPACK_SLOTS
        ]
        rows.append(row(item_guid=11, name="Linen Cloth", count=5, slot=39))
        plan = bank.plan(bank.members_from_rows(rows, ["Grug"]), REAL)
        self.assertEqual(plan.moves, ())
        self.assertTrue(any("no room" in note for note in plan.notes))

    def test_a_deposit_makes_room_for_the_withdrawal_behind_it(self):
        """Deposits first is not cosmetic: it is what lets a character with no
        free slots use a bank at all."""
        rows = [
            row(item_guid=n, name="Rough Stone", slot=n) for n in bank.BACKPACK_SLOTS
        ]
        rows[0] = row(item_guid=900, name="Malachite", count=9, slot=23)
        rows.append(row(item_guid=11, name="Linen Cloth", count=5, slot=39))
        moves = bank.plan(bank.members_from_rows(rows, ["Grug"]), REAL).moves
        self.assertEqual(
            [(m.verb, m.guid) for m in moves],
            [(bank.DEPOSIT, 900), (bank.WITHDRAW, 11)],
        )


class ThePairCannotOscillate(unittest.TestCase):
    """A pass that deposits on Monday and withdraws on Tuesday would look
    exactly like a working feature while burning the queue."""

    def test_the_reagent_total_counts_both_sides_of_the_counter(self):
        rows = [
            row(item_guid=1, name="Linen Cloth", count=30, slot=23),
            row(item_guid=2, name="Linen Cloth", count=30, slot=39),
        ]
        members = bank.members_from_rows(rows, ["Grug"])
        self.assertEqual(bank.reagent_totals(members), {"Linen Cloth": 60})

    def test_moving_a_stack_over_the_counter_does_not_change_the_verdict(self):
        carried = [
            row(item_guid=1, name="Malachite", count=30, slot=23),
            row(item_guid=2, name="Malachite", count=30, slot=24),
        ]
        after = [carried[0], dict(carried[1], slot=39)]
        before = bank.plan(bank.members_from_rows(carried, ["Grug"]), REAL)
        settled = bank.plan(bank.members_from_rows(after, ["Grug"]), REAL)
        # Guid 2 was deposited by the first plan; the second must not fetch it
        # straight back out.
        self.assertIn(2, [m.guid for m in before.moves])
        self.assertNotIn(bank.WITHDRAW, [m.verb for m in settled.moves])

    def test_nothing_is_ever_both_deposited_and_withdrawn_in_one_plan(self):
        rows = [
            row(item_guid=1, name="Malachite", count=9, slot=23),
            row(item_guid=2, name="Linen Cloth", count=5, slot=39),
        ]
        moves = bank.plan(bank.members_from_rows(rows, ["Grug"]), REAL).moves
        guids = [m.guid for m in moves]
        self.assertEqual(len(guids), len(set(guids)))


class TheCommandIsTheOneTheExecutorParses(unittest.TestCase):
    """mod-overseer#207's grammar, and it is not negotiable from this side."""

    def test_the_two_verbs_this_module_emits(self):
        self.assertEqual(bank.DEPOSIT, "deposit")
        self.assertEqual(bank.WITHDRAW, "withdraw")

    def test_the_guid_form_and_nothing_else(self):
        move = bank.Move(
            character="Grug",
            verb=bank.DEPOSIT,
            guid=4211,
            item="Malachite",
            count=9,
            why="",
        )
        self.assertEqual(bank.command(move), "deposit guid:4211")

    def test_a_withdraw_says_withdraw(self):
        move = bank.Move(
            character="Grug",
            verb=bank.WITHDRAW,
            guid=7,
            item="Linen Cloth",
            count=5,
            why="",
        )
        self.assertEqual(bank.command(move), "withdraw guid:7")

    def test_there_is_no_entry_form(self):
        """The same entry can sit in the bags AND in the bank at once, which is
        what a deposit produces, so an entry would have two right answers."""
        source = pathlib.Path(bank.__file__).read_text(encoding="utf-8")
        self.assertNotIn("entry:", source.replace("no `entry:` form", ""))

    def test_buy_slot_is_deliberately_not_emitted(self):
        """It is in the grammar and it is argued about in the docstring rather
        than half-built here."""
        self.assertFalse(hasattr(bank, "BUY_SLOT"))
        self.assertIn("buy slot", bank.__doc__)

    def test_the_log_line_names_the_command_that_was_written(self):
        move = bank.Move(
            character="Grug",
            verb=bank.DEPOSIT,
            guid=4211,
            item="Malachite",
            count=9,
            why="nobody can cut it",
        )
        line = bank.lines([move])[0]
        self.assertIn("deposit guid:4211", line)
        self.assertIn("nobody can cut it", line)

    def test_lines_takes_the_moves_that_were_written_not_the_plan(self):
        """A pass logs what it WROTE. Half a plan can be dropped by the retry
        window, and a log that reported the plan would be lying."""
        self.assertEqual(bank.lines([]), [])


if __name__ == "__main__":
    unittest.main()
