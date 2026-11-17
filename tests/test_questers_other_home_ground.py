"""A quester never hunts on the other faction's home ground (#1912).

A Horde quester died 1045 times to a Darnassus Sentinel between 2026-10-20 and
2026-10-26. A quest it held names a creature that also spawns on Teldrassil,
and the hunt chose the spawn nearest the quester. Teldrassil (with Darnassus on
it) is the Alliance's island; its guards kill a Horde member on sight. The hunt
now skips every spawn on the other side's island, and the quester takes the
next spawn or the crossing instead.
"""

import unittest

import classquest
import questers
from test_questers import DUROTAR, giver, mirra, quest, spawn, started, ended

TAUREN = 6
ELF = 4
KALIMDOR = 1
# Teldrassil's box on map 1 is x 8437..11831, y -1277..3814 (weaponskill.ISLANDS).
ISLAND = (9000.0, 100.0)
MAINLAND = (-400.0, -2000.0)


def cat(*spawns):
    q = quest(900, DUROTAR, 10, kill=703, count=5, title="Webwood Pelts")
    return questers.catalogue(
        [q],
        [
            giver(900, "start", 5900, 900, -450.0, -2000.0, map_id=KALIMDOR),
            giver(900, "end", 5900, 900, -450.0, -2000.0, map_id=KALIMDOR),
        ],
        list(spawns),
        [],
        [started(900, 900)],
        [ended(900, 900)],
    )


def member(race, x=8800.0, y=100.0):
    return mirra(
        name="Tahomi",
        level=10,
        race=race,
        map_id=KALIMDOR,
        x=x,
        y=y,
        zone_id=DUROTAR,
        quest_log={900: questers.STATUS_INCOMPLETE},
        quest_progress={900: 0},
        quest_objectives={900: {703: 0}},
    )


def on_island(guid=6001):
    return spawn(guid, 703, *ISLAND, level=10, map_id=KALIMDOR)


def on_mainland(guid=6002):
    return spawn(guid, 703, *MAINLAND, level=10, map_id=KALIMDOR)


class AHordeQuesterSkipsTheAllianceIsland(unittest.TestCase):
    def test_it_hunts_the_mainland_spawn_though_the_island_one_is_nearer(self):
        move = questers.plan(
            cat(on_island(), on_mainland()), member(TAUREN), questers.Clock(), 0.0
        ).move
        self.assertEqual(classquest.HUNT, move.kind)
        self.assertEqual(6002, move.spot.guid)

    def test_a_quest_with_only_island_spawns_is_not_hunted(self):
        move = questers.plan(
            cat(on_island()), member(TAUREN), questers.Clock(), 0.0
        ).move
        self.assertTrue(move is None or move.kind != classquest.HUNT, move)

    def test_the_field_list_drops_island_spawns_for_the_horde_only(self):
        c = cat(on_island(), on_mainland())
        quest_ = c.quest(900)
        horde = questers._held_objective_fields(member(TAUREN), 900, quest_)
        alliance = questers._held_objective_fields(member(ELF), 900, quest_)
        self.assertEqual({6002}, {s.guid for s in horde})
        self.assertEqual({6001, 6002}, {s.guid for s in alliance})


if __name__ == "__main__":
    unittest.main()
