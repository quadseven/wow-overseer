"""The death knight is a class the class quest book reads (2026-10-08).

Cave's Brug is a level 60 death knight stranded in the death knight starting
zone with one chain quest done and no class quest step at all: the book knew the
nine classic classes and nothing above level 45. The starting chain is the one
death knight range it reads (QuestSortID -372, AllowableClasses 32, level 55).
"""

import unittest

import classquest


class TheDeathKnightIsRead(unittest.TestCase):
    def test_a_quest_for_class_mask_32_is_the_death_knights(self):
        self.assertEqual(classquest.klass_of({"classes": 32, "sort": 0}), 6)

    def test_a_quest_in_the_death_knight_sort_is_the_death_knights(self):
        self.assertEqual(classquest.klass_of({"classes": 0, "sort": -372}), 6)

    def test_the_class_has_a_name_and_a_mask(self):
        self.assertEqual(classquest.CLASS_NAMES[6], "death knight")
        self.assertIn(32, classquest.SINGLE_CLASS_MASKS)

    def test_the_sql_reads_the_chain_past_the_classic_cap(self):
        sql = classquest.QUESTS_SQL
        self.assertIn("-372", sql)
        self.assertIn(
            "THEN %d ELSE %d END"
            % (classquest.MAX_DEATH_KNIGHT_QUEST_LEVEL, classquest.MAX_QUEST_LEVEL),
            sql,
        )

    def test_a_level_55_death_knight_quest_is_past_the_classic_cap(self):
        self.assertGreater(55, classquest.MAX_QUEST_LEVEL)
        self.assertGreaterEqual(classquest.MAX_DEATH_KNIGHT_QUEST_LEVEL, 55)


if __name__ == "__main__":
    unittest.main()
