"""The walk on after a death-loop hearth is asked again, and only so often (#2014).

The hearth step writes the walk on in the same instant as the hearth, and the
module refuses it while the hearth still holds the member. The resume
(guildjobs.death_loop_resume) asks again once the refusal's wait has passed;
this pins that it stops after RESUME_HELD_RETRIES refusals in a row.
"""

import unittest

from test_guildjobs_death_loop_resume import (
    at_home,
    hearthed,
    refused_walk,
    resume,
)

BOUND = 3


class TheWalkAfterTheHearth(unittest.TestCase):
    def test_a_walk_refused_as_held_is_sent_again_once_the_wait_passes(self):
        self.assertIsNotNone(resume(at_home(), (hearthed(30), refused_walk(29)))[0])

    def test_the_retry_is_bounded_when_the_hold_never_lifts(self):
        refusals = tuple(
            refused_walk(40 - 7 * i) for i in range(BOUND)
        )
        self.assertIsNone(resume(at_home(), (hearthed(45),) + refusals))

    def test_one_fewer_refusal_still_retries(self):
        refusals = tuple(
            refused_walk(40 - 7 * i) for i in range(BOUND - 1)
        )
        self.assertIsNotNone(resume(at_home(), (hearthed(45),) + refusals)[0])

    def test_refusals_from_before_the_landed_hearth_are_not_counted(self):
        old = tuple(refused_walk(80 + i) for i in range(BOUND))
        self.assertIsNotNone(resume(at_home(), (hearthed(30),) + old)[0])


if __name__ == "__main__":
    unittest.main()
