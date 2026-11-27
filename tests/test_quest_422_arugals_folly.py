"""Arugal's Folly (quest 422, Silverpine Forest, level 11) asks for one
Remedy of Arugal (item 3155), which the world rows name as gameobject loot
of entry 1571: a chest, not a creature drop.

The questers read gameobject loot (classquest.CHEST_SQL) and open the chest
with the module's `use-gameobject` row, so a quest whose only source is a
spawned chest is worked, not filed as unsourced. A quester can finish it:
take the quest, walk to the chest and open it, then hand it in.

The fixture takes the world rows the ticket cites - the required item and
its gameobject loot entry - and adds the spawn the rows imply. The levels
are invented: the lane could not read the live world.

No reason string is keyed on this quest's id: the ledger words come from the
general STALLED_UNSOURCED rule, which names the missing source.
"""

import unittest

import classquest
import questers
from test_questers import HUMAN, ORC, PRIEST, giver, mirra, quest, spawn

SILVERPINE = 130
ARUGALS_FOLLY = 422
REMEDY_OF_ARUGAL = 3155
CHEST = 1571
QUEST_LEVEL = 11
MIN_LEVEL = 9
TWO_HOURS_OF_PASSES = 13


def chest_spawn(guid, entry, x, y, map_id=0):
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": "Remedy Chest",
        "rank": 0,
        "level": 0,
    }


def arugals_folly_world(chest=True):
    row = quest(ARUGALS_FOLLY, SILVERPINE, QUEST_LEVEL, min_level=MIN_LEVEL,
                title="Arugal's Folly")
    row.update(item1=REMEDY_OF_ARUGAL, item_count1=1)
    giver_rows = [
        giver(ARUGALS_FOLLY, "start", 9001, 9001, 0, 0),
        giver(ARUGALS_FOLLY, "end", 9001, 9001, 0, 0),
    ]
    object_rows = [chest_spawn(9010, CHEST, 100.0, 0.0)] if chest else []
    return questers.catalogue(
        [row],
        giver_rows,
        [],
        [],
        [{"quest": ARUGALS_FOLLY, "kind": "creature", "entry": 9001}],
        [{"quest": ARUGALS_FOLLY, "kind": "creature", "entry": 9001}],
        chest_rows=[{"item": REMEDY_OF_ARUGAL, "entry": CHEST}] if chest else (),
        object_rows=object_rows,
    )


def fresh_member():
    """A quester that does not yet hold the quest, at its giver."""
    return mirra(
        name="Mortane",
        level=QUEST_LEVEL,
        race=ORC,
        class_id=PRIEST,
        zone_id=SILVERPINE,
        x=0.0,
        y=0.0,
    )


def holder(counts=None):
    """Mortane holding the quest, with the remedy counted `counts` times."""
    counts = counts or {REMEDY_OF_ARUGAL: 0}
    return mirra(
        name="Mortane",
        level=QUEST_LEVEL,
        race=ORC,
        class_id=PRIEST,
        zone_id=SILVERPINE,
        x=0.0,
        y=0.0,
        quest_log={ARUGALS_FOLLY: questers.STATUS_INCOMPLETE},
        quest_progress={ARUGALS_FOLLY: sum(counts.values())},
        quest_item_objectives={ARUGALS_FOLLY: counts},
    )


class AQuesterFinishesArugalsFolly(unittest.TestCase):
    def setUp(self):
        self.cat = arugals_folly_world()
        self.clock = questers.Clock()

    def test_the_gameobject_loot_source_is_a_chest_use(self):
        quest422 = self.cat.quest(ARUGALS_FOLLY)
        (use,) = quest422.uses
        self.assertEqual(
            (use.verb, use.item, use.targets),
            (classquest.USE_OBJECT, REMEDY_OF_ARUGAL, (CHEST,)),
        )
        self.assertEqual([s.guid for s in use.spots], [9010])
        self.assertTrue(questers._chested(quest422))

    def test_take_open_chest_and_hand_in_finishes_it(self):
        take = questers.plan(self.cat, fresh_member(), self.clock, 0.0)
        self.assertEqual((take.move.kind, take.move.quest),
                         (classquest.TAKE, ARUGALS_FOLLY))

        held = holder()
        use = questers.plan(self.cat, held, self.clock, 0.0,
                            last_quest=ARUGALS_FOLLY)
        self.assertEqual((use.move.kind, use.move.quest),
                         (classquest.USE, ARUGALS_FOLLY))
        self.assertEqual(use.move.spot.guid, 9010)
        step = questers.step_for(held, use.move, 0,
                                 self.cat.quest(ARUGALS_FOLLY))
        self.assertEqual(step.rows[0].command, "use-gameobject %d" % CHEST)

        opened = holder(counts={REMEDY_OF_ARUGAL: 1})
        hand_in = questers.plan(self.cat, opened, self.clock, 0.0)
        self.assertEqual((hand_in.move.kind, hand_in.move.quest),
                         (classquest.TURN_IN, ARUGALS_FOLLY))

    def test_without_a_chest_the_ledger_says_unsourced(self):
        cat = arugals_folly_world(chest=False)
        member = holder()
        plan = questers.plan(cat, member, self.clock, 0.0,
                             last_quest=ARUGALS_FOLLY)
        self.assertEqual(plan.broken, ())
        for i in range(1, TWO_HOURS_OF_PASSES):
            plan = questers.plan(cat, member, self.clock, 600.0 * i,
                                 last_quest=ARUGALS_FOLLY)
        self.assertEqual([b.quest for b in plan.broken], [ARUGALS_FOLLY])
        self.assertEqual(plan.broken[0].reason, questers.STALLED_UNSOURCED)


if __name__ == "__main__":
    unittest.main()
