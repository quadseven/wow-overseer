"""Collecting Memories (quest 168, The Deadmines, level 18): what the
quester does with each sourcing of its one required item.

The quest asks for four Miners' Union Cards (item 1894), dropped by
creature entries 623, 624 and 625. Those entries, the level and the
minimum level are the ticket's world rows. The ticket lists no giver or
spawn rows, so the giver entry and the spawns are fixture-only, and the
zone stands in with the Deadmines place id the site's places table uses.

Five questers held the quest for two hours of play and its objectives
did not move at all. Loot rows alone do not say a dropper is spawned, so
this file pins the quester's behaviour for each sourcing the world rows
can hide, in the shape of the Recipe For Death rows:

  * the item's droppers spawned: the quest is open, is taken, is hunted
    at a dropper, and is handed in when the four cards are gathered;
  * no dropper spawned: the item can never be gathered, so the quest is
    not open, and a quester already holding it stalls with the unsourced
    reason (questers.STALLED_UNSOURCED), which says why no one can
    finish it.
"""

import unittest

import classquest
import questers
from test_questers import ended, giver, mirra, quest, spawn

DEADMINES = 36
COLLECTING_MEMORIES = 168
MINERS_UNION_CARD = 1894
DROPPERS = (623, 624, 625)
# Fixture-only entry: the ticket does not include the giver rows.
GIVER = 9002


def memories_world(spawn_droppers=True):
    row = quest(
        COLLECTING_MEMORIES,
        DEADMINES,
        18,
        min_level=14,
        title="Collecting Memories",
    )
    row.update(item1=MINERS_UNION_CARD, item_count1=4)
    loot = [{"item": MINERS_UNION_CARD, "entry": e} for e in DROPPERS]
    spawns = []
    if spawn_droppers:
        spawns = [
            spawn(9100 + i, e, 100.0 + 30 * i, 0.0, level=18, name="Miner")
            for i, e in enumerate(DROPPERS)
        ]
    return questers.catalogue(
        [row],
        [
            giver(COLLECTING_MEMORIES, "start", 9901, GIVER, 0, 0),
            giver(COLLECTING_MEMORIES, "end", 9901, GIVER, 0, 0),
        ],
        spawns,
        loot,
        [{"quest": COLLECTING_MEMORIES, "kind": "creature", "entry": GIVER}],
        [ended(COLLECTING_MEMORIES, GIVER)],
    )


def member(**kw):
    base = dict(level=18, zone_id=DEADMINES)
    base.update(kw)
    return mirra(**base)


def holder(**kw):
    base = dict(
        quest_log={COLLECTING_MEMORIES: questers.STATUS_INCOMPLETE},
        quest_progress={COLLECTING_MEMORIES: 0},
        quest_item_objectives={COLLECTING_MEMORIES: {MINERS_UNION_CARD: 0}},
    )
    base.update(kw)
    return member(**base)


class CollectingMemoriesWithSpawnedDroppersWorks(unittest.TestCase):
    def test_spawned_droppers_is_open_taken_and_hunted(self):
        cat = memories_world()
        self.assertTrue(questers.open_to(cat, member(), COLLECTING_MEMORIES))
        take = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertEqual(
            (take.move.kind, take.move.quest),
            (classquest.TAKE, COLLECTING_MEMORIES),
        )
        hunt = questers.plan(cat, holder(), questers.Clock(), 0.0)
        self.assertEqual(
            (hunt.move.kind, hunt.move.quest),
            (classquest.HUNT, COLLECTING_MEMORIES),
        )
        self.assertIn(hunt.move.spot.entry, DROPPERS)

    def test_the_four_cards_are_handed_in(self):
        cat = memories_world()
        done = holder(
            quest_progress={COLLECTING_MEMORIES: 4},
            quest_item_objectives={COLLECTING_MEMORIES: {MINERS_UNION_CARD: 4}},
        )
        hand_in = questers.plan(cat, done, questers.Clock(), 0.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest),
            (classquest.TURN_IN, COLLECTING_MEMORIES),
        )


class CollectingMemoriesWithNoSpawnedDropper(unittest.TestCase):
    def test_no_dropper_spawned_is_not_open(self):
        cat = memories_world(spawn_droppers=False)
        self.assertFalse(questers.open_to(cat, member(), COLLECTING_MEMORIES))
        plan = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertTrue(plan.move is None or plan.move.quest != COLLECTING_MEMORIES)

    def test_a_holder_stalls_with_the_unsourced_reason(self):
        cat = memories_world(spawn_droppers=False)
        clock = questers.Clock()
        plan = questers.plan(cat, holder(), clock, 0.0, last_quest=COLLECTING_MEMORIES)
        for minute in range(1, 14):
            plan = questers.plan(
                cat,
                holder(),
                clock,
                600.0 * minute,
                last_quest=COLLECTING_MEMORIES,
            )
        self.assertEqual(
            [b.reason for b in plan.broken if b.quest == COLLECTING_MEMORIES],
            [questers.STALLED_UNSOURCED],
        )


if __name__ == "__main__":
    unittest.main()
