"""War Banners (quest 464, Wetlands, level 26).

The brief supplies the quest's level, minimum level, previous quest, required
item and creature entries that drop it. The quest, loot, spawn and log rows
below use the shapes read by questers.QUESTS_SQL, classquest.LOOT_SQL,
classquest.SPAWNS_SQL and questers.LOG_SQL. Giver, spawn GUID, position and
level values are fixture-only because the brief does not include those rows.
"""

import datetime
import unittest

import classhunt
import classquest
import questers
import questledger
from test_questers import ended, giver, mirra, quest, spawn

WETLANDS = 11
QUEST = 464
PREVIOUS_QUEST = 473
BANNER = 3337
DROPPERS = (1034, 1035, 1036, 1037, 1038, 1057, 2091)
GIVER = 90464
INCOMPLETE = questers.STATUS_INCOMPLETE
OLD = datetime.datetime(2026, 1, 1, 0, 0, 0)
NOW = datetime.datetime(2026, 1, 2, 0, 0, 0)


def war_banners_world():
    row = quest(QUEST, WETLANDS, 26, min_level=23, prev=PREVIOUS_QUEST, count=0,
                title="War Banners")
    row.update(item1=BANNER, item_count1=8)
    giver_rows = [
        giver(QUEST, "start", 1, GIVER, 100.0, 0.0, name="Quest giver"),
        giver(QUEST, "end", 2, GIVER, 100.0, 0.0, name="Quest giver"),
    ]
    spawn_rows = [
        spawn(index + 1, entry, 200.0 + 30.0 * index, 0.0, level=26)
        for index, entry in enumerate(DROPPERS)
    ]
    return questers.catalogue(
        [row],
        giver_rows,
        spawn_rows,
        [{"item": BANNER, "entry": entry} for entry in DROPPERS],
        [{"quest": QUEST, "kind": "creature", "entry": GIVER}],
        [ended(QUEST, GIVER)],
    )


def member(**changes):
    values = {
        "name": "Test Quester",
        "level": 26,
        "zone_id": WETLANDS,
        "x": 100.0,
        "y": 0.0,
        "quests_done": frozenset({PREVIOUS_QUEST}),
    }
    values.update(changes)
    return mirra(**values)


class WarBannersItemObjective(unittest.TestCase):
    def test_a_quester_takes_hunts_and_turns_in_the_war_banners(self):
        cat = war_banners_world()

        take = questers.plan(cat, member(), questers.Clock(), 0.0)
        self.assertEqual((take.move.kind, take.move.quest), (classquest.TAKE, QUEST))

        holder = member(
            quest_log={QUEST: INCOMPLETE},
            quest_progress={QUEST: 3},
            quest_item_objectives={QUEST: {BANNER: 3}},
        )
        hunt = questers.plan(cat, holder, questers.Clock(), 0.0)
        self.assertEqual((hunt.move.kind, hunt.move.quest), (classquest.HUNT, QUEST))
        self.assertIn(hunt.move.spot.entry, DROPPERS)
        step = questers.step_for(holder, hunt.move, 0, cat.quest(QUEST))
        self.assertEqual(
            step.rows[0].command,
            "hunt-spawn creature:%d item:%d count:8 max:%d"
            % (hunt.move.spot.entry, BANNER, classhunt.MAX_SECONDS),
        )

        complete = member(
            quest_log={QUEST: INCOMPLETE},
            quest_progress={QUEST: 8},
            quest_item_objectives={QUEST: {BANNER: 8}},
        )
        turn_in = questers.plan(cat, complete, questers.Clock(), 0.0)
        self.assertEqual(
            (turn_in.move.kind, turn_in.move.quest), (classquest.TURN_IN, QUEST)
        )

    def test_a_stalled_ledger_row_clears_when_the_quest_is_back_in_the_log(self):
        old = {
            "quest": QUEST,
            "guid": 1,
            "character_name": "Test Quester",
            "state": questledger.BROKEN,
            "first_taken": OLD,
            "finished": OLD,
            "reason": questers.STALLED,
        }

        (entry,) = questledger.changes(
            {1: "Test Quester"},
            [old],
            [{"guid": 1, "quest": QUEST, "status": INCOMPLETE}],
            [],
            NOW,
        )

        self.assertEqual((entry.state, entry.reason), (questledger.TAKEN, ""))


if __name__ == "__main__":
    unittest.main()
