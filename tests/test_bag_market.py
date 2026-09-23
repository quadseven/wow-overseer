"""Bigger bags for members whose bag positions are all full (bag_market).

The fixture is the dev realm as read on 2026-09-23: every bag each member
wears, what each carries in the purse, and every general bag on sale in the
Alliance auction house, with the item guids and auction ids renumbered. The
replay runs the planner pass after pass, putting each bought bag on and
taking its listing off the house, until nothing more is worth buying.
"""

import pathlib
import unittest

import bag_market
from bag_market import AUCTION, VENDOR, Listing, Purse
from bag_upgrade import Bag, Member

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge.py"

_guid = iter(range(1000, 9999))


def worn(*sizes):
    return tuple(Bag("bag%d" % n, n, guid=next(_guid), entry=9000 + n) for n in sizes)


# Worn bag sizes, in position order, as character_inventory held them.
ALLIANCE = [
    Member("Bork", 4, worn=worn(10, 16, 16, 8)),
    Member("Grog", 4, worn=worn(8, 8, 10, 8)),
    Member("Grug", 4, worn=worn(16, 16, 8, 14)),
    Member("Og", 4, worn=worn(10, 8, 16, 16)),
    Member("Ugga", 4, worn=worn(6, 8, 8, 8)),
]
ALLIANCE_PURSES = {
    "Bork": Purse(60, 218081),
    "Grog": Purse(60, 191423),
    "Grug": Purse(60, 409214),
    "Og": Purse(60, 160943),
    "Ugga": Purse(60, 160367),
}

HORDE = [
    Member("Oz", 4, worn=worn(6, 6, 6, 6)),
    Member("Uzza", 4, worn=worn(6, 6, 6, 6)),
    Member("Zork", 4, worn=worn(6, 6, 6, 6)),
    Member("Zrog", 4, worn=worn(6, 6, 6, 6)),
    Member("Zug", 4, worn=worn(6, 6, 8, 6)),
]
HORDE_PURSES = {
    "Oz": Purse(24, 26139),
    "Uzza": Purse(22, 21496),
    "Zork": Purse(22, 21434),
    "Zrog": Purse(23, 23411),
    "Zug": Purse(25, 3791),
}


def _house(rows):
    return tuple(
        Listing(AUCTION, 500 + i, entry, name, slots, price, unique=bool(unique))
        for i, (entry, name, slots, price, unique) in enumerate(rows)
    )


# The Alliance house's general bags, buyout only (houseid 2, subclass 0).
ALLIANCE_HOUSE = _house(
    [
        (1652, "Sturdy Lunchbox", 12, 6878, 0),
        (1725, "Large Knapsack", 12, 8665, 0),
        (1725, "Large Knapsack", 12, 8929, 0),
        (1725, "Large Knapsack", 12, 9356, 0),
        (1725, "Large Knapsack", 12, 9748, 0),
        (4499, "Huge Brown Sack", 12, 37128, 0),
        (4499, "Huge Brown Sack", 12, 38012, 0),
        (4499, "Huge Brown Sack", 12, 43307, 0),
        (1470, "Murloc Skin Bag", 10, 1523, 1),
        (933, "Large Rucksack", 10, 3425, 0),
        (804, "Large Blue Sack", 10, 4243, 0),
        (5765, "Black Silk Pack", 10, 6505, 0),
        (4497, "Heavy Brown Bag", 10, 9140, 0),
        (4498, "Brown Leather Satchel", 8, 1483, 0),
        (4498, "Brown Leather Satchel", 8, 1688, 0),
        (2657, "Red Leather Bag", 8, 1888, 0),
        (5572, "Small Green Pouch", 6, 1400, 0),
        (4496, "Small Brown Pouch", 6, 1699, 0),
    ]
)

# The general bags a town vendor stocks, at item_template.BuyPrice.
VENDOR_STOCK = tuple(
    Listing(VENDOR, entry, entry, name, slots, price)
    for entry, name, slots, price in [
        (4496, "Small Brown Pouch", 6, 500),
        (4498, "Brown Leather Satchel", 8, 2500),
        (4497, "Heavy Brown Bag", 10, 20000),
        (4499, "Huge Brown Sack", 12, 100000),
    ]
)
EVERY_STOCK = frozenset(listing.entry for listing in VENDOR_STOCK)


def replay(members, purses, listings, **kw):
    """Run passes until nothing is bought; return (members, purses, passes)."""
    listings = list(listings)
    purses = dict(purses)
    passes = []
    for _ in range(20):
        upgrades, _notes = bag_market.plan_upgrades(members, purses, listings, **kw)
        if not upgrades:
            break
        passes.append(upgrades)
        members = bag_market.after(members, upgrades)
        sold = {u.listing.key for u in upgrades if u.listing.source == AUCTION}
        listings = [
            item
            for item in listings
            if not (item.source == AUCTION and item.key in sold)
        ]
        for u in upgrades:
            before = purses[u.buyer]
            purses[u.buyer] = Purse(before.level, before.money - u.price)
    return members, purses, passes


class TheMeasuredFamiliesReplayed(unittest.TestCase):
    def test_before(self):
        self.assertEqual(
            bag_market.worn_slots(ALLIANCE),
            {"Bork": 50, "Grog": 34, "Grug": 54, "Og": 50, "Ugga": 30},
        )

    def test_the_first_pass_buys_a_12_slot_bag_for_all_five(self):
        upgrades, _ = bag_market.plan_upgrades(
            ALLIANCE, ALLIANCE_PURSES, ALLIANCE_HOUSE
        )
        self.assertEqual(
            [(u.buyer, u.listing.name, u.listing.price, u.gain) for u in upgrades],
            [
                ("Ugga", "Sturdy Lunchbox", 6878, 6),
                ("Grog", "Large Knapsack", 8665, 4),
                ("Bork", "Large Knapsack", 8929, 4),
                ("Og", "Large Knapsack", 9356, 4),
                ("Grug", "Large Knapsack", 9748, 4),
            ],
        )
        self.assertEqual(
            bag_market.worn_slots(bag_market.after(ALLIANCE, upgrades)),
            {"Bork": 54, "Grog": 38, "Grug": 58, "Og": 54, "Ugga": 36},
        )

    def test_the_alliance_family_replayed_to_the_end(self):
        members, purses, passes = replay(ALLIANCE, ALLIANCE_PURSES, ALLIANCE_HOUSE)
        self.assertEqual(
            bag_market.worn_slots(members),
            {"Bork": 54, "Grog": 40, "Grug": 58, "Og": 54, "Ugga": 40},
        )
        spent = sum(ALLIANCE_PURSES[n].money - purses[n].money for n in purses)
        self.assertEqual(spent, 52767)
        self.assertEqual(len(passes), 3)

    def test_the_horde_family_at_a_vendor_replayed_to_the_end(self):
        reach = {m.name: EVERY_STOCK for m in HORDE}
        free = {m.name: 5 for m in HORDE}
        members, purses, _ = replay(
            HORDE, HORDE_PURSES, VENDOR_STOCK, reach=reach, free_slots=free
        )
        self.assertEqual(
            bag_market.worn_slots(members),
            {"Oz": 32, "Uzza": 32, "Zork": 32, "Zrog": 32, "Zug": 26},
        )
        # Zug's 3,791 copper is under his 7,500 reserve, so nothing is spent.
        self.assertEqual(purses["Zug"].money, 3791)


class TheSpendingRule(unittest.TestCase):
    def test_the_reserve_is_kept(self):
        purses = {"Ugga": Purse(60, 18000 + 6877)}
        upgrades, notes = bag_market.plan_upgrades(
            [ALLIANCE[4]], purses, ALLIANCE_HOUSE[:1]
        )
        self.assertEqual(upgrades, ())
        self.assertIn("cannot buy a bag bigger", notes[0])

    def test_the_family_share_binds_a_poor_family(self):
        # 25 percent of 30,000 is 7,500: one Lunchbox, then nothing.
        members = [ALLIANCE[4], ALLIANCE[1]]
        purses = {"Ugga": Purse(1, 15000), "Grog": Purse(1, 15000)}
        upgrades, _ = bag_market.plan_upgrades(members, purses, ALLIANCE_HOUSE)
        self.assertEqual([u.buyer for u in upgrades], ["Ugga"])
        self.assertLessEqual(sum(u.price for u in upgrades), 7500)

    def test_a_bag_dearer_than_the_slot_cap_is_refused(self):
        huge = [x for x in VENDOR_STOCK if x.slots == 12]
        upgrades, _ = bag_market.plan_upgrades(
            [ALLIANCE[1]],
            ALLIANCE_PURSES,
            huge,
            reach={"Grog": EVERY_STOCK},
            free_slots={"Grog": 5},
        )
        self.assertEqual(upgrades, ())

    def test_a_gain_below_the_minimum_is_not_bought(self):
        member = Member("Grug", 4, worn=worn(12, 12, 12, 12))
        upgrades, _ = bag_market.plan_upgrades(
            [member], {"Grug": Purse(60, 10**6)}, ALLIANCE_HOUSE
        )
        self.assertEqual(upgrades, ())


class WhoIsOffered(unittest.TestCase):
    def test_an_empty_position_is_left_to_the_open_position_purchase(self):
        member = Member("Bork", 4, worn=worn(10, 16, 16))
        upgrades, _ = bag_market.plan_upgrades(
            [member], ALLIANCE_PURSES, ALLIANCE_HOUSE
        )
        self.assertEqual(upgrades, ())

    def test_a_bigger_bag_already_carried_is_not_bought_again(self):
        spare = Bag("Large Knapsack", 12, guid=77, entry=1725)
        member = Member("Ugga", 4, worn=ALLIANCE[4].worn, carried=(spare,))
        upgrades, notes = bag_market.plan_upgrades(
            [member], ALLIANCE_PURSES, ALLIANCE_HOUSE
        )
        self.assertEqual(upgrades, ())
        self.assertIn("already has a 12-slot bag coming", notes[0])

    def test_a_bigger_bag_in_the_mail_is_not_bought_again(self):
        upgrades, _ = bag_market.plan_upgrades(
            [ALLIANCE[4]], ALLIANCE_PURSES, ALLIANCE_HOUSE, mailed={"Ugga": [12]}
        )
        self.assertEqual(upgrades, ())

    def test_an_auction_listing_is_sold_to_one_buyer(self):
        members = [ALLIANCE[4], ALLIANCE[1]]
        upgrades, _ = bag_market.plan_upgrades(
            members, ALLIANCE_PURSES, ALLIANCE_HOUSE[:1]
        )
        self.assertEqual([u.buyer for u in upgrades], ["Ugga"])

    def test_a_unique_bag_is_not_sold_to_its_owner(self):
        murloc = [x for x in ALLIANCE_HOUSE if x.unique]
        owner = Member("Ugga", 4, worn=worn(6, 8, 8) + (Bag("Murloc", 10, entry=1470),))
        upgrades, _ = bag_market.plan_upgrades([owner], ALLIANCE_PURSES, murloc)
        self.assertEqual(upgrades, ())

    def test_a_vendor_bag_needs_reach_and_a_free_slot(self):
        ugga = [ALLIANCE[4]]
        purses = {"Ugga": Purse(60, 10**6)}
        for reach, free in (({}, {"Ugga": 5}), ({"Ugga": EVERY_STOCK}, {"Ugga": 0})):
            upgrades, _ = bag_market.plan_upgrades(
                ugga, purses, VENDOR_STOCK, reach=reach, free_slots=free
            )
            self.assertEqual(upgrades, ())
        upgrades, _ = bag_market.plan_upgrades(
            ugga,
            purses,
            VENDOR_STOCK,
            reach={"Ugga": EVERY_STOCK},
            free_slots={"Ugga": 1},
        )
        self.assertEqual(upgrades[0].listing.name, "Brown Leather Satchel")

    def test_the_house_bag_beats_a_smaller_vendor_bag(self):
        upgrades, _ = bag_market.plan_upgrades(
            [ALLIANCE[4]],
            ALLIANCE_PURSES,
            VENDOR_STOCK + ALLIANCE_HOUSE,
            reach={"Ugga": EVERY_STOCK},
            free_slots={"Ugga": 3},
        )
        self.assertEqual(upgrades[0].listing.source, AUCTION)
        self.assertEqual(upgrades[0].listing.slots, 12)


class TheRows(unittest.TestCase):
    def test_commands(self):
        (up,), _ = bag_market.plan_upgrades(
            [ALLIANCE[4]], ALLIANCE_PURSES, ALLIANCE_HOUSE[:1]
        )
        self.assertEqual(up.command, "buy auction:500")
        self.assertEqual(up.equip_command, "e Hitem:1652:0")
        (vendor,), _ = bag_market.plan_upgrades(
            [HORDE[0]],
            HORDE_PURSES,
            VENDOR_STOCK,
            reach={"Oz": EVERY_STOCK},
            free_slots={"Oz": 2},
        )
        self.assertEqual(vendor.command, "entry:4498 count:1 max:2500")

    def test_the_new_bag_replaces_the_smallest(self):
        (up,), _ = bag_market.plan_upgrades(
            [ALLIANCE[2]], ALLIANCE_PURSES, ALLIANCE_HOUSE[:1]
        )
        (grug,) = bag_market.after([ALLIANCE[2]], [up])
        self.assertEqual(sorted(b.slots for b in grug.worn), [12, 14, 16, 16])


class TheSellPathBeforeADiscoveryWalk(unittest.TestCase):
    def test_bag_pressure_makes_the_flight_walk_wait(self):
        why = bag_market.discovery_waits({"Grug": 9, "Ugga": 0, "Og": 3})
        self.assertIn("Og, Ugga", why)

    def test_room_to_spare_lets_it_walk(self):
        self.assertEqual(bag_market.discovery_waits({"Grug": 9, "Ugga": 4}), "")


def _body(source, start, end):
    begin = source.index(start)
    return source[begin : source.index(end, begin + len(start))]


class TheBridgeWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8")

    def test_the_auction_pass_buys_bags_before_its_reagent_gate(self):
        body = _body(
            self.source,
            "    async def _auction_once(self)",
            "    async def _auction_sales_once(",
        )
        self.assertLess(
            body.index("self._auction_bag_upgrades("),
            body.index("if not shoppers:"),
        )

    def test_the_auction_half_buys_only_at_a_counter_of_the_planned_house(self):
        body = _body(
            self.source,
            "    async def _auction_bag_upgrades(",
            "    async def _auction_shortfall(",
        )
        self.assertIn("bag_market.plan_upgrades(", body)
        self.assertIn("_fetch_auctioneer, upgrade.buyer", body)
        # At a counter the plan is made against that counter's house, which
        # can be the neutral one.
        self.assertIn("if at_counter\n", body)
        self.assertIn('upgrade.command, "bags"', body)
        self.assertIn("_claim_town_slot(", body)
        self.assertIn("_recent_bag_buys", body)
        self.assertIn("_fetch_mailed_bags", body)

    def test_the_vendor_half_runs_before_the_open_position_return(self):
        body = _body(
            self.source,
            "    async def _buy_bags_once(",
            "    async def _vendor_bag_upgrades(",
        )
        self.assertLess(
            body.index("self._vendor_bag_upgrades("),
            body.index("if not wanting:"),
        )

    def test_the_vendor_half_writes_the_buy_and_the_equip(self):
        body = _body(
            self.source,
            "    async def _vendor_bag_upgrades(",
            "    async def _aim_at_bag_vendor(",
        )
        self.assertIn("towntrip.BUY_KIND", body)
        self.assertIn("_insert_bag_equip, upgrade", body)
        self.assertIn("upgrade.listing.source != bag_market.VENDOR", body)

    def test_the_flight_pass_yields_to_bag_pressure_before_it_claims(self):
        body = _body(
            self.source,
            "    async def _flight_learn_once(self)",
            "    async def _flight_learn_loop(self)",
        )
        self.assertLess(
            body.index("bag_market.discovery_waits("),
            body.index("self._claim_town_slot(FLIGHT_CLAIMANT"),
        )
        self.assertIn("self._town_slot.forget(FLIGHT_CLAIMANT)", body)

    def test_only_general_bags_are_read(self):
        for name in ("_BAG_LISTINGS_SQL = (", "_MAILED_BAGS_SQL = ("):
            sql = _body(self.source, name, "\n)\n")
            self.assertIn("it.subclass = 0", sql)

    def test_the_image_carries_the_module(self):
        self.assertIn("bag_market.py", (ROOT / "Dockerfile").read_text())


if __name__ == "__main__":
    unittest.main()
