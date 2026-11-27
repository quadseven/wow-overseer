"""Quest 183 uses the objective spawns outside its quest zone.

The fixture takes QuestLevel, MinLevel, RequiredNpcOrGo and its count from the
brief; its 57 spawn coordinates are test-only points in another zone. Its rows
have the shapes read by questers.QUESTS_SQL,
classquest.GIVERS_SQL, classquest.SPAWNS_SQL, classquest.STARTERS_SQL and
questers.ENDERS_SQL. Spawn zones come from the spawn coordinates and
places.zone_id_at; creature.zoneId is not present in classquest.Spawn.
"""

import unittest
from dataclasses import replace

import classquest
import places
import questers
from test_questers import ended, giver, quest, spawn, started, walk

QUEST = 183
BOAR = 708
BOAR_SPAWNS = 57
DUN_MOROGH = 1
ELWYNN = 12
DUN_MOROGH_POINT = (-5600.0, -500.0)
ELWYNN_POINT = (-9500.0, 0.0)
GIVER = 7108


def boar_world():
    """A synthetic fixture matching the brief's objective and spawn counts."""
    row = quest(
        QUEST,
        DUN_MOROGH,
        3,
        min_level=1,
        kill=BOAR,
        count=12,
        title="The Boar Hunter",
    )
    givers = [
        giver(QUEST, "start", 7183, GIVER, *DUN_MOROGH_POINT),
        giver(QUEST, "end", 7184, GIVER, *DUN_MOROGH_POINT),
    ]
    spawns = [
        spawn(
            8000 + index,
            BOAR,
            ELWYNN_POINT[0] + index * 4.0,
            ELWYNN_POINT[1],
            level=3,
        )
        for index in range(BOAR_SPAWNS)
    ]
    return questers.catalogue(
        [row],
        givers,
        spawns,
        [],
        [started(QUEST, GIVER)],
        [ended(QUEST, GIVER)],
    )


def quester(**values):
    defaults = {
        "name": "FixtureQuester",
        "level": 3,
        "race": 3,
        "class_id": 1,
        "map_id": 0,
        "x": DUN_MOROGH_POINT[0],
        "y": DUN_MOROGH_POINT[1],
        "zone_id": DUN_MOROGH,
        "online": True,
    }
    defaults.update(values)
    return questers.Member(**defaults)


class BoarHunterQuest(unittest.TestCase):
    def test_quester_can_finish_by_hunting_spawns_outside_quest_zone(self):
        cat = boar_world()
        self.assertEqual(places.zone_id_at(0, *DUN_MOROGH_POINT), DUN_MOROGH)
        self.assertEqual(places.zone_id_at(0, *ELWYNN_POINT), ELWYNN)
        self.assertEqual(len(cat.quest(QUEST).fields), BOAR_SPAWNS)

        moves, result = walk(quester(), cat)

        self.assertIn((classquest.TAKE, QUEST), moves)
        self.assertIn((classquest.HUNT, QUEST), moves)
        self.assertIn((classquest.TURN_IN, QUEST), moves)
        self.assertIn(QUEST, result.quests_done)

    def test_stall_reason_explains_no_boar_spawn_in_quest_zone(self):
        cat = boar_world()
        holder = quester(
            quest_log={QUEST: questers.STATUS_INCOMPLETE},
            quest_progress={QUEST: 0},
        )
        clock = questers.Clock()
        broken = []
        for seconds in range(0, questers.STALL_SECONDS + 1, 600):
            broken = questers.failures(cat, holder, clock, seconds, last_quest=QUEST)

        self.assertEqual(
            [entry.ledger_reason for entry in broken],
            [
                "%s; its objective creature %d has no spawn in the quest's zone "
                "(%d total in other zones)" % (questers.STALLED, BOAR, BOAR_SPAWNS)
            ],
        )

    def test_unknown_spawn_locations_do_not_claim_the_quest_zone_is_empty(self):
        cat = boar_world()
        original = cat.quest(QUEST)
        unknown = replace(original.fields[-1], x=1e9, y=1e9)
        quest_with_unknown_spawn = replace(
            original, fields=(*original.fields[:-1], unknown)
        )

        reason = questers._broken_reason(
            quest_with_unknown_spawn,
            cat.facts[QUEST],
            questers.STATUS_INCOMPLETE,
            questers.STALL_SECONDS,
            frozenset(),
            {},
        )

        self.assertEqual(reason, questers.STALLED)

    def test_a_spawn_in_the_quest_zone_suppresses_the_zone_note(self):
        cat = boar_world()
        original = cat.quest(QUEST)
        in_zone = replace(
            original.fields[0],
            x=DUN_MOROGH_POINT[0],
            y=DUN_MOROGH_POINT[1],
        )
        quest_with_in_zone_spawn = replace(
            original, fields=(in_zone, *original.fields[1:])
        )

        reason = questers._broken_reason(
            quest_with_in_zone_spawn,
            cat.facts[QUEST],
            questers.STATUS_INCOMPLETE,
            questers.STALL_SECONDS,
            frozenset(),
            {},
        )

        self.assertEqual(reason, questers.STALLED)


if __name__ == "__main__":
    unittest.main()
