"""The death-dialog dismissal gate: only a dialog seen on two consecutive
checks may be dismissed, at the click point the detector measured.

The detector itself lives with the client that owns the pixels; these tests
exercise the gate at its public seam, death_dismiss.verdict, with the same
shaped values the detector returns: an (fx, fy) pair of image fractions, or
None when the dialog is absent.
"""

import unittest

import death_dismiss

FIRST = (0.512, 0.231)
SECOND = (0.508, 0.233)


class TwoChecksDismiss(unittest.TestCase):
    def test_two_consecutive_sightings_dismiss_at_the_measured_point(self):
        """The click goes to the current check's measured point, not to a
        remembered constant and not to the previous check's point."""
        self.assertEqual(SECOND, death_dismiss.verdict(FIRST, SECOND))

    def test_a_single_sighting_is_never_clicked(self):
        """A dialog seen once is transient until proven otherwise."""
        self.assertIsNone(death_dismiss.verdict(None, SECOND))

    def test_a_sighting_then_absence_clicks_nothing(self):
        self.assertIsNone(death_dismiss.verdict(FIRST, None))

    def test_no_sighting_on_either_check_clicks_nothing(self):
        self.assertIsNone(death_dismiss.verdict(None, None))


class NothingRaises(unittest.TestCase):
    def test_a_malformed_current_point_is_treated_as_absent(self):
        self.assertIsNone(death_dismiss.verdict(FIRST, "not-a-point"))
        self.assertIsNone(death_dismiss.verdict(FIRST, (0.5,)))
        self.assertIsNone(death_dismiss.verdict(FIRST, (0.5, float("nan"))))

    def test_a_malformed_previous_point_is_treated_as_absent(self):
        self.assertIsNone(death_dismiss.verdict("not-a-point", SECOND))

    def test_nothing_in_the_gate_can_raise(self):
        for previous, current in (
            (None, None),
            (object(), object()),
            ((1, 2, 3), (0.5, 0.5)),
            (None, (2.0, 0.5)),
        ):
            self.assertIsNone(death_dismiss.verdict(previous, current))


if __name__ == "__main__":
    unittest.main()
