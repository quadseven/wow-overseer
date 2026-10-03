"""The trade-range check refuses exactly at the line, like the core does.

mod-overseer's test_give_range.cpp pins the core's own compare as strict:
exactly TRADE_DISTANCE (11.11 yards) is refused. gear._within_trade_range is
the one Python copy of that rule (bag_pressure aliases it; handover and the
gear passes all funnel through it), so it must refuse the boundary too -
otherwise a hand-over planned at exactly 11.11 yards can only become an
error row.
"""

import unittest

import gear


def _spot(map_id, x, y=0.0):
    return gear.Spot(map_id=map_id, x=x, y=y)


class TheBoundaryMatchesTheCore(unittest.TestCase):
    def test_together(self):
        self.assertTrue(gear._within_trade_range(_spot(1, 0.0), _spot(1, 0.0)))

    def test_just_inside(self):
        self.assertTrue(
            gear._within_trade_range(_spot(1, 0.0), _spot(1, gear.TRADE_YARDS - 0.01))
        )

    def test_exactly_at_the_line_is_refused(self):
        self.assertFalse(
            gear._within_trade_range(_spot(1, 0.0), _spot(1, gear.TRADE_YARDS))
        )

    def test_just_outside(self):
        self.assertFalse(
            gear._within_trade_range(_spot(1, 0.0), _spot(1, gear.TRADE_YARDS + 0.01))
        )

    def test_another_map_is_refused_at_zero_distance(self):
        self.assertFalse(gear._within_trade_range(_spot(0, 0.0), _spot(1, 0.0)))


if __name__ == "__main__":
    unittest.main()
