"""A sale walk refused for a passing reason is asked again soon (#1592).

WHY THIS EXISTS. The live check of #1592 on 2026-11-04 found 89 of the 162
members of Cave and Bonkers at one free bag slot or fewer, and a read on
2026-11-07 found 95. The bridge log archive from 2026-11-06 12:00Z to
2026-11-07 17:42Z holds about 300 member sale walks (`walk-to-vendor any`
rows from the `sell-walk` source). About a third of them ended for a reason
that says nothing about the vendor or the road: 40 "character is held by
another verb", 25 "character is in combat", 16 "character is on a flight
path", 3 "a walk is already under way for this character". The worldserver
log names the hold behind almost every "held by another verb" walk refusal
in that window (101 of 104 vendor walks): the member had just revived at a
spirit healer, and the module holds a member with Resurrection Sickness
still for at most 690 seconds.

Each of those refused walks still counted as a sale, so the member waited
the full 120 minute sale cooldown with its bags still full, and every kill
in the meantime left its loot on the corpse. The food trip had the same
fault and the same fix (test_supply_passing_refusal, #1906): a refusal of
this kind waits LEVEL_TRANSIENT_RETRY_MINUTES, and the guild jobs walk wall
(job_walk_backoff) keeps a held member waiting until the hold has lapsed.
A refusal that says something about the walk (the other side's ground, a
death on the road, a stall) keeps the full cooldown, and so does a walk
whose sale was served.
"""

import unittest

import guildjobs
from test_bound_blues_sell import ekka

NAME = "Ekka"


def sale(reason, age, status="error"):
    """One sale step as the module answers it: the walk to a vendor (the
    `sell-walk` source, so recent_from_rows reads it as a `sell` walk), then
    a sell row, which fails "vendor not in range" when the walk did not
    arrive."""
    walk = guildjobs.Recent(
        NAME,
        "sell",
        age,
        status=status,
        walk=True,
        refusal=reason,
        reason=reason,
        command="walk-to-vendor any max:20000",
    )
    after = "applied" if status == "applied" else "error"
    row = guildjobs.Recent(
        NAME,
        "sell",
        age,
        status=after,
        reason="" if after == "applied" else "vendor not in range",
        command="guid:7001",
    )
    return (walk, row)


def cooling(rows):
    return guildjobs._cooling(ekka(), "sell", rows)


class APassingRefusalIsAskedAgain(unittest.TestCase):
    def test_held_by_another_verb_waits_minutes_not_two_hours(self):
        self.assertFalse(cooling(sale("character is held by another verb", 20)))

    def test_in_combat_waits_minutes_not_two_hours(self):
        self.assertFalse(cooling(sale("character is in combat", 20)))

    def test_on_a_flight_waits_minutes_not_two_hours(self):
        self.assertFalse(cooling(sale("character is on a flight path", 20)))

    def test_a_fight_on_the_way_to_the_vendor_waits_minutes(self):
        self.assertFalse(cooling(sale("entered combat on the way to the vendor", 20)))

    def test_inside_the_short_wait_it_still_cools(self):
        self.assertTrue(cooling(sale("character is held by another verb", 2)))

    def test_a_death_on_the_road_keeps_the_two_hours(self):
        self.assertTrue(cooling(sale("died on the way to the vendor", 20)))

    def test_a_lasting_refusal_keeps_the_two_hours(self):
        why = "the way to the nearest vendor crosses the other side's ground"
        self.assertTrue(cooling(sale(why, 20)))

    def test_a_sale_that_was_served_keeps_the_two_hours(self):
        self.assertTrue(cooling(sale("", 20, status="applied")))

    def test_an_older_passing_refusal_under_a_newer_served_sale_keeps_it(self):
        rows = sale("", 20, status="applied") + sale(
            "character is held by another verb", 40
        )
        self.assertTrue(cooling(rows))


class AFullMemberSellsAgainAfterTheHold(unittest.TestCase):
    def test_a_full_member_held_twenty_minutes_ago_walks_to_sell(self):
        rows = sale("character is held by another verb", 20)
        step = guildjobs._full_bags_first(ekka(), None, rows, 600.0)
        self.assertIsNotNone(step)
        self.assertEqual(step.action, "sell")

    def test_the_held_walk_wall_still_holds_it_until_the_hold_lapses(self):
        # The walk wall reads the same rows: a member held two minutes ago
        # waits out HELD_BACKOFF_MINUTES before any guild jobs walk.
        wall, wait = guildjobs.job_walk_backoff(
            NAME, sale("character is held by another verb", 2)
        )
        self.assertEqual(wall, "character is held by another verb")
        self.assertGreater(wait, 0)


if __name__ == "__main__":
    unittest.main()
