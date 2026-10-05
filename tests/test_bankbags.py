"""Bank bag slots: bought when affordable, filled with a spare bag (#625).

Measured on wow-dev 2026-10-05: every family member had bought 0 of 7 bank bag
slots and Grog's bank was full. The prices are the realm's BankBagSlotPrices.
"""

import pathlib
import unittest

import bankbags as bb

BRIDGE = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
LINEN = 4238


def facts(**over):
    base = dict(name="Grog", money=497700, bought=0, placed=0, worn=(8, 10, 10, 12))
    base.update(over)
    return bb.Facts(**base)


class ASlotIsBoughtWhenAffordable(unittest.TestCase):
    def test_the_first_slot_with_grogs_purse(self):
        step, _ = bb.step(facts())
        self.assertEqual(step.command, "buy slot")
        self.assertIn("bank bag slot 1 for 1000 copper", step.why)

    def test_the_purse_must_hold_four_times_the_price(self):
        step, why = bb.step(facts(money=399999, bought=2, placed=2))
        self.assertIsNone(step)
        self.assertIn("waits to buy bank bag slot 3", why)
        self.assertEqual(
            bb.step(facts(money=400000, bought=2, placed=2))[0].command, "buy slot"
        )

    def test_an_empty_bought_slot_is_filled_before_another_is_bought(self):
        step, why = bb.step(facts(bought=1, placed=0))
        self.assertIsNone(step)
        self.assertIn("1 empty bank bag slot(s) and no spare bag", why)

    def test_seven_is_every_slot(self):
        step, why = bb.step(facts(bought=7, placed=7, money=10**9))
        self.assertIsNone(step)
        self.assertIn("every bank bag slot", why)

    def test_the_prices_are_the_realms(self):
        self.assertEqual(
            bb.SLOT_PRICES, (1000, 10000, 100000, 250000, 250000, 250000, 250000)
        )


class ASpareBagFillsTheSlot(unittest.TestCase):
    def test_the_biggest_spare_no_upgrade_goes_in(self):
        spare = (bb.Bag(11, 5571, 6), bb.Bag(12, 4240, 8), bb.Bag(13, 10050, 12))
        step, _ = bb.step(facts(bought=1, spare=spare))
        self.assertEqual(
            step.command,
            "place-bag guid:12",
            "the 12 is an upgrade over its 8; the 8 is not",
        )

    def test_a_bag_a_family_member_would_wear_is_not_banked(self):
        f = facts(bought=1, spare=(bb.Bag(12, 4240, 8),))
        self.assertIsNone(bb.step(f, floor=6)[0])
        self.assertEqual(bb.family_floor([f, facts(name="Ugga", worn=(6, 8, 8, 8))]), 6)
        self.assertEqual(bb.family_floor([facts(worn=(8, 8))]), 0)

    def test_a_crafters_ladder_bag_is_the_guilds(self):
        f = facts(
            bought=1, worn=(10, 10, 10, 10), crafter=True, spare=(bb.Bag(9, LINEN, 6),)
        )
        self.assertIsNone(bb.step(f)[0])
        self.assertEqual(
            bb.step(
                facts(bought=1, worn=(10, 10, 10, 10), spare=(bb.Bag(9, LINEN, 6),))
            )[0].command,
            "place-bag guid:9",
        )


class TheRowsReadAsFacts(unittest.TestCase):
    def test_worn_carried_inside_a_worn_bag_and_banked(self):
        people = [{"name": "Grog", "money": 5000, "bank_slots": 2}]
        rows = [
            {
                "holder": "Grog",
                "item_guid": 1,
                "entry": 1,
                "slots": 10,
                "bag": 0,
                "slot": 19,
            },
            {
                "holder": "Grog",
                "item_guid": 2,
                "entry": 2,
                "slots": 8,
                "bag": 0,
                "slot": 25,
            },
            {
                "holder": "Grog",
                "item_guid": 3,
                "entry": 3,
                "slots": 6,
                "bag": 1,
                "slot": 4,
            },
            {
                "holder": "Grog",
                "item_guid": 4,
                "entry": 4,
                "slots": 6,
                "bag": 0,
                "slot": 67,
            },
            {
                "holder": "Grog",
                "item_guid": 5,
                "entry": 5,
                "slots": 6,
                "bag": 4,
                "slot": 0,
            },
        ]
        (f,) = bb.facts_from_rows(people, rows, {"Grog"})
        self.assertEqual((f.money, f.bought, f.placed, f.worn), (5000, 2, 1, (10,)))
        self.assertEqual(
            sorted(b.guid for b in f.spare),
            [2, 3],
            "a bag inside a bank bag is not carried",
        )
        self.assertTrue(f.crafter)

    def test_the_bank_look_asks_at_a_banker(self):
        body = BRIDGE[BRIDGE.index("    async def _bank_bag_slots(") :]
        body = body[: body.index("\n    async def ")]
        self.assertIn("town.banker", body)
        self.assertIn("bankbags.step(f, floor)", body)


if __name__ == "__main__":
    unittest.main()
