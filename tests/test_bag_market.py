"""Bigger bags for members whose bag positions are all full (bag_market).

The fixture is the dev realm as read on 2026-09-23: every bag each member
wears, what each carries in the purse, and every general bag on sale in the
Alliance auction house. Item entries, sizes and prices are the realm's; item
guids and auction ids are renumbered, and a worn bag's entry is invented. The
replay runs the planner pass after pass, putting each bought bag on and
taking its listing off the house, until nothing more is worth buying.
"""

import ast
import asyncio
import itertools
import pathlib
import types
import unittest

import bag_market
import bag_pressure
from bag_market import AUCTION, VENDOR, Listing, Purse
from bag_upgrade import Bag, Member

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge.py"

_guid = itertools.count(1000)


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

# The general bags a town vendor stocks, at acore_world.item_template.BuyPrice
# as read on 2026-09-23 (entries 4496, 4498, 4497 and 4499).
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


# The held member as read on 2026-10-19: 3 free slots, an 8-slot bag as its
# smallest, 12 gold 81 silver 14 copper at level 43. The rest of the family's
# purses as read the same hour, so the family share is the measured one.
HELD = Member("Grog", 4, worn=worn(8, 10, 10, 12))
HELD_PURSES = {
    "Bork": Purse(41, 90181),
    "Grog": Purse(43, 128114),
    "Grug": Purse(45, 108148),
    "Og": Purse(39, 329311),
    "Ugga": Purse(42, 150433),
}


def _held(free, listings=VENDOR_STOCK, purses=HELD_PURSES):
    return bag_market.plan_upgrades(
        [HELD],
        purses,
        listings,
        reach={"Grog": EVERY_STOCK},
        free_slots={"Grog": free},
    )


class TheBagFloor(unittest.TestCase):
    """A member at the bag floor buys the vendor's biggest bag it can afford."""

    def test_the_held_member_buys_the_vendors_12_slot_bag(self):
        upgrades, notes = _held(3)
        self.assertEqual(notes, ())
        self.assertEqual(
            [(u.buyer, u.listing.name, u.gain, u.price) for u in upgrades],
            [("Grog", "Huge Brown Sack", 4, 100000)],
        )
        self.assertIn("slot cap gives way at the bag floor (3 free)", upgrades[0].why)
        self.assertEqual(upgrades[0].command, "entry:4499 count:1 max:100000")
        self.assertEqual(upgrades[0].equip_command, "e Hitem:4499:0")

    def test_one_slot_above_the_floor_the_cap_still_refuses(self):
        upgrades, notes = _held(4)
        self.assertEqual(upgrades, ())
        self.assertIn("at most 2500 a slot", notes[0])
        self.assertNotIn("bag floor", notes[0])

    def test_the_reserve_still_binds_at_the_floor(self):
        # 100,000 for the sack plus 12,900 kept back at level 43, one short:
        # the 10-slot bag is the most it can afford.
        purses = dict(HELD_PURSES, Grog=Purse(43, 112899))
        upgrades, _ = _held(3, purses=purses)
        self.assertEqual([u.listing.name for u in upgrades], ["Heavy Brown Bag"])
        # One copper short of the 10-slot bag too: nothing, and the note says
        # the cap was not what refused it.
        purses = dict(HELD_PURSES, Grog=Purse(43, 12900 + 19999))
        upgrades, notes = _held(3, purses=purses)
        self.assertEqual(upgrades, ())
        self.assertIn("no cap on a vendor's bag at the bag floor", notes[0])

    def test_the_family_share_still_binds_at_the_floor(self):
        # The held member alone: a quarter of 128,114 is 32,028.
        upgrades, _ = _held(3, purses={"Grog": HELD_PURSES["Grog"]})
        self.assertEqual([u.listing.name for u in upgrades], ["Heavy Brown Bag"])

    def test_an_auction_listing_keeps_the_cap_at_the_floor(self):
        sacks = [x for x in ALLIANCE_HOUSE if x.entry == 4499]
        upgrades, _ = _held(3, listings=sacks)
        self.assertEqual(upgrades, ())

    def test_a_full_member_still_has_nowhere_to_land_a_bag(self):
        upgrades, _ = _held(0)
        self.assertEqual(upgrades, ())

    def test_cap_yields_reads_only_a_real_floor(self):
        self.assertTrue(bag_market.cap_yields(0))
        self.assertTrue(bag_market.cap_yields(3))
        for free in (4, -1, None, "2", True):
            self.assertFalse(bag_market.cap_yields(free), free)


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

    def test_a_spare_inside_the_replaced_bag_is_not_on_the_way(self):
        worn_bags = tuple(
            Bag(
                "Small Brown Pouch" if slots == 6 else "Brown Leather Bag",
                slots,
                guid=guid,
                position=position,
            )
            for guid, position, slots in (
                (1, 19, 6),
                (2, 20, 6),
                (3, 21, 6),
                (4, 22, 8),
            )
        )
        spare = Bag("Heavy Brown Bag", 10, guid=5, entry=4497, inside=3)
        member = Member("Uzza", 4, worn=worn_bags, carried=(spare,))
        self.assertEqual(bag_market.on_the_way(member), 0)

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
        # 1470 is the realm's Murloc Skin Bag entry, the unique bag above.
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
        # 4 free is one above the bag floor, so the slot cap still binds.
        upgrades, _ = bag_market.plan_upgrades(
            ugga,
            purses,
            VENDOR_STOCK,
            reach={"Ugga": EVERY_STOCK},
            free_slots={"Ugga": 4},
        )
        self.assertEqual(upgrades[0].listing.name, "Brown Leather Satchel")

    def test_an_outland_or_northrend_bag_is_never_bought(self):
        # The classic ruleset: a 16-slot Netherweave Bag and a 20-slot
        # Frostweave Bag on the house are passed over for a classic 12.
        house = _house(
            [
                (21841, "Netherweave Bag", 16, 9000, 0),
                (41599, "Frostweave Bag", 20, 9000, 0),
                (1725, "Large Knapsack", 12, 8665, 0),
            ]
        )
        upgrades, _ = bag_market.plan_upgrades([ALLIANCE[4]], ALLIANCE_PURSES, house)
        self.assertEqual([u.listing.entry for u in upgrades], [1725])

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


# One row per (vendor, bag), shaped like bridge._BAG_VENDOR_SQL's answer: the
# bag vendor forty yards from where Grug's family stands, stocking the Heavy
# Brown Bag (10 slots, 20,000 copper) Grog's purse allows.
UPGRADE_VENDOR_ROWS = [
    dict(
        entry=3487,
        name="Kalyimah Stormcloud",
        faction=126,
        map_id=1,
        yards=40.0,
        item=4497,
        item_name="Heavy Brown Bag",
        slots=10,
        price=20000,
    ),
]


def _standing(*names, at=(1, 0.0, 0.0)):
    return {
        n: bag_pressure.Standing(
            name=n, map_id=at[0], x=at[1], y=at[2], in_combat=False, job="quest"
        )
        for n in names
    }


def _upgrade_trip(members, purses, free, rows=None, leader="Grug", **kw):
    vendors = bag_pressure.bag_vendors_from_rows(
        UPGRADE_VENDOR_ROWS if rows is None else rows
    )
    names = [m.name for m in members] + [leader]
    kw.setdefault("standing", _standing(*names))
    kw.setdefault("leader", leader)
    return bag_market.upgrade_vendor_trip(
        members, purses, vendors, free_slots=dict(free), **kw
    )


class TheUpgradeWalk(unittest.TestCase):
    """#1218: a member with full positions but small bags is walked to a bag
    vendor for an upgrade.

    The health endpoint read Bork and Ugga stuck following Grug for 4.3 hours
    on "Bork, Grog at the bag floor and no town pass has made room". Grog, one
    of the two members the hold names, held 3 free slots, wore an 8-slot bag
    as its smallest and carried 12.8 gold at level 43: past the slot cap since
    #1220, an upgrade it can afford, yet no town pass ever walked it to the
    bag vendor forty yards off. `_vendor_bag_upgrades` buys only for a member
    already standing at a vendor that stocks bags, and `bag_vendor_trip`
    walks only members with an empty bag position, so a full-position member
    at the floor never reaches the counter its upgrade is sold at.
    """

    def test_the_held_member_is_walked_to_the_bag_vendor(self):
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 3})
        self.assertEqual(trip.target, "3487")
        self.assertEqual(trip.vendor.name, "Kalyimah Stormcloud")
        self.assertEqual(trip.buyers, ("Grog",))
        self.assertEqual(trip.why_not, "")

    def test_a_member_with_an_empty_position_is_left_to_the_bag_walk(self):
        member = Member("Bork", 4, worn=worn(10, 16, 16))
        trip = _upgrade_trip([member], HELD_PURSES, {"Bork": 2}, leader="Grug")
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())

    def test_a_member_with_no_free_slot_has_nowhere_to_land_a_bag(self):
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 0})
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())

    def test_a_member_with_a_bag_bought_in_the_window_is_not_walked(self):
        # `_vendor_bag_upgrades` sells nothing to a member whose auction bag
        # is still on the way, so a walk for it would end at a closed counter.
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 3}, pending={"Grog"})
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())

    def test_a_broke_member_is_not_walked(self):
        purses = dict(HELD_PURSES, Grog=Purse(43, 12900 + 19999))
        trip = _upgrade_trip([HELD], purses, {"Grog": 3})
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())

    def test_the_slot_cap_yields_only_at_the_floor(self):
        # The Heavy Brown Bag costs 10,000 copper a slot added, past the
        # 2,500 cap: at the floor the walk goes, one slot above it does not.
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 4})
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())

    def test_no_vendor_within_five_hundred_yards_is_no_trip(self):
        far = [dict(UPGRADE_VENDOR_ROWS[0], yards=501.0)]
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 3}, rows=far)
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())

    def test_no_trip_mid_run(self):
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 3}, in_run=True)
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())
        self.assertIn("dungeon run", trip.why_not)

    def test_a_vendor_already_stood_at_is_no_walk(self):
        here = [dict(UPGRADE_VENDOR_ROWS[0], yards=5.0)]
        trip = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 3}, rows=here)
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ("Grog",))
        self.assertEqual(trip.vendor.name, "Kalyimah Stormcloud")


class TheUpgradeWalkWiring(unittest.TestCase):
    """#1218: the bag walk falls back to an upgrade trip for full members."""

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8")

    def test_the_bag_walk_falls_back_to_an_upgrade_trip(self):
        body = _body(
            self.source,
            "    async def _aim_at_bag_vendor(",
            "    async def _bank_exit_route(",
        )
        self.assertIn("bag_pressure.bag_vendor_trip(", body)
        self.assertIn("_aim_upgrade_trip(", body)

    def test_the_upgrade_trip_plans_a_bigger_bag_per_vendor(self):
        body = _body(
            self.source,
            "    async def _aim_upgrade_trip(",
            "    async def _bank_exit_route(",
        )
        self.assertIn("bag_market.upgrade_vendor_trip(", body)
        self.assertIn("_fetch_bag_state", body)
        self.assertIn("_bag_purses", body)
        self.assertIn("_recent_bag_buys", body)


def _load_aim_upgrade_trip(recent, calls):
    """The bridge's `_aim_upgrade_trip`, exec'd against fakes for its reads.

    Only the database reads are faked; the planner and the trip are the real
    `bag_market` and `bag_pressure`, so what the fetch returns has to flow into
    `upgrade_vendor_trip` for the answer to change.
    """
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    func = next(
        n
        for c in tree.body
        if isinstance(c, ast.ClassDef)
        for n in c.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_aim_upgrade_trip"
    )
    module = ast.Module(body=[func], type_ignores=[])

    async def to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def recent_bag_buys(minutes):
        calls.append(minutes)
        return set(recent)

    ns = {
        "asyncio": types.SimpleNamespace(to_thread=to_thread),
        "bag_market": bag_market,
        "bag_upgrade": types.SimpleNamespace(
            members_from_rows=lambda rows, names: [HELD]
        ),
        "log": types.SimpleNamespace(
            info=lambda *a, **k: None, exception=lambda *a, **k: None
        ),
        "GIVE_RETRY_MINUTES": 77,
        "_fetch_free_slots": lambda names: {"Grog": 3},
        "_fetch_bag_state": lambda names: [],
        "_fetch_mailed_bags": lambda names: {},
        "_recent_bag_buys": recent_bag_buys,
    }
    exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102
    me = types.SimpleNamespace()

    async def purses(names):
        return HELD_PURSES

    me._bag_purses = purses
    return lambda: asyncio.run(
        ns["_aim_upgrade_trip"](
            me,
            ["Grog"],
            "Grug",
            _standing("Grog", "Grug"),
            bag_pressure.bag_vendors_from_rows(UPGRADE_VENDOR_ROWS),
        )
    )


class TheUpgradeTripBehavior(unittest.TestCase):
    """#1218 via #1262: the recent-buys fetch drives the trip, not just a name."""

    def test_a_member_with_a_recent_bag_buy_is_not_walked(self):
        calls = []
        trip = _load_aim_upgrade_trip({"Grog"}, calls)()
        self.assertEqual(trip.target, "")
        self.assertEqual(trip.buyers, ())
        self.assertEqual(calls, [77])

    def test_without_a_recent_buy_the_member_is_walked(self):
        calls = []
        trip = _load_aim_upgrade_trip(set(), calls)()
        self.assertEqual(trip.target, "3487")
        self.assertEqual(trip.buyers, ("Grog",))
        self.assertEqual(calls, [77])


class TheBridgeWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8")

    def test_the_auction_pass_buys_bags_before_its_reagent_gate(self):
        body = _body(
            self.source,
            "    async def _auction_once(self",
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


class TheCapYieldsWhileTheFamilyIsHeldInTown(unittest.TestCase):
    """#1375: the hold is let go at CAMPAIGN_RESUME_FREE_SLOTS, so the cap gives
    way below that line while the family is held in town.

    Measured on the dev realm 2026-10-24: Grug's family was held 45 minutes on
    "Bork, Grog, Ugga below 8 free slots" (4, 6 and 7 free), and the bags pass
    said "Ugga cannot buy a bag bigger than its 8-slot one ... at most 2500 a
    slot" with 18 gold to spend.
    """

    def test_the_floor_is_the_resume_line_while_held(self):
        line = bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS - 1
        self.assertTrue(bag_market.cap_yields(line, held=True))
        self.assertFalse(bag_market.cap_yields(line + 1, held=True))
        self.assertFalse(bag_market.cap_yields(4))
        for free in (-1, None, "2", True):
            self.assertFalse(bag_market.cap_yields(free, held=True), free)

    def test_a_held_member_between_the_lines_buys_the_vendor_bag(self):
        refused, _ = bag_market.plan_upgrades(
            [HELD],
            HELD_PURSES,
            VENDOR_STOCK,
            reach={"Grog": EVERY_STOCK},
            free_slots={"Grog": 6},
        )
        self.assertEqual(refused, ())
        bought, _ = bag_market.plan_upgrades(
            [HELD],
            HELD_PURSES,
            VENDOR_STOCK,
            reach={"Grog": EVERY_STOCK},
            free_slots={"Grog": 6},
            held=True,
        )
        self.assertEqual([u.buyer for u in bought], ["Grog"])
        self.assertEqual(bought[0].listing.source, VENDOR)

    def test_a_held_member_between_the_lines_is_walked_to_the_vendor(self):
        idle = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 6})
        self.assertEqual(idle.buyers, ())
        held = _upgrade_trip([HELD], HELD_PURSES, {"Grog": 6}, held=True)
        self.assertEqual(held.buyers, ("Grog",))

    def test_the_bags_pass_reads_the_hold_off_the_town_slot(self):
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("held = bool(self._cohort_town_slot(cohort).town_first)", source)
        self.assertIn("held=bool(slot.town_first)", source)
