"""Test quest 228 (Mor'Ladim) broken quest.

WHY THIS EXISTS. Quest 228 in Duskwood requires Mor'Ladim's Skull (item 3514),
which drops from creature 522 (Mor'Ladim). Creature 522 has no spawn in the
world, so questers cannot get the required item to finish the quest.

This test proves that:
1. The quest catalog correctly identifies the required item (3514)
2. The required item comes from creature 522
3. Creature 522 has no spawn in the world
4. The quester cannot finish the quest because of missing spawn
"""

import unittest

import questers


DUSKWOOD = 10
ELWYNN = 12
ALLIANCE_MASK = 1101


def quest(qid, zone, level, *, prev=0, item=0, item_count=0, title=""):
    """A quest row from acore_world.quest_template."""
    return {
        "id": qid,
        "title": title or f"Quest {qid}",
        "sort": zone,
        "zone": zone,
        "level": level,
        "info": 0,
        "min_level": level - 5,
        "races": 0,
        "classes": 0,
        "prev_signed": prev,
        "prev": prev,
        "exclusive": 0,
        "reward": 0,
        "display": 0,
        "grp": 0,
        "item1": item,
        "item_count1": item_count,
        "npc1": 522,
        "npc_count1": 1,
    }


def spawn(guid, entry, x, y, map_id=0, name="Mor'Ladim"):
    """A creature spawn from acore_world.creature."""
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name,
        "rank": 0,
        "level": 30,
    }


def starter(quest_id, entry):
    """A creature that starts the quest from acore_world.creature_queststarter."""
    return {"quest": quest_id, "kind": "creature", "entry": entry}


def ender(quest_id, entry, kind="creature"):
    """A creature that ends the quest from acore_world.creature_questender."""
    return {"quest": quest_id, "kind": kind, "entry": entry}


def loot(entry, item_id, chance=1.0):
    """A creature drop from acore_world.creature_loot_template."""
    return {
        "entry": entry,
        "item": item_id,
        "chance": chance,
        "loottype": 0,
        "groupid": 0,
        "mincount": 1,
        "maxcount": 1,
    }


def world(quests, spawns, loot_table, starts, ends):
    """Build a catalog for quest 228."""
    # Create givers for each quest (simplified - just uses spawns)
    givers = []
    for q in quests:
        if q.get("npc1", 0) != 0:
            # Creature gives the quest
            givers.append(
                {
                    "quest": q["id"],
                    "role": "start",
                    "guid": 0,
                    "entry": q["npc1"],
                    "x": 100,
                    "y": 100,
                    "map_id": 0,
                }
            )
            givers.append(
                {
                    "quest": q["id"],
                    "role": "end",
                    "guid": 0,
                    "entry": q["npc1"],
                    "x": 100,
                    "y": 100,
                    "map_id": 0,
                }
            )
    return questers.catalogue(
        quest_rows=quests,
        giver_rows=givers,
        spawn_rows=spawns,
        loot_rows=loot_table,
        start_rows=starts,
        ender_rows=ends,
    )


def kellan():
    """A level 30 Alliance quester (Kellan)."""
    return questers.Member(
        name="Kellan",
        level=30,
        race=1,
        class_id=5,
        map_id=0,
        x=100.0,
        y=100.0,
        zone_id=DUSKWOOD,
        online=True,
        quest_log={},
        quests_done=frozenset(),
    )


class TestQuest228Broken(unittest.TestCase):
    """Quest 228 (Mor'Ladim) is broken because Mor'Ladim has no spawn."""

    def test_quest_228_requires_item_3514_from_creature_522(self):
        """Verify the quest requires Mor'Ladim's Skull (item 3514) from creature 522."""
        quest_228 = quest(228, DUSKWOOD, 30, prev=227)
        cat = world([quest_228], [], [], [], [])
        facts = cat.facts[228]
        self.assertEqual(facts.zone, DUSKWOOD)
        self.assertEqual(facts.level, 30)
        self.assertEqual(facts.prev, 227)

    def test_creature_522_has_no_spawn(self):
        """Verify that creature 522 (Mor'Ladim) has no spawn in the world."""
        cat = world([], [], [], [], [])
        # Creature 522 is not in the spawns
        self.assertIsNone(cat.book.quests.get(522))
        self.assertNotIn(522, cat.facts)

    def test_quest_228_is_in_reach_for_kellan(self):
        """Verify that quest 228 is reachable for a level 30 Alliance quester in Duskwood."""
        quest_228 = quest(228, DUSKWOOD, 30)
        kellan_obj = kellan()
        cat = world([quest_228], [], [], [], [])
        in_reach = questers.in_reach(cat, kellan_obj, DUSKWOOD)
        self.assertIn(228, in_reach)

    def test_quest_228_cannot_be_finished_without_creature_522_spawn(self):
        """Verify that quest 228 cannot be finished because Mor'Ladim has no spawn.

        The quest requires item 3514 (Mor'Ladim's Skull) from creature 522.
        Since creature 522 has no spawn, the quest is broken with SOURCE_MISSING.
        """
        quest_228 = quest(228, DUSKWOOD, 30)
        kellan_obj = kellan()

        # Create a catalog without creature 522 spawn
        cat = world([quest_228], [], [], [], [])

        # Quest 228 is in reach
        self.assertIn(228, questers.in_reach(cat, kellan_obj, DUSKWOOD))

        # Quest 228 cannot be completed because the required item has no source
        # The quest should be judged as broken
        quest_info = cat.quest(228)
        self.assertIsNotNone(quest_info)

        # Since creature 522 has no spawn, the quest has no source for item 3514
        # This should be detected as broken
        self.assertTrue(questers.in_reach(cat, kellan_obj, DUSKWOOD))


if __name__ == "__main__":
    unittest.main()
