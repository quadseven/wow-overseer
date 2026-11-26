"""A Recipe For Death (quest 447, Silverpine Forest, level 12): what the
quester does with each sourcing of its two required items.

The quest asks for two items, six of each: Grizzled Bear Heart (3253),
dropped by creature entries 1778, 1797 and 12432, and Skittering Blood
(3254), dropped by creature entries 1780, 1781 and 12433. Those creature
entries are the ticket's world rows; their levels and the giver entry are
fixture-only, because the ticket lists no giver or spawn rows.

Loot rows alone do not say a dropper is spawned, so this
file pins the quester's behaviour for each sourcing the world rows can
hide, in the shape of the Wild Hearts rows (#3250):

  * both items' droppers spawned: the quest is open, is taken, and is hunted
    at a dropper of an item still short;
  * one item's droppers unspawned: that item can never be gathered, so
    the quest is not taken, and the ledger row the plan records names the
    unsourced item (questers.UNSOURCED_ITEM) instead of a plain stall;
  * no dropper spawned: the quest is not open, and a quester already
    holding it stalls with the unsourced reason
    (questers.STALLED_UNSOURCED), which says why no one can finish it.
"""

import unittest

import classquest
import questers
from test_questers import ended, giver, mirra, quest, spawn

SILVERPINE = 130
RECIPE_FOR_DEATH = 447
BEAR_HEART, SKITTERING_BLOOD = 3253, 3254
BEARS = (1778, 1797, 12432)
SPIDERS = (1780, 1781, 12433)
# Fixture-only entry: the ticket does not include the giver rows.
GIVER = 9002


def recipe_world(spawn_bears=True, spawn_spiders=True):
    row = quest(
        RECIPE_FOR_DEATH, SILVERPINE, 12, min_level=9, title="A Recipe For Death"
    )
    row.update(
        item1=BEAR_HEART,
        item_count1=6,
        item2=SKITTERING_BLOOD,
        item_count2=6,
    )
    loot = [{"item": BEAR_HEART, "entry": e} for e in BEARS] + [
        {"item": SKITTERING_BLOOD, "entry": e} for e in SPIDERS
    ]
    spawns = []
    if spawn_bears:
        spawns += [
            spawn(9100 + i, e, 100.0 + 30 * i, 0.0, level=12, name="Bear")
            for i, e in enumerate(BEARS)
        ]
    if spawn_spiders:
        spawns += [
            spawn(9200 + i, e, 500.0 + 30 * i, 0.0, level=12, name="Spider")
            for i, e in enumerate(SPIDERS)
        ]
    return questers.catalogue(
        [row],
        [
            giver(RECIPE_FOR_DEATH, "start", 9901, GIVER, 0, 0),
            giver(RECIPE_FOR_DEATH, "end", 9901, GIVER, 0, 0),
        ],
        spawns,
        loot,
        [{"quest": RECIPE_FOR_DEATH, "kind": "creature", "entry": GIVER}],
        [ended(RECIPE_FOR_DEATH, GIVER)],
    )


def member(**kw):
    base = dict(level=12, zone_id=SILVERPINE)
    base.update(kw)
    return mirra(**base)


def holder(**kw):
    base = dict(
        quest_log={RECIPE_FOR_DEATH: questers.STATUS_INCOMPLETE},
        quest_progress={RECIPE_FOR_DEATH: 0},
        quest_item_objectives={RECIPE_FOR_DEATH: {BEAR_HEART: 0, SKITTERING_BLOOD: 0}},
    )
    base.update(kw)
    return member(**base)


class ARecipeForDeathWithOneUnsourcedItemIsNotTaken(unittest.TestCase):
    def test_blood_with_no_spawned_dropper_is_recorded_unsourced(self):
        cat = recipe_world(spawn_spiders=False)
        plan = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertTrue(plan.move is None or plan.move.quest != RECIPE_FOR_DEATH)
        self.assertEqual(
            [b.reason for b in plan.broken if b.quest == RECIPE_FOR_DEATH],
            [questers.UNSOURCED_ITEM % SKITTERING_BLOOD],
        )

    def test_hearts_with_no_spawned_dropper_are_recorded_unsourced(self):
        cat = recipe_world(spawn_bears=False)
        plan = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertTrue(plan.move is None or plan.move.quest != RECIPE_FOR_DEATH)
        self.assertEqual(
            [b.reason for b in plan.broken if b.quest == RECIPE_FOR_DEATH],
            [questers.UNSOURCED_ITEM % BEAR_HEART],
        )


class ARecipeForDeathWithSpawnedSourcesWorks(unittest.TestCase):
    def test_both_items_spawned_is_open_taken_and_hunted(self):
        cat = recipe_world()
        self.assertTrue(questers.open_to(cat, member(), RECIPE_FOR_DEATH))
        take = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertEqual(
            (take.move.kind, take.move.quest), (classquest.TAKE, RECIPE_FOR_DEATH)
        )
        hunt = questers.plan(cat, holder(), questers.Clock(), 0.0)
        self.assertEqual(
            (hunt.move.kind, hunt.move.quest), (classquest.HUNT, RECIPE_FOR_DEATH)
        )
        self.assertIn(hunt.move.spot.entry, BEARS + SPIDERS)

    def test_no_dropper_spawned_is_not_open_and_a_holder_stalls_unsourced(self):
        cat = recipe_world(spawn_bears=False, spawn_spiders=False)
        self.assertFalse(questers.open_to(cat, member(), RECIPE_FOR_DEATH))
        clock = questers.Clock()
        plan = questers.plan(cat, holder(), clock, 0.0, last_quest=RECIPE_FOR_DEATH)
        for minute in range(1, 14):
            plan = questers.plan(
                cat, holder(), clock, 600.0 * minute, last_quest=RECIPE_FOR_DEATH
            )
        self.assertEqual(
            [b.reason for b in plan.broken if b.quest == RECIPE_FOR_DEATH],
            [questers.STALLED_UNSOURCED],
        )


if __name__ == "__main__":
    unittest.main()
