"""Quest 103 is broken: Keeper of the Flame.

This test fixture creates a quest row for quest 103 and verifies that it is
correctly loaded into the quest catalogue.
"""

import sys
import types
import unittest

sys.path.insert(0, "tests")
from _stub_modules import PYMYSQL, stub_modules

# Quest 103: Keeper of the Flame
# From the WoW database, this quest requires killing 10 Rage Scorpions in Westfall
QUEST103_ROW = {
    "quest": 103,
    "title": "Keeper of the Flame",
    "level": 16,
    "min_level": 16,
    "sort": 16,  # Westfall
    "races": 0,  # All races
    "classes": 0,  # All classes
    "follows": 0,
    "npc1": 2999,  # Rage Scorpion (negative in the database)
    "npc_count1": 10,
}


class TestQuest103(unittest.TestCase):
    def catalogue(self, row, givers, spawns, creature_names):
        """Create a quest catalogue from fixture rows."""
        import questcatalogue as qc

        qc.forget()

        def read(sql):
            if sql == qc.QUESTS_SQL:
                return [row]
            elif sql == qc.GIVERS_SQL:
                return givers
            elif sql == qc.CREATURE_NAMES_SQL:
                return creature_names
            elif sql == qc.SPAWN_COUNTS_SQL:
                return spawns
            return []

        return qc.load(read)

    def test_quest103_is_in_the_catalogue(self):
        """Quest 103 should be in the catalogue and have the correct details."""
        # Givers are in Westfall (map 0 is the world, but quests are zone-based)
        givers = [
            {"quest": 103, "role": "start", "map_id": 0},
            {"quest": 103, "role": "end", "map_id": 0},
        ]

        # Rage Scorpion spawns in Westfall
        spawns = [
            {"entry": 2999, "zone": 16, "n": 5},  # Westfall
        ]

        creature_names = [
            {"entry": 2999, "name": "Rage Scorpion"},
        ]

        catalogue = self.catalogue(QUEST103_ROW, givers, spawns, creature_names)

        # Verify the quest is in the catalogue
        self.assertEqual(len(catalogue), 1)
        q = catalogue[0]

        # Check the basic quest details
        self.assertEqual(q.id, 103)
        self.assertEqual(q.title, "Keeper of the Flame")
        self.assertEqual(q.level, 16)
        self.assertEqual(q.min_level, 16)
        self.assertEqual(q.zone, 16)  # Westfall
        self.assertEqual(q.zone_name, "Westfall")
        self.assertEqual(q.faction, "both")
        self.assertEqual(q.races, 0)
        self.assertEqual(q.classes, 0)
        self.assertEqual(q.follows, 0)

        # Check the objective
        self.assertEqual(len(q.objectives), 1)
        obj = q.objectives[0]
        self.assertEqual(obj["entry"], 2999)
        self.assertEqual(obj["count"], 10)
        self.assertEqual(obj["name"], "Rage Scorpion")
        self.assertEqual(obj["kind"], "creature")
        self.assertEqual(obj["zone_count"], 5)  # Spawns in Westfall
        self.assertEqual(obj["total_count"], 5)

        # Verify that selecting by zone returns the quest
        by_zone = questcatalogue.select(catalogue, zone=16)
        self.assertEqual(len(by_zone), 1)
        self.assertEqual(by_zone[0].id, 103)

    def test_quest103_objective_counts_are_correct(self):
        """Verify that quest 103 shows the correct objective counts."""
        from _stub_modules import PYMYSQL, stub_modules

        with stub_modules(pymysql=PYMYSQL):
            import questcatalogue as qc

            qc.forget()

            def read(sql):
                if sql == qc.QUESTS_SQL:
                    return [QUEST103_ROW]
                elif sql == qc.GIVERS_SQL:
                    return [
                        {"quest": 103, "role": "start", "map_id": 0},
                        {"quest": 103, "role": "end", "map_id": 0},
                    ]
                elif sql == qc.CREATURE_NAMES_SQL:
                    return [{"entry": 2999, "name": "Rage Scorpion"}]
                elif sql == qc.SPAWN_COUNTS_SQL:
                    return [
                        {"entry": 2999, "zone": 16, "n": 5},
                        {"entry": 2999, "zone": 17, "n": 3},  # Other zone
                    ]
                return []

            catalogue = qc.load(read)
            q = catalogue[0]

            # Check the objective has the correct spawn counts
            obj = q.objectives[0]
            self.assertEqual(obj["zone_count"], 5)  # Only in Westfall
            self.assertEqual(obj["total_count"], 8)  # Across all zones


if __name__ == "__main__":
    unittest.main()
