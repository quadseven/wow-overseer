"""A held remote item quest crosses continents and preserves local fallback."""

import unittest

import classhunt
import classquest
import guildjobs
import questers
from test_questers import DUROTAR, REDRIDGE, giver, mirra, quest, spawn

DUSKWOOD = 10
DUN_MOROGH = 1
TIRISFAL = 85


class NewPlagueQuest(unittest.TestCase):
    """The ticket's quest and item rows, with synthetic giver geometry.

    The ticket supplies quest 367, level 6, item 2858 x5, and creature
    entries 1547, 1548, and 1549. It says a creature starts the quest but
    does not include giver entries or spawn coordinates, so all spawn
    geometry is modeled here only to exercise the planner's row contract.
    """

    def catalogue(self):
        wanted = quest(
            367,
            TIRISFAL,
            6,
            min_level=6,
            title="A New Plague",
        )
        wanted.update(item1=2858, item_count1=5)
        giver_entry = 99999
        givers = [
            giver(367, "start", 9001, giver_entry, 0, 0, name="Quest NPC"),
            giver(367, "end", 9001, giver_entry, 0, 0, name="Quest NPC"),
        ]
        starters = [{"quest": 367, "kind": "creature", "entry": giver_entry}]
        enders = [{"quest": 367, "kind": "creature", "entry": giver_entry}]
        entries = (1547, 1548, 1549)
        spawns = [
            spawn(9100 + i, entry, 100.0 + i * 10, 0, level=6)
            for i, entry in enumerate(entries)
        ]
        loot = [{"item": 2858, "entry": entry} for entry in entries]
        return questers.catalogue([wanted], givers, spawns, loot, starters, enders)

    def test_the_ticket_objective_rows_support_take_hunt_and_hand_in(self):
        cat = self.catalogue()
        member = mirra(
            name="Quest Tester",
            level=6,
            map_id=0,
            x=0.0,
            y=0.0,
            zone_id=TIRISFAL,
            online=True,
        )

        take = questers.plan(cat, member, questers.Clock(), 0.0).move
        self.assertEqual((take.kind, take.quest), (classquest.TAKE, 367))

        hunting = questers.Member(
            **{
                **member.__dict__,
                "x": 100.0,
                "quest_log": {367: questers.STATUS_INCOMPLETE},
                "quest_progress": {367: 0},
                "quest_item_objectives": {367: {2858: 0}},
            }
        )
        hunt = questers.plan(cat, hunting, questers.Clock(), 0.0).move
        self.assertEqual((hunt.kind, hunt.quest), (classquest.HUNT, 367))
        self.assertIn(hunt.spot.entry, {1547, 1548, 1549})
        self.assertEqual(
            classhunt.command(cat.quest(367), hunt.spot.entry),
            "hunt-spawn creature:%d item:2858 count:5 max:480" % hunt.spot.entry,
        )

        ready = questers.Member(
            **{
                **hunting.__dict__,
                "x": 0.0,
                "quest_progress": {367: 5},
                "quest_item_objectives": {367: {2858: 5}},
            }
        )
        hand_in = questers.plan(cat, ready, questers.Clock(), 0.0).move
        self.assertEqual((hand_in.kind, hand_in.quest), (classquest.TURN_IN, 367))


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

    def _worgen_catalogue(self, spawn_map):
        # Fixture of the ticket's world rows for quest 173 (Worgen in the
        # Woods, Duskwood, level 28): creature 533 x6, 0 spawns in the quest
        # zone, 27 in the world. The spawn rows are of the shape
        # classquest.SPAWNS_SQL reads (creature table: guid, entry, map,
        # position, name, rank, maxlevel); the quest row is of the shape
        # questers.QUESTS_SQL reads. The 27 spawns stand on `spawn_map`,
        # outside the quest zone, so a quester in Duskwood must cross to
        # work them.
        worgen = quest(
            173,
            DUSKWOOD,
            28,
            min_level=23,
            kill=533,
            count=6,
            title="Worgen in the Woods",
        )
        spawns = [
            spawn(
                9000 + i,
                533,
                5000.0 + i * 10,
                0.0,
                level=28,
                map_id=spawn_map,
                name="Nightbane Shadow Weaver",
            )
            for i in range(27)
        ]
        return questers.catalogue(
            [worgen],
            [
                giver(173, "start", 8001, 801, 0, 0),
                giver(173, "end", 8001, 801, 400, 0),
            ],
            spawns,
            [],
            [{"quest": 173, "kind": "creature", "entry": 801}],
            [{"quest": 173, "kind": "creature", "entry": 801}],
        )

    def _worgen_holder(self):
        return mirra(
            name="Durga",
            level=28,
            map_id=0,
            zone_id=DUSKWOOD,
            x=0.0,
            y=0.0,
            quest_log={173: questers.STATUS_INCOMPLETE},
            quest_progress={173: 0},
            quest_objectives={173: {533: 0}},
        )

    def test_a_held_worgen_quest_is_not_stalled_while_its_crossing_stands(self):
        # Quest 173 has no spawn in Duskwood but 27 in the world, on the
        # other continent: _hunt crosses to them, so the stall clock must
        # not run as if nothing could work the quest. Two hours of play
        # standing in Duskwood leave it unbroken, on its crossing move.
        cat = self._worgen_catalogue(spawn_map=1)
        durga = self._worgen_holder()
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, durga, clock, 600.0 * i)
            self.assertEqual(plan.broken, ())
        self.assertEqual(
            (plan.move.kind, plan.move.quest, plan.move.to_map),
            (classquest.CROSS, 173, 1),
        )
        arrived = questers.Member(**{**durga.__dict__, "map_id": 1, "zone_id": DUROTAR})
        hunt = questers.plan(cat, arrived, questers.Clock(), 0.0).move
        self.assertEqual(
            (hunt.kind, hunt.quest, hunt.spot.entry),
            (classquest.HUNT, 173, 533),
        )

    def test_a_held_worgen_quest_with_no_crossing_route_still_stalls(self):
        # The same world rows with the spawns on no classic continent
        # (far_map answers -1): nothing routes to them, so the stall
        # clock still runs and the quest is still found broken.
        cat = self._worgen_catalogue(spawn_map=530)
        durga = self._worgen_holder()
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, durga, clock, 600.0 * i)
        self.assertEqual(
            [(b.quest, b.reason) for b in plan.broken],
            [(173, questers.STALLED)],
        )


class HeldQuestOnTheIslesRoute(unittest.TestCase):
    # Fixture of the ticket's world rows for quest 182 (The Troll Cave,
    # Dun Morogh, level 4): creature 706 x10, 0 spawns in the quest zone,
    # 62 in the world. The rows give no map for the 62, so the fixture
    # stands them on map 530, the starting isles: the one routed map a
    # quester's hunt could not see, because it asked far_map (the two
    # classic continents only) where classquest.cross_map also knows the
    # Alliance boat to the isles. A quester that took the quest and then
    # crossed to Kalimdor holds it with every spawn a boat ride away.
    def _troll_cave_catalogue(self, spawn_map):
        troll_cave = quest(
            182,
            DUN_MOROGH,
            4,
            min_level=1,
            kill=706,
            count=10,
            title="The Troll Cave",
        )
        spawns = [
            spawn(
                9000 + i,
                706,
                5000.0 + i * 10,
                0.0,
                level=5,
                map_id=spawn_map,
                name="Frostmane Troll Whelp",
            )
            for i in range(62)
        ]
        return questers.catalogue(
            [troll_cave],
            [
                giver(182, "start", 8002, 802, 0, 0),
                giver(182, "end", 8002, 802, 400, 0),
            ],
            spawns,
            [],
            [{"quest": 182, "kind": "creature", "entry": 802}],
            [{"quest": 182, "kind": "creature", "entry": 802}],
        )

    def _holder_on_kalimdor(self):
        return mirra(
            name="Mirra",
            level=10,
            race=1,
            map_id=1,
            zone_id=DUROTAR,
            x=0.0,
            y=0.0,
            quest_log={182: questers.STATUS_INCOMPLETE},
            quest_progress={182: 0},
            quest_objectives={182: {706: 0}},
        )

    def test_a_held_troll_cave_quest_crosses_to_its_isle_spawns(self):
        cat = self._troll_cave_catalogue(spawn_map=530)
        holder = self._holder_on_kalimdor()
        move = questers.plan(cat, holder, questers.Clock(), 0.0).move
        self.assertEqual(
            (move.kind, move.quest, move.to_map),
            (classquest.CROSS, 182, 530),
        )
        arrived = questers.Member(
            **{**holder.__dict__, "map_id": 530, "zone_id": DUN_MOROGH}
        )
        hunt = questers.plan(cat, arrived, questers.Clock(), 0.0).move
        self.assertEqual(
            (hunt.kind, hunt.quest, hunt.spot.entry),
            (classquest.HUNT, 182, 706),
        )

    def test_a_held_troll_cave_quest_is_huntable_and_its_stall_is_retried(self):
        cat = self._troll_cave_catalogue(spawn_map=530)
        holder = self._holder_on_kalimdor()
        self.assertFalse(questers._unhuntable(cat, holder, 182))
        retry = questers.stalled_holds_with_actionable_objectives(
            cat, holder, {182: questers.STALLED}
        )
        self.assertEqual(retry, frozenset({182}))

    def test_a_held_troll_cave_quest_with_spawns_on_no_routed_map_still_stalls(self):
        # The same world rows with the spawns on a map no crossing route
        # reaches: the stall clock still runs and the quest is still
        # found broken, as before.
        cat = self._troll_cave_catalogue(spawn_map=571)
        holder = mirra(
            name="Mirra",
            level=10,
            race=3,
            map_id=0,
            zone_id=DUN_MOROGH,
            x=0.0,
            y=0.0,
            quest_log={182: questers.STATUS_INCOMPLETE},
            quest_progress={182: 0},
            quest_objectives={182: {706: 0}},
        )
        clock = questers.Clock()
        plan = None
        for i in range(13):
            plan = questers.plan(cat, holder, clock, 600.0 * i)
        self.assertEqual(
            [(b.quest, b.reason) for b in plan.broken],
            [(182, questers.STALLED)],
        )
