"""A use the module refuses the same way every time stops being asked (#678).

On the dev realm every cast-spell-on-mainhand row for quest 12842 was refused
"no Runeforge is within spell range" (62 of 62 in three days, three death
knights). Each refusal read as `retry later`, so a step asked three times and
the next pass began again, for ever. A streak of the same refusal with no use
done between is a defect, not a wait: the quest is given up for its hold-off
and the stuck read names the refusal.
"""

import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import classuse

WHY = "no Runeforge is within spell range"


class RefusalStreakTests(unittest.TestCase):
    def test_the_same_refusal_trips_at_the_limit_and_not_before(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            self.assertFalse(s.refused("Saevor", 12842, WHY))
        self.assertTrue(s.refused("Saevor", 12842, WHY))

    def test_a_done_use_clears_the_streak(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            s.refused("Saevor", 12842, WHY)
        s.done("Saevor", 12842)
        self.assertFalse(s.refused("Saevor", 12842, WHY))

    def test_a_different_refusal_restarts_the_count(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            s.refused("Saevor", 12842, WHY)
        self.assertFalse(s.refused("Saevor", 12842, "the main-hand spell is on cooldown"))

    def test_members_and_quests_count_apart(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            s.refused("Saevor", 12842, WHY)
        self.assertFalse(s.refused("Brug", 12842, WHY))
        self.assertFalse(s.refused("Saevor", 12843, WHY))

    def test_the_reason_is_kept_for_the_stuck_read(self):
        s = classuse.RefusalStreaks()
        s.refused("Saevor", 12842, WHY)
        self.assertEqual(s.last_reason("Saevor", 12842), WHY)
        self.assertEqual(s.last_reason("Brug", 12842), "")


if __name__ == "__main__":
    unittest.main()
