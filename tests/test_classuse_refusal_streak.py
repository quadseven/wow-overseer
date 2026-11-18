"""A use the module refuses the same way every time stops being asked (#678).

Worked example: a cast-spell-on-mainhand row is refused with the same reason on
every ask. Each refusal read as `retry later`, so a step asked three times and
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
            self.assertFalse(s.refused("Alpha", 100, WHY))
        self.assertTrue(s.refused("Alpha", 100, WHY))

    def test_a_done_use_clears_the_streak(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            s.refused("Alpha", 100, WHY)
        s.done("Alpha", 100)
        self.assertFalse(s.refused("Alpha", 100, WHY))

    def test_a_different_refusal_restarts_the_count(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            s.refused("Alpha", 100, WHY)
        self.assertFalse(s.refused("Alpha", 100, "the main-hand spell is on cooldown"))

    def test_members_and_quests_count_apart(self):
        s = classuse.RefusalStreaks()
        for _ in range(classuse.STREAK_LIMIT - 1):
            s.refused("Alpha", 100, WHY)
        self.assertFalse(s.refused("Beta", 100, WHY))
        self.assertFalse(s.refused("Alpha", 101, WHY))


if __name__ == "__main__":
    unittest.main()
