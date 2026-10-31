"""A bought bank bag position needs a bag, even with four bags already worn."""

import ast
import asyncio
import dataclasses
import pathlib
import unittest
from dataclasses import replace
from types import SimpleNamespace

import bag_pressure
import bag_upgrade
import bankbags
import towntrip


class BankBagsReachThePurchasePath(unittest.TestCase):
    def buy(self, *, facts=None, offer=None, free=1, at_vendor=True, seen=()):
        rows = [
            dict(
                holder="Og",
                guid=100 + i,
                entry=4499,
                name="Worn",
                slots=12,
                used=12,
                bag=0,
                slot=19 + i,
                subclass=0,
            )
            for i in range(4)
        ]
        facts = (
            facts
            if facts is not None
            else [bankbags.Facts("Og", money=300000, bought=1, worn=(12,) * 4)]
        )
        offer = offer or bag_pressure.BagOffer(4496, "Small Brown Pouch", 6, 500)
        purchases, equips, upgrading = [], [], []

        async def upgrades(*args, **kwargs):
            upgrading.extend(m.name for m in args[0])
            return None

        def buyers(names, positions):
            return (
                [
                    bag_pressure.BagBuyer(
                        n,
                        44,
                        facts[0].money,
                        positions[n],
                        free,
                        frozenset({offer.entry}) if at_vendor else frozenset(),
                    )
                    for n in names
                ],
                set(names) if at_vendor else set(),
            )

        env = dict(
            asyncio=asyncio,
            bag_pressure=bag_pressure,
            bag_upgrade=bag_upgrade,
            bankbags=bankbags,
            towntrip=towntrip,
            replace=replace,
            dataclasses=dataclasses,
            log=SimpleNamespace(info=lambda *a: None, exception=lambda *a: None),
            GIVE_RETRY_MINUTES=60,
            _fetch_bag_state=lambda names: rows,
            _fetch_bank_bag_facts=lambda names: facts,
            _bag_buyers=buyers,
            _fetch_bag_offers=lambda entries: [offer],
            _campaign_waiting=lambda names: False,
            _recent_town_keys=lambda minutes: set(seen),
            _insert_town_errand=lambda errand: purchases.append(errand) or 1,
            _insert_bag_equip=lambda purchase: equips.append(purchase) or 1,
        )
        source = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
        tree = ast.parse(source.read_text())
        method = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_buy_bags_once"
        )
        exec(
            compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"),
            env,
        )
        needy = asyncio.run(
            env["_buy_bags_once"](
                SimpleNamespace(_vendor_bag_upgrades=upgrades), ["Og"]
            )
        )
        return purchases, equips, needy, upgrading

    def test_a_vendor_purchase_fills_a_bank_position_without_equipping_it(self):
        purchases, equips, needy, upgrading = self.buy()
        self.assertEqual([p.command for p in purchases], ["entry:4496 count:1 max:500"])
        self.assertEqual(equips, [], "a bank bag must not replace a larger worn bag")
        self.assertEqual(needy, ())
        self.assertEqual(
            upgrading, [], "the same purse and free slot cannot buy two bags"
        )

    def test_no_bank_position_or_a_spare_already_carried_means_no_purchase(self):
        for f in [
            bankbags.Facts("Og", bought=0, worn=(12,) * 4),
            bankbags.Facts(
                "Og", bought=1, worn=(12,) * 4, spare=(bankbags.Bag(200, 4496, 6),)
            ),
        ]:
            with self.subTest(f=f):
                self.assertEqual(self.buy(facts=[f])[0], [])

    def test_no_free_inventory_slot_or_no_spare_money_means_no_purchase(self):
        self.assertEqual(self.buy(free=0)[0], [])
        self.assertEqual(
            self.buy(facts=[bankbags.Facts("Og", money=100, bought=1, worn=(12,) * 4)])[
                0
            ],
            [],
        )

    def test_recent_purchase_is_not_queued_again(self):
        self.assertEqual(self.buy(seen={("Og", "entry:4496 count:1 max:500")})[0], [])

    def test_a_bag_too_large_for_placement_still_needs_another_vendor(self):
        purchases, equips, needy, _ = self.buy(
            offer=bag_pressure.BagOffer(1234, "Too large", 16, 100)
        )
        self.assertEqual(purchases, [])
        self.assertEqual(equips, [])
        self.assertEqual(
            [(b.name, b.max_slots, b.bank) for b in needy], [("Og", 12, True)]
        )

    def test_walking_buyers_keep_their_bank_constraints(self):
        purchases, _, needy, _ = self.buy(at_vendor=False)
        self.assertEqual(purchases, [])
        trip = bag_pressure.bag_vendor_trip(
            needy,
            [
                bag_pressure.BagVendor(
                    1,
                    "Bad",
                    0,
                    20,
                    offers=(bag_pressure.BagOffer(1234, "Huge", 16, 100),),
                ),
                bag_pressure.BagVendor(
                    2,
                    "Good",
                    0,
                    30,
                    offers=(bag_pressure.BagOffer(4496, "Pouch", 6, 500),),
                ),
            ],
            leader="Og",
            standing={"Og": bag_pressure.Standing("Og", map_id=0)},
        )
        self.assertEqual(trip.target, "2")

    def test_the_purchased_bag_has_an_existing_bank_placement_step(self):
        purchases, _, _, _ = self.buy()
        self.assertTrue(purchases)
        f = bankbags.Facts(
            "Og", bought=1, worn=(12,) * 4, spare=(bankbags.Bag(200, 4496, 6),)
        )
        step, _ = bankbags.step(f, 12)
        self.assertEqual(step.command, "place-bag guid:200")

    def test_the_corps_master_does_not_buy_a_bag_placement_will_reserve(self):
        f = bankbags.Facts("Og", money=300000, bought=1, worn=(12,) * 4, crafter=True)
        entry = next(iter(f.protected_entries))
        self.assertEqual(
            self.buy(
                facts=[f], offer=bag_pressure.BagOffer(entry, "Corps bag", 6, 100)
            )[0],
            [],
        )

    def test_bank_space_gets_the_largest_usable_bag_the_reserve_allows(self):
        buyer = bag_pressure.BagBuyer(
            "Og", 44, 300000, 1, 1, frozenset({1, 2}), bank=True, max_slots=8
        )
        small = bag_pressure.BagOffer(1, "Small", 6, 500)
        larger = bag_pressure.BagOffer(2, "Larger", 8, 2000)
        purchases, _ = bag_pressure.bag_purchases([buyer], [small, larger])
        self.assertEqual([p.entry for p in purchases], [2])
        purchases, _ = bag_pressure.bag_purchases(
            [buyer], [small, replace(larger, price=300001)]
        )
        self.assertEqual([p.entry for p in purchases], [1])


if __name__ == "__main__":
    unittest.main()
