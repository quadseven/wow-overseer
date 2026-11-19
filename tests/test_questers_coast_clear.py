"""A held quest whose objective spawns stand only on the starting isles.

Fixture of the ticket's world rows for quest 152 (The Coast Isn't Clear,
Westfall, level 19, MinLevel 10): kill 7 each of creatures 126, 171, 127
and 517, with spawn totals 25, 33, 22 and 28 in the world and none in the
quest zone. The rows give no map for those spawns, so the fixture stands
them on map 530, the starting isles: the one routed map a quester's hunt
could not see, because it asked classquest.far_map (the two classic
continents only) where classquest.cross_map also knows the Alliance boat
to the isles. A quester that took the quest and then crossed to Kalimdor
holds it with every spawn a boat ride away.
"""

import unittest

import classquest
import questers
from test_questers import WESTFALL, giver, mirra, quest, spawn

DUROTAR = 14
# (entry, spawn total in the world rows, name the rows give)
OBJECTIVES = (
    (126, 25, "Murloc Coastrunner"),
    (171, 33, "Murloc Warrior"),
    (127, 22, "Murloc Tidehunter"),
    (517, 28, "Murloc Oracle"),
)


def coast_catalogue(spawn_map):
    row = quest(
        152,
        WESTFALL,
        19,
        min_level=10,
        kill=126,
        count=7,
        title="The Coast Isn't Clear",
    )
    row.update(npc2=171, npc_count2=7, npc3=127, npc_count3=7, npc4=517, npc_count4=7)
    spawns = []
    guid = 9000
    for entry, total, name in OBJECTIVES:
        for _ in range(total):
            guid += 1
            spawns.append(
                spawn(
                    guid,
                    entry,
                    5000.0 + guid,
                    0.0,
                    level=15,
                    map_id=spawn_map,
                    name=name,
                )
            )
    return questers.catalogue(
        [row],
        [
            giver(152, "start", 8152, 815, 0, 0),
            giver(152, "end", 8152, 815, 400, 0),
        ],
        spawns,
        [],
        [{"quest": 152, "kind": "creature", "entry": 815}],
        [{"quest": 152, "kind": "creature", "entry": 815}],
    )


def holder_on_kalimdor():
    return mirra(
        name="Durga",
        level=19,
        map_id=1,
        zone_id=DUROTAR,
        x=0.0,
        y=0.0,
        quest_log={152: questers.STATUS_INCOMPLETE},
        quest_progress={152: 0},
        quest_objectives={152: {126: 0, 171: 0, 127: 0, 517: 0}},
    )


class HeldCoastQuestOnTheIslesRoute(unittest.TestCase):
    def test_a_held_coast_quest_crosses_to_its_isle_spawns(self):
        cat = coast_catalogue(spawn_map=530)
        holder = holder_on_kalimdor()
        move = questers.plan(cat, holder, questers.Clock(), 0.0).move
        self.assertIsNotNone(move)
        self.assertEqual(
            (move.kind, move.quest, move.to_map),
            (classquest.CROSS, 152, 530),
        )
        arrived = questers.Member(
            **{**holder.__dict__, "map_id": 530, "zone_id": WESTFALL}
        )
        hunt = questers.plan(cat, arrived, questers.Clock(), 0.0).move
        self.assertEqual((hunt.kind, hunt.quest), (classquest.HUNT, 152))
        self.assertIn(hunt.spot.entry, (126, 171, 127, 517))

    def test_a_held_coast_quest_is_huntable_and_its_stall_is_retried(self):
        cat = coast_catalogue(spawn_map=530)
        holder = holder_on_kalimdor()
        self.assertFalse(questers._unhuntable(cat, holder, 152))
        retry = questers.stalled_holds_with_actionable_objectives(
            cat, holder, {152: questers.STALLED}
        )
        self.assertEqual(retry, frozenset({152}))

    def test_a_held_coast_quest_with_spawns_on_no_routed_map_still_stalls(self):
        # The same world rows with the spawns on a map no crossing route
        # reaches: the stall clock still runs and the quest is still
        # found broken, as before.
        cat = coast_catalogue(spawn_map=571)
        holder = mirra(
            name="Durga",
            level=19,
            map_id=0,
            zone_id=WESTFALL,
            x=0.0,
            y=0.0,
            quest_log={152: questers.STATUS_INCOMPLETE},
            quest_progress={152: 0},
            quest_objectives={152: {126: 0, 171: 0, 127: 0, 517: 0}},
        )
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, holder, clock, 600.0 * i)
        self.assertEqual(
            [(b.quest, b.reason) for b in plan.broken],
            [(152, questers.STALLED)],
        )


if __name__ == "__main__":
    unittest.main()
