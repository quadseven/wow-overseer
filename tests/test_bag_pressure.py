import unittest

from bag_pressure import (ItemForSale, bag_purchase_allowed, sellable,
                          town_run_needed, vendor_batch, vendor_candidates)


class BagPressureTests(unittest.TestCase):
    def test_full_family_triggers_town_run(self):
        self.assertTrue(town_run_needed(44, 44))
        self.assertFalse(town_run_needed(10, 44))

    def test_never_sells_a_rare(self):
        self.assertFalse(sellable(ItemForSale(quality=3, sell_price=500)))

    def test_never_sells_quest_or_profession_materials(self):
        self.assertFalse(sellable(ItemForSale(quality=1, quest_item=True, sell_price=1)))
        self.assertFalse(sellable(ItemForSale(quality=1, reagent=True, sell_price=1)))
        self.assertFalse(sellable(ItemForSale(quality=1, profession_needed=True, sell_price=1)))

    def test_sells_only_positive_value_common_goods(self):
        self.assertTrue(sellable(ItemForSale(quality=0, sell_price=10)))
        self.assertFalse(sellable(ItemForSale(quality=1, sell_price=0)))

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


if __name__ == "__main__":
    unittest.main()
