"""A guild member's mail collect refused for bag room waits four hours (#2633).

The collect cooldown is an hour whatever the last row answered, so a member
whose bags stay full was walked to the mailbox, refused, and sent again about
every hour with nothing in between to make room.
"""

import unittest

import guildjobs
from test_guild_collects_mail import TAKES, _member

FULL = '{"outcome":"refused","reason":"no room in the bags","retryable":true}'
OTHER = '{"outcome":"refused","reason":"letter not found","retryable":true}'


def asks(age, result, walk=False):
    recent = [
        guildjobs.Recent(
            "Argam", "collect", age, status="error", result=result, walk=walk
        )
    ]
    plan = guildjobs.plan([_member()], mail={"Argam": TAKES}, recent=recent)
    return "collect" in [s.action for s in plan.steps]


class ACollectRefusedForBagRoom(unittest.TestCase):
    def test_it_is_not_asked_again_after_two_hours(self):
        self.assertFalse(asks(120, FULL))

    def test_it_is_asked_again_after_four_hours(self):
        self.assertTrue(asks(241, FULL))

    def test_another_refusal_keeps_the_hour(self):
        self.assertTrue(asks(90, OTHER))

    def test_a_walk_row_is_not_a_refusal(self):
        self.assertTrue(asks(90, FULL, walk=True))


if __name__ == "__main__":
    unittest.main()
