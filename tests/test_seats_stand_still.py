"""A raid seat levelling first is not hearthed for waiting on its dungeon group.

WHY THIS EXISTS. Levelling first (guildjobs.levelling_first) leaves a seat
below the cap with no step while it waits for a dungeon ask, so it stands on
one spot. The stood-still hearth read that as stuck after an hour: after the
change the daily hearth rows for such seats more than doubled, and each hearth
carried a seat home and held it "on a guild job" away from the asks it was
waiting on. A seat now waits SEAT_STILL_MINUTES; every other member keeps
STILL_MINUTES.
"""

import unittest

import guildjobs
import standstill
from test_seats_level_first import NOT_A_SEAT, SEAT, hungry_member


def hearths(member, minutes):
    step = guildjobs.stood_still_step(member, minutes, ())
    return step is not None and step.action == "hearth"


def open_member(name=SEAT, **over):
    over.setdefault("map_id", 0)
    over.setdefault("online", True)
    return hungry_member(name, **over)


class TheSeatsStand(unittest.TestCase):
    def test_a_seat_below_the_cap_is_not_hearthed_after_an_hour(self):
        self.assertFalse(hearths(open_member(), standstill.STILL_MINUTES + 5))

    def test_a_seat_below_the_cap_is_hearthed_when_the_longer_wait_is_out(self):
        self.assertTrue(hearths(open_member(), standstill.SEAT_STILL_MINUTES))

    def test_a_member_off_the_lineup_is_hearthed_after_an_hour(self):
        self.assertTrue(hearths(open_member(NOT_A_SEAT), standstill.STILL_MINUTES))

    def test_the_switch_off_restores_the_hour(self):
        import os

        old = os.environ.get(guildjobs.SEATS_LEVEL_FIRST_ENV)
        os.environ[guildjobs.SEATS_LEVEL_FIRST_ENV] = "off"
        try:
            self.assertTrue(hearths(open_member(), standstill.STILL_MINUTES))
        finally:
            if old is None:
                os.environ.pop(guildjobs.SEATS_LEVEL_FIRST_ENV, None)
            else:
                os.environ[guildjobs.SEATS_LEVEL_FIRST_ENV] = old


if __name__ == "__main__":
    unittest.main()
