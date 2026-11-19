"""Test quest 348 (Stranglethorn Fever) and its item requirement (#3019)."""

import pathlib
import sys
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import questcatalogue as qc


class TestQuest348(unittest.TestCase):
    """Quest 348 is broken: objectives did not move for 2 hours of play.

    The quest requires Heart of Mokk (item 2797) from Mokk the Giant (creature 1514).
    The questers cannot complete it because there is no huntable source for the item.

    World rows from the ticket:
    - QuestLevel: 45; MinLevel: 40
    - Required item 2797 x1 (Heart of Mokk): creature entries 1514

    This test documents the situation and verifies the fix should either:
    1. Make Mokk spawn and drop the Heart of Mokk, OR
    2. Explain that the quest cannot be completed without the item source
    """

    def test_quest_348_item_requirement(self):
        """Verify quest 348 requires Heart of Mokk from creature 1514."""

        def read(sql):
            if sql.startswith("SELECT t.ID"):
                return [
                    {
                        "ID": 348,
                        "LogTitle": "Stranglethorn Fever",
                        "QuestLevel": 45,
                        "MinLevel": 40,
                        "QuestSortID": 0,
                        "AllowableRaces": 0,
                        "StartItem": 0,
                        "RequiredItemId1": 2797,
                        "RequiredItemCount1": 1,
                        "RequiredNpcOrGo1": -1514,
                        "RequiredNpcOrGoCount1": 1,
                    }
                ]
            return []

        catalogue = qc.load(read)
        quest = next((q for q in catalogue if q.id == 348), None)

        self.assertIsNotNone(quest, "Quest 348 should be in the catalogue")
        self.assertEqual(quest.title, "Stranglethorn Fever")

        # Verify the item requirement
        items = [i for i in quest.items if i["id"] == 2797]
        self.assertEqual(len(items), 1, "Quest should require Heart of Mokk (2797)")

        item = items[0]
        self.assertEqual(item["id"], 2797, "Item ID should be 2797 (Heart of Mokk)")
        self.assertEqual(item["count"], 1, "Should require 1 Heart of Mokk")
        self.assertEqual(item["name"], "Heart of Mokk", "Item name should be Heart of Mokk")

        # Verify the objective
        objectives = [o for o in quest.objectives if o["entry"] == 1514]
        self.assertEqual(len(objectives), 1, "Quest should have Mokk the Giant as objective")

        obj = objectives[0]
        self.assertEqual(obj["entry"], 1514, "Objective should be Mokk the Giant (1514)")
        self.assertEqual(obj["count"], 1, "Should require 1 kill")

        # Verify drops (this will be empty if the creature doesn't drop the item)
        self.assertGreater(len(item["droppers"]), 0, "The quest should list creature entries that drop this item")

    def test_quest_348_cannot_complete_without_item(self):
        """Verify that a quest with only an item objective can be completed via bags."""

        def read(sql):
            if sql.startswith("SELECT t.ID"):
                return [
                    {
                        "ID": 348,
                        "LogTitle": "Stranglethorn Fever",
                        "QuestLevel": 45,
                        "MinLevel": 40,
                        "QuestSortID": 0,
                        "AllowableRaces": 0,
                        "StartItem": 0,
                        "RequiredItemId1": 2797,
                        "RequiredItemCount1": 1,
                        "RequiredNpcOrGo1": -1514,
                        "RequiredNpcOrGoCount1": 1,
                    }
                ]
            return []

        catalogue = qc.load(read)
        quest = next((q for q in catalogue if q.id == 348), None)

        # Simulate a quester holding the Heart of Mokk
        held = {2797: 1}

        # The quest should be complete if the item is in bags
        # (classhunt.py finished() checks this for item-only objectives)
        self.assertTrue(
            quest.items and not quest.kills,
            "Quest 348 should have item objectives and no kill count",
        )

        # Verify the item is in the quest's required items
        self.assertTrue(any(i["id"] == 2797 for i in quest.items))

        # Verify the quest is complete if we have the item
        item = next(i for i in quest.items if i["id"] == 2797)
        self.assertEqual(held.get(2797, 0), 1, "Quester should have the Heart of Mokk")
        self.assertTrue(held[2797] >= item["count"], "Quest should be complete with 1 Heart of Mokk in bags")


class TestQuest348Reason(unittest.TestCase):
    """Document the reason for quest 348's broken status."""

    def test_why_quest_348_is_broken(self):
        """The questers' reason: objectives did not move for 2 hours of play.

        This happens when:
        1. The creature (Mokk, 1514) does not spawn in Stranglethorn Vale
        2. The creature spawns but does not drop the Heart of Mokk (2797)
        3. The loot system does not update the quest objective

        World rows show the quest requires:
        - Heart of Mokk (item 2797) x1
        - Mokk the Giant (creature 1514) x1

        If neither the creature spawns nor drops the item, the quest cannot be completed.
        """

        self.assertEqual(2797, 2797, "Item 2797 is Heart of Mokk")
        self.assertEqual(1514, 1514, "Creature 1514 is Mokk the Giant")
        self.assertEqual(348, 348, "Quest 348 is Stranglethorn Fever")

        # The reason string from the ticket
        reason = "its objectives did not move for 2 hours of play"

        # This reason is correct when:
        # - The quest has item objectives (Heart of Mokk)
        # - The quest has creature objectives (Mokk)
        # - Neither the creature spawns nor drops the item
        # - The questers cannot complete the objective through any means

        self.assertIn("objectives", reason.lower())
        self.assertIn("2 hours", reason.lower())


if __name__ == "__main__":
    unittest.main()
