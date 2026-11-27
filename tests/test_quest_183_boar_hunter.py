"""Test that quest 183 reports the correct reason when boars are not in its zone."""

import unittest
from unittest.mock import MagicMock

from questers import Broken, Catalogue, Facts, _off_home, _broken_reason, _fields_gone, _chested


class TestQuest183(unittest.TestCase):
    """Quest 183: The Boar Hunter"""

    def test_off_home_maps_spawns_on_different_map(self):
        """_off_home should report spawns that are not on the quest's home map."""
        facts = Facts(
            zone=1,
            level=3,
            home_map=0,
            classes=0,
            max_level=0,
            prev=0,
            giver_named=False,
            ender_npcs=False,
            ender_objects=False,
            object_enders=(),
            object_unspawned=False,
            before=(),
            provided_item=0,
            chain_next=0,
            chain_before=(),
            breadcrumb_for=0,
            breadcrumbs=(),
            min_rep=0,
            max_rep=0,
            scripted_event=False,
        )
        # Create a mock quest with spawns on a different map
        mock_quest = MagicMock(
            id=183,
            title="The Boar Hunter",
            kills=[(708, 12)],  # Kill 12 Small Crag Boar
            items=[],
            uses=[],
            fields=[
                MagicMock(entry=708, map_id=1, guid=1),  # Spawns on map 1
                MagicMock(entry=708, map_id=1, guid=2),
                MagicMock(entry=708, map_id=1, guid=3),
            ],
            enders=(),
            races=0,
            requirements=MagicMock(),
            chain_next=MagicMock(),
            next_quest=MagicMock(),
            exclusive=MagicMock(),
        )
        mock_quest.fields = mock_quest.fields
        mock_quest.uses = []

        # All spawns are on map 1, but home_map is 0, so they're off home
        out = _off_home(mock_quest, facts)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0], (708, 3))  # 3 spawns reported as off home

    def test_off_home_maps_spawns_on_same_map(self):
        """_off_home should not report spawns that are on the quest's home map."""
        facts = Facts(
            zone=1,
            level=3,
            home_map=1,  # Same map as spawns
            classes=0,
            max_level=0,
            prev=0,
            giver_named=False,
            ender_npcs=False,
            ender_objects=False,
            object_enders=(),
            object_unspawned=False,
            before=(),
            provided_item=0,
            chain_next=0,
            chain_before=(),
            breadcrumb_for=0,
            breadcrumbs=(),
            min_rep=0,
            max_rep=0,
            scripted_event=False,
        )
        # Create a mock quest with spawns on the same map
        mock_quest = MagicMock(
            id=183,
            title="The Boar Hunter",
            kills=[(708, 12)],
            items=[],
            uses=[],
            fields=[
                MagicMock(entry=708, map_id=1, guid=1),  # Spawns on map 1
                MagicMock(entry=708, map_id=1, guid=2),
                MagicMock(entry=708, map_id=1, guid=3),
            ],
            enders=(),
            races=0,
            requirements=MagicMock(),
            chain_next=MagicMock(),
            next_quest=MagicMock(),
            exclusive=MagicMock(),
        )
        mock_quest.fields = mock_quest.fields
        mock_quest.uses = []

        # All spawns are on map 1, and home_map is also 1
        out = _off_home(mock_quest, facts)
        self.assertEqual(len(out), 0)  # No spawns off home

    def test_fields_gone(self):
        """_fields_gone should return True when all spawns are marked as gone."""
        mock_quest = MagicMock(
            id=183,
            title="The Boar Hunter",
            kills=[(708, 12)],
            items=[],
            uses=[],
            fields=[
                MagicMock(entry=708, map_id=1, guid=1),
                MagicMock(entry=708, map_id=1, guid=2),
                MagicMock(entry=708, map_id=1, guid=3),
            ],
            enders=(),
            races=0,
            requirements=MagicMock(),
            chain_next=MagicMock(),
            next_quest=MagicMock(),
            exclusive=MagicMock(),
        )
        mock_quest.fields = mock_quest.fields
        mock_quest.uses = []

        gone = {1, 2, 3}
        result = _fields_gone(mock_quest, gone)
        self.assertTrue(result)

    def test_not_fields_gone(self):
        """_fields_gone should return False when not all spawns are gone."""
        mock_quest = MagicMock(
            id=183,
            title="The Boar Hunter",
            kills=[(708, 12)],
            items=[],
            uses=[],
            fields=[
                MagicMock(entry=708, map_id=1, guid=1),
                MagicMock(entry=708, map_id=1, guid=2),
                MagicMock(entry=708, map_id=1, guid=3),
            ],
            enders=(),
            races=0,
            requirements=MagicMock(),
            chain_next=MagicMock(),
            next_quest=MagicMock(),
            exclusive=MagicMock(),
        )
        mock_quest.fields = mock_quest.fields
        mock_quest.uses = []

        gone = {1}
        result = _fields_gone(mock_quest, gone)
        self.assertFalse(result)

    def test_chested_quest(self):
        """_chested should return True for quests with chest objectives."""
        mock_quest = MagicMock(
            id=183,
            title="The Boar Hunter",
            kills=[(708, 12)],
            items=[],
            uses=[
                MagicMock(
                    verb="use-gameobject",
                    item=1,
                    spots=[MagicMock(guid=1)],
                )
            ],
            fields=[],
            enders=(),
            chest=None,
            races=0,
            requirements=MagicMock(),
            chain_next=MagicMock(),
            next_quest=MagicMock(),
            exclusive=MagicMock(),
        )
        mock_quest.fields = mock_quest.fields
        mock_quest.uses = mock_quest.uses

        result = _chested(mock_quest)
        self.assertTrue(result)

    def test_no_chest(self):
        """_chested should return False for quests without chests."""
        mock_quest = MagicMock(
            id=183,
            title="The Boar Hunter",
            kills=[(708, 12)],
            items=[],
            uses=[],
            fields=[],
            enders=(),
            chest=None,
            races=0,
            requirements=MagicMock(),
            chain_next=MagicMock(),
            next_quest=MagicMock(),
            exclusive=MagicMock(),
        )
        mock_quest.fields = mock_quest.fields
        mock_quest.uses = []

        result = _chested(mock_quest)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
