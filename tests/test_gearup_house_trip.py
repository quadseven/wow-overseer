"""A gear-short member reaches an auction house when home has none (#1170).

Measured on wow-dev on 2026-09-28: gearup logged `not at an auctioneer` for
the family's mage and priest forty times in a day, because the family is bound
in Ratchet, which has no auction house, and mod-overseer refuses the
`auctioneer` keyword past its 1500-yard town-service walk. The rows below are
the auctioneer spawns on Kalimdor as the bridge's query reads them, measured
from the Ratchet bind point on 2026-10-18.

bridge.py imports discord and cannot be imported here, so its wiring is read
as text, the way test_gearup_vendor_pass does.
"""

import ast
import pathlib
import re
import unittest

import auction
import flightlearn
import gearup
import modsource

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge.py"
DECISIONS_H = modsource.DECISIONS_H

KALIMDOR = 1


def _row(entry, name, faction, yards, map_id=KALIMDOR):
    return {
        "entry": entry,
        "name": name,
        "faction": faction,
        "map_id": map_id,
        "yards": yards,
    }


# From the Ratchet bind point: Orgrimmar (29), Thunder Bluff (104), Gadgetzan
# (474), Everlook (855) and Darnassus (80).
FROM_RATCHET = [
    _row(8724, "Auctioneer Wabang", 29, 2831.6),
    _row(8674, "Auctioneer Stampi", 104, 3763.3),
    _row(8661, "Auctioneer Beardo", 474, 6191.7),
    _row(9857, "Auctioneer Grizzlin", 855, 7886.9),
    _row(15678, "Auctioneer Silva'las", 80, 12448.9),
]


class AFamilyWhoseHomeHasNoAuctionHouse(unittest.TestCase):
    def test_an_alliance_family_in_ratchet_is_sent_to_gadgetzan(self):
        trip = auction.house_trip("alliance", FROM_RATCHET, map_id=KALIMDOR)
        self.assertEqual("8661", trip.aim)
        self.assertEqual("Auctioneer Beardo", trip.name)
        self.assertEqual(auction.HOUSE_NEUTRAL, trip.house)
        self.assertEqual("", trip.why_not)

    def test_a_horde_family_in_ratchet_is_sent_to_orgrimmar(self):
        trip = auction.house_trip("horde", FROM_RATCHET, map_id=KALIMDOR)
        self.assertEqual("8724", trip.aim)
        self.assertEqual(auction.HOUSE_HORDE, trip.house)

    def test_the_far_aim_is_a_creature_entry_the_travel_column_takes(self):
        import travel

        trip = auction.house_trip("alliance", FROM_RATCHET, map_id=KALIMDOR)
        self.assertEqual(trip.aim, travel.resolve(trip.aim))
        self.assertNotEqual(auction.AUCTIONEER_ROLE, trip.aim)

    def test_the_other_sides_counter_is_never_the_aim(self):
        # Orgrimmar is the nearest counter, and it is no Alliance house.
        trip = auction.house_trip("alliance", FROM_RATCHET[:1], map_id=KALIMDOR)
        self.assertEqual("", trip.aim)
        self.assertIn("no auction house of this side", trip.why_not)

    def test_nobody_short_of_gear_takes_no_trip(self):
        trip = auction.house_trip("alliance", FROM_RATCHET, map_id=KALIMDOR, far=False)
        self.assertEqual("", trip.aim)
        self.assertIn("6191 yards", trip.why_not)

    def test_a_house_beyond_the_trip_limit_is_not_walked_to(self):
        rows = [_row(15678, "Auctioneer Silva'las", 80, 12448.9)]
        trip = auction.house_trip("alliance", rows, map_id=KALIMDOR)
        self.assertEqual("", trip.aim)
        self.assertIn("beyond the 7500-yard trip limit", trip.why_not)

    def test_a_counter_within_a_town_walk_keeps_the_keyword(self):
        rows = [_row(8670, "Auctioneer Chilton", 12, 41.0, map_id=0)]
        trip = auction.house_trip("alliance", rows, map_id=0)
        self.assertEqual(auction.AUCTIONEER_ROLE, trip.aim)
        self.assertEqual(auction.HOUSE_ALLIANCE, trip.house)

    def test_only_counters_on_the_leaders_map_count(self):
        rows = [_row(8670, "Auctioneer Chilton", 12, 41.0, map_id=0)]
        trip = auction.house_trip("alliance", rows, map_id=KALIMDOR)
        self.assertEqual("", trip.aim)

    def test_outland_and_northrend_send_nobody(self):
        rows = [_row(1, "Brassbolt Mechawrench", 534, 10.0, map_id=571)]
        self.assertEqual("", auction.house_trip("horde", rows, map_id=571).aim)
        self.assertEqual("", auction.house_trip("horde", rows, map_id=None).aim)

    def test_an_unreadable_row_is_skipped(self):
        rows = [{"entry": "x"}, None, _row(8661, "Auctioneer Beardo", 474, 6191.7)]
        trip = auction.house_trip("alliance", rows, map_id=KALIMDOR)
        self.assertEqual("8661", trip.aim)


class WhichCounterServesWhichSide(unittest.TestCase):
    def test_neutral_serves_both_sides_and_an_unknown_one(self):
        for team in ("alliance", "horde", ""):
            self.assertEqual(auction.HOUSE_NEUTRAL, auction.counter_house(team, 474))

    def test_a_side_counter_serves_only_its_side(self):
        self.assertEqual(auction.HOUSE_ALLIANCE, auction.counter_house("alliance", 80))
        self.assertEqual(0, auction.counter_house("horde", 80))
        self.assertEqual(auction.HOUSE_HORDE, auction.counter_house("Horde", 29))
        self.assertEqual(0, auction.counter_house("alliance", 29))
        self.assertEqual(0, auction.counter_house("", 29))

    def test_an_unplaced_faction_serves_nobody(self):
        self.assertEqual(0, auction.counter_house("alliance", 35))

    def test_the_side_sets_and_the_neutral_set_do_not_overlap(self):
        alliance = auction.SIDE_AUCTIONEER_FACTIONS[auction.HOUSE_ALLIANCE]
        horde = auction.SIDE_AUCTIONEER_FACTIONS[auction.HOUSE_HORDE]
        self.assertFalse(alliance & horde)
        self.assertFalse((alliance | horde) & auction.NEUTRAL_AUCTIONEER_FACTIONS)

    def test_the_trip_limit_is_inside_the_modules_backstop(self):
        # 20 minutes at the measured long-walk rate (flightlearn.REACH_YARDS).
        self.assertLess(
            auction.HOUSE_TRIP_MAX_YARDS, 20 * flightlearn.WALK_YARDS_PER_MINUTE
        )
        self.assertGreater(auction.HOUSE_TRIP_MAX_YARDS, 6191.7)


def _short(purse, worn=(), level=35):
    return {
        "level": level,
        "purse": purse,
        "equipped": {slot: {"item_level": 30} for slot in worn},
    }


class TheGearShortGate(unittest.TestCase):
    def test_six_empty_slots_and_the_purse_floor_make_the_trip(self):
        worn = ("mainhand", "chest", "legs", "feet", "hands", "head",
                "shoulder", "waist", "wrist", "back", "neck")  # fmt: skip
        facts = {"Og": _short(25000, worn), "Ugga": _short(25000, worn + ("finger1",))}
        self.assertEqual(("Og",), gearup.house_trip_shoppers(facts))

    def test_an_empty_main_hand_is_a_gap_on_its_own(self):
        facts = {"Og": _short(20000, ("chest", "legs"))}
        self.assertEqual(("Og",), gearup.house_trip_shoppers(facts))

    def test_a_member_below_the_purse_floor_does_not(self):
        facts = {"Og": _short(19999)}
        self.assertEqual((), gearup.house_trip_shoppers(facts))

    def test_the_bridge_passes_the_campaign_gates_numbers(self):
        src = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("GEARUP_GATE_EMPTY_SLOTS = 6", src)
        self.assertIn("GEARUP_GATE_MIN_PURSE = 20000", src)


def _method(name):
    module = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


class TheBridgeSendsTheLeader(unittest.TestCase):
    def test_a_leader_not_at_a_counter_asks_where_the_house_is(self):
        body = ast.unparse(_method("_gearup_house"))
        self.assertIn("await self._gearup_house_trip(leader, facts)", body)
        self.assertIn("await self._gearup_far_house(leader, trip, cohort)", body)
        far = ast.unparse(_method("_gearup_far_house"))
        self.assertIn(
            "self._claim_town_slot(GEAR_HOUSE_CLAIMANT, leader, trip.aim", far
        )

    def test_the_trip_reads_the_leaders_standing_and_the_spawns(self):
        body = ast.unparse(_method("_gearup_house_trip"))
        self.assertIn("_fetch_auctioneer_spawns", body)
        self.assertIn("gearup.house_trip_shoppers(", body)
        self.assertIn("auction.house_trip(", body)
        self.assertIn("far=bool(shoppers)", body)

    def test_the_trip_holds_the_traveller_for_a_lease_of_its_own(self):
        src = BRIDGE.read_text(encoding="utf-8")
        self.assertIn(
            "TOWN_SLOT_GEAR_HOUSE_LEASE_SECONDS = flightlearn.lease_for("
            "auction.HOUSE_TRIP_MAX_YARDS)",
            src,
        )
        self.assertEqual(
            2,
            src.count("GEAR_HOUSE_CLAIMANT: TOWN_SLOT_GEAR_HOUSE_LEASE_SECONDS,"),
        )

    def test_the_spawn_query_reads_the_auctioneer_flag(self):
        src = BRIDGE.read_text(encoding="utf-8")
        start = src.index("_AUCTIONEER_SPAWNS_SQL = (")
        sql = src[start : src.index("\n)\n", start)]
        self.assertIn("ct.faction AS faction", sql)
        self.assertIn("cr.map = %s AND (ct.npcflag & %s) <> 0", sql)


def _module_walk_limit():
    if not modsource.exists(DECISIONS_H):
        return None
    found = re.search(
        r"constexpr float TOWN_COUNTER_MAX_WALK_YARDS = ([0-9.]+)f;",
        modsource.read(DECISIONS_H, encoding="utf-8", errors="replace"),
    )
    return float(found.group(1)) if found else None


@unittest.skipIf(
    _module_walk_limit() is None,
    "the pinned mod-overseer predates TOWN_COUNTER_MAX_WALK_YARDS; this "
    "comparison engages when the pin reaches it",
)
class TheModuleAgrees(unittest.TestCase):
    def test_the_town_walk_is_the_modules(self):
        self.assertEqual(_module_walk_limit(), auction.TOWN_COUNTER_WALK_YARDS)


if __name__ == "__main__":
    unittest.main()
