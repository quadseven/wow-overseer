"""A held remote item quest crosses continents and preserves local fallback."""

import unittest

import classquest
import guildjobs
import questers
from test_questers import DUROTAR, REDRIDGE, giver, mirra, quest, spawn


class HeldRemoteItemObjectives(unittest.TestCase):
    def test_a_held_fangore_quest_crosses_to_its_item_dropper(self):
        wanted = quest(180, REDRIDGE, 26, title="Wanted: Lieutenant Fangore")
        wanted.update(item1=3632, item_count1=1)
        cat = questers.catalogue(
            [wanted],
            [
                giver(180, "start", 5180, 187, 0, 0),
                giver(180, "end", 5181, 187, 400, 0),
            ],
            [spawn(5703, 703, 100, 0, level=26, map_id=0)],
            [{"item": 3632, "entry": 703}],
            [{"quest": 180, "kind": "creature", "entry": 187}],
            [{"quest": 180, "kind": "creature", "entry": 187}],
        )
        sylvi = mirra(
            name="Sylvi",
            level=28,
            race=4,
            map_id=1,
            zone_id=1657,
            quest_log={180: questers.STATUS_INCOMPLETE},
            quest_progress={180: 0},
            quest_objectives={180: {}},
        )

        move = questers.plan(cat, sylvi, questers.Clock(), 0.0).move

        self.assertEqual(
            (move.kind, move.quest, move.to_map), (classquest.CROSS, 180, 0)
        )
        arrived = questers.Member(
            **{**sylvi.__dict__, "map_id": 0, "zone_id": REDRIDGE}
        )
        hunt = questers.plan(cat, arrived, questers.Clock(), 0.0).move
        self.assertEqual(
            (hunt.kind, hunt.quest, hunt.spot.entry), (classquest.HUNT, 180, 703)
        )

    def test_a_failed_held_quest_crossing_leaves_other_zones_available(self):
        wanted = quest(180, REDRIDGE, 26, title="Wanted: Lieutenant Fangore")
        wanted.update(item1=3632, item_count1=1)
        elsewhere = quest(181, DUROTAR, 28, title="A Durotar Errand")
        cat = questers.catalogue(
            [wanted, elsewhere],
            [
                giver(180, "start", 5180, 187, 0, 0),
                giver(180, "end", 5181, 187, 400, 0),
                giver(181, "start", 5182, 188, 100, 100, map_id=1),
                giver(181, "end", 5183, 188, 200, 200, map_id=1),
            ],
            [spawn(5703, 703, 100, 0, level=26, map_id=0)],
            [{"item": 3632, "entry": 703}],
            [
                {"quest": 180, "kind": "creature", "entry": 187},
                {"quest": 181, "kind": "creature", "entry": 188},
            ],
            [
                {"quest": 180, "kind": "creature", "entry": 187},
                {"quest": 181, "kind": "creature", "entry": 188},
            ],
        )
        sylvi = mirra(
            name="Sylvi",
            level=28,
            race=4,
            map_id=1,
            zone_id=1657,
            quest_log={180: questers.STATUS_INCOMPLETE},
        )
        crossing = {
            "id": 7,
            "target_name": "Sylvi",
            "command": "cross-to-map map:0",
            "source": "guildjobs:quester-cross:Sylvi",
            "status": "error",
            "result": '{"outcome":"refused","reason":"no transport the module knows sails from this map to that map for this faction","retry":false,"map":0,"steps":0}',
            "age": 2,
        }

        plan = questers.plan(
            cat,
            sylvi,
            questers.Clock(),
            0.0,
            crossings=guildjobs.recent_from_rows([crossing]),
        )

        self.assertEqual((plan.move.kind, plan.move.quest), (classquest.TAKE, 181))
