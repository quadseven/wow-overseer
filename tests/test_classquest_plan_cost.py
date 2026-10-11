"""The guild job plan must not hold the event loop (2026-10-11).

Eight minutes after a bridge restart the gateway logged "heartbeat blocked for
more than 10/20/30/40 seconds" while the pass planned its 142 members. The
loop thread stood in guildjobs.owed_members -> class_owed -> class_avoid ->
classquest.roll_oldest -> all_tried -> _densest, whose pack count is quadratic
in a creature's spawns, run per marked quest per member, twice a member. These
tests hold the call counts, not the clock: a young mark never scans a quest's
spawns, all_tried never counts packs, and the book-wide tables are built once
per book, not once per member.
"""

import unittest
from unittest import mock

import classquest
import guildjobs
from test_classquest import KALIMDOR, book, qrow, who, givers, LIZARD, HIDE


def packs(n):
    """n spawns of one creature on Kalimdor, 100 yards apart (one pack each)."""
    return [
        dict(LIZARD, guid=9000 + i, x=500.0 + 100 * i, y=-4000.0) for i in range(n)
    ]


def spread_book(n=6):
    return book(spawn_rows=packs(n) + [HIDE])


class TheAllTried(unittest.TestCase):
    def quest(self):
        return spread_book().quests[1498]

    def test_it_never_counts_packs(self):
        m = who(quest_log={1498: 3})
        with mock.patch.object(classquest, "_densest", side_effect=AssertionError):
            classquest.all_tried(m, self.quest(), ())

    def test_it_agrees_with_the_densest_pack_walk(self):
        m = who(quest_log={1498: 3})
        quest = self.quest()
        places = [(int(s.map_id), s.x, s.y) for s in quest.fields]
        for k in range(len(places) + 1):
            avoid = tuple(places[:k])
            fields = classquest.within_level(m, classquest.solo_fields(quest))
            want = bool(fields) and classquest._densest(m, fields, avoid) is None
            self.assertEqual(classquest.all_tried(m, quest, avoid), want, k)
        near = ((KALIMDOR, places[0][1] + 10.0, places[0][2]),)
        self.assertFalse(classquest.all_tried(m, quest, near))
        every = tuple((p[0], p[1] + 5.0, p[2]) for p in places)
        self.assertTrue(classquest.all_tried(m, quest, every))


class TheRollOldest(unittest.TestCase):
    def test_a_young_mark_does_not_scan_the_spawns(self):
        m = who(quest_log={1498: 3})
        quest = spread_book().quests[1498]
        spots = [(1, 500.0, -4000.0, classquest.SPAWN_RETRY_MINUTES - 1)]
        with mock.patch.object(classquest, "all_tried", side_effect=AssertionError):
            got = classquest.roll_oldest(m, quest, ((1, 500.0, -4000.0),), spots)
        self.assertEqual(got, ((1, 500.0, -4000.0),))

    def test_an_old_mark_is_still_retried_once_every_pack_is_tried(self):
        m = who(quest_log={1498: 3})
        quest = spread_book(2).quests[1498]
        every = tuple((int(s.map_id), s.x, s.y) for s in quest.fields)
        old = classquest.SPAWN_RETRY_MINUTES
        spots = [(1, every[0][1], every[0][2], old)]
        got = classquest.roll_oldest(m, quest, every, spots)
        self.assertNotIn(every[0], got)
        self.assertIn(every[-1], got)
        self.assertLess(len(got), len(every))


class ThePerBookTables(unittest.TestCase):
    def test_they_are_built_once_per_book(self):
        b = spread_book()
        self.assertIs(classquest.spawn_entries(b), classquest.spawn_entries(b))
        self.assertIs(classquest.slow_respawns(b), classquest.slow_respawns(b))

    def test_a_new_book_gets_its_own(self):
        a, b = spread_book(3), spread_book(5)
        self.assertEqual(len(classquest.spawn_entries(a)), 4)
        self.assertEqual(len(classquest.spawn_entries(b)), 6)
        self.assertEqual(len(classquest.spawn_entries(a)), 4)


if __name__ == "__main__":
    unittest.main()
