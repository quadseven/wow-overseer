"""A vendor errand the module calls done, and nothing queued, ends on a clock.

Dev realm, 2026-11-18: the module logged "reached 'vendor' - errand done" in 0
seconds, fifteen seconds apart, while the bridge held the aim under bag
pressure with no sales outstanding. The module may not clear a column it did
not write, so the aim stood and every poll read it as a new walk.
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
        self.assertIn("bag_pressure.counter_done_step(", source)
        self.assertIn("_counter_done_since", source)


if __name__ == "__main__":
    unittest.main()
