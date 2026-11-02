"""Test that quest progress tracking SQL includes mobcount and itemcount.

READ AS TEXT, NOT IMPORTED. bridge.py imports discord, and this suite is
stdlib-only by design (see the module docstring) - the same reason
test_schema_degrade.py reads the C++ source rather than linking it.
"""

import pathlib
import unittest


class TestQuestProgressTracking(unittest.TestCase):
    """Verify that mobcount and itemcount are read from character_queststatus."""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            pathlib.Path(__file__).resolve().parent.parent / "bridge.py"
        ).read_text(encoding="utf-8")

    def _quest_sql(self):
        start = self.src.index("_QUEST_SQL = ")
        return self.src[start : self.src.index('"""', self.src.index('"""', start) + 3)]

    def _ledger_held_sql(self):
        start = self.src.index("_LEDGER_HELD_SQL = (")
        return self.src[start : self.src.index(chr(10) + ")", start)]

    def test_quest_sql_tracks_progress(self):
        """_QUEST_SQL must select mobcount and itemcount to track quest progress."""
        sql = self._quest_sql()

        # These fields are needed to calculate how much of an objective is complete
        self.assertIn("q.mobcount1", sql, "_QUEST_SQL missing mobcount1")
        self.assertIn("q.mobcount2", sql, "_QUEST_SQL missing mobcount2")
        self.assertIn("q.mobcount3", sql, "_QUEST_SQL missing mobcount3")
        self.assertIn("q.mobcount4", sql, "_QUEST_SQL missing mobcount4")
        self.assertIn("q.itemcount1", sql, "_QUEST_SQL missing itemcount1")
        self.assertIn("q.itemcount2", sql, "_QUEST_SQL missing itemcount2")
        self.assertIn("q.itemcount3", sql, "_QUEST_SQL missing itemcount3")
        self.assertIn("q.itemcount4", sql, "_QUEST_SQL missing itemcount4")

    def test_ledger_held_sql_tracks_progress(self):
        """_LEDGER_HELD_SQL must select mobcount and itemcount to track progress.

        This is the critical fix for the issue where quest 93 "Dusky Crab Cakes"
        in Duskwood had objectives that didn't move for 2 hours. The system
        wasn't tracking mobcount and itemcount at all, so quest progress appeared
        to never change even when questers were making progress on kills and
        item collection objectives.

        Quest 93 objectives: kill 10 Darkshire Wagtails (mobcount1) and
        collect 5 Dusky Crab Cakes (itemcount1). Without these fields, the
        council couldn't see progress and would incorrectly believe the quest
        was stuck.
        """
        sql = self._ledger_held_sql()

        # These fields are needed to track how much of an objective is complete
        self.assertIn("q.mobcount1", sql, "_LEDGER_HELD_SQL missing mobcount1")
        self.assertIn("q.mobcount2", sql, "_LEDGER_HELD_SQL missing mobcount2")
        self.assertIn("q.mobcount3", sql, "_LEDGER_HELD_SQL missing mobcount3")
        self.assertIn("q.mobcount4", sql, "_LEDGER_HELD_SQL missing mobcount4")
        self.assertIn("q.itemcount1", sql, "_LEDGER_HELD_SQL missing itemcount1")
        self.assertIn("q.itemcount2", sql, "_LEDGER_HELD_SQL missing itemcount2")
        self.assertIn("q.itemcount3", sql, "_LEDGER_HELD_SQL missing itemcount3")
        self.assertIn("q.itemcount4", sql, "_LEDGER_HELD_SQL missing itemcount4")

    def test_ledger_held_sql_filters_status(self):
        """_LEDGER_HELD_SQL must filter for active quests (status 1 or 3)."""
        sql = self._ledger_held_sql()

        # The same filter as _QUEST_SQL, which ensures consistent behavior
        self.assertIn(
            "q.status IN (1, 3)",
            sql,
            "an abandoned row must not read as a held quest",
        )

    def test_ledger_held_sql_joins_characters_table(self):
        """_LEDGER_HELD_SQL must join with characters for name lookups."""
        sql = self._ledger_held_sql()

        self.assertIn("JOIN characters c", sql)
        self.assertIn("c.guid = q.guid", sql)

    def test_ledger_held_sql_has_progress_on_quest_93(self):
        """The fix directly addresses quest 93 by adding progress tracking.

        Quest 93 "Dusky Crab Cakes" in Duskwood is a level 20 quest with:
        - Objective 1: Kill 10 Darkshire Wagtails (mobcount1)
        - Objective 2: Collect 5 Dusky Crab Cakes (itemcount1)

        With this fix, the council can now see:
        - "I need 5 more Darkshire Wagtails for Dusky Crab Cakes"
        - "I need 3 more Dusky Crab Cakes for Dusky Crab Cakes"

        Before this fix, these counts would show as "I need 10 more Darkshire
        Wagtails for Dusky Crab Cakes" and "I need 5 more Dusky Crab Cakes for
        Dusky Crab Cakes" forever, because mobcount1 and itemcount1 were not
        being read from character_queststatus.
        """
        sql = self._ledger_held_sql()

        # The fix adds the progress fields that make quest 93 trackable
        self.assertIn("q.mobcount1", sql, "quest 93's wagtail kills must be tracked")
        self.assertIn("q.itemcount1", sql, "quest 93's crab collection must be tracked")


if __name__ == "__main__":
    unittest.main()
