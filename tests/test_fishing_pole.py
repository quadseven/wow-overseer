"""craft_supply.pole_errand / pole_need - the Fishing Pole job='fish' needs.

mod-overseer#530. job='fish' turns on mod-playerbots' own fishing AI
(mod-overseer#448), whose EquipFishingPoleAction equips a pole from the bags
and buys one only for a random bot - nobody on this roster is one. So all five
characters sat at Fishing 1/75 with no pole between them. These tests pin the
purchase: one basic pole (entry 6256, 23 copper, read from
acore_world.item_template), bought once, only while the family is on
job='fish', never for a character who already owns any pole.

The bridge half is read as TEXT, the way test_craft_supply.py reads it:
bridge.py imports discord and cannot be imported here.
"""

import pathlib
import re
import unittest

import craft_supply
import jobs
from towntrip import Town

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

FISHING_POLE = 6256
EMPTY_VIAL = 3371
# Helenia Olden, a Theramore vendor that stocks the pole on map 1 - the one
# the issue names. Distance is illustrative; supply_trip only ranks by it.
HELENIA = craft_supply.VendorSpawn(
    entry=4897, name="Helenia Olden", faction=894, map_id=1, yards=1400.0
)


def _town(*stocks):
    return Town(repairs=False, stocks=frozenset(stocks), vendor=bool(stocks))


def _block(signature: str) -> str:
    src = BRIDGE.read_text(encoding="utf-8")
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


class ThePoleIsTheOneTheIssueNamed(unittest.TestCase):
    def test_entry_name_and_price(self):
        self.assertEqual(craft_supply.FISHING_POLE, (6256, "Fishing Pole", 23))

    def test_the_mode_is_jobs_own_fish(self):
        self.assertEqual(craft_supply.FISH_MODE, "fish")
        self.assertIn(craft_supply.FISH_MODE, jobs.IMPLEMENTED)


class PoleErrand(unittest.TestCase):
    def test_a_member_with_no_pole_at_a_stocking_counter_buys_exactly_one(self):
        errand, note = craft_supply.pole_errand(
            "Ugga", False, 1_721_704, 4, _town(FISHING_POLE)
        )
        self.assertIsNone(note)
        self.assertEqual(errand.member, "Ugga")
        self.assertEqual(errand.kind, "buy")
        self.assertEqual(errand.command, "entry:6256 count:1 max:23")
        self.assertEqual(errand.spend, 23)

    def test_a_member_who_owns_any_pole_is_sold_nothing(self):
        self.assertEqual(
            craft_supply.pole_errand("Grug", True, 1_658_352, 4, _town(FISHING_POLE)),
            (None, None),
        )

    def test_a_counter_without_the_pole_says_so(self):
        errand, note = craft_supply.pole_errand(
            "Ugga", False, 1_721_704, 4, _town(EMPTY_VIAL)
        )
        self.assertIsNone(errand)
        self.assertIn("Fishing Pole (6256)", note)

    def test_full_bags_refuse(self):
        errand, note = craft_supply.pole_errand(
            "Ugga", False, 1_721_704, 0, _town(FISHING_POLE)
        )
        self.assertIsNone(errand)
        self.assertIn("no free bag slot", note)

    def test_an_empty_purse_refuses(self):
        errand, note = craft_supply.pole_errand(
            "Ugga", False, 22, 4, _town(FISHING_POLE)
        )
        self.assertIsNone(errand)
        self.assertIn("cannot afford", note)


class PoleNeed(unittest.TestCase):
    def test_no_pole_and_no_stocking_counter_is_a_trip(self):
        self.assertEqual(
            craft_supply.pole_need("Ugga", False, _town()),
            craft_supply.Need("Ugga", FISHING_POLE, "Fishing Pole"),
        )

    def test_a_holder_needs_no_trip(self):
        self.assertIsNone(craft_supply.pole_need("Ugga", True, _town()))

    def test_standing_at_a_stocking_counter_needs_no_trip(self):
        self.assertIsNone(craft_supply.pole_need("Ugga", False, _town(FISHING_POLE)))

    def test_the_trip_aims_the_leader_at_a_vendor_that_stocks_the_pole(self):
        need = craft_supply.pole_need("Ugga", False, _town())
        trip = craft_supply.supply_trip(
            [need], {FISHING_POLE: [HELENIA]}, leader="Grog", map_id=1
        )
        self.assertEqual(trip.traveller, "Grog")
        self.assertEqual(trip.target, "4897")
        self.assertEqual(trip.entry, FISHING_POLE)


class TheBridgeBuysThePoleOnlyOnFish(unittest.TestCase):
    def setUp(self):
        self.supply = _block("    async def _craft_supply_once(")
        self.poles = _block("    async def _buy_fishing_poles(")

    def test_the_fish_branch_comes_before_the_craft_gate(self):
        fish = self.supply.index("if mode == craft_supply.FISH_MODE:")
        gate = self.supply.index("if mode not in (")
        self.assertLess(fish, gate)
        self.assertIn("self._buy_fishing_poles(names, cohort)", self.supply)

    def test_the_decisions_are_the_pure_modules(self):
        self.assertIn("craft_supply.pole_errand(", self.poles)
        self.assertIn("craft_supply.pole_need(", self.poles)
        self.assertIn("_fetch_pole_holders", self.poles)
        self.assertIn("self._walk_for_reagents(needs, cohort)", self.poles)
        self.assertIn("_insert_town_errand", self.poles)
        self.assertNotIn("6256", self.poles)

    def test_any_pole_in_reach_counts_and_the_bank_does_not(self):
        sql = _block("def _fetch_pole_holders(")
        self.assertIn("it.class = 2 AND it.subclass = 20", sql)
        self.assertIn("ci.bag = 0 AND ci.slot < 39", sql)
        self.assertIn("wb.slot BETWEEN 19 AND 22", sql)


if __name__ == "__main__":
    unittest.main()
