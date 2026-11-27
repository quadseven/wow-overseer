"""Quest 364's two creature objectives remain reachable to a level 2 quester.

The ticket supplies the objective entries, counts, and spawn totals. Spawn
levels and positions below are synthetic because the ticket did not measure
them; the fixture keeps them in Tirisfal and within the quester's hunt range.
"""

import unittest
from dataclasses import replace

import classquest
import questers
from test_questers import giver, mirra, quest, spawn

QUEST = 364
TIRISFAL = 85
MAP = 0
ZOMBIE = 1501
GHOUL = 1502


def mindless_ones_catalogue():
    row = quest(
        QUEST,
        TIRISFAL,
        2,
        min_level=1,
        kill=ZOMBIE,
        count=5,
        title="The Mindless Ones",
    )
    row["npc2"] = GHOUL
    row["npc_count2"] = 5
    spawns = [
        spawn(150100 + i, ZOMBIE, float(i * 10), 0, level=2, map_id=MAP)
        for i in range(28)
    ] + [
        spawn(150200 + i, GHOUL, float(i * 10), 20, level=2, map_id=MAP)
        for i in range(35)
    ]
    return questers.catalogue(
        [row],
        [
            giver(QUEST, "start", 36401, 1500, 0, 0, map_id=MAP),
            giver(QUEST, "end", 36402, 1500, 0, 0, map_id=MAP),
        ],
        spawns,
        [],
        [{"quest": QUEST, "kind": "creature", "entry": 1500}],
        [{"quest": QUEST, "kind": "creature", "entry": 1500}],
    )


class MindlessOnes(unittest.TestCase):
    def test_a_level_two_quester_hunts_both_objectives_and_can_finish(self):
        cat = mindless_ones_catalogue()
        member = mirra(
            level=2,
            map_id=MAP,
            zone_id=TIRISFAL,
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 0},
            quest_objectives={QUEST: {ZOMBIE: 0, GHOUL: 0}},
        )
        clock = questers.Clock()
        observed = set()

        for count in range(10):
            plan = questers.plan(cat, member, clock, count * 120.0)
            self.assertIsNotNone(plan.move)
            self.assertEqual(classquest.HUNT, plan.move.kind)
            entry = plan.move.spot.entry
            self.assertIn(entry, (ZOMBIE, GHOUL))
            observed.add(entry)
            objectives = dict(member.quest_objectives[QUEST])
            objectives[entry] += 1
            member = replace(
                member,
                quest_progress={QUEST: sum(objectives.values())},
                quest_objectives={QUEST: objectives},
                quest_log={
                    QUEST: (
                        questers.STATUS_COMPLETE
                        if sum(objectives.values()) == 10
                        else questers.STATUS_INCOMPLETE
                    )
                },
            )

        self.assertEqual({ZOMBIE, GHOUL}, observed)
        plan = questers.plan(cat, member, clock, 1200.0)
        self.assertEqual(classquest.TURN_IN, plan.move.kind)
        self.assertEqual((), plan.broken)

    def test_a_reachable_hunt_does_not_add_the_ledger_stall_reason(self):
        cat = mindless_ones_catalogue()
        member = mirra(
            level=2,
            map_id=MAP,
            zone_id=TIRISFAL,
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 0},
            quest_objectives={QUEST: {ZOMBIE: 0, GHOUL: 0}},
        )
        clock = questers.Clock()
        plan = None
        for minute in range(0, 121, 10):
            plan = questers.plan(cat, member, clock, minute * 60.0)
        self.assertIsNotNone(plan.move)
        self.assertEqual(classquest.HUNT, plan.move.kind)
        self.assertEqual((), plan.broken)


if __name__ == "__main__":
    unittest.main()
