"""Battle of Hillsbrad (quest 527): use all four available kill objectives.

The quest and objective counts come from the ticket's world rows. Spawn
multiplicities and map come from the same rows. The fixtures use the shapes of
questers.QUESTS_SQL, questers.LOG_SQL, classquest.GIVERS_SQL and
classquest.SPAWNS_SQL. Coordinates and creature levels only place the test
characters and targets; they are not claims about the live world.
"""

import unittest

import classhunt
import classquest
import questers
import questledger
from test_questers import ORC, PRIEST, giver, quest, spawn, world

HILLSBRAD = 267
QUEST = 527
OBJECTIVES = {2266: 6, 2360: 6, 232: 1, 2403: 1}
SPAWNS_PER_OBJECTIVE = 23
MAP = 0


def battle_catalogue():
    row = quest(QUEST, HILLSBRAD, 24, min_level=19, title="Battle of Hillsbrad")
    for index, (entry, count) in enumerate(OBJECTIVES.items(), start=1):
        row["npc%d" % index] = entry
        row["npc_count%d" % index] = count

    targets = []
    guid = 52700
    for objective_index, entry in enumerate(OBJECTIVES):
        for spawn_index in range(SPAWNS_PER_OBJECTIVE):
            targets.append(
                spawn(
                    guid,
                    entry,
                    100.0 + objective_index * 100.0 + spawn_index,
                    0.0,
                    level=0,
                    map_id=MAP,
                    name="Objective creature",
                )
            )
            guid += 1

    quest_giver = giver(QUEST, "start", 52701, 52702, 0.0, 0.0, map_id=MAP)
    quest_ender = giver(QUEST, "end", 52703, 52704, 0.0, 0.0, map_id=MAP)
    return world(
        extra_quests=[row],
        extra_givers=[quest_giver, quest_ender],
        extra_spawns=targets,
    )


def holder(objectives=None):
    objectives = objectives or {entry: 0 for entry in OBJECTIVES}
    member_row = {
        "guid": 1,
        "name": "TestQuester",
        "level": 24,
        "race": ORC,
        "class_id": PRIEST,
        "online": 1,
        "map_id": MAP,
        "pos_x": 0.0,
        "pos_y": 0.0,
        "zone_id": HILLSBRAD,
    }
    log_row = {
        "guid": 1,
        "quest": QUEST,
        "status": questers.STATUS_INCOMPLETE,
        "progress": sum(objectives.values()),
    }
    for index, entry in enumerate(OBJECTIVES, start=1):
        log_row["npc%d" % index] = entry
        log_row["mobcount%d" % index] = objectives[entry]
    return questers.members_from_rows([member_row], [log_row], [])[0]


class BattleOfHillsbrad(unittest.TestCase):
    def test_hunt_rows_cover_each_objective_and_finish_the_quest(self):
        cat = battle_catalogue()
        member = holder()
        clock = questers.Clock()

        while sum(member.quest_objectives[QUEST].values()) < sum(OBJECTIVES.values()):
            plan = questers.plan(cat, member, clock, 0.0)
            self.assertIsNotNone(plan.move)
            self.assertEqual(
                (plan.move.kind, plan.move.quest), (classquest.HUNT, QUEST)
            )

            step = questers.step_for(member, plan.move, 0.0, cat.quest(QUEST))
            self.assertIsNotNone(step)
            hunt = next(
                row.command for row in step.rows if classhunt.is_hunt_row(row.command)
            )
            self.assertEqual(classhunt.entry_of(hunt), plan.move.spot.entry)

            objectives = dict(member.quest_objectives[QUEST])
            objectives[plan.move.spot.entry] = OBJECTIVES[plan.move.spot.entry]
            member = holder(objectives)

        completed = questers.plan(cat, member, clock, 0.0)
        self.assertEqual(
            (completed.move.kind, completed.move.quest),
            (classquest.TURN_IN, QUEST),
        )

    def test_a_retried_stall_clears_when_the_quest_is_back_in_the_log(self):
        old = {
            "quest": QUEST,
            "guid": 1,
            "character_name": "TestQuester",
            "state": "broken",
            "first_taken": None,
            "finished": None,
            "reason": questers.STALLED,
        }
        changed = questledger.changes(
            {1: "TestQuester"},
            [old],
            [{"quest": QUEST, "guid": 1, "status": questers.STATUS_INCOMPLETE}],
            [],
            None,
        )
        self.assertEqual(
            [(entry.state, entry.reason) for entry in changed], [("taken", "")]
        )


if __name__ == "__main__":
    unittest.main()
