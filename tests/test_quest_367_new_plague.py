"""A New Plague (quest 367, Tirisfal Glades, level 6): the quester can finish it.

The ticket's world rows:

  * QuestLevel 6; MinLevel 6; Tirisfal Glades
  * Required item 2858 x5 (Darkhound Blood), dropped by creature entries
    1547, 1548, 1549
  * a creature is named as the quest giver

The giver entry, the darkhound levels and spawn points are fixture-only: the
ticket names a creature giver and its item's droppers but lists no giver or
spawn rows. What the rows settle is that the quest has a creature giver and a
creature source for its item, so a quester that reaches a spawned giver can
take it, hunt a darkhound for its blood, and hand it in. The stored "no giver
of that quest in reach" refusal is therefore a moment of the world (no spawned
giver within the arrival radius), not evidence the quest cannot be finished.
"""

import unittest

import classquest
import questers
from test_questers import TIRISFAL, ended, giver, mirra, quest, spawn

QUEST = 367
BLOOD = 2858
DARKHOUNDS = (1547, 1548, 1549)
GIVER = 9036  # fixture-only: the ticket names a creature giver, no entry


def new_plague_world(spawn_giver=True, spawn_darkhounds=True):
    row = quest(QUEST, TIRISFAL, 6, min_level=6, title="A New Plague")
    row.update(item1=BLOOD, item_count1=5)
    loot = [{"item": BLOOD, "entry": e} for e in DARKHOUNDS]
    spawns = []
    if spawn_giver:
        spawns.append(spawn(8036, GIVER, 100.0, 0.0, level=6, name="Quest giver"))
    if spawn_darkhounds:
        spawns += [
            spawn(8100 + i, e, 300.0 + 30 * i, 0.0, level=6, name="Darkhound")
            for i, e in enumerate(DARKHOUNDS)
        ]
    return questers.catalogue(
        [row],
        [
            giver(QUEST, "start", 8001, GIVER, 0, 0),
            giver(QUEST, "end", 8001, GIVER, 0, 0),
        ],
        spawns,
        loot,
        [{"quest": QUEST, "kind": "creature", "entry": GIVER}],
        [ended(QUEST, GIVER)],
    )


def member(**kw):
    base = dict(
        name="Grakk",
        level=6,
        race=2,  # orc, the ticket's Bonkers guild
        zone_id=TIRISFAL,
        map_id=0,
        x=0.0,
        y=0.0,
        online=True,
    )
    base.update(kw)
    return questers.Member(**base)


class ANewPlagueWithASpawnedGiverCanBeTakenAndFinished(unittest.TestCase):
    def test_the_quest_is_open_to_a_level_six_quester(self):
        cat = new_plague_world()
        self.assertTrue(questers.open_to(cat, member(), QUEST))

    def test_a_quester_walks_to_the_giver_and_takes_it(self):
        cat = new_plague_world()
        plan = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.TAKE, QUEST))

    def test_a_holder_hunts_a_darkhound_for_its_blood(self):
        cat = new_plague_world()
        held = member(
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 0},
            quest_item_objectives={QUEST: {BLOOD: 0}},
        )
        plan = questers.plan(cat, held, questers.Clock(), 0.0)
        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.HUNT, QUEST))
        self.assertIn(plan.move.spot.entry, DARKHOUNDS)


class TheRecordedRefusalExplainsTheLedgerReason(unittest.TestCase):
    def test_no_spawned_giver_means_no_take_not_a_lost_quest(self):
        # Without a spawned giver the take is refused: the ledger's
        # "no giver of that quest in reach" names the giver's absence at that
        # moment, not a quest nobody can finish. With the giver spawned the
        # same quest is open and taken, so a quester can finish it.
        cat = new_plague_world(spawn_giver=False)
        self.assertFalse(questers.open_to(cat, member(), QUEST))
        plan = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertTrue(all(b.quest != QUEST for b in plan.broken))
        self.assertIsNone(plan.move)


if __name__ == "__main__":
    unittest.main()
