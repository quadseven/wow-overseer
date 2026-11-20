"""Quest 263: In Defense of the King's Lands (#2349).

World rows: required creatures 1197 (Stonesplinter Shaman) x10 and 1164
(Stonesplinter Bonesnapper) x10 have 0 spawn(s) on the quest's map and
23/17 spawns total. With no objective spawn on the quest's map a quester
cannot finish the quest; this is named from those rows.
"""

import unittest

import questers
from test_questers import giver, mirra, quest, spawn

LOCH_MODAN = 38
EASTERN_KINGDOMS = 0
KALIMDOR = 1
HUMAN = 1
QUEST = 263
PREV = 237
SHAMAN = 1197
BONESNAPPER = 1164


def defence_catalogue(on_map=0, off_map_shaman=23, off_map_bonesnapper=17):
    row = quest(
        QUEST,
        LOCH_MODAN,
        15,
        min_level=10,
        prev=PREV,
        kill=SHAMAN,
        count=10,
        title="In Defense of the King's Lands",
    )
    row.update(kill2=BONESNAPPER, count2=10)
    spawns = []
    for i in range(on_map):
        spawns.append(
            spawn(
                8100 + i,
                SHAMAN,
                -5000.0 + 10 * i,
                -3000.0,
                level=14,
                map_id=EASTERN_KINGDOMS,
                name="Stonesplinter Shaman",
            )
        )
        spawns.append(
            spawn(
                8200 + i,
                BONESNAPPER,
                -5020.0 + 10 * i,
                -3020.0,
                level=14,
                map_id=EASTERN_KINGDOMS,
                name="Stonesplinter Bonesnapper",
            )
        )
    for i in range(off_map_shaman):
        spawns.append(
            spawn(
                9100 + i,
                SHAMAN,
                1000.0 + 10 * i,
                1000.0,
                level=14,
                map_id=KALIMDOR,
                name="Stonesplinter Shaman",
            )
        )
    for i in range(off_map_bonesnapper):
        spawns.append(
            spawn(
                9200 + i,
                BONESNAPPER,
                1100.0 + 10 * i,
                1100.0,
                level=14,
                map_id=KALIMDOR,
                name="Stonesplinter Bonesnapper",
            )
        )
    return questers.catalogue(
        [row],
        [
            giver(
                QUEST,
                "start",
                90263,
                1092,
                -4821.0,
                -2695.0,
                map_id=EASTERN_KINGDOMS,
                name="Mountaineer Cobbleflint",
            ),
            giver(
                QUEST,
                "end",
                90263,
                1092,
                -4821.0,
                -2695.0,
                map_id=EASTERN_KINGDOMS,
                name="Mountaineer Cobbleflint",
            ),
        ],
        spawns,
        [],
        [{"quest": QUEST, "kind": "creature", "entry": 1092}],
        [{"quest": QUEST, "kind": "creature", "entry": 1092}],
    )


def bromli(**kw):
    base = dict(
        name="Bromli",
        level=15,
        race=HUMAN,
        map_id=EASTERN_KINGDOMS,
        zone_id=LOCH_MODAN,
        x=-4800.0,
        y=-2700.0,
        quests_done=frozenset({PREV}),
    )
    base.update(kw)
    return mirra(**base)


class Quest263InDefenseOfTheKingsLands(unittest.TestCase):
    def test_objectives_off_the_quest_map_cannot_be_finished(self):
        cat = defence_catalogue(on_map=0, off_map_shaman=23, off_map_bonesnapper=17)
        member = bromli(quest_log={QUEST: questers.STATUS_INCOMPLETE})
        clock = questers.Clock()
        broken = []
        for i in range(14):
            plan = questers.plan(cat, member, clock, 600.0 * i)
            broken.extend(plan.broken)
        reasons = " ".join(str(b.reason) for b in broken)
        self.assertTrue(broken)
        self.assertIn("no spawn on the quest's map", reasons)


if __name__ == "__main__":
    unittest.main()
