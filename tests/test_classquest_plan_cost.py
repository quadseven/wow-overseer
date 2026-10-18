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

import math
import random
import unittest
from unittest import mock

import classquest
from test_classquest import KALIMDOR, book, who, LIZARD, HIDE


def packs(n):
    """n spawns of one creature on Kalimdor, 100 yards apart (one pack each)."""
    return [dict(LIZARD, guid=9000 + i, x=500.0 + 100 * i, y=-4000.0) for i in range(n)]


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


def reference_densest(member, spawns, avoid=()):
    """_densest as it was before #833's second cut: every spawn measured
    against every other. The new one must pick exactly what this picks."""
    here = [
        s
        for s in spawns
        if int(s.map_id) == int(member.map_id) and not classquest._avoids(s, avoid)
    ]
    if not here:
        return None

    def pack(s):
        return sum(
            1 for o in here if math.hypot(o.x - s.x, o.y - s.y) <= classquest.PACK_YARDS
        )

    return min(here, key=lambda s: (-pack(s), classquest._yards(member, s), s.guid))


class TheDensestPack(unittest.TestCase):
    """2026-10-18: after the first cut, a synthetic book of 200 quests x 150
    spawns with 142 members still spent 85% of its plan in _densest's pack
    count (every spawn measured against every other), now reached through
    _hunt_move for each owed quest of each member, twice a member."""

    def test_far_apart_spawns_are_not_measured_against_each_other(self):
        n = 120
        far = [
            dict(LIZARD, guid=9000 + i, x=500.0 + 1000 * i, y=-4000.0) for i in range(n)
        ]
        quest = book(spawn_rows=far + [HIDE]).quests[1498]
        m = who(quest_log={1498: 3})
        real = math.hypot
        calls = []

        def counted(*a):
            calls.append(a)
            return real(*a)

        with mock.patch.object(classquest.math, "hypot", side_effect=counted):
            got = classquest._densest(m, quest.fields)
        self.assertIsNotNone(got)
        # One pack test per spawn (itself) and one distance to the member
        # each, not n * n pack tests.
        self.assertLess(len(calls), 4 * (n + 1))

    def test_it_picks_what_every_spawn_against_every_other_picks(self):
        rng = random.Random(833)
        for trial in range(300):
            rows = []
            for i in range(rng.randint(0, 60)):
                cx = rng.choice((0.0, 130.0, 250.0, 1000.0, -360.0))
                rows.append(
                    dict(
                        LIZARD,
                        guid=20000 + i,
                        map_id=rng.choice((KALIMDOR, KALIMDOR, KALIMDOR, 0)),
                        x=cx + rng.uniform(-150.0, 150.0) + rng.choice((0.0, 0.5)),
                        y=-4000.0 + rng.uniform(-150.0, 150.0),
                    )
                )
            # Spawns exactly PACK_YARDS apart, on a cell edge and off it.
            for j, (x, y) in enumerate(
                (
                    (0.0, 0.0),
                    (120.0, 0.0),
                    (240.0, 0.0),
                    (-120.0, 0.0),
                    (0.0, 120.0),
                    (59.9, 60.1),
                )
            ):
                rows.append(dict(LIZARD, guid=30000 + j, x=x, y=y))
            spawns = classquest._spawns_by_entry(rows).get(LIZARD["entry"], ())
            m = who(
                quest_log={1498: 3}, x=rng.uniform(-500, 1500), y=rng.uniform(-4500, 0)
            )
            places = [(int(s.map_id), s.x, s.y) for s in spawns]
            avoid = (
                tuple(rng.sample(places, rng.randint(0, len(places)))) if places else ()
            )
            for left in ((), avoid):
                want = reference_densest(m, spawns, left)
                got = classquest._densest(m, spawns, left)
                self.assertEqual(
                    None if want is None else want.guid,
                    None if got is None else got.guid,
                    (trial, left),
                )

    def test_a_spawn_with_no_number_for_a_place_still_gets_an_answer(self):
        rows = [
            dict(LIZARD, guid=1, x=0.0, y=0.0),
            dict(LIZARD, guid=2, x=50.0, y=0.0),
            dict(LIZARD, guid=3, x=float("nan"), y=0.0),
            dict(LIZARD, guid=4, x=900.0, y=0.0),
        ]
        spawns = classquest._spawns_by_entry(rows)[LIZARD["entry"]]
        m = who(quest_log={1498: 3}, x=900.0, y=0.0)
        want = reference_densest(m, spawns)
        self.assertEqual(classquest._densest(m, spawns).guid, want.guid)


if __name__ == "__main__":
    unittest.main()
