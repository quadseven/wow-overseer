"""Infiltration (quest 533) can hunt its required Syndicate Missive.

The ticket supplies quest 533's level and item objective, and the item 3601
dropper entries 2240 and 2241. Its additional reward relation to quest 535
does not change the creature-drop route. Fixture-only giver and spawn rows
provide positions so the planner can exercise that route without claiming
those positions came from a live read.

Rows use the shapes read by bridge._quester_catalogue and
bridge._fetch_quester_facts: questers.QUESTS_SQL, classquest.LOOT_SQL,
classquest.SPAWNS_SQL, questers.STARTERS_SQL, questers.ENDERS_SQL, and
questers.LOG_SQL. The ledger transition uses the rows written by
bridge._record_quest_broken and questledger.changes. Hunt result fields come
from HuntJson in the pinned module and bridge._JOB_RECENT_SQL's recent rows.
"""

import datetime
import json
import unittest
from dataclasses import replace

import classhunt
import classquest
import guildjobs
import questledger
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


def item_hunt_row(row_id, age, entry, loot_items=()):
    command = "hunt-spawn creature:%d item:%d count:1 max:%d" % (
        entry,
        MISSIVE,
        classhunt.MAX_SECONDS,
    )
    return {
        "id": row_id,
        "target_name": "Quester",
        "command": command,
        "source": guildjobs.source_for(questers.ACTION, "Quester"),
        "status": "applied",
        "age": age,
        "result": json.dumps(
            {
                "outcome": "timeout",
                "reason": "the clock ran out",
                "retry": "",
                "character": "Quester",
                "entry": entry,
                "count": 1,
                "item": MISSIVE,
                "kills": 4,
                "pulls": 27,
                "loot_count": len(loot_items),
                "loot_items": loot_items,
            },
            separators=(",", ":"),
        ),
    }


class Infiltration(unittest.TestCase):
    def test_quester_hunts_the_missive_dropper_then_can_hand_it_in(self):
        cat = infiltration_catalogue()
        holder = quester()
        recent = questers.attempts(
            [
                item_hunt_row(1, 55, DROPPERS[0], [2589]),
                item_hunt_row(2, 35, DROPPERS[0], [2589]),
                item_hunt_row(3, 15, DROPPERS[0], [2589]),
            ]
        )
        plan = questers.plan(
            cat, holder, questers.Clock(), 0.0, tried=recent, last_quest=QUEST
        )

        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.HUNT, QUEST))
        self.assertEqual(plan.move.spot.entry, DROPPERS[1])
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
        self.assertFalse(any(broken.quest == QUEST for broken in hand_in.broken))

    def test_looting_the_missive_keeps_that_dropper_available(self):
        rows = [
            item_hunt_row(1, 55, DROPPERS[0], [2589]),
            item_hunt_row(2, 35, DROPPERS[0], [2589]),
            item_hunt_row(3, 15, DROPPERS[0], [2589]),
            item_hunt_row(4, 5, DROPPERS[0], [MISSIVE]),
        ]

        self.assertNotIn(
            DROPPERS[0], questers.fruitless_entries("Quester", questers.attempts(rows))
        )

    def test_a_full_loot_list_does_not_prove_the_missive_was_not_looted(self):
        rows = [
            item_hunt_row(1, 55, DROPPERS[0], [2589]),
            item_hunt_row(2, 35, DROPPERS[0], [2589]),
            item_hunt_row(3, 15, DROPPERS[0], [2589]),
            item_hunt_row(4, 5, DROPPERS[0], list(range(10000, 10032))),
        ]

        self.assertNotIn(
            DROPPERS[0], questers.fruitless_entries("Quester", questers.attempts(rows))
        )

    def test_rewarding_the_quest_clears_its_stall_reason_from_the_ledger(self):
        first_taken = datetime.datetime(2026, 11, 28, 0, 0)
        now = datetime.datetime(2026, 11, 28, 2, 0)
        broken = {
            "quest": QUEST,
            "guid": 1,
            "character_name": "Quester",
            "state": questledger.BROKEN,
            "first_taken": first_taken,
            "finished": now,
            "reason": questers.STALLED,
        }

        [entry] = questledger.changes(
            {1: "Quester"},
            [broken],
            [],
            [{"guid": 1, "quest": QUEST}],
            now,
        )

        self.assertEqual((entry.state, entry.reason), (questledger.COMPLETED, ""))


if __name__ == "__main__":
    unittest.main()
