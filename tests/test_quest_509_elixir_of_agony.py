"""Quest 509's item source is gameobject loot, not creature loot.

The supplied world rows name item 3502 and gameobject source entry 1723. A
spawned source should be opened by the quester; if the fixture has no spawn
row, the ledger should identify that missing gameobject source.
"""

import unittest

import classquest
import questers
from test_questers import HORDE_MASK, ended, giver, quest, spawn

QUEST = 509
HILLSBRAD = 267
ITEM = 3502
SOURCE = 1723
GIVER = 9509


def elixir_world(spawn_source):
    row = quest(
        QUEST,
        HILLSBRAD,
        28,
        min_level=24,
        races=HORDE_MASK,
        title="Elixir of Agony",
    )
    row.update(item1=ITEM, item_count1=6)
    return questers.catalogue(
        [row],
        [
            giver(QUEST, "start", 9509, GIVER, 0, 0, name="Quest giver"),
            giver(QUEST, "end", 9509, GIVER, 0, 0, name="Quest giver"),
        ],
        [],
        [],
        [{"quest": QUEST, "kind": "creature", "entry": GIVER}],
        [ended(QUEST, GIVER)],
        chest_rows=[{"item": ITEM, "entry": SOURCE}],
        object_rows=[spawn(9510, SOURCE, 10, 0, name="Mudsnout Blossom")]
        if spawn_source
        else [],
    )


def quester(**values):
    member = {
        "name": "Quester A",
        "level": 28,
        "race": 2,
        "class_id": 5,
        "map_id": 0,
        "x": 0.0,
        "y": 0.0,
        "zone_id": HILLSBRAD,
        "online": True,
    }
    member.update(values)
    return questers.Member(**member)


class ElixirOfAgony(unittest.TestCase):
    def test_spawned_gameobject_source_can_be_opened_and_turned_in(self):
        cat = elixir_world(spawn_source=True)
        member = quester()
        take = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual((take.move.kind, take.move.quest), (classquest.TAKE, QUEST))

        holder = quester(
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 0},
            quest_item_objectives={QUEST: {ITEM: 0}},
        )
        use = questers.plan(cat, holder, questers.Clock(), 0.0)
        self.assertEqual((use.move.kind, use.move.quest), (classquest.USE, QUEST))
        step = questers.step_for(holder, use.move, 0, cat.quest(QUEST))
        self.assertEqual(step.rows[0].command, "use-gameobject %d" % SOURCE)

        completed = quester(
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 6},
            quest_item_objectives={QUEST: {ITEM: 6}},
        )
        hand_in = questers.plan(cat, completed, questers.Clock(), 0.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, QUEST)
        )

    def test_missing_gameobject_spawn_is_named_in_the_ledger_reason(self):
        cat = elixir_world(spawn_source=False)
        holder = quester(
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 0},
            quest_item_objectives={QUEST: {ITEM: 0}},
        )
        clock = questers.Clock()
        plan = questers.plan(cat, holder, clock, 0.0, last_quest=QUEST)
        for minute in range(1, 14):
            plan = questers.plan(
                cat,
                holder,
                clock,
                600.0 * minute,
                last_quest=QUEST,
            )

        self.assertEqual([broken.quest for broken in plan.broken], [QUEST])
        self.assertIn("gameobject source entries 1723", plan.broken[0].reason)
        self.assertIn("with no spawn row", plan.broken[0].reason)


if __name__ == "__main__":
    unittest.main()
