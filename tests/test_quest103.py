"""Quest 103 is broken: Keeper of the Flame.

The world rows are the AzerothCore / Wrath rows for this quest, read
from the public databases, not invented: quest_template 103 is level
16, MinLevel 10, QuestSortID 40 (Westfall), AllowableRaces and
AllowableClasses 0, RequiredItemId1 814 (Flask of Oil) with count 5 and
no RequiredNpcOrGo; creature_queststarter and creature_questender name
Captain Grayson (392), who has a spawn on map 0 in Westfall; item 814
drops from Harvest Golem (36), Harvest Watcher (114), Harvest Reaper
(115) and Rusty Harvest Golem (480), all spawned in Westfall. A
quester holding this quest therefore has a creature to hunt for its
item, and the catalogue must carry that item with those droppers.
"""

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import questcatalogue as qc  # noqa: E402

QUEST103_ROW = {
    "quest": 103,
    "title": "Keeper of the Flame",
    "level": 16,
    "min_level": 10,
    "sort": 40,
    "races": 0,
    "classes": 0,
    "follows": 0,
    "provided_item": 0,
    "item1": 814,
    "item_count1": 5,
    "item2": 0,
    "item_count2": 0,
    "item3": 0,
    "item_count3": 0,
    "item4": 0,
    "item_count4": 0,
    "item5": 0,
    "item_count5": 0,
    "item6": 0,
    "item_count6": 0,
    "objective1": 0,
    "objective_count1": 0,
    "objective2": 0,
    "objective_count2": 0,
    "objective3": 0,
    "objective_count3": 0,
    "objective4": 0,
    "objective_count4": 0,
}

GIVERS = [
    {"quest": 103, "role": "start", "map_id": 0},
    {"quest": 103, "role": "end", "map_id": 0},
]

ITEM_NAMES = [{"entry": 814, "name": "Flask of Oil"}]

DROPS = [
    {"item": 814, "entry": 36},
    {"item": 814, "entry": 114},
    {"item": 814, "entry": 115},
    {"item": 814, "entry": 480},
]


def load_catalogue():
    qc.forget()

    def read(sql):
        if sql == qc.QUESTS_SQL:
            return [QUEST103_ROW]
        if sql == qc.GIVERS_SQL:
            return GIVERS
        if sql.startswith("SELECT entry, name FROM acore_world.item_template"):
            return ITEM_NAMES
        if sql == qc.DROP_SQL.format(ids="814"):
            return DROPS
        return []

    return qc.load(read)


class TestQuest103(unittest.TestCase):
    def tearDown(self):
        qc.forget()

    def test_quest103_is_in_the_catalogue_with_its_item(self):
        catalogue = load_catalogue()
        self.assertEqual(len(catalogue), 1)
        q = catalogue[0]
        self.assertEqual(q.id, 103)
        self.assertEqual(q.title, "Keeper of the Flame")
        self.assertEqual(q.level, 16)
        self.assertEqual(q.min_level, 10)
        self.assertEqual(q.zone, 40)
        self.assertEqual(q.zone_name, "Westfall")
        self.assertEqual(q.faction, "both")
        self.assertEqual(q.races, 0)
        self.assertEqual(q.classes, 0)
        self.assertEqual(q.follows, 0)
        self.assertEqual(q.objectives, ())
        self.assertEqual(len(q.items), 1)
        item = q.items[0]
        self.assertEqual(item["id"], 814)
        self.assertEqual(item["count"], 5)
        self.assertEqual(item["name"], "Flask of Oil")
        self.assertEqual(item["droppers"], [36, 114, 115, 480])
        by_zone = qc.select(catalogue, zone=40)
        self.assertEqual([x.id for x in by_zone], [103])


if __name__ == "__main__":
    unittest.main()
