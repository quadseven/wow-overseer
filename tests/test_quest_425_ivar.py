"""Quest 425's item drop waits at the hunt module's lethal level boundary.

The quest, item, and creature entry come from ticket #3181. Fixture rows use
the shapes read by questers.QUESTS_SQL, classquest.LOOT_SQL,
classquest.SPAWNS_SQL, and questers.LOG_SQL, assembled with test_questers
helpers. The level-15 spawn is synthetic: it places the supplied dropper at
the module's three-level lethal boundary for a level-12 quester.
"""

import unittest

import classhunt
import classquest
import questers
from test_questers import giver, mirra, quest, spawn, started, ended

QUEST = 425
ITEM = 3621
CREATURE = 1971
SILVERPINE = 130
EASTERN_KINGDOMS = 0
TARGET_LEVEL = 15
QUESTER_LEVEL = 12


def ivar_world():
    row = quest(
        QUEST,
        SILVERPINE,
        12,
        min_level=10,
        prev=430,
        title="Ivar the Foul",
    )
    row.update(item1=ITEM, item_count1=1)
    return questers.catalogue(
        [row],
        [
            giver(QUEST, "start", 4001, 401, 0, 0),
            giver(QUEST, "end", 4002, 402, 0, 0),
        ],
        [
            spawn(
                4003,
                CREATURE,
                100.0,
                0.0,
                level=TARGET_LEVEL,
                map_id=EASTERN_KINGDOMS,
                name="Objective creature",
            )
        ],
        [{"item": ITEM, "entry": CREATURE}],
        [started(QUEST, 401)],
        [ended(QUEST, 402)],
    )


def holder(level=QUESTER_LEVEL, progress=0, item_count=0):
    return mirra(
        name="QuestBot",
        level=level,
        map_id=EASTERN_KINGDOMS,
        x=0.0,
        y=0.0,
        zone_id=SILVERPINE,
        quest_log={QUEST: questers.STATUS_INCOMPLETE},
        quests_done=frozenset({430}),
        quest_progress={QUEST: progress},
        quest_objectives={QUEST: {}},
        quest_item_objectives={QUEST: {ITEM: item_count}},
    )


class IvarTheFoul(unittest.TestCase):
    def test_a_level_12_quester_waits_on_the_module_lethal_boundary(self):
        cat = ivar_world()
        member = holder()
        clock = questers.Clock()

        plans = [
            questers.plan(cat, member, clock, 600.0 * minute) for minute in range(13)
        ]

        self.assertTrue(
            all(p.move is None or p.move.kind != classquest.HUNT for p in plans)
        )
        self.assertTrue(all(not any(b.quest == QUEST for b in p.broken) for p in plans))

    def test_the_quester_hunts_the_item_drop_when_it_can_kill_the_target(self):
        cat = ivar_world()
        member = holder(level=QUESTER_LEVEL + 1)

        plan = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, plan.move, 0, cat.quest(QUEST))

        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.HUNT, QUEST))
        self.assertEqual(plan.move.spot.entry, CREATURE)
        self.assertEqual(
            step.rows[0].command,
            "hunt-spawn creature:%d item:%d count:1 max:%d"
            % (CREATURE, ITEM, classhunt.MAX_SECONDS),
        )

    def test_the_required_item_completes_the_quest_and_sends_it_to_turn_in(self):
        cat = ivar_world()
        member = holder(progress=1, item_count=1)

        plan = questers.plan(cat, member, questers.Clock(), 0.0)

        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.TURN_IN, QUEST))


if __name__ == "__main__":
    unittest.main()
