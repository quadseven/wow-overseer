"""A vendor errand the module calls done, and nothing queued, ends on a clock.

The module declares the errand done on arrival and may not clear a column it
did not write, so a standing aim is re-read as a new walk every poll while the
bridge holds it under bag pressure.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bag_pressure  # noqa: E402

LIMIT = bag_pressure.COUNTER_DONE_RELEASE_SECONDS


class CounterDoneStep(unittest.TestCase):
    def test_the_clock_starts_on_the_first_reading_and_does_not_release(self):
        since, release = bag_pressure.counter_done_step(None, 1000.0, True, 0, True)
        self.assertEqual(since, 1000.0)
        self.assertFalse(release)

    def test_it_releases_once_the_clock_has_run(self):
        since, release = bag_pressure.counter_done_step(
            1000.0, 1000.0 + LIMIT, True, 0, True
        )
        self.assertEqual(since, 1000.0)
        self.assertTrue(release)

    def test_it_does_not_release_a_second_early(self):
        _, release = bag_pressure.counter_done_step(
            1000.0, 1000.0 + LIMIT - 1, True, 0, True
        )
        self.assertFalse(release)

    def test_a_module_that_has_not_said_done_never_starts_the_clock(self):
        since, release = bag_pressure.counter_done_step(None, 1000.0, True, 0, False)
        self.assertIsNone(since)
        self.assertFalse(release)

    def test_a_flicker_of_the_modules_report_keeps_the_clock(self):
        since, release = bag_pressure.counter_done_step(
            1000.0, 1000.0 + LIMIT + 5, True, 0, False
        )
        self.assertEqual(since, 1000.0)
        self.assertTrue(release)

    def test_a_queued_sale_clears_the_clock(self):
        since, release = bag_pressure.counter_done_step(
            1000.0, 1000.0 + LIMIT * 5, True, 3, True
        )
        self.assertIsNone(since)
        self.assertFalse(release)

    def test_an_unreadable_queue_clears_the_clock_and_never_releases(self):
        since, release = bag_pressure.counter_done_step(
            1000.0, 1000.0 + LIMIT * 5, True, -1, True
        )
        self.assertIsNone(since)
        self.assertFalse(release)

    def test_a_leader_off_the_counter_clears_the_clock(self):
        since, release = bag_pressure.counter_done_step(
            1000.0, 1000.0 + LIMIT * 5, False, 0, True
        )
        self.assertIsNone(since)
        self.assertFalse(release)

    def test_the_bridge_asks_before_it_holds(self):
        with open(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge.py"
            ),
            encoding="utf-8",
        ) as fh:
            source = fh.read()
        self.assertIn("bag_pressure.bound_pressure_hold(", source)


class BoundPressureHold(unittest.TestCase):
    def setUp(self):
        bag_pressure._COUNTER_DONE_SINCE.clear()

    def ask(self, now, step=None, outstanding=0, intent=None, vendor=True):
        return bag_pressure.bound_pressure_hold(
            step or bag_pressure.VENDOR_ERRAND_HOLD,
            "Grug",
            now,
            vendor,
            "vendor",
            outstanding,
            {"current_kind": "quest"} if intent is None else intent,
        )

    def test_a_hold_becomes_the_release_after_the_bound(self):
        self.assertEqual(self.ask(1000.0), bag_pressure.VENDOR_ERRAND_HOLD)
        self.assertEqual(self.ask(1000.0 + LIMIT), bag_pressure.VENDOR_ERRAND_RELEASE)

    def test_an_errand_the_module_still_holds_is_never_released(self):
        economy = {"current_kind": "economy"}
        self.ask(1000.0, intent=economy)
        self.assertEqual(
            self.ask(1000.0 + LIMIT * 3, intent=economy),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )

    def test_an_absent_intent_row_never_starts_the_clock(self):
        self.assertEqual(self.ask(1000.0, intent={}), bag_pressure.VENDOR_ERRAND_HOLD)
        self.assertEqual(
            self.ask(1000.0 + LIMIT * 3, intent={}), bag_pressure.VENDOR_ERRAND_HOLD
        )
        self.assertEqual(bag_pressure._COUNTER_DONE_SINCE, {})

    def test_a_clock_for_a_leader_who_left_is_dropped(self):
        self.ask(1000.0)
        bag_pressure.bound_pressure_hold(
            bag_pressure.VENDOR_ERRAND_HOLD,
            "Other",
            1000.0 + LIMIT * 11,
            True,
            "vendor",
            1,
            {"current_kind": "quest"},
        )
        self.assertNotIn("Grug", bag_pressure._COUNTER_DONE_SINCE)

    def test_a_queued_sale_keeps_the_hold(self):
        self.ask(1000.0)
        self.assertEqual(
            self.ask(1000.0 + LIMIT * 3, outstanding=2),
            bag_pressure.VENDOR_ERRAND_HOLD,
        )

    def test_only_a_hold_is_turned_into_a_release(self):
        self.ask(1000.0)
        self.assertEqual(
            self.ask(1000.0 + LIMIT, step=bag_pressure.VENDOR_ERRAND_AIM),
            bag_pressure.VENDOR_ERRAND_AIM,
        )


if __name__ == "__main__":
    unittest.main()
