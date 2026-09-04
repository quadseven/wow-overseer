import unittest

import dungeon_plan


class DungeonPlanTests(unittest.TestCase):
    def setUp(self):
        self.family = [{"name": "Grug", "class": "WARRIOR", "role": "tank",
                        "equipped": {"weapon": 18}, "carried": []},
                       {"name": "Ugga", "class": "PRIEST", "role": "healer",
                        "equipped": {"weapon": 12}, "carried": []}]
        self.loot = [{"entry": 100, "name": "Tank Axe", "quality": 3,
                      "item_level": 25, "slot": "weapon", "roles": ["tank"]},
                     {"entry": 101, "name": "Healer Wand", "quality": 3,
                      "item_level": 24, "slot": "weapon", "roles": ["healer"]}]

    def test_items_name_only_real_family_upgrades(self):
        targets = dungeon_plan.item_targets(self.loot, self.family)
        self.assertEqual([row["name"] for row in targets], ["Tank Axe", "Healer Wand"])
        self.assertEqual(targets[0]["targets"][0]["name"], "Grug")

    def test_owned_item_is_not_recommended_again(self):
        self.family[0]["carried"] = [{"entry": 100}]
        self.assertEqual(len(dungeon_plan.item_targets(self.loot, self.family)), 1)

    def test_challenge_mode_is_bounded(self):
        dungeon = {"map_id": 36, "name": "Deadmines", "level": 24}
        self.assertTrue(dungeon_plan.challenge_for(21, dungeon, dungeon_plan.CHALLENGE)["eligible"])
        self.assertFalse(dungeon_plan.challenge_for(21, dungeon, dungeon_plan.SAFE)["eligible"])

    def test_next_skips_completed_and_unsafe(self):
        dungeons = [{"map_id": 1, "name": "Too hard", "level": 30, "order": 1},
                    {"map_id": 2, "name": "Next", "level": 21, "order": 2}]
        result = dungeon_plan.recommend_next(dungeons, 21, {1}, dungeon_plan.SAFE)
        self.assertEqual(result["map_id"], 2)

    def test_next_never_recommends_catalogued_but_unrunnable_dungeon(self):
        dungeons = [{"map_id": 389, "name": "Ragefire Chasm", "level": 15,
                     "order": 1, "runnable": False},
                    {"map_id": 36, "name": "The Deadmines", "level": 20,
                     "order": 2, "runnable": True}]
        result = dungeon_plan.recommend_next(dungeons, 20, set())
        self.assertEqual(result["map_id"], 36)

    def test_catalog_marks_unimplemented_portals_without_calling_them_ready(self):
        payload = dungeon_plan.build_payload([{"name": "Grug", "level": 20}], set())
        ragefire = next(row for row in payload["dungeons"] if row["map_id"] == 389)
        deadmines = next(row for row in payload["dungeons"] if row["map_id"] == 36)
        self.assertFalse(ragefire["runnable"])
        self.assertEqual(ragefire["availability"],
                         "catalogued; portal and traversal not implemented")
        self.assertTrue(deadmines["runnable"])

    def test_payload_is_honest_about_missing_loot(self):
        payload = dungeon_plan.build_payload([{"name": "Grug", "level": 20}], set())
        self.assertEqual(payload["next"]["map_id"], 36)
        self.assertEqual(payload["dungeons"][0]["loot"], [])
        self.assertIn("verified", payload["loot_status"])


if __name__ == "__main__":
    unittest.main()
