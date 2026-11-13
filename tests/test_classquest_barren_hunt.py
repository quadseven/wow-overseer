"""A run of hunts at one pack that kill stops restarting the stall clock (#2188).

A seat past level 40 repeated one class quest hunt for hours: every row ended
applied with kills and no change in the quest's counters. The kills made
`_class_move` call `Hunts.productive`, which restarts the 30 minute stall clock,
so the pack was never rerolled and the quest never given up for help. One or two
such rows are still the ground being worked (a full bag): see
test_classquest_tried_memory. Loot is no evidence: the module counts every item
looted, greys included, so a pack that drops only greys looted something each time.
"""

import unittest
from unittest import mock

import classquest
import guildjobs
from test_classquest import who
from test_classquest_tried_memory import HUNTER, hunt, recent, two_packs

STALL_SECONDS = classquest.HUNT_STALL_MINUTES * 60


def barren(rid, age):
    return hunt(rid, "Aa", "applied", age, "timeout", "the clock ran out", 4, 0)


def looted(rid, age):
    return hunt(rid, "Aa", "applied", age, "timeout", "the clock ran out", 4, 2)


def hunts_after_a_stall(*rows):
    """Run `_class_move` once to start the hunt clock, then again past the stall
    with these hunt rows, and return the hunts memory."""
    hunts = classquest.Hunts()
    member = who("Aa", **HUNTER)
    book = two_packs()
    guildjobs._class_move(member, book, recent(), hunts, 0.0)
    guildjobs._class_move(member, book, recent(*rows), hunts, float(STALL_SECONDS + 60))
    return hunts


@mock.patch.object(classquest, "TRIED_EPOCH", 0)
class BarrenHunt(unittest.TestCase):
    def test_a_run_of_barren_hunts_lets_the_stall_clock_run_out(self):
        hunts = hunts_after_a_stall(barren(1, 20), barren(2, 12), barren(3, 4))
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_fewer_barren_hunts_than_the_bound_still_restart_the_clock(self):
        hunts = hunts_after_a_stall(barren(1, 12), barren(2, 4))
        self.assertEqual(hunts.get("Aa").tried, ())

    def test_grey_loot_does_not_hide_the_run(self):
        # Each row looted something (a grey), the quest's counters never moved.
        hunts = hunts_after_a_stall(looted(1, 20), looted(2, 12), looted(3, 4))
        self.assertEqual(len(hunts.get("Aa").tried), 1)

    def test_a_kill_row_at_another_pack_starts_its_own_count(self):
        other = hunt(5, "Aa", "applied", 4, "timeout", "the clock ran out", 4, 0)
        other = dict(other, command=other["command"].replace("3130", "3131"))
        rows = recent(barren(1, 20), barren(2, 12), other)
        self.assertEqual(guildjobs.barren_hunt_rows("Aa", rows), 1)
        hunts = hunts_after_a_stall(barren(1, 20), barren(2, 12), other)
        self.assertEqual(hunts.get("Aa").tried, ())

    def test_the_run_is_counted_newest_first_and_only_for_rows_that_killed(self):
        refused = hunt(9, "Aa", "error", 2, "refused", "no living creature", 0, 0)
        rows = recent(barren(1, 20), barren(2, 12), barren(3, 4), refused)
        self.assertEqual(guildjobs.barren_hunt_rows("Aa", rows), 3)

    def test_a_barren_run_tries_every_pack_and_then_has_no_move_left(self):
        # With two packs, two stalls try both; the member then has no hunt move
        # and the plan asks for help, as a stalled hunt does.
        hunts = classquest.Hunts()
        member = who("Aa", **HUNTER)
        book = two_packs()
        rows = recent(barren(1, 20), barren(2, 12), barren(3, 4))
        now = 0.0
        guildjobs._class_move(member, book, recent(), hunts, now)
        moves = []
        for _ in range(2):
            now += STALL_SECONDS + 60
            moves.append(guildjobs._class_move(member, book, rows, hunts, now)[0])
        self.assertEqual(len(hunts.get("Aa").tried), 2)
        self.assertIsNotNone(moves[0])
        self.assertIsNone(moves[1])


if __name__ == "__main__":
    unittest.main()
