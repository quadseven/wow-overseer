import unittest

import disposition
from bag_pressure import (ItemForSale, bag_purchase_allowed, family_town_run_needed,
                          gear_candidates, item_binding, sellable, town_run_needed,
                          protection_counts, vendor_batch, vendor_candidates,
                          vendor_holders_to_queue)

# The family in town: a vendor in reach, nothing else built yet.
IN_TOWN = disposition.Family(vendor_reachable=True)


def gear(**kw):
    """One carried armour row, shaped as the vendor SQL returns it."""
    base = dict(holder="Grog", level=26, item_guid=5001, count=1,
                instance_flags=0, name="Smelting Pants", quality=2,
                sell_price=966, required_level=16, bonding=2, item_class=4)
    base.update(kw)
    return base


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
        self.assertFalse(sellable(ItemForSale(quality=1, quest_item=True, sell_price=1)))
        self.assertFalse(sellable(ItemForSale(quality=1, reagent=True, sell_price=1)))
        self.assertFalse(sellable(ItemForSale(quality=1, profession_needed=True, sell_price=1)))

    def test_sells_only_positive_value_common_goods(self):
        self.assertTrue(sellable(ItemForSale(quality=0, sell_price=10)))
        self.assertFalse(sellable(ItemForSale(quality=1, sell_price=0)))

    def test_protection_counts_explain_overlapping_bag_pressure(self):
        rows = [
            {"quality": 3, "sell_price": 20, "quest_item": True,
             "reagent": False, "profession_needed": False},
            {"quality": 1, "sell_price": 3, "quest_item": False,
             "reagent": True, "profession_needed": True},
            {"quality": 0, "sell_price": 1},
        ]
        self.assertEqual(
            protection_counts(rows),
            {"rows": 3, "quest": 1, "reagent": 1, "profession": 1,
             "rare_or_better": 1, "unknown": 1},
        )

    def test_bag_purchase_requires_empty_position_and_reserve(self):
        self.assertTrue(bag_purchase_allowed(20000, 5000, True))
        self.assertFalse(bag_purchase_allowed(12000, 5000, True))
        self.assertFalse(bag_purchase_allowed(20000, 5000, False))

    def test_vendor_candidates_preserve_identity_and_count(self):
        rows = [{"holder": "Og", "item_guid": 42, "count": 7,
                 "quality": 0, "sell_price": 12,
                 "quest_item": False, "reagent": False,
                 "profession_needed": False}]
        self.assertEqual(vendor_candidates(rows)[0].item_guid, 42)
        self.assertEqual(vendor_candidates(rows)[0].count, 7)

    def test_vendor_candidates_fail_closed_for_unknowns(self):
        rows = [{"holder": "Og", "item_guid": 43, "count": 1,
                 "quality": 0, "sell_price": 12}]
        self.assertEqual(vendor_candidates(rows), ())

    def test_vendor_batch_scopes_one_travelling_holder(self):
        rows = vendor_candidates([
            {"holder": "Og", "item_guid": 7, "count": 1,
             "quality": 0, "sell_price": 3, "quest_item": False,
             "reagent": False, "profession_needed": False},
            {"holder": "Grug", "item_guid": 8, "count": 2,
             "quality": 1, "sell_price": 4, "quest_item": False,
             "reagent": False, "profession_needed": False},
        ])
        holder, batch = vendor_batch(rows)
        self.assertEqual(holder, "Grug")
        self.assertEqual([item.holder for item in batch], ["Grug"])

    def test_leader_arrival_queues_followers_for_executor_retry(self):
        rows = vendor_candidates([
            {"holder": "Og", "item_guid": 7, "count": 1,
             "quality": 0, "sell_price": 3, "quest_item": False,
             "reagent": False, "profession_needed": False},
            {"holder": "Grug", "item_guid": 8, "count": 1,
             "quality": 0, "sell_price": 4, "quest_item": False,
             "reagent": False, "profession_needed": False},
        ])
        self.assertEqual(
            ("Grug", "Og"),
            vendor_holders_to_queue(
                rows, leader="Grug", leader_at_counter=True,
                holder_at_counter=lambda _: False,
            ),
        )

    def test_before_leader_arrival_range_gate_is_preserved(self):
        rows = vendor_candidates([
            {"holder": "Og", "item_guid": 7, "count": 1,
             "quality": 0, "sell_price": 3, "quest_item": False,
             "reagent": False, "profession_needed": False},
            {"holder": "Grug", "item_guid": 8, "count": 1,
             "quality": 0, "sell_price": 4, "quest_item": False,
             "reagent": False, "profession_needed": False},
        ])
        self.assertEqual(
            ("Grug",),
            vendor_holders_to_queue(
                rows, leader="Grug", leader_at_counter=False,
                holder_at_counter=lambda name: name == "Grug",
            ),
        )


class BindingIsAFactAboutTheCopy(unittest.TestCase):

    def test_a_worn_bind_on_equip_green_is_soulbound(self):
        """38 of the family's 111 bind-on-equip greens are in this state."""
        self.assertEqual(item_binding(gear(bonding=2, instance_flags=1)),
                         disposition.BIND_ON_PICKUP)

    def test_an_unworn_bind_on_equip_green_is_still_tradable(self):
        self.assertEqual(item_binding(gear(bonding=2, instance_flags=0)),
                         disposition.BIND_ON_EQUIP)

    def test_a_bonding_value_we_cannot_read_is_no_answer_at_all(self):
        self.assertEqual(item_binding(gear(bonding=99)), "")
        self.assertEqual(gear_candidates([gear(bonding=99)], IN_TOWN), ())


class OnlyGearNobodyElseCouldEverUse(unittest.TestCase):
    """Clearing the bags without spending what the family cannot get back."""

    def test_an_outgrown_soulbound_piece_is_offered_to_the_vendor(self):
        got = gear_candidates([gear(instance_flags=1, required_level=15)],
                              IN_TOWN)
        self.assertEqual([c.item_guid for c in got], [5001])
        self.assertEqual(got[0].holder, "Grog")

    def test_a_tradable_green_is_left_alone_while_nothing_can_list_it(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=0, required_level=15)],
                            IN_TOWN), ())

    def test_gear_close_to_level_is_never_sold_however_it_is_bound(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=25)],
                            IN_TOWN), ())

    def test_a_worthless_piece_is_not_walked_to_a_vendor(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=15,
                                  sell_price=0)], IN_TOWN), ())

    def test_a_quest_item_is_refused_even_wearing_an_armour_class(self):
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=15,
                                  item_class=12)], IN_TOWN), ())

    def test_a_row_missing_the_facts_is_dropped_not_guessed_at(self):
        broken = gear(instance_flags=1, required_level=15)
        del broken["sell_price"]
        self.assertEqual(gear_candidates([broken], IN_TOWN), ())

    def test_no_vendor_in_reach_means_nothing_is_queued(self):
        away = disposition.Family(vendor_reachable=False)
        self.assertEqual(
            gear_candidates([gear(instance_flags=1, required_level=15)],
                            away), ())

    def test_turning_the_auction_on_stops_the_vendor_taking_them(self):
        """When mod-overseer#208 lands, the same soulbound piece is still a
        vendor sale, because soulbound is the fact that decides it."""
        both = disposition.EXECUTABLE_TODAY | {disposition.AUCTION}
        got = gear_candidates([gear(instance_flags=1, required_level=15)],
                              IN_TOWN, available=both)
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
