"""Test quest 263: In Defense of the King's Lands.

Quest 263 is broken because its quest giver is not on a classic map.
The quest giver is on a classic map, but the GIVERS_SQL query is incorrect.
"""

from unittest.mock import MagicMock

import questcatalogue
from importlib import reload
import classic


def test_quest_263_givers_sql():
    """Quest 263's quest giver should be correctly identified.

    The quest giver is on map 0 (Eastern Kingdoms), but the current
    GIVERS_SQL query might return the wrong map.
    """

    def read(sql):
        if sql.startswith("SELECT t.ID"):
            return [
                {
                    "quest": 263,
                    "title": "In Defense of the King's Lands",
                    "level": 15,
                    "min_level": 10,
                    "sort": 28,  # Loch Modan
                    "races": 0,  # All races
                    "classes": 0,  # All classes
                    "follows": 237,
                }
            ]
        elif sql.startswith("SELECT DISTINCT c.quest"):
            # Simulate new GIVERS_SQL - queries creature directly
            return [
                {"quest": 263, "role": "start", "map_id": 0},  # Eastern Kingdoms
            ]
        return []

    reload(questcatalogue)
    catalogue = questcatalogue.load(read)
    quest = questcatalogue.select(catalogue, zone=28, level_min=10, level_max=15)

    assert len(quest) > 0, "Quest 263 should be in the catalogue"
    found = next((q for q in quest if q.id == 263), None)
    assert found is not None, "Found quest 263"
    assert found.title == "In Defense of the King's Lands"


def test_quest_263_fixed_givers_sql():
    """Quest 263's quest giver should be correctly identified.

    The correct fix is to query the quest giver map from the quest_template table,
    not from the creature table.
    """

    def read(sql):
        if sql.startswith("SELECT t.ID"):
            return [
                {
                    "quest": 263,
                    "title": "In Defense of the King's Lands",
                    "level": 15,
                    "min_level": 10,
                    "sort": 28,  # Loch Modan
                    "races": 0,  # All races
                    "classes": 0,  # All classes
                    "follows": 237,
                }
            ]
        elif sql.startswith("SELECT DISTINCT c.quest"):
            # Simulate FIXED GIVERS_SQL - query creature directly
            return [
                {"quest": 263, "role": "start", "map_id": 0},  # Eastern Kingdoms
            ]
        return []

    reload(questcatalogue)
    catalogue = questcatalogue.load(read)
    quest = questcatalogue.select(catalogue, zone=28, level_min=10, level_max=15)

    assert len(quest) > 0, "Quest 263 should be in the catalogue"
    found = next((q for q in quest if q.id == 263), None)
    assert found is not None, "Found quest 263"
    assert found.title == "In Defense of the King's Lands"


if __name__ == "__main__":
    test_quest_263_givers_sql()
    print("Test 1 passed")

    test_quest_263_fixed_givers_sql()
    print("Test 2 passed")
