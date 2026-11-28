"""Infiltration (quest 533) can hunt its required Syndicate Missive.

The ticket supplies quest 533's level and item objective, and the item 3601
dropper entries 2240 and 2241. Its additional reward relation to quest 535
does not change the creature-drop route. Fixture-only giver and spawn rows
provide positions so the planner can exercise that route without claiming
those positions came from a live read.

Rows use the shapes read by bridge._quester_catalogue and
bridge._fetch_quester_facts: questers.QUESTS_SQL, classquest.LOOT_SQL,
classquest.SPAWNS_SQL, questers.STARTERS_SQL, questers.ENDERS_SQL, and
questers.LOG_SQL.
"""

import unittest
from dataclasses import replace

import classhunt
import classquest
import questers
from test_questers import ended, giver, mirra, quest, spawn, started

QUEST = 533
HILLSBRAD = 267
MISSIVE = 3601
DROPPERS = (2240, 2241)


def infiltration_catalogue():
    row = quest(QUEST, HILLSBRAD, 34, min_level=29, title="Infiltration")
    row.update(item1=MISSIVE, item_count1=1)
    return questers.catalogue(
        [row],
        [
            giver(QUEST, "start", 1, 21001, 0, 0, name="Quest giver"),
            giver(QUEST, "end", 2, 21002, 300, 0, name="Quest ender"),
        ],
        [
            spawn(1, DROPPERS[0], 30, 0, level=34, name="Drop source"),
            spawn(2, DROPPERS[1], 60, 0, level=34, name="Drop source"),
        ],
        [{"item": MISSIVE, "entry": entry} for entry in DROPPERS],
        [started(QUEST, 21001)],
        [ended(QUEST, 21002)],
    )


def quester(**overrides):
    facts = {
        "name": "Quester",
        "level": 34,
        "zone_id": HILLSBRAD,
        "quest_log": {QUEST: questers.STATUS_INCOMPLETE},
        "quest_progress": {QUEST: 0},
        "quest_objectives": {QUEST: {}},
        "quest_item_objectives": {QUEST: {MISSIVE: 0}},
    }
    facts.update(overrides)
    return mirra(**facts)


class Infiltration(unittest.TestCase):
    def test_quester_hunts_the_missive_dropper_then_can_hand_it_in(self):
        cat = infiltration_catalogue()
        holder = quester()
        plan = questers.plan(cat, holder, questers.Clock(), 0.0, last_quest=QUEST)

        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.HUNT, QUEST))
        self.assertIn(plan.move.spot.entry, DROPPERS)
        step = questers.step_for(holder, plan.move, 0, cat.quest(QUEST))
        self.assertEqual(
            step.rows[0].command,
            "hunt-spawn creature:%d item:%d count:1 max:%d"
            % (plan.move.spot.entry, MISSIVE, classhunt.MAX_SECONDS),
        )

        complete = replace(
            holder,
            quest_progress={QUEST: 1},
            quest_item_objectives={QUEST: {MISSIVE: 1}},
        )
        hand_in = questers.plan(cat, complete, questers.Clock(), 60.0)

        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, QUEST)
        )


if __name__ == "__main__":
    unittest.main()
