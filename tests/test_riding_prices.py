"""Riding rank prices come from the trainer table at run time (ticket 2625)."""

import unittest

import guildjobs
import purse
from test_family_riding import GOLD, seat


class RidingPricesFromTheTrainerTable(unittest.TestCase):
    def tearDown(self):
        purse.install_trainer_rows([])

    def test_rows_replace_the_constant_price_and_level(self):
        ranks = purse.trainer_ranks(
            [{"SpellId": purse.APPRENTICE.spell, "MoneyCost": 90000, "ReqLevel": 30}]
        )
        self.assertEqual((ranks[0].cost, ranks[0].level), (90000, 30))
        self.assertEqual(ranks[1], purse.JOURNEYMAN)

    def test_a_zero_price_row_is_not_a_price(self):
        ranks = purse.trainer_ranks(
            [{"SpellId": purse.APPRENTICE.spell, "MoneyCost": 0, "ReqLevel": 20}]
        )
        self.assertEqual(ranks, purse.RIDING_RANKS)

    def test_riding_due_and_the_order_use_the_installed_price(self):
        purse.install_trainer_rows(
            [{"SpellId": purse.APPRENTICE.spell, "MoneyCost": 90000, "ReqLevel": 20}]
        )
        self.assertEqual(purse.riding_due(60, 0).cost, 90000)
        order = purse.order("Grugg", 60, 300 * GOLD)
        self.assertEqual(order.want(purse.RIDING).copper, 90000)

    def test_the_family_step_saves_for_the_table_price(self):
        purse.install_trainer_rows(
            [{"SpellId": purse.APPRENTICE.spell, "MoneyCost": 90000, "ReqLevel": 20}]
        )
        step, note = guildjobs.family_riding_step(seat(money=5 * GOLD), [])
        self.assertIsNone(step)
        self.assertIn("saves for", note)
        step, _ = guildjobs.family_riding_step(seat(money=10 * GOLD - 1), [])
        self.assertIsNone(step)
        step, _ = guildjobs.family_riding_step(seat(money=10 * GOLD), [])
        self.assertIsNotNone(step)


if __name__ == "__main__":
    unittest.main()
