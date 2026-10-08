"""A death knight stranded in its starting zone is planned first (2026-10-08).

Cave's Brug, a level 60 death knight standing in the starting zone (map 609),
got no class step for half an hour after his quest was dropped, while 34 of
Cave's members owed a class quest: the scarce per-pass slots go first to tank
warriors and healers, then by level, and he was neither. He carries the guild's
hand-me-down gear, so he comes first.
"""

import unittest

import classquest
import guildjobs
from test_classquest_use import who

DK = 6


def knight(**over):
    base = dict(
        name="Brug",
        class_id=DK,
        level=60,
        map_id=classquest.DEATH_KNIGHT_START_MAP,
    )
    base.update(over)
    return who(**base)


class ThePriority(unittest.TestCase):
    def test_a_knight_in_its_starting_zone_is_first(self):
        self.assertEqual(guildjobs.class_priority(knight()), 0)

    def test_a_knight_already_out_is_ordinary(self):
        self.assertEqual(guildjobs.class_priority(knight(map_id=0)), 1)

    def test_a_knight_in_the_zone_is_planned_before_a_higher_level_member(self):
        other = who(name="Aaa", class_id=3, level=60)
        order = guildjobs._class_ordered([other, knight()], object())
        self.assertEqual([m.name for m in order], ["Brug", "Aaa"])


if __name__ == "__main__":
    unittest.main()
