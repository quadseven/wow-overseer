"""Test for quest 179 (Dwarven Outfitters) item-based stall tracking.

Quest 179 requires Tough Wolf Meat (item 750) from creatures 704, 705.
When a quest has only items (no creatures to hunt), it should still be
tracked by the stall clock and marked as broken after STALL_SECONDS if
its objectives don't move.
"""

import unittest
import questers
import classquest


def member(**kw):
    """Create a test quester member."""
    base = dict(
        name="Mirra",
        level=5,
        race=1,  # Human
        class_id=5,  # Priest
        map_id=0,
        x=0.0,
        y=0.0,
        zone_id=10,  # Elwynn Forest
        online=True,
        alive=True,
    )
    base.update(kw)
    return questers.Member(**base)


def world():
    """Create a minimal world for testing."""
    return {}


def cat():
    """Create a minimal catalogue for testing with facts."""
    return questers.Catalogue(
        book=classquest.Book({}),
        facts={
            179: questers.Facts(
                zone=10,
                level=5,
                classes=0,
                ender_npcs=True,
                ender_objects=False,
            )
        },
        bands={},
        hostile={},
    )


class TestQuest179(unittest.TestCase):
    """Quest 179 (Dwarven Outfitters) - item-only quest."""

    def test_quest_179_has_items_no_creatures(self):
        """Quest 179 is an item-only quest with no creature fields."""
        quest = classquest.Quest(
            179,
            "Dwarven Outfitters",
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            items=(750,),
        )
        self.assertEqual(quest.items, (750,))
        self.assertEqual(quest.kills, ())
        self.assertEqual(quest.fields, ())

    def test_item_only_quest_unhuntable(self):
        """Item-only quests are unhuntable (no fields to hunt)."""
        quest = classquest.Quest(
            179,
            "Dwarven Outfitters",
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            items=(750,),
        )
        member_instance = member(level=5, x=0, quest_log={179: 1})
        unhuntable = questers._unhuntable(cat(), member_instance, 179)
        self.assertTrue(unhuntable)

    def test_item_only_quest_in_working_set(self):
        """Item-only quests should be in the working set when in zone."""
        quest = classquest.Quest(
            179,
            "Dwarven Outfitters",
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            items=(750,),
        )
        member_instance = member(level=5, x=0, quest_log={179: 1})
        working = questers._working(cat(), member_instance)
        self.assertIn(179, working)

    def test_item_only_quest_stalled_after_2_hours(self):
        """Item-only quests should stall after 2 hours of play."""
        quest = classquest.Quest(
            179,
            "Dwarven Outfitters",
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            items=(750,),
        )
        member_instance = member(level=5, x=0, quest_log={179: 1})

        clock = questers.Clock()
        now = 1234567890.0

        # Simulate 2 hours of play (7200 seconds) by observing increasing progress
        # Start with 0 items, increase by 1 each time
        played = 0
        for i in range(8):  # Increase progress to 8
            played += clock.observe("Mirra", 179, (1, i), now, True)

        facts = questers.Facts(zone=10, level=5, classes=0, ender_npcs=True, ender_objects=False)
        reason = questers._broken_reason(
            quest, facts, 1, played, frozenset(), {}, final=None
        )

        # Should be stalled, not STALLED_UNSOURCED
        self.assertEqual(reason, questers.STALLED)

    def test_item_only_quest_not_stalled_before_2_hours(self):
        """Item-only quests should not stall before 2 hours of play."""
        quest = classquest.Quest(
            179,
            "Dwarven Outfitters",
            1,
            1,
            0,
            0,
            0,
            0,
            0,
            items=(750,),
        )
        member_instance = member(level=5, x=0, quest_log={179: 1})

        clock = questers.Clock()
        now = 1234567890.0

        # Simulate 1 hour of play (3600 seconds) by observing increasing progress
        played = 0
        for i in range(4):  # Increase progress to 4
            played += clock.observe("Mirra", 179, (1, i), now, True)

        facts = questers.Facts(zone=10, level=5, classes=0, ender_npcs=True, ender_objects=False)
        reason = questers._broken_reason(
            quest, facts, 1, played, frozenset(), {}, final=None
        )

        # Should not be stalled yet
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
