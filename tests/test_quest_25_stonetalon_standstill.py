"""A held quest whose every objective spawn is over the quester's level (#1728).

Quest 25, Stonetalon Standstill (Ashenvale, level 25), was dropped as stalled
by five questers: "its objectives did not move for 2 hours of play". A quester
may take a quest up to levelroute.ABOVE (3) levels over itself (`open_to`),
but hunts only spawns at most classquest.OVERLEVEL_MAX (3) levels over itself
(`_hunt`). A quester three levels under the quest whose objective creatures
stand a level or more over the quest held it with nothing it would hunt, so
`_unhuntable` ran its stall clock as if no one could work the quest, and two
hours later it was dropped and filed broken. It was waiting for the quester's
levels, not stuck.

The lane had no read of the world rows, so the objective's creature entry,
its spawn count and its spawn level below are invented; the quest id, title,
zone and level are the ticket's. The rows are shaped as questers.catalogue
reads them (QUESTS_SQL, STARTERS_SQL, ENDERS_SQL), through the helpers of
test_questers.
"""

import unittest

import classquest
import questers
from test_questers import giver, mirra, quest, spawn

ASHENVALE = 331
KALIMDOR = 1
ORC = 2
QUEST = 25
TARGET = 90025  # invented: the world rows were not read
TARGET_LEVEL = 26
TWO_HOURS_OF_PASSES = 13


def standstill_catalogue(target_level=TARGET_LEVEL):
    row = quest(
        QUEST,
        ASHENVALE,
        25,
        min_level=20,
        kill=TARGET,
        count=8,
        title="Stonetalon Standstill",
    )
    spawns = [
        spawn(
            7000 + i,
            TARGET,
            300.0 + 10 * i,
            0.0,
            level=target_level,
            map_id=KALIMDOR,
            name="Objective creature",
        )
        for i in range(6)
    ]
    return questers.catalogue(
        [row],
        [
            giver(QUEST, "start", 8025, 825, 0, 0, map_id=KALIMDOR),
            giver(QUEST, "end", 8025, 825, 0, 0, map_id=KALIMDOR),
        ],
        spawns,
        [],
        [{"quest": QUEST, "kind": "creature", "entry": 825}],
        [{"quest": QUEST, "kind": "creature", "entry": 825}],
    )


def holder(level=22):
    return mirra(
        name="Grakk",
        level=level,
        race=ORC,
        map_id=KALIMDOR,
        zone_id=ASHENVALE,
        x=0.0,
        y=0.0,
        quest_log={QUEST: questers.STATUS_INCOMPLETE},
        quest_progress={QUEST: 0},
        quest_objectives={QUEST: {TARGET: 0}},
    )


def two_hours_of_play(cat, member, last_quest=0) -> questers.Plan:
    """The Plan of the pass after two hours of play with nothing moved."""
    clock = questers.Clock()
    plan = questers.plan(cat, member, clock, 0.0, last_quest=last_quest)
    for i in range(1, TWO_HOURS_OF_PASSES):
        plan = questers.plan(cat, member, clock, 600.0 * i, last_quest=last_quest)
    return plan


def hunt_of(member) -> classquest.Move:
    move = questers.plan(standstill_catalogue(), member, questers.Clock(), 0.0).move
    assert move is not None
    return move


class StonetalonStandstillOverTheQuestersLevel(unittest.TestCase):
    def test_the_quester_may_take_it_three_levels_under_it(self):
        member = questers.Member(**{**holder().__dict__, "quest_log": {}})
        self.assertTrue(questers.open_to(standstill_catalogue(), member, QUEST))

    def test_its_objective_is_too_high_to_hunt_at_that_level(self):
        move = questers.plan(standstill_catalogue(), holder(), questers.Clock(), 0.0)
        self.assertIsNone(move.move)

    def test_its_clock_waits_while_its_objective_is_over_the_quester(self):
        self.assertFalse(questers._unhuntable(standstill_catalogue(), holder(), QUEST))

    def test_two_hours_of_waiting_for_levels_files_it_nowhere(self):
        plan = two_hours_of_play(standstill_catalogue(), holder())
        self.assertEqual([b.quest for b in plan.broken], [])

    def test_the_quester_hunts_it_once_it_levels(self):
        move = hunt_of(holder(level=23))
        self.assertEqual((move.kind, move.quest), (classquest.HUNT, QUEST))
        self.assertEqual(getattr(move.spot, "entry", 0), TARGET)

    def test_a_hunted_objective_that_never_moves_still_stalls(self):
        plan = two_hours_of_play(
            standstill_catalogue(target_level=24), holder(), last_quest=QUEST
        )
        self.assertEqual(
            [(b.quest, b.reason) for b in plan.broken], [(QUEST, questers.STALLED)]
        )


if __name__ == "__main__":
    unittest.main()
