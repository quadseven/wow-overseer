"""A food walk refused for a passing reason is asked again next pass.

WHY THIS EXISTS. After the death loop's food rung shipped (#1906), the pass
at 2026-11-06 01:33 UTC sent 9 members in death loops to a food vendor. 5 of
the walks came back "character is held by another verb" within six seconds
and 1 came back "character is in combat". The worldserver log names the
hold: each member had just revived at a spirit healer, and the module holds
a member with Resurrection Sickness still for at most 690 seconds. The
refused walk still counted as a supply trip, so the member waited the full
60 minute supply cooldown, still with nothing to eat, and died again in the
meantime.

A refusal of this kind says nothing about the vendor or the road. Like the
level walk's (_step_row_wait), it waits LEVEL_TRANSIENT_RETRY_MINUTES, and
the guild jobs walk wall (job_walk_held) keeps a held member waiting until
the hold has lapsed. A refusal that says something about the walk keeps the
full cooldown.
"""

import unittest

import guildjobs
import restsupply
from test_guild_rest_supply import member

NAME = "Femur"


def trip(reason, age, status="error"):
    """One food trip as the module answers it: the walk to the vendor, then
    the sell and buy rows, which fail "vendor not in range" when the walk did
    not arrive."""
    walk = guildjobs.Recent(
        NAME,
        restsupply.ACTION,
        age,
        status=status,
        refusal=reason,
        reason=reason,
        command="walk-to-vendor item:4605 max:20000",
    )
    after = "applied" if status == "applied" else "error"
    sale = guildjobs.Recent(
        NAME,
        restsupply.ACTION,
        age,
        status=after,
        reason="" if after == "applied" else "vendor not in range",
        command="guid:18106420",
    )
    buy = guildjobs.Recent(
        NAME,
        restsupply.ACTION,
        age,
        status=after,
        reason="" if after == "applied" else "vendor not in range",
        command="entry:4605 count:1 max:125",
    )
    return (walk, sale, buy)


def cooling(rows):
    return guildjobs._cooling(member(), restsupply.ACTION, rows)


class APassingRefusalIsAskedAgain(unittest.TestCase):
    def test_held_by_another_verb_waits_minutes_not_an_hour(self):
        self.assertFalse(cooling(trip("character is held by another verb", 20)))

    def test_in_combat_waits_minutes_not_an_hour(self):
        self.assertFalse(cooling(trip("character is in combat", 20)))

    def test_inside_the_short_wait_it_still_cools(self):
        self.assertTrue(cooling(trip("character is held by another verb", 2)))

    def test_a_lasting_refusal_keeps_the_hour(self):
        why = "the way to the spawn crosses the other side's ground"
        self.assertTrue(cooling(trip(why, 20)))

    def test_a_trip_that_was_served_keeps_the_hour(self):
        self.assertTrue(cooling(trip("", 20, status="applied")))

    def test_an_older_passing_refusal_under_a_newer_served_trip_keeps_the_hour(self):
        rows = trip("", 20, status="applied") + trip(
            "character is held by another verb", 40
        )
        self.assertTrue(cooling(rows))


if __name__ == "__main__":
    unittest.main()
