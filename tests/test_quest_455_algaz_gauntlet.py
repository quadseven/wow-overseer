"""Quest 455's two creature objectives are routable from its world rows.

The fixture uses the row shapes read by questers.QUESTS_SQL,
classquest.SPAWNS_SQL, questers.MEMBERS_SQL, questers.LOG_SQL, and
questledger's ledger and rewarded queries. Objective ids, counts, and spawn
totals match the ticket's supplied world rows; spawn coordinates and levels
are fixture values only.
"""

import datetime
import unittest

import classhunt
import classquest
import questers
import questledger
from tests.test_questers import giver, quest, spawn


def character_row():
    """One row in the shape returned by questers.MEMBERS_SQL."""
    return {
        "guid": 1,
        "name": "QuestTester",
        "class_id": 5,
        "race": 1,
        "level": 21,
        "online": 1,
        "map_id": 0,
        "saved_zone": 11,
        "pos_x": 10.0,
        "pos_y": 0.0,
        "zone_id": 11,
        "health": 100,
        "has_corpse": 0,
    }


def quest_log_row(status, scouts, grunts):
    """One row in the shape returned by questers.LOG_SQL."""
    return {
        "guid": 1,
        "quest": 455,
        "status": status,
        "progress": scouts + grunts,
        "npc1": 2103,
        "mobcount1": scouts,
        "npc2": 2102,
        "mobcount2": grunts,
    }


class AlgazGauntlet(unittest.TestCase):
    def test_both_objectives_route_to_hunts_and_reward_clears_the_stall(self):
        row = quest(
            455,
            11,
            21,
            min_level=19,
            kill=2103,
            count=8,
            title="The Algaz Gauntlet",
        )
        row.update(npc2=2102, npc_count2=6)
        givers = [
            giver(455, "start", 4550, 2100, 0, 0, name="Quest giver"),
            giver(455, "end", 4550, 2100, 0, 0, name="Quest giver"),
        ]
        starts = [{"quest": 455, "kind": "creature", "entry": 2100}]
        ends = [{"quest": 455, "kind": "creature", "entry": 2100}]
        spawns = [spawn(10000 + i, 2103, 10 + i, 0, level=0) for i in range(17)] + [
            spawn(20000 + i, 2102, 100 + i, 0, level=0) for i in range(17)
        ]
        catalogue = questers.catalogue([row], givers, spawns, [], starts, ends)
        character = character_row()
        clock = questers.Clock()

        (member,) = questers.members_from_rows(
            [character], [quest_log_row(questers.STATUS_INCOMPLETE, 0, 0)], []
        )
        scout = questers.plan(catalogue, member, clock, 0.0)
        self.assertEqual(
            (scout.move.kind, scout.move.quest, scout.move.spot.entry),
            (classquest.HUNT, 455, 2103),
        )
        scout_step = questers.step_for(member, scout.move, 0, catalogue.quest(455))
        self.assertEqual(
            scout_step.rows[0].command,
            "hunt-spawn creature:2103 count:8 max:%d" % classhunt.MAX_SECONDS,
        )

        (member,) = questers.members_from_rows(
            [character], [quest_log_row(questers.STATUS_INCOMPLETE, 8, 0)], []
        )
        grunt = questers.plan(catalogue, member, clock, 600.0)
        self.assertEqual(
            (grunt.move.kind, grunt.move.quest, grunt.move.spot.entry),
            (classquest.HUNT, 455, 2102),
        )
        grunt_step = questers.step_for(member, grunt.move, 0, catalogue.quest(455))
        self.assertEqual(
            grunt_step.rows[0].command,
            "hunt-spawn creature:2102 count:6 max:%d" % classhunt.MAX_SECONDS,
        )

        (complete,) = questers.members_from_rows(
            [character], [quest_log_row(questers.STATUS_COMPLETE, 8, 6)], []
        )
        hand_in = questers.plan(catalogue, complete, clock, 1200.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, 455)
        )

        old_ledger = {
            "quest": 455,
            "guid": 1,
            "character_name": "QuestTester",
            "state": questledger.BROKEN,
            "first_taken": datetime.datetime(2026, 1, 1),
            "finished": datetime.datetime(2026, 1, 1),
            "reason": questers.STALLED,
        }
        [updated] = questledger.changes(
            {1: "QuestTester"},
            [old_ledger],
            [],
            [{"guid": 1, "quest": 455}],
            datetime.datetime(2026, 1, 2),
        )
        self.assertEqual(updated.state, questledger.COMPLETED)
        self.assertEqual(updated.reason, "")

    def test_full_sequence_from_take_to_turn_in(self):
        row = quest(
            455,
            11,
            21,
            min_level=19,
            kill=2103,
            count=8,
            title="The Algaz Gauntlet",
        )
        row.update(npc2=2102, npc_count2=6)
        givers = [
            giver(455, "start", 4550, 2100, 0, 0, name="Quest giver"),
            giver(455, "end", 4550, 2100, 0, 0, name="Quest giver"),
        ]
        starts = [{"quest": 455, "kind": "creature", "entry": 2100}]
        ends = [{"quest": 455, "kind": "creature", "entry": 2100}]
        spawns = [spawn(10000 + i, 2103, 10 + i, 0, level=0) for i in range(17)] + [
            spawn(20000 + i, 2102, 100 + i, 0, level=0) for i in range(17)
        ]
        catalogue = questers.catalogue([row], givers, spawns, [], starts, ends)
        character = character_row()
        clock = questers.Clock()

        # Start with no quest in log
        (member,) = questers.members_from_rows(
            [character], [quest_log_row(questers.STATUS_INCOMPLETE, 0, 0)], []
        )
        # But the quest is not in the log yet - simulate a fresh member
        member = questers.Member(
            **{
                **member.__dict__,
                "quest_log": {},
                "quest_progress": {},
                "quest_objectives": {},
                "quest_item_objectives": {},
            }
        )

        # 1. Take the quest
        take_move = questers.plan(catalogue, member, clock, 0.0)
        self.assertEqual(
            (take_move.move.kind, take_move.move.quest), (classquest.TAKE, 455)
        )

        # 2. After taking, hunt scouts
        member_after_take = questers.Member(
            **{
                **member.__dict__,
                "quest_log": {455: questers.STATUS_INCOMPLETE},
                "quest_progress": {455: 0},
                "quest_objectives": {455: {2103: 0, 2102: 0}},
                "quest_item_objectives": {455: {}},
            }
        )
        scout_move = questers.plan(catalogue, member_after_take, clock, 60.0)
        self.assertEqual(
            (scout_move.move.kind, scout_move.move.quest, scout_move.move.spot.entry),
            (classquest.HUNT, 455, 2103),
        )

        # 3. After 8 scouts, hunt grunts
        member_after_scouts = questers.Member(
            **{
                **member_after_take.__dict__,
                "quest_progress": {455: 8},
                "quest_objectives": {455: {2103: 8, 2102: 0}},
            }
        )
        grunt_move = questers.plan(catalogue, member_after_scouts, clock, 600.0)
        self.assertEqual(
            (grunt_move.move.kind, grunt_move.move.quest, grunt_move.move.spot.entry),
            (classquest.HUNT, 455, 2102),
        )

        # 4. After 6 grunts, turn in
        member_complete = questers.Member(
            **{
                **member_after_scouts.__dict__,
                "quest_log": {455: questers.STATUS_COMPLETE},
                "quest_progress": {455: 14},
                "quest_objectives": {455: {2103: 8, 2102: 6}},
            }
        )
        hand_in = questers.plan(catalogue, member_complete, clock, 1200.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, 455)
        )


if __name__ == "__main__":
    unittest.main()
