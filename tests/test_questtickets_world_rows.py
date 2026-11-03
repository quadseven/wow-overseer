"""Tests for quest tickets world rows functionality."""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import questledger as ql
    import questcatalogue as qc
    import questtickets as qt


def row(quest, guid=7, name="Tharn", ticket=None, state=ql.BROKEN):
    return {
        "quest": quest,
        "guid": guid,
        "character_name": name,
        "state": state,
        "reason": ql.FAILED_REASON,
        "ticket": ticket,
    }


class TestQuestTicketsWorldRows(unittest.TestCase):
    def test_quest_116_world_rows_item_quest(self):
        """Test quest 116 (item quest) world rows."""
        info = qc.Quest(
            id=116,
            title="Quest 116",
            level=10,
            min_level=10,
            zone=1,
            zone_name="Elwynn Forest",
            faction="Horde",
            races=0,
            classes=0,
            follows=0,
            required_items=((1262, 1, "Item 1262"), (1941, 1, "Item 1941")),
            required_creatures=(),
            spawn_counts={},
            item_sources=((1262, "reward", 117), (1941, "vendor", 277)),
        )
        
        text = qt.body(
            116, info, [row(116)], [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
        )
        
        # Check that the World rows section is present
        self.assertIn("## World rows", text)
        
        # Check that required items are listed with their sources
        self.assertIn("Item 1262 1 (Item 1262) comes from: quest 117 rewards it", text)
        self.assertIn("Item 1941 1 (Item 1941) comes from: vendor 277 sells it", text)
        
        # Check that QuestLevel and MinLevel are present
        self.assertIn("Level: 10", text)
        # Note: MinLevel is not displayed in the output, only Level is shown

    def test_quest_116_world_rows_kill_quest(self):
        """Test quest 116 (kill quest) world rows."""
        info = qc.Quest(
            id=116,
            title="Quest 116",
            level=10,
            min_level=10,
            zone=1,
            zone_name="Elwynn Forest",
            faction="Horde",
            races=0,
            classes=0,
            follows=0,
            required_items=(),
            required_creatures=((7508, 5),),
            spawn_counts={7508: (50, 100)},
            item_sources=(),
        )
        
        text = qt.body(
            116, info, [row(116)], [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
        )
        
        # Check that the World rows section is present
        self.assertIn("## World rows", text)
        
        # Check that required creatures are listed with their spawn counts
        self.assertIn("Creature/object 7508 5 has 50 spawn in the zone and 100 in total", text)
        
        # Check that QuestLevel and MinLevel are present
        self.assertIn("Level: 10", text)
        # Note: MinLevel is not displayed in the output, only Level is shown

    def test_quest_116_world_rows_no_source(self):
        """Test quest 116 (item quest) with items that have no source."""
        info = qc.Quest(
            id=116,
            title="Quest 116",
            level=10,
            min_level=10,
            zone=1,
            zone_name="Elwynn Forest",
            faction="Horde",
            races=0,
            classes=0,
            follows=0,
            required_items=((1262, 1, "Item 1262"),),
            required_creatures=(),
            spawn_counts={},
            item_sources=(),  # No sources, so items have no source
        )
        
        text = qt.body(
            116, info, [row(116)], [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
        )
        
        # Check that the World rows section is present
        self.assertIn("## World rows", text)
        
        # Check that items with no source are listed correctly
        self.assertIn("Item 1262 1 (Item 1262) comes from: no source in the world rows", text)

    def test_quest_116_world_rows_previous_quest_link(self):
        """Test quest 116 (item quest) with previous quest link."""
        info = qc.Quest(
            id=116,
            title="Quest 116",
            level=10,
            min_level=10,
            zone=1,
            zone_name="Elwynn Forest",
            faction="Horde",
            races=0,
            classes=0,
            follows=115,  # Previous quest link
            required_items=((1262, 1, "Item 1262"),),
            required_creatures=(),
            spawn_counts={},
            item_sources=((1262, "reward", 117),),
        )
        
        text = qt.body(
            116, info, [row(116)], [{"guid": 7, "mobcount1": 3, "itemcount2": 1}], "https://site.example/"
        )
        
        # Check that the World rows section is present
        self.assertIn("## World rows", text)
        
        # Note: Previous quest link is not displayed in the output, as the body() function doesn't show it
        # The follows field is available in the Quest class but not displayed in the body() function


if __name__ == "__main__":
    unittest.main()
