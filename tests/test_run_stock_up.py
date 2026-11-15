"""A run is not opened on four free slots while one sale would make a run's room.

A family went into a dungeon with 4 to 5 free slots each and 13 to 19 stacks a
vendor would buy, filled to nothing inside, and left the drops it could not
carry on the corpses for hours. The stock-up is one bounded vendor stop.
"""

import pathlib
import unittest

import bag_pressure

ROOT = pathlib.Path(__file__).resolve().parent.parent

FREE = {"Bork": 5, "Grog": 4, "Grug": 5, "Og": 14, "Ugga": 10}
SELLABLE = {"Bork": 13, "Grog": 14, "Grug": 19, "Og": 11, "Ugga": 12}


class StockUpShort(unittest.TestCase):
    def test_members_between_the_floor_and_a_runs_room_with_a_sale_wait(self):
        self.assertEqual(
            ("Bork", "Grog", "Grug"),
            bag_pressure.campaign_resume_short(FREE, sellable=SELLABLE),
        )

    def test_without_a_read_of_the_sale_nothing_new_is_held(self):
        self.assertEqual((), bag_pressure.campaign_resume_short(FREE))
        self.assertEqual((), bag_pressure.campaign_resume_short(FREE, sellable={}))

    def test_a_member_nothing_can_lift_is_not_waited_for(self):
        self.assertEqual(
            (),
            bag_pressure.campaign_resume_short(
                {"Zug": 5}, sellable={"Zug": bag_pressure.STOCK_UP_MIN_SELLABLE - 1}
            ),
        )

    def test_the_stop_is_bounded_well_under_the_resume_ceiling(self):
        self.assertLess(
            bag_pressure.STOCK_UP_CEILING_SECONDS,
            bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS,
        )
        self.assertEqual(
            (),
            bag_pressure.campaign_resume_short(
                FREE,
                held_seconds=bag_pressure.STOCK_UP_CEILING_SECONDS,
                sellable=SELLABLE,
            ),
        )

    def test_the_old_floor_still_holds_for_the_whole_ceiling(self):
        free = {"Zug": 3}
        held = bag_pressure.STOCK_UP_CEILING_SECONDS + 1
        self.assertEqual(
            ("Zug",),
            bag_pressure.campaign_resume_short(
                free, held_seconds=held, sellable={"Zug": 30}
            ),
        )

    def test_the_vendor_trip_goes_for_the_stock_up(self):
        self.assertFalse(bag_pressure.town_first_trip_worth(FREE, SELLABLE))
        self.assertTrue(
            bag_pressure.town_first_trip_worth(FREE, SELLABLE, stock_up=True)
        )

    def test_the_errand_does_not_end_on_four_free_slots_with_a_sale_waiting(self):
        self.assertTrue(bag_pressure.bag_room_made(FREE))
        self.assertFalse(bag_pressure.bag_room_made(FREE, sellable=SELLABLE))


class TheClaimInsideIsTrue(unittest.TestCase):
    def test_the_in_run_line_does_not_promise_room_it_cannot_make(self):
        src = (ROOT / "bridge.py").read_text()
        start = src.index("economy: bag pressure is urgent during a dungeon")
        body = src[start - 200 : start + 900]
        self.assertNotIn("the run makes bag room inside", body)
        self.assertIn("grey", body)


class TheGateReadsTheSale(unittest.TestCase):
    def test_town_first_passes_the_last_sale_read(self):
        src = (ROOT / "bridge.py").read_text()
        start = src.index("def _town_first(")
        body = src[start : src.index("\n\n\n", start)]
        self.assertIn("_VENDOR_SELLABLE", body)


if __name__ == "__main__":
    unittest.main()
