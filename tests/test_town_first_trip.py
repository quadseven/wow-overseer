"""A campaign held in town for bag room sells up to its resume floor."""

import pathlib
import unittest

import bag_pressure

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TownFirstTripWorth(unittest.TestCase):
    def test_the_horde_family_measured_on_wow_dev_goes_to_a_vendor(self):
        free = {"Oz": 7, "Uzza": 8, "Zork": 5, "Zrog": 10, "Zug": 4}
        sellable = {"Oz": 17, "Uzza": 18, "Zork": 14, "Zrog": 16, "Zug": 17}
        self.assertFalse(bag_pressure.family_town_run_needed(free, sellable=sellable))
        self.assertTrue(bag_pressure.town_first_trip_worth(free, sellable))

    def test_nobody_short_of_the_floor_takes_no_trip(self):
        free = {"Oz": 8, "Zug": 12}
        self.assertFalse(bag_pressure.town_first_trip_worth(free, {"Oz": 5, "Zug": 5}))

    def test_a_member_selling_cannot_help_takes_no_trip(self):
        self.assertFalse(bag_pressure.town_first_trip_worth({"Zug": 4}, {"Zug": 0}))


class VendorPassAsksTheHold(unittest.TestCase):
    def test_the_pass_mode_consults_the_town_hold_outside_a_run(self):
        src = (ROOT / "bridge.py").read_text()
        start = src.index("    async def _vendor_pass_mode(self")
        body = src[start : src.index("        return mode", start)]
        self.assertIn("_town_first_hold", body)
        self.assertIn("town_first_trip_worth", body)
        self.assertIn("not in_run", body)

    def test_an_armed_campaign_is_not_a_town_hold(self):
        src = (ROOT / "bridge.py").read_text()
        start = src.index("def _town_first_hold(")
        body = src[start : src.index("\n\n\n", start)]
        self.assertIn('startswith("dungeon")', body)


if __name__ == "__main__":
    unittest.main()
