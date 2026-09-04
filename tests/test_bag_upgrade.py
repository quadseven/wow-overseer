"""The family already owned the room it needed.

Measured 2026-09-04 on the dev family: 273 of 274 slots used, four of five at
zero free, transfers failing with "receiver bags are full", and SIX unequipped
bags being carried between them while Bork had an empty bag position. These
tests are written from those exact inventories, because the bug was not that
the arithmetic was wrong - there was no arithmetic at all.
"""
import unittest

from bag_pressure import ItemForSale, sellable
from bag_upgrade import (Bag, Member, bags_in_plan, fill_empty_positions,
                         give_command, plan_bag_moves, plan_family_bags,
                         slots_gained, upgrade_swaps)

# The real thing, as measured. Bork is the one with somewhere to put a bag.
BORK_WORN = [Bag("Small Black Pouch", 6, used=6),
             Bag("Small Black Pouch", 6, used=6),
             Bag("Linen Bag", 6, used=6)]
GROG_CARRIED = [Bag("Red Leather Bag", 12), Bag("Green Leather Bag", 12)]


class TheEmptyPositionIsFreeRoom(unittest.TestCase):

    def test_borks_empty_position_is_filled(self):
        moves = fill_empty_positions(4, BORK_WORN, GROG_CARRIED)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].action, "equip")
        self.assertEqual(moves[0].position, 3)

    def test_the_largest_carried_bag_is_the_one_put_on(self):
        moves = fill_empty_positions(
            4, BORK_WORN, [Bag("Small Black Pouch", 6), Bag("Red Leather Bag", 12)])
        self.assertEqual(moves[0].bag, "Red Leather Bag")

    def test_the_gain_counts_the_slot_the_bag_gives_back(self):
        """A carried bag costs a slot AND provides none, which is why filling a
        position is worth its capacity plus one rather than just its capacity."""
        moves = fill_empty_positions(4, BORK_WORN, [Bag("Red Leather Bag", 12)])
        self.assertEqual(moves[0].slots_gained, 13)

    def test_a_character_with_every_position_full_gets_no_equip(self):
        full = BORK_WORN + [Bag("Linen Bag", 6, used=6)]
        self.assertEqual(fill_empty_positions(4, full, GROG_CARRIED), [])

    def test_nothing_carried_means_nothing_to_do(self):
        self.assertEqual(fill_empty_positions(4, BORK_WORN, []), [])

    def test_two_empty_positions_take_the_two_biggest_in_order(self):
        moves = fill_empty_positions(
            4, BORK_WORN[:2],
            [Bag("Small Black Pouch", 6), Bag("Red Leather Bag", 12),
             Bag("Green Leather Bag", 10)])
        self.assertEqual([m.bag for m in moves],
                         ["Red Leather Bag", "Green Leather Bag"])


class ASwapMustNotStrandWhatComesOut(unittest.TestCase):
    """The dangerous half. Every test here is about refusing a move."""

    def test_a_strictly_larger_bag_replaces_a_small_one(self):
        moves = upgrade_swaps([Bag("Small Black Pouch", 6, used=0)],
                              [Bag("Red Leather Bag", 12)], free_slots=0)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].replaces, "Small Black Pouch")
        self.assertEqual(moves[0].slots_gained, 6)

    def test_an_equal_sized_bag_is_not_an_upgrade(self):
        """Moving items for no gain is not a decision, it is churn."""
        self.assertEqual(upgrade_swaps([Bag("Linen Bag", 6, used=0)],
                                       [Bag("Small Black Pouch", 6)],
                                       free_slots=10), [])

    def test_a_smaller_bag_is_never_put_on(self):
        self.assertEqual(upgrade_swaps([Bag("Red Leather Bag", 12, used=0)],
                                       [Bag("Small Black Pouch", 6)],
                                       free_slots=10), [])

    def test_a_full_bag_is_not_taken_off_with_nowhere_to_put_its_contents(self):
        """Six items come out and the swap only creates two slots. Refuse."""
        self.assertEqual(upgrade_swaps([Bag("Small Black Pouch", 6, used=6)],
                                       [Bag("Linen Bag", 8)],
                                       free_slots=0), [])

    def test_the_same_swap_is_allowed_once_there_is_room_to_land(self):
        moves = upgrade_swaps([Bag("Small Black Pouch", 6, used=6)],
                              [Bag("Linen Bag", 8)], free_slots=4)
        self.assertEqual(len(moves), 1)

    def test_one_carried_bag_cannot_fill_two_positions(self):
        moves = upgrade_swaps(
            [Bag("Small Black Pouch", 6, used=0), Bag("Small Black Pouch", 6, used=0)],
            [Bag("Red Leather Bag", 12)], free_slots=20)
        self.assertEqual(len(moves), 1)

    def test_a_bag_already_spoken_for_is_not_reused(self):
        moves = upgrade_swaps([Bag("Small Black Pouch", 6, used=0)],
                              [Bag("Red Leather Bag", 12)], free_slots=20,
                              already_used={"Red Leather Bag"})
        self.assertEqual(moves, [])


class ThePlanAsAWhole(unittest.TestCase):

    def test_bork_gets_a_bag_from_the_family(self):
        moves = plan_bag_moves(4, BORK_WORN, GROG_CARRIED, free_slots=0)
        self.assertTrue(moves)
        self.assertEqual(moves[0].action, "equip")
        self.assertGreater(slots_gained(moves), 0)

    def test_filling_a_position_first_can_make_a_swap_possible(self):
        """Order matters and this is why: the equip hands back room, and that
        room is what lets a full bag be swapped afterwards. Planned the other
        way round, the swap is refused."""
        worn = [Bag("Small Black Pouch", 6, used=6)]
        carried = [Bag("Red Leather Bag", 12), Bag("Green Leather Bag", 12)]
        moves = plan_bag_moves(4, worn, carried, free_slots=0)
        self.assertEqual([m.action for m in moves][:2], ["equip", "equip"])

    def test_a_settled_character_is_left_alone(self):
        worn = [Bag("Red Leather Bag", 12, used=1)] * 4
        self.assertEqual(plan_bag_moves(4, worn, [], free_slots=30), [])

    def test_no_position_is_moved_twice(self):
        moves = plan_bag_moves(4, BORK_WORN, GROG_CARRIED, free_slots=20)
        positions = [m.position for m in moves]
        self.assertEqual(len(positions), len(set(positions)))

    def test_no_bag_is_used_twice(self):
        moves = plan_bag_moves(4, BORK_WORN, GROG_CARRIED, free_slots=20)
        names = [m.bag for m in moves]
        self.assertEqual(len(names), len(set(names)))

    def test_every_move_carries_its_reason(self):
        for move in plan_bag_moves(4, BORK_WORN, GROG_CARRIED, free_slots=20):
            self.assertTrue(move.why.strip(),
                            "a move with no reason cannot be reviewed in a log")


class TheSaleRuleMustNotSellTheseBags(unittest.TestCase):
    """The interaction that makes these two modules one decision.

    A Small Black Pouch is a common item with a vendor price, so the sale rule
    approves it on its own terms. If a vendor run were planned before the bags
    were put on, the family would sell the exact room it was going to town to
    buy.
    """

    def test_the_sale_rule_would_happily_sell_a_pouch(self):
        pouch = ItemForSale(quality=1, sell_price=125)
        self.assertTrue(sellable(pouch),
                        "if this ever becomes False the guard below is moot, "
                        "but the plan must still be consulted")

    def test_the_plan_names_the_bags_that_must_be_spared(self):
        moves = plan_bag_moves(4, BORK_WORN, GROG_CARRIED, free_slots=0)
        spared = bags_in_plan(moves)
        self.assertIn(moves[0].bag, spared)

    def test_nothing_is_spared_when_no_move_needs_it(self):
        worn = [Bag("Red Leather Bag", 12, used=1)] * 4
        self.assertEqual(bags_in_plan(plan_bag_moves(4, worn, [], 30)), set())

# The measured family, 2026-09-04. Four of them carry spare bags and have no
# empty position; the one with an empty position carries none. That mismatch is
# the whole reason a per-character plan decides nothing here.
FAMILY = [
    Member("Grug", 4, worn=tuple(Bag("worn", 16, used=16, guid=900 + i) for i in range(4)),
           carried=(Bag("Small Red Pouch", 6, guid=11),
                    Bag("Small Black Pouch", 6, guid=12),
                    Bag("Small Black Pouch", 6, guid=13))),
    Member("Ugga", 4, worn=tuple(Bag("worn", 10, used=10, guid=910 + i) for i in range(4)),
           carried=()),
    Member("Og", 4, worn=tuple(Bag("worn", 14, used=14, guid=920 + i) for i in range(4)),
           carried=(Bag("Small Black Pouch", 6, guid=21),)),
    Member("Grog", 4, worn=tuple(Bag("worn", 11, used=11, guid=930 + i) for i in range(4)),
           carried=(Bag("Red Leather Bag", 12, guid=31),
                    Bag("Green Leather Bag", 12, guid=32))),
    Member("Bork", 4, worn=tuple(Bag("worn", 13, used=13, guid=940 + i) for i in range(3)),
           carried=()),
]


class TheFamilyHandsBorkABag(unittest.TestCase):
    """The measured case, end to end."""

    def test_exactly_one_handover_is_planned(self):
        """One empty position in the whole family means one move. Planning more
        would be planning bags into positions that do not exist."""
        self.assertEqual(len(plan_family_bags(FAMILY)), 1)

    def test_it_goes_to_the_one_with_somewhere_to_put_it(self):
        self.assertEqual(plan_family_bags(FAMILY)[0].receiver, "Bork")

    def test_the_biggest_idle_bag_in_the_family_is_the_one_sent(self):
        """Grog's two leather bags at 12 beat three Small Black Pouches at 6,
        and it does not matter that Grug is carrying more of them. Grog holds
        two bags of the SAME size, so the alphabetical tie-break decides -
        arbitrary but stable, which is the property that matters."""
        move = plan_family_bags(FAMILY)[0]
        self.assertEqual((move.giver, move.bag), ("Grog", "Green Leather Bag"))

    def test_the_gain_counts_both_ends(self):
        """The bag stops costing Grog a slot and starts giving Bork twelve, so
        the transfer helps both characters, not just the receiver."""
        self.assertEqual(plan_family_bags(FAMILY)[0].slots_gained, 13)

    def test_the_move_names_the_exact_item(self):
        """Three identical Small Black Pouches exist. An entry id would name
        any of them; the guid names the one that was weighed."""
        self.assertEqual(plan_family_bags(FAMILY)[0].guid, 32)
        self.assertEqual(give_command(plan_family_bags(FAMILY)[0]), "guid:32")

    def test_every_handover_explains_itself(self):
        for move in plan_family_bags(FAMILY):
            self.assertTrue(move.why.strip())
            self.assertIn(move.receiver, move.why)


class NothingIsPlannedTwice(unittest.TestCase):

    def test_two_empty_positions_get_two_different_bags(self):
        family = list(FAMILY)
        family[-1] = Member("Bork", 4, worn=tuple(
            Bag("worn", 13, used=13, guid=940 + i) for i in range(2)), carried=())
        moves = plan_family_bags(family)
        self.assertEqual(len(moves), 2)
        self.assertEqual(len({m.guid for m in moves}), 2)

    def test_more_empty_positions_than_spare_bags_is_not_invented_around(self):
        """Six spares exist in the measured family; ask for more and the plan
        must stop rather than name a bag twice."""
        family = [Member("Bork", 4, worn=(), carried=()),
                  Member("Grog", 4, worn=(), carried=(Bag("Red Leather Bag", 12, guid=31),))]
        moves = plan_family_bags(family)
        self.assertEqual(len(moves), 1)

    def test_nobody_gives_a_bag_to_themselves(self):
        """Putting on a bag you already carry is not a give, and give is the
        only mechanism there is. A plan that emitted one would be a command the
        world refuses."""
        alone = [Member("Grug", 4, worn=(Bag("worn", 16, used=16, guid=900),),
                        carried=(Bag("Small Red Pouch", 6, guid=11),))]
        self.assertEqual(plan_family_bags(alone), [])

    def test_a_family_with_no_empty_positions_is_left_alone(self):
        settled = [Member(m.name, 4,
                          worn=tuple(Bag("worn", 12, used=1, guid=800 + i) for i in range(4)),
                          carried=m.carried)
                   for i, m in enumerate(FAMILY)]
        self.assertEqual(plan_family_bags(settled), [])

    def test_a_family_carrying_nothing_spare_is_left_alone(self):
        bare = [Member("Bork", 4, worn=(), carried=())]
        self.assertEqual(plan_family_bags(bare), [])


class ThePlanIsStable(unittest.TestCase):
    """A plan that reordered between runs would make the give queue flap and
    the logs unreadable."""

    def test_the_same_family_plans_the_same_way_twice(self):
        self.assertEqual(plan_family_bags(FAMILY), plan_family_bags(FAMILY))

    def test_member_order_does_not_change_the_answer(self):
        self.assertEqual(plan_family_bags(FAMILY),
                         plan_family_bags(list(reversed(FAMILY))))


if __name__ == "__main__":
    unittest.main()
