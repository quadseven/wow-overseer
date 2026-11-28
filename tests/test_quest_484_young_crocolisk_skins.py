"""Quest 484's item-objective path from take through turn-in.

The quest level, minimum level, item count and creature entry are the ticket's
world rows. Giver and spawn rows are fixture-only because the ticket has no
giver or creature-spawn rows. Their shapes follow questers.QUESTS_SQL,
classquest.GIVERS_SQL, classquest.SPAWNS_SQL, classquest.LOOT_SQL,
questers.STARTERS_SQL and questers.ENDERS_SQL; the test does not claim those
fixture-only spawns exist in the live world.
"""

import unittest
from dataclasses import replace

import classquest
import questers
from test_questers import HUMAN, PRIEST, ended, giver, mirra, quest, spawn

YOUNG_CROCOLISK_SKINS = 484
YOUNG_CROCOLISK_SKIN = 3397
YOUNG_WETLANDS_CROCOLISK = 1417
WETLANDS = 11
FIXTURE_GIVER = 9002


def quest_world():
    row = quest(
        YOUNG_CROCOLISK_SKINS,
        WETLANDS,
        22,
        min_level=18,
        title="Young Crocolisk Skins",
    )
    row.update(item1=YOUNG_CROCOLISK_SKIN, item_count1=4)
    return questers.catalogue(
        [row],
        [
            giver(YOUNG_CROCOLISK_SKINS, "start", 9001, FIXTURE_GIVER, 0, 0),
            giver(YOUNG_CROCOLISK_SKINS, "end", 9001, FIXTURE_GIVER, 0, 0),
        ],
        [
            spawn(9001, FIXTURE_GIVER, 0, 0, level=20, name="Fixture giver"),
            spawn(
                9002,
                YOUNG_WETLANDS_CROCOLISK,
                100,
                0,
                level=20,
                name="Fixture crocolisk",
            ),
        ],
        [{"item": YOUNG_CROCOLISK_SKIN, "entry": YOUNG_WETLANDS_CROCOLISK}],
        [
            {
                "quest": YOUNG_CROCOLISK_SKINS,
                "kind": "creature",
                "entry": FIXTURE_GIVER,
            }
        ],
        [ended(YOUNG_CROCOLISK_SKINS, FIXTURE_GIVER)],
    )


class AQuesterCanWorkYoungCrocoliskSkins(unittest.TestCase):
    def test_the_item_drop_source_is_hunted_and_the_quest_is_turned_in(self):
        cat = quest_world()
        member = mirra(
            name="Quester A",
            level=22,
            race=HUMAN,
            class_id=PRIEST,
            zone_id=WETLANDS,
            x=0.0,
            y=0.0,
        )

        self.assertTrue(questers.open_to(cat, member, YOUNG_CROCOLISK_SKINS))
        take = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual(
            (take.move.kind, take.move.quest),
            (classquest.TAKE, YOUNG_CROCOLISK_SKINS),
        )

        holding = replace(
            member,
            quest_log={YOUNG_CROCOLISK_SKINS: questers.STATUS_INCOMPLETE},
            quest_progress={YOUNG_CROCOLISK_SKINS: 0},
            quest_item_objectives={YOUNG_CROCOLISK_SKINS: {YOUNG_CROCOLISK_SKIN: 0}},
        )
        hunt = questers.plan(cat, holding, questers.Clock(), 60.0)
        self.assertEqual(
            (hunt.move.kind, hunt.move.quest, hunt.move.spot.entry),
            (classquest.HUNT, YOUNG_CROCOLISK_SKINS, YOUNG_WETLANDS_CROCOLISK),
        )
        step = questers.step_for(
            holding, hunt.move, 30, cat.quest(YOUNG_CROCOLISK_SKINS)
        )
        self.assertEqual(
            step.rows[0].command,
            "hunt-spawn creature:1417 item:3397 count:4 max:480",
        )

        complete = replace(
            holding,
            quest_progress={YOUNG_CROCOLISK_SKINS: 4},
            quest_item_objectives={YOUNG_CROCOLISK_SKINS: {YOUNG_CROCOLISK_SKIN: 4}},
        )
        turn_in = questers.plan(cat, complete, questers.Clock(), 120.0)
        self.assertEqual(
            (turn_in.move.kind, turn_in.move.quest, turn_in.move.spot.entry),
            (classquest.TURN_IN, YOUNG_CROCOLISK_SKINS, FIXTURE_GIVER),
        )


if __name__ == "__main__":
    unittest.main()
