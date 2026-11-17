"""A quester stops asking for a hunt that never kills (#2188).

On the dev realm one quester asked `hunt-spawn creature:<entry> count:1
max:480` 34 times in 16 hours; every row ended `unchanged` ("the clock ran
out") with 0 kills after 140 or more pulls, or was refused "no living creature
of the entry within reach". The pack nearest the quester stayed the nearest, so
the same row was written again and again. Rows are built as the bridge reads
them (questers.attempts).
"""

import json
import unittest

import classquest
import guildjobs
import questers
from test_questers import mirra, world

KOBOLDS = 201  # the kill objective of quest 2 in test_questers.world()
SOURCE = guildjobs.source_for(questers.ACTION, "Mirra")
NOT_THERE = "no living creature of the entry within reach"
CLOCK = "the clock ran out"


def hunt_row(age, status="unchanged", kills=0, reason=CLOCK, entry=KOBOLDS):
    body = {
        "outcome": "timeout" if status == "unchanged" else "refused",
        "reason": reason,
        "retry": "later",
        "entry": entry,
        "kills": kills,
        "pulls": 144,
    }
    return {
        "id": 1000 + age,
        "target_name": "Mirra",
        "command": "hunt-spawn creature:%d count:1 max:480" % entry,
        "source": SOURCE,
        "status": status,
        "age": age,
        "result": json.dumps(body, separators=(",", ":")),
    }


def holder():
    return mirra(quests_done=frozenset({1, 3, 6}), quest_log={2: 3})


def move(rows):
    tried = questers.attempts(rows)
    return questers.next_move(world(), holder(), tried=tried)[0]


class AHuntThatNeverKillsIsLeft(unittest.TestCase):
    def test_a_quester_with_no_hunt_row_hunts_the_nearest_pack(self):
        self.assertEqual(move([]).kind, classquest.HUNT)

    def test_fewer_than_the_bound_of_empty_hunts_is_asked_again(self):
        rows = [hunt_row(10 * i + 5) for i in range(questers.FRUITLESS_HUNTS - 1)]
        self.assertEqual(move(rows).kind, classquest.HUNT)

    def test_the_bound_of_empty_hunts_leaves_the_creature(self):
        rows = [hunt_row(10 * i + 5) for i in range(questers.FRUITLESS_HUNTS)]
        self.assertNotEqual(move(rows).kind, classquest.HUNT)

    def test_a_refusal_for_no_creature_in_reach_counts_the_same(self):
        rows = [
            hunt_row(10 * i + 5, status="error", reason=NOT_THERE)
            for i in range(questers.FRUITLESS_HUNTS)
        ]
        self.assertNotEqual(move(rows).kind, classquest.HUNT)

    def test_a_hunt_that_killed_resets_the_count(self):
        rows = [hunt_row(10 * i + 5) for i in range(questers.FRUITLESS_HUNTS)]
        rows.append(hunt_row(1, status="applied", kills=3, reason="done"))
        self.assertEqual(move(rows).kind, classquest.HUNT)

    def test_a_refusal_for_a_full_bag_is_not_an_empty_hunt(self):
        rows = [
            hunt_row(10 * i + 5, status="error", reason="no free bag slot")
            for i in range(questers.FRUITLESS_HUNTS)
        ]
        self.assertNotIn(KOBOLDS, questers.fruitless_entries("Mirra", questers.attempts(rows)))

    def test_it_hunts_again_once_the_rows_are_old(self):
        age = questers.FRUITLESS_MINUTES + 5
        rows = [hunt_row(age + i) for i in range(questers.FRUITLESS_HUNTS)]
        self.assertEqual(move(rows).kind, classquest.HUNT)

    def test_another_creature_is_not_left_for_this_ones_rows(self):
        rows = [hunt_row(10 * i + 5, entry=999) for i in range(questers.FRUITLESS_HUNTS)]
        self.assertEqual(move(rows).kind, classquest.HUNT)

    def test_a_quest_it_cannot_hunt_runs_its_stall_clock(self):
        rows = [hunt_row(10 * i + 5) for i in range(questers.FRUITLESS_HUNTS)]
        tried = questers.attempts(rows)
        working = questers._working(
            world(), holder(), 0, frozenset(), frozenset(),
            questers.fruitless_entries("Mirra", tried),
        )
        self.assertIn(2, working)


if __name__ == "__main__":
    unittest.main()
