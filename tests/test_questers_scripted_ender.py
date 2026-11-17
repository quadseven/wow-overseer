"""A gameobject the core does not spawn by default takes no quest in.

Quest 310, Bitter Rivals, is handed in at gameobject 270. Its one spawn has
spawntimesecs -600, which the core loads as "not spawned by default"
(GameObject::LoadFromDB, m_spawnedByDefault = false): the object is in the
world only after a script respawns it, here Jarven Thunderbrew's waypoint
script after quest 308 is finished. Questers walked to the spawn, arrived,
and were refused "no object that takes that quest in reach" again and again.

ENDERS_SQL now carries each spawn's spawntimesecs, a spawn that is not spawned
by default is not a place to hand in at, and the quest is judged as one whose
object is summoned by a script (#1606): a complete quest is recorded broken
with the object's reason and not walked, an incomplete one is worked."""

import unittest

import classquest
import questers
from test_questers import mirra, object_ended, object_world


def scripted(qid=40, entry=270, guid=5001, x=300.0):
    """A gameobject ender row whose spawn is not spawned by default."""
    row = object_ended(qid, entry, guid=guid, x=x)
    row["spawn_time"] = -600
    return row


def standing(qid=40, entry=270, guid=5001, x=300.0):
    row = object_ended(qid, entry, guid=guid, x=x)
    row["spawn_time"] = 600
    return row


class ASpawnThatIsNotSpawnedByDefault(unittest.TestCase):
    def test_the_sql_reads_the_spawn_time(self):
        self.assertIn("spawntimesecs", questers.ENDERS_SQL)

    def test_a_complete_quest_is_not_walked_to_it_and_is_broken_with_the_reason(self):
        cat = object_world(scripted())
        p = questers.plan(cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0)
        self.assertEqual(
            [(b.quest, b.reason) for b in p.broken],
            [(40, questers.OBJECT_ENDER_MISSING)],
        )
        self.assertNotEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 40))
        self.assertNotEqual((p.move.kind, p.move.quest), (classquest.ABANDON, 40))

    def test_an_incomplete_quest_is_not_judged_on_the_object(self):
        cat = object_world(scripted())
        self.assertTrue(cat.facts[40].object_unspawned)
        self.assertEqual(cat.facts[40].object_enders, ())

    def test_a_spawn_with_a_positive_spawn_time_is_still_handed_in_at(self):
        cat = object_world(standing())
        p = questers.plan(cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0)
        self.assertEqual(p.broken, ())
        self.assertEqual((p.move.kind, p.move.quest), (classquest.TURN_IN, 40))
        self.assertFalse(cat.facts[40].object_unspawned)

    def test_a_row_without_a_spawn_time_reads_as_a_standing_spawn(self):
        cat = object_world(object_ended(40, 270, guid=5001, x=300.0))
        self.assertFalse(cat.facts[40].object_unspawned)
        self.assertEqual(len(cat.facts[40].object_enders), 1)

    def test_one_standing_spawn_among_scripted_ones_is_still_a_place(self):
        cat = object_world(scripted(guid=5001), standing(guid=5002, x=500.0))
        p = questers.plan(cat, mirra(quest_log={40: 1}), questers.Clock(), 0.0)
        self.assertEqual(p.broken, ())
        self.assertEqual(p.move.spot.guid, 5002)


if __name__ == "__main__":
    unittest.main()
