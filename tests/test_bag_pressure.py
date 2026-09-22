import ast
import pathlib
import unittest

import disposition
from bag_pressure import (
    ItemForSale,
    bag_candidates,
    bag_purchase_allowed,
    family_town_run_needed,
    gear_candidates,
    item_binding,
    sellable,
    town_run_needed,
    protection_counts,
    vendor_batch,
    vendor_candidates,
    vendor_holders_to_queue,
)

# The family in town: a vendor in reach, nothing else built yet.
IN_TOWN = disposition.Family(vendor_reachable=True)


def gear(**kw):
    """One carried armour row, shaped as the vendor SQL returns it."""
    base = dict(
        holder="Grog",
        level=26,
        item_guid=5001,
        count=1,
        instance_flags=0,
        name="Smelting Pants",
        quality=2,
        sell_price=966,
        required_level=16,
        bonding=2,
        item_class=4,
    )
    base.update(kw)
    return base


def bag(**kw):
    """One carried container row, shaped as the vendor SQL returns it.

    Defaults are Grug's real "Green Leather Bag" (infra#4163): 8 slots,
    common quality, unbound, worth 875 copper - a redundant duplicate of one
    of his two equipped 8-slot bags.
    """
    base = dict(
        holder="Grug",
        item_guid=9001,
        count=1,
        instance_flags=0,
        name="Green Leather Bag",
        quality=1,
        sell_price=875,
        item_class=1,
        container_slots=8,
        bonding=0,
    )
    base.update(kw)
    return base


# Grug's real four equipped bags (infra#4163): two 16-slot, two 8-slot.
GRUG_EQUIPPED_BAGS = {"Grug": (16, 16, 8, 8)}


class BagPressureTests(unittest.TestCase):
    def test_full_family_triggers_town_run(self):
        self.assertTrue(town_run_needed(44, 44))
        self.assertFalse(town_run_needed(10, 44))

    def test_any_family_member_at_the_floor_triggers_town_run(self):
        self.assertTrue(family_town_run_needed({"Grug": 0, "Ugga": 10}))
        self.assertTrue(family_town_run_needed({"Grug": 2}))
        # mod-overseer's town trip starts at three free slots. The bridge must
        # produce its sale rows at the same boundary or the family reaches the
        # vendor and waits through the whole dwell with nothing to execute.
        self.assertTrue(family_town_run_needed({"Grug": 3, "Ugga": 10}))
        self.assertFalse(family_town_run_needed({"Grug": 4, "Ugga": 10}))

    def test_unknown_family_capacity_does_not_trigger_a_blind_trip(self):
        self.assertFalse(family_town_run_needed({}))
        self.assertFalse(family_town_run_needed({"Grug": -1}))
        self.assertFalse(family_town_run_needed({"Grug": None}))

    def test_never_sells_a_rare(self):
        self.assertFalse(sellable(ItemForSale(quality=3, sell_price=500)))

    def test_never_sells_quest_or_profession_materials(self):
        self.assertFalse(
            sellable(ItemForSale(quality=1, quest_item=True, sell_price=1))
        )
        self.assertFalse(sellable(ItemForSale(quality=1, reagent=True, sell_price=1)))
        self.assertFalse(
            sellable(ItemForSale(quality=1, profession_needed=True, sell_price=1))
        )

    def test_sells_only_positive_value_common_goods(self):
        self.assertTrue(sellable(ItemForSale(quality=0, sell_price=10)))
        self.assertFalse(sellable(ItemForSale(quality=1, sell_price=0)))

    def test_protection_counts_explain_overlapping_bag_pressure(self):
        rows = [
            {
                "quality": 3,
                "sell_price": 20,
                "quest_item": True,
                "reagent": False,
                "profession_needed": False,
            },
            {
                "quality": 1,
                "sell_price": 3,
                "quest_item": False,
                "reagent": True,
                "profession_needed": True,
            },
            {"quality": 0, "sell_price": 1},
        ]
        self.assertEqual(
            protection_counts(rows),
            {
                "rows": 3,
                "quest": 1,
                "reagent": 1,
                "profession": 1,
                "rare_or_better": 1,
                "unknown": 1,
            },
        )

    def test_bag_purchase_requires_empty_position_and_reserve(self):
        self.assertTrue(bag_purchase_allowed(20000, 5000, True))
        self.assertFalse(bag_purchase_allowed(12000, 5000, True))
        self.assertFalse(bag_purchase_allowed(20000, 5000, False))

    def test_vendor_candidates_preserve_identity_and_count(self):
        rows = [
            {
                "holder": "Og",
                "item_guid": 42,
                "count": 7,
                "quality": 0,
                "sell_price": 12,
                "quest_item": False,
                "reagent": False,
                "profession_needed": False,
            }
        ]
        self.assertEqual(vendor_candidates(rows)[0].item_guid, 42)
        self.assertEqual(vendor_candidates(rows)[0].count, 7)

    def test_vendor_candidates_fail_closed_for_unknowns(self):
        rows = [
            {
                "holder": "Og",
                "item_guid": 43,
                "count": 1,
                "quality": 0,
                "sell_price": 12,
            }
        ]
        self.assertEqual(vendor_candidates(rows), ())

    def test_vendor_batch_scopes_one_travelling_holder(self):
        rows = vendor_candidates(
            [
                {
                    "holder": "Og",
                    "item_guid": 7,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 3,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
                {
                    "holder": "Grug",
                    "item_guid": 8,
                    "count": 2,
                    "quality": 1,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
            ]
        )
        holder, batch = vendor_batch(rows)
        self.assertEqual(holder, "Grug")
        self.assertEqual([item.holder for item in batch], ["Grug"])

    def test_leader_arrival_queues_followers_for_executor_retry(self):
        rows = vendor_candidates(
            [
                {
                    "holder": "Og",
                    "item_guid": 7,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 3,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
                {
                    "holder": "Grug",
                    "item_guid": 8,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
            ]
        )
        self.assertEqual(
            ("Grug", "Og"),
            vendor_holders_to_queue(
                rows,
                leader="Grug",
                leader_at_counter=True,
                holder_at_counter=lambda _: False,
            ),
        )

    def test_before_leader_arrival_range_gate_is_preserved(self):
        rows = vendor_candidates(
            [
                {
                    "holder": "Og",
                    "item_guid": 7,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 3,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
                {
                    "holder": "Grug",
                    "item_guid": 8,
                    "count": 1,
                    "quality": 0,
                    "sell_price": 4,
                    "quest_item": False,
                    "reagent": False,
                    "profession_needed": False,
                },
            ]
        )
        self.assertEqual(
            ("Grug",),
            vendor_holders_to_queue(
                rows,
                leader="Grug",
                leader_at_counter=False,
                holder_at_counter=lambda name: name == "Grug",
            ),
        )


class BindingIsAFactAboutTheCopy(unittest.TestCase):
    def test_a_worn_bind_on_equip_green_is_soulbound(self):
        """38 of the family's 111 bind-on-equip greens are in this state."""
        self.assertEqual(
            item_binding(gear(bonding=2, instance_flags=1)), disposition.BIND_ON_PICKUP
        )

    def test_an_unworn_bind_on_equip_green_is_still_tradable(self):
        self.assertEqual(
            item_binding(gear(bonding=2, instance_flags=0)), disposition.BIND_ON_EQUIP
        )

    def test_a_bonding_value_we_cannot_read_is_no_answer_at_all(self):
        self.assertEqual(item_binding(gear(bonding=99)), "")
        self.assertEqual(gear_candidates([gear(bonding=99)], IN_TOWN), ())


class OnlyGearNobodyElseCouldEverUse(unittest.TestCase):
    """Clearing the bags without spending what the family cannot get back."""

    def test_an_outgrown_soulbound_piece_is_offered_to_the_vendor(self):
        got = gear_candidates([gear(instance_flags=1, required_level=15)], IN_TOWN)
        self.assertEqual([c.item_guid for c in got], [5001])
        self.assertEqual(got[0].holder, "Grog")

    def test_a_tradable_green_is_left_alone_while_nothing_can_list_it(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=0, required_level=15)], IN_TOWN), ()
        )

    def test_gear_close_to_level_is_never_sold_however_it_is_bound(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=25)], IN_TOWN), ()
        )

    def test_a_worthless_piece_is_not_walked_to_a_vendor(self):
        self.assertEqual(
            gear_candidates(
                [gear(instance_flags=1, required_level=15, sell_price=0)], IN_TOWN
            ),
            (),
        )

    def test_a_quest_item_is_refused_even_wearing_an_armour_class(self):
        self.assertEqual(
            gear_candidates(
                [gear(instance_flags=1, required_level=15, item_class=12)], IN_TOWN
            ),
            (),
        )

    def test_a_row_missing_the_facts_is_dropped_not_guessed_at(self):
        broken = gear(instance_flags=1, required_level=15)
        del broken["sell_price"]
        self.assertEqual(gear_candidates([broken], IN_TOWN), ())

    def test_no_vendor_in_reach_means_nothing_is_queued(self):
        away = disposition.Family(vendor_reachable=False)
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=15)], away), ()
        )

    def test_turning_the_auction_on_stops_the_vendor_taking_them(self):
        """When mod-overseer#208 lands, the same soulbound piece is still a
        vendor sale, because soulbound is the fact that decides it."""
        both = disposition.EXECUTABLE_TODAY | {disposition.AUCTION}
        got = gear_candidates(
            [gear(instance_flags=1, required_level=15)], IN_TOWN, available=both
        )
        self.assertEqual(len(got), 1)


class RedundantCarriedBags(unittest.TestCase):
    """Bags that duplicate what a holder already wears (infra#4163)."""

    def test_a_bag_no_better_than_the_smallest_equipped_one_is_sold(self):
        got = bag_candidates([bag()], GRUG_EQUIPPED_BAGS)
        self.assertEqual([c.item_guid for c in got], [9001])
        self.assertEqual(got[0].holder, "Grug")

    def test_a_bag_that_beats_the_smallest_equipped_one_is_kept(self):
        """Grug's real Netherweave Bag: 16 slots beats his two 8-slot bags -
        an upgrade, not vendor trash, even though it is still unbound."""
        self.assertEqual(
            bag_candidates(
                [bag(container_slots=16, quality=2, sell_price=10000)],
                GRUG_EQUIPPED_BAGS,
            ),
            (),
        )

    def test_a_bind_on_equip_bag_is_kept_even_when_it_is_no_upgrade(self):
        """One accidental /equip from being useful - out of scope here."""
        self.assertEqual(bag_candidates([bag(bonding=2)], GRUG_EQUIPPED_BAGS), ())

    def test_a_holder_with_no_known_equipped_bags_keeps_everything(self):
        self.assertEqual(bag_candidates([bag()], {}), ())
        self.assertEqual(bag_candidates([bag(holder="Ugga")], GRUG_EQUIPPED_BAGS), ())

    def test_the_owners_never_dispose_mark_protects_a_bag(self):
        self.assertEqual(
            bag_candidates(
                [bag()], GRUG_EQUIPPED_BAGS, keep_names=("Green Leather Bag",)
            ),
            (),
        )

    def test_a_worthless_bag_is_not_walked_to_a_vendor(self):
        self.assertEqual(bag_candidates([bag(sell_price=0)], GRUG_EQUIPPED_BAGS), ())

    def test_a_non_container_item_class_is_never_treated_as_a_bag(self):
        self.assertEqual(bag_candidates([bag(item_class=12)], GRUG_EQUIPPED_BAGS), ())

    def test_a_row_missing_the_facts_is_dropped_not_guessed_at(self):
        broken = bag()
        del broken["container_slots"]
        self.assertEqual(bag_candidates([broken], GRUG_EQUIPPED_BAGS), ())


if __name__ == "__main__":
    unittest.main()


BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"


class TheVendorPassAsksBothHalvesTests(unittest.TestCase):
    """infra#4190: the wiring, not the predicate.

    `family_town_run_needed` grew a `sellable` half, but a caller that omits
    it still compiles and still returns the old answer - which is exactly how
    this would silently regress. bridge.py imports discord and cannot be
    imported here, so this parses it instead. Parsed rather than grepped
    because the comments around these calls quote the old one-argument shape
    verbatim, and a text match would find the prose describing the bug and
    pass while the bug was live.
    """

    def _vendor_once(self):
        tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                and node.name == "_vendor_once"
            ):
                return node
        self.fail("_vendor_once not found in bridge.py")

    def test_every_pressure_question_in_the_vendor_pass_supplies_sellable(self):
        calls = []
        for node in ast.walk(self._vendor_once()):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "family_town_run_needed"
            ):
                calls.append(node)
        self.assertTrue(calls, "the vendor pass asks no pressure question")
        for call in calls:
            kwargs = {kw.arg for kw in call.keywords}
            self.assertIn(
                "sellable",
                kwargs,
                f"bridge.py line {call.lineno}: family_town_run_needed without "
                "`sellable=` asks only whether somebody is full, not whether a "
                "vendor could help - which is infra#4190",
            )


class AVendorTripMustBeAbleToHelpTests(unittest.TestCase):
    """infra#4190: pressure nobody can answer starved the travel column.

    Og's measured position on 2026-09-19 is the case these pin: 0 free slots
    of 62, one sellable spare bag, everything else protected. Selling all a
    vendor would take reaches 1 free slot against a trigger of 3, so the
    pressure could never clear and the vendor pass re-took the column for
    hours writing no sale.
    """

    def test_a_member_a_vendor_cannot_lift_past_the_trigger_is_not_pressure(self):
        # Og: 0 free, exactly one thing a vendor would accept. 0 + 1 = 1,
        # which is still under the trigger, so the trip cannot answer him.
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": 1}))

    def test_a_member_a_vendor_can_lift_past_the_trigger_is_pressure(self):
        # 0 + 4 clears a trigger of 3, so the trip is worth taking.
        self.assertTrue(family_town_run_needed({"Og": 0}, sellable={"Og": 4}))

    def test_exactly_reaching_the_trigger_is_not_enough(self):
        # `free <= minimum_free` is what RAISED the pressure, so landing back
        # on the boundary would re-raise it on the next cycle - the trip has
        # to get them past it or it buys nothing.
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": 3}))
        self.assertTrue(family_town_run_needed({"Og": 1}, sellable={"Og": 3}))

    def test_one_relievable_member_is_enough_even_beside_a_hopeless_one(self):
        # Og cannot be helped; Ugga can. The family should still go.
        self.assertTrue(
            family_town_run_needed({"Og": 0, "Ugga": 1}, sellable={"Og": 1, "Ugga": 9})
        )

    def test_a_member_with_room_is_never_pressure_however_much_he_carries(self):
        self.assertFalse(family_town_run_needed({"Bork": 11}, sellable={"Bork": 40}))

    def test_an_unlisted_member_reads_as_nothing_to_sell(self):
        # Fail closed, matching the existing unknown-capacity bias: a name the
        # caller could not measure must not send the family on a blind trip.
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={}))

    def test_a_broken_sellable_count_is_skipped_rather_than_trusted(self):
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": -5}))
        self.assertFalse(family_town_run_needed({"Og": 0}, sellable={"Og": None}))

    def test_omitting_the_argument_preserves_the_original_behaviour(self):
        # Every caller that only wants "is anyone low" is unchanged.
        self.assertTrue(family_town_run_needed({"Og": 0}))
        self.assertTrue(family_town_run_needed({"Og": 0}, sellable=None))
