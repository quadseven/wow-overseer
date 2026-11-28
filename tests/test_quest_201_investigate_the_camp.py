"""Quest 201 Investigate the Camp: why no quester finishes it, from the world rows.

The ticket's world rows: QuestLevel 32, MinLevel 28, Stranglethorn Vale, and
no required item or creature/object rows. Its four ledger rows hold the stall
reason (questers.STALLED), written by bridge._record_quest_broken.

With no objective row there is no counter for a quester's hunt, loot or use to
move, so a held quest cannot progress. The quester pass names that, after two
hours of play, as NO_OBJECTIVES rather than a bare stall, and drops the quest.
No cause beyond the world rows is named here.

The giver/ender entry and spawn position are fixture-only: the ticket lists no
giver, ender or spawn rows.
"""

import unittest

import classhunt
import classquest
import questers
from test_questers import ORC, PRIEST, giver, mirra, quest, world

INVESTIGATE_THE_CAMP = 201
STRANGLETHORN = 33


def camp_world():
    row = quest(
        INVESTIGATE_THE_CAMP,
        STRANGLETHORN,
        32,
        min_level=28,
        title="Investigate the Camp",
    )
    row["npc_count1"] = 0
    return world(
        extra_quests=[row],
        extra_givers=[
            giver(INVESTIGATE_THE_CAMP, "start", 9201, 7201, 0, 0),
            giver(INVESTIGATE_THE_CAMP, "end", 9201, 7201, 0, 0),
        ],
    )


def holder():
    return mirra(
        name="Durga",
        level=32,
        race=ORC,
        class_id=PRIEST,
        zone_id=STRANGLETHORN,
        quest_log={INVESTIGATE_THE_CAMP: questers.STATUS_INCOMPLETE},
    )


def play(cat, member, minutes):
    clock, found, move = questers.Clock(), [], None
    for minute in range(0, minutes + 1, 5):
        p = questers.plan(
            cat, member, clock, minute * 60.0, last_quest=INVESTIGATE_THE_CAMP
        )
        found += [b.reason for b in p.broken if b.quest == INVESTIGATE_THE_CAMP]
        move = p.move or move
    return found, move


class WhyNoQuesterFinishesInvestigateTheCamp(unittest.TestCase):
    def test_the_world_rows_give_it_no_objective(self):
        world_quest = camp_world().quest(INVESTIGATE_THE_CAMP)
        self.assertEqual((world_quest.kills, world_quest.items), ((), ()))
        self.assertEqual(0, classhunt.wanted(world_quest))

    def test_it_is_not_broken_before_two_hours_of_play(self):
        found, _move = play(camp_world(), holder(), 115)
        self.assertEqual([], found)

    def test_two_hours_of_play_name_the_missing_objectives_not_a_stall(self):
        found, move = play(camp_world(), holder(), 120)
        self.assertEqual([questers.NO_OBJECTIVES], found)
        self.assertNotIn(questers.STALLED, found)
        self.assertEqual(
            (move.kind, move.quest), (classquest.ABANDON, INVESTIGATE_THE_CAMP)
        )


if __name__ == "__main__":
    unittest.main()
