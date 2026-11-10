"""A family held out of its dungeon is not silent on it (the silent-head breaker).

A family that finishes a run and is then held at the bag floor for many hours
is put back on its dungeon job by the queue when room is made, and the very
next stall pass used to read all those hours since the last boss credit as
silence ON THE DOOR, leave it, cancel the queue row and send the family back to
quest until the planner found another door. The family had not been on the door
at all: its own queue held it off.

The silence clock must restart when a family comes back from a hold, and still
fire when a family is genuinely on the job and nothing happens.
"""

import unittest

import campaignqueue
import dungeonstall
import jobs
from test_campaign_queue import _load

HEAD = {"id": 159, "keyword": "dire-maul-east-east", "status": campaignqueue.ACTIVE}
NAMES = ["Ugga", "Bork"]
TEN_HOURS = 10 * 3600


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def silent_stall(job, db_seconds, clock, seen):
    ns = _load(
        ["_silent_stall"],
        {
            "campaignqueue": campaignqueue,
            "dungeonstall": dungeonstall,
            "jobs": jobs,
            "time": clock,
            "_OFF_DUNGEON_JOB_AT": seen,
            "_jobs_of": lambda names: {n: job["now"] for n in names},
            "_silent_seconds": lambda head_id, names: db_seconds["now"],
        },
    )
    return ns["_silent_stall"]


class AHeldFamilyStartsItsSilenceWhenTheHoldEnds(unittest.TestCase):
    def setUp(self):
        self.clock, self.seen = Clock(), {}
        self.job = {"now": "quest"}
        self.db = {"now": TEN_HOURS}
        self.check = silent_stall(self.job, self.db, self.clock, self.seen)

    def test_the_pass_right_after_a_hold_does_not_leave_the_door(self):
        self.assertIsNone(self.check(HEAD, NAMES))  # held: on quest
        self.clock.now += 60
        self.job["now"] = "dungeon:dire-maul-east-east"  # the queue re-asserts
        self.assertIsNone(self.check(HEAD, NAMES))

    def test_a_family_silent_for_two_hours_on_the_job_after_the_hold_leaves(self):
        self.assertIsNone(self.check(HEAD, NAMES))
        self.job["now"] = "dungeon:dire-maul-east-east"
        self.clock.now += 60
        self.assertIsNone(self.check(HEAD, NAMES))
        self.clock.now += 2 * 3600
        self.assertIsNotNone(self.check(HEAD, NAMES))

    def test_a_family_that_was_never_held_is_judged_on_the_database_clock(self):
        self.job["now"] = "dungeon:dire-maul-east-east"
        self.assertIsNotNone(self.check(HEAD, NAMES))

    def test_the_cap_never_lengthens_a_shorter_database_silence(self):
        self.assertIsNone(self.check(HEAD, NAMES))
        self.job["now"] = "dungeon:dire-maul-east-east"
        self.db["now"] = 600
        self.clock.now += 3 * 3600
        self.assertIsNone(self.check(HEAD, NAMES))

    def test_another_head_is_not_held_by_this_heads_clock(self):
        self.assertIsNone(self.check(HEAD, NAMES))
        self.job["now"] = "dungeon:dire-maul-east-east"
        other = dict(HEAD, id=160)
        self.assertIsNotNone(self.check(other, NAMES))


if __name__ == "__main__":
    unittest.main()
