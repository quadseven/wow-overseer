"""Elixir of Suffering (quest 496, Hillsbrad Foothills, level 22).

The ticket's world rows name two required items and their creature droppers.
This fixture checks that the planner hunts each missing item and hands in the
quest once complete. Quest and loot row shapes follow classquest.QUESTS_SQL
and classquest.LOOT_SQL; spawn and giver shapes follow classquest.SPAWNS_SQL
and classquest.GIVERS_SQL; item counters follow questers.LOG_SQL. Spawn
levels, positions, GUIDs and giver rows are synthetic because the ticket did
not include them.
"""

import unittest

import classquest
import questers
from test_questers import giver, mirra, quest, spawn, world

HILLSBRAD = 267
QUEST = 496
GRAY_BEAR_TONGUE = 3476
CREEPER_ICHOR = 3477
GRAY_BEAR_DROPPERS = (2351, 2354, 2356, 14280)
CREEPER_DROPPERS = (2348, 2349, 2350, 14279)
TWO_HOURS_OF_PASSES = 13


def elixir_world():
    row = quest(QUEST, HILLSBRAD, 22, min_level=19, title="Elixir of Suffering")
    row.update(
        item1=GRAY_BEAR_TONGUE,
        item_count1=10,
        item2=CREEPER_ICHOR,
        item_count2=1,
    )
    spawns, loot = [], []
    entries = (*GRAY_BEAR_DROPPERS, *CREEPER_DROPPERS)
    for index, entry in enumerate(entries):
        spawns.append(
            spawn(
                9500 + index,
                entry,
                100.0 + 25 * index,
                0.0,
                level=22,
                name="Objective creature",
            )
        )
        item = GRAY_BEAR_TONGUE if entry in GRAY_BEAR_DROPPERS else CREEPER_ICHOR
        loot.append({"item": item, "entry": entry})
    return world(
        extra_quests=[row],
        extra_givers=[
            giver(QUEST, "start", 9496, 990496, 0, 0, name="Fixture giver"),
            giver(QUEST, "end", 9496, 990496, 0, 0, name="Fixture giver"),
        ],
        extra_spawns=spawns,
        extra_loot=loot,
    )


def holder(**overrides):
    values = dict(
        name="QuestTester",
        level=22,
        zone_id=HILLSBRAD,
        x=0.0,
        y=0.0,
        quest_log={QUEST: questers.STATUS_INCOMPLETE},
        quest_progress={QUEST: 0},
        quest_item_objectives={QUEST: {GRAY_BEAR_TONGUE: 0, CREEPER_ICHOR: 0}},
    )
    values.update(overrides)
    return mirra(**values)


class ElixirOfSuffering(unittest.TestCase):
    def test_it_hunts_each_missing_item_and_hands_in_the_complete_quest(self):
        cat = elixir_world()

        first = questers.plan(cat, holder(), questers.Clock(), 0.0)
        self.assertEqual((first.move.kind, first.move.quest), (classquest.HUNT, QUEST))
        self.assertIn(first.move.spot.entry, GRAY_BEAR_DROPPERS)
        first_step = questers.step_for(holder(), first.move, 0, cat.quest(QUEST))
        self.assertIn("item:3476 count:10", first_step.rows[0].command)

        second_holder = holder(
            quest_progress={QUEST: 10},
            quest_item_objectives={QUEST: {GRAY_BEAR_TONGUE: 10, CREEPER_ICHOR: 0}},
        )
        second = questers.plan(cat, second_holder, questers.Clock(), 0.0)
        self.assertEqual(
            (second.move.kind, second.move.quest), (classquest.HUNT, QUEST)
        )
        self.assertIn(second.move.spot.entry, CREEPER_DROPPERS)
        second_step = questers.step_for(second_holder, second.move, 0, cat.quest(QUEST))
        self.assertIn("item:3477 count:1", second_step.rows[0].command)

        complete_holder = holder(
            quest_log={QUEST: questers.STATUS_COMPLETE},
            quest_progress={QUEST: 11},
            quest_item_objectives={QUEST: {GRAY_BEAR_TONGUE: 10, CREEPER_ICHOR: 1}},
        )
        handin = questers.plan(cat, complete_holder, questers.Clock(), 0.0)
        self.assertEqual(
            (handin.move.kind, handin.move.quest), (classquest.TURN_IN, QUEST)
        )

    def test_two_hours_without_item_progress_keeps_the_generic_stall_reason(self):
        cat = elixir_world()
        member = holder()
        clock = questers.Clock()
        plan = questers.plan(cat, member, clock, 0.0, last_quest=QUEST)
        self.assertEqual(plan.move.kind, classquest.HUNT)

        for index in range(1, TWO_HOURS_OF_PASSES):
            plan = questers.plan(cat, member, clock, 600.0 * index, last_quest=QUEST)

        self.assertEqual(
            [(broken.quest, broken.reason) for broken in plan.broken],
            [(QUEST, questers.STALLED)],
        )


if __name__ == "__main__":
    unittest.main()
