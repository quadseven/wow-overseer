"""An item only a chest holds is worked by opening the chest.

The Pocket Watch of quest 64 is looted from a wardrobe, the Honey Ripple of
quest 77 from a supply crate and the four Fragments of quest 299 from relics
and loose soil: gameobject loot, no creature drops any of them. The questers
read creature fields only, so each quest had nothing to hunt, stalled two
hours and was filed broken. The catalogue now reads the chests
(classquest.CHEST_SQL) and the questers open them with the module's
`use-gameobject` row."""

import unittest

import classquest
import questers
from test_questers import ORC, WESTFALL, ended, giver, mirra, quest, spawn

WATCH, WARDROBE = 841, 290
SILVERPINE = 130
HILLSBRAD, RESCUE = 267, 498
LOCKED_BALL_AND_CHAIN = (1721, 1722)
WILD_HEARTS, WORG_HEART = 429, 3164
WORG_ENTRIES = (1765, 1766, 1923, 12431)
# Fixture-only entries: the ticket does not include the giver or spawn rows.
WILD_GIVER, WILD_CHEST = 9002, 9003


def chest_spawn(guid, entry, x, y, map_id=0, name="Wardrobe"):
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": name,
        "rank": 0,
        "level": 0,
        "z": 5.0,
    }


def heirloom_world(chests=True):
    heirloom = quest(64, WESTFALL, 12, title="The Forgotten Heirloom")
    heirloom.update(item1=WATCH, item_count1=1)
    return questers.catalogue(
        [heirloom],
        [giver(64, "start", 1064, 237, 0, 0), giver(64, "end", 1064, 237, 0, 0)],
        [],
        [],
        [{"quest": 64, "kind": "creature", "entry": 237}],
        [{"quest": 64, "kind": "creature", "entry": 237}],
        chest_rows=[{"item": WATCH, "entry": WARDROBE}] if chests else (),
        object_rows=[chest_spawn(2290, WARDROBE, 300.0, 0.0)] if chests else (),
    )


def wild_hearts_world(spawn_droppers=True, spawn_chest=False):
    wild_hearts = quest(WILD_HEARTS, SILVERPINE, 11, min_level=10, title="Wild Hearts")
    wild_hearts.update(item1=WORG_HEART, item_count1=6)
    giver_rows = [
        giver(WILD_HEARTS, "start", 9901, WILD_GIVER, 0, 0, name="Quest giver"),
        giver(WILD_HEARTS, "end", 9901, WILD_GIVER, 0, 0, name="Quest giver"),
    ]
    source_spawns = (
        [
            spawn(9910 + i, entry, 100.0 + 30.0 * i, 0.0, level=11, name="Worg")
            for i, entry in enumerate(WORG_ENTRIES)
        ]
        if spawn_droppers
        else []
    )
    object_rows = [chest_spawn(9990, WILD_CHEST, 250.0, 0.0)] if spawn_chest else []
    return questers.catalogue(
        [wild_hearts],
        giver_rows,
        source_spawns,
        [{"item": WORG_HEART, "entry": entry} for entry in WORG_ENTRIES],
        [{"quest": WILD_HEARTS, "kind": "creature", "entry": WILD_GIVER}],
        [ended(WILD_HEARTS, WILD_GIVER)],
        chest_rows=[{"item": WORG_HEART, "entry": WILD_CHEST}],
        object_rows=object_rows,
    )


def rescue_world(spawned=True):
    rescue = quest(RESCUE, HILLSBRAD, 22, min_level=17, title="The Rescue")
    rescue.update(
        npc1=-LOCKED_BALL_AND_CHAIN[0],
        npc_count1=1,
        npc2=-LOCKED_BALL_AND_CHAIN[1],
        npc_count2=1,
    )
    giver_rows = [
        giver(RESCUE, "start", 9004, 9005, 0.0, 0.0, name="Quest giver"),
        giver(RESCUE, "end", 9004, 9005, 0.0, 0.0, name="Quest giver"),
    ]
    object_rows = (
        [
            chest_spawn(9991, 1721, 100.0, 0.0, name="Locked ball and chain"),
            chest_spawn(9992, 1722, 200.0, 0.0, name="Locked ball and chain"),
        ]
        if spawned
        else []
    )
    return questers.catalogue(
        [rescue],
        giver_rows,
        [],
        [],
        [{"quest": RESCUE, "kind": "creature", "entry": 9005}],
        [ended(RESCUE, 9005)],
        object_rows=object_rows,
    )


def rescue_holder(**kw):
    base = dict(
        level=22,
        race=ORC,
        zone_id=HILLSBRAD,
        x=0.0,
        y=0.0,
        quest_log={RESCUE: questers.STATUS_INCOMPLETE},
        quest_progress={RESCUE: 0},
        quest_objectives={RESCUE: {1721: 0, 1722: 0}},
    )
    base.update(kw)
    return mirra(**base)


def holder(**kw):
    base = dict(
        level=12,
        zone_id=WESTFALL,
        x=0.0,
        y=0.0,
        quest_log={64: questers.STATUS_INCOMPLETE},
        quests_done=frozenset({20, 21}),
        quest_progress={64: 0},
        quest_item_objectives={64: {WATCH: 0}},
    )
    base.update(kw)
    return mirra(**base)


class TheCatalogueReadsTheChest(unittest.TestCase):
    def test_a_required_item_no_creature_drops_is_a_chest_use(self):
        quest64 = heirloom_world().quest(64)
        (use,) = quest64.uses
        self.assertEqual(
            (use.verb, use.item, use.targets),
            (classquest.USE_OBJECT, WATCH, (WARDROBE,)),
        )
        self.assertEqual([s.guid for s in use.spots], [2290])
        self.assertTrue(questers._object_sourced(quest64))

    def test_with_no_chest_rows_the_quest_has_no_use(self):
        self.assertEqual(heirloom_world(chests=False).quest(64).uses, ())

    def test_unspawned_gameobject_loot_does_not_make_an_item_huntable(self):
        # The issue's rows name creature loot and a gameobject loot source for
        # item 3164. Those template rows do not say that any source is spawned.
        # The fixture uses bridge._quester_catalogue's result shapes from
        # questers.QUESTS_SQL, classquest.LOOT_SQL, classquest.SPAWNS_SQL,
        # classquest.CHEST_SQL and classquest.OBJECT_SPAWNS_SQL, with no spawn
        # row for any item source.
        cat = wild_hearts_world(spawn_droppers=False)
        wild_hearts = cat.quest(WILD_HEARTS)
        (use,) = wild_hearts.uses

        self.assertEqual(
            (use.verb, use.item, use.spots), (classquest.USE_OBJECT, WORG_HEART, ())
        )
        self.assertFalse(questers._object_sourced(wild_hearts))
        member = mirra(level=11, zone_id=SILVERPINE)
        self.assertNotIn(WILD_HEARTS, questers.in_reach(cat, member, SILVERPINE))
        self.assertFalse(questers.open_to(cat, member, WILD_HEARTS))

    def test_wild_hearts_ledger_explains_template_rows_without_a_spawn(self):
        cat = wild_hearts_world(spawn_droppers=False)
        holder = mirra(
            level=11,
            zone_id=SILVERPINE,
            quest_log={WILD_HEARTS: questers.STATUS_INCOMPLETE},
            quest_progress={WILD_HEARTS: 0},
            quest_item_objectives={WILD_HEARTS: {WORG_HEART: 0}},
        )
        clock = questers.Clock()
        plan = questers.plan(cat, holder, clock, 0.0, last_quest=WILD_HEARTS)

        for minute in range(1, 13):
            plan = questers.plan(
                cat, holder, clock, 600.0 * minute, last_quest=WILD_HEARTS
            )

        self.assertEqual([b.quest for b in plan.broken], [WILD_HEARTS])
        self.assertEqual(plan.broken[0].reason, questers.STALLED_UNSOURCED)

    def test_wild_hearts_can_take_hunt_and_hand_in_with_spawned_item_sources(self):
        cat = wild_hearts_world(spawn_droppers=True)
        member = mirra(level=11, zone_id=SILVERPINE)

        take = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual(
            (take.move.kind, take.move.quest), (classquest.TAKE, WILD_HEARTS)
        )

        holder = mirra(
            level=11,
            zone_id=SILVERPINE,
            quest_log={WILD_HEARTS: questers.STATUS_INCOMPLETE},
            quest_progress={WILD_HEARTS: 0},
            quest_item_objectives={WILD_HEARTS: {WORG_HEART: 0}},
        )
        hunt = questers.plan(cat, holder, questers.Clock(), 0.0)
        self.assertEqual(
            (hunt.move.kind, hunt.move.quest), (classquest.HUNT, WILD_HEARTS)
        )
        self.assertIn(hunt.move.spot.entry, WORG_ENTRIES)
        step = questers.step_for(holder, hunt.move, 0, cat.quest(WILD_HEARTS))
        self.assertIn("item:%d" % WORG_HEART, step.rows[0].command)

        completed = mirra(
            level=11,
            zone_id=SILVERPINE,
            quest_log={WILD_HEARTS: questers.STATUS_INCOMPLETE},
            quest_progress={WILD_HEARTS: 6},
            quest_item_objectives={WILD_HEARTS: {WORG_HEART: 6}},
        )
        hand_in = questers.plan(cat, completed, questers.Clock(), 0.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, WILD_HEARTS)
        )

    def test_wild_hearts_can_open_a_spawned_gameobject_source(self):
        cat = wild_hearts_world(spawn_droppers=False, spawn_chest=True)
        member = mirra(level=11, zone_id=SILVERPINE)
        take = questers.plan(cat, member, questers.Clock(), 0.0)
        self.assertEqual(
            (take.move.kind, take.move.quest), (classquest.TAKE, WILD_HEARTS)
        )

        holder = mirra(
            level=11,
            zone_id=SILVERPINE,
            quest_log={WILD_HEARTS: questers.STATUS_INCOMPLETE},
            quest_progress={WILD_HEARTS: 0},
            quest_item_objectives={WILD_HEARTS: {WORG_HEART: 0}},
        )
        use = questers.plan(cat, holder, questers.Clock(), 0.0)
        self.assertEqual((use.move.kind, use.move.quest), (classquest.USE, WILD_HEARTS))
        self.assertEqual(use.move.spot.guid, 9990)
        step = questers.step_for(holder, use.move, 0, cat.quest(WILD_HEARTS))
        self.assertEqual(step.rows[0].command, "use-gameobject %d" % WILD_CHEST)

        completed = mirra(
            level=11,
            zone_id=SILVERPINE,
            quest_log={WILD_HEARTS: questers.STATUS_INCOMPLETE},
            quest_progress={WILD_HEARTS: 6},
            quest_item_objectives={WILD_HEARTS: {WORG_HEART: 6}},
        )
        hand_in = questers.plan(cat, completed, questers.Clock(), 0.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, WILD_HEARTS)
        )


class TheQuesterOpensTheChest(unittest.TestCase):
    def test_a_held_chest_quest_is_a_use_move_at_the_chest(self):
        p = questers.plan(heirloom_world(), holder(), questers.Clock(), 0.0)
        self.assertEqual((p.move.kind, p.move.quest), (classquest.USE, 64))
        self.assertEqual(p.move.spot.guid, 2290)
        self.assertIsInstance(p.move.spot, questers.ObjectSpawn)
        self.assertIn("opens", p.move.said)

    def test_the_step_walks_to_the_chest_and_writes_the_use_row(self):
        cat = heirloom_world()
        member = holder()
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, p.move, 0, cat.quest(64))
        self.assertEqual(
            [(r.kind, r.command) for r in step.rows], [("quest", "use-gameobject 290")]
        )
        self.assertTrue(
            step.walk.command.startswith("walk-to-spawn gameobject:2290 near:4")
        )

    def test_beside_the_chest_the_step_writes_the_row_with_no_walk(self):
        cat = heirloom_world()
        member = holder(x=299.0)
        p = questers.plan(cat, member, questers.Clock(), 0.0)
        step = questers.step_for(member, p.move, 0, cat.quest(64))
        self.assertIsNone(step.walk)
        self.assertEqual(step.rows[0].command, "use-gameobject 290")

    def test_an_item_already_counted_leaves_the_chest_alone(self):
        member = holder(quest_item_objectives={64: {WATCH: 1}})
        self.assertEqual(
            questers.object_spots(member, 64, heirloom_world().quest(64)), ()
        )

    def test_a_chest_on_another_map_is_not_walked_to(self):
        cat = heirloom_world()
        far = holder(map_id=1)
        self.assertIsNone(questers._nearest_object(far, 64, cat.quest(64)))

    def test_a_chest_the_walk_left_is_passed_over(self):
        cat = heirloom_world()
        self.assertIsNone(
            questers._nearest_object(holder(), 64, cat.quest(64), frozenset({2290}))
        )


class AChestQuestIsWorkedNotUnsourced(unittest.TestCase):
    def stall(self, cat):
        member = holder()
        clock = questers.Clock()
        p = questers.plan(cat, member, clock, 0.0, last_quest=64)
        self.assertEqual(p.broken, ())
        for i in range(1, 14):
            p = questers.plan(cat, member, clock, 600.0 * i, last_quest=64)
        return p

    def test_a_chest_quest_that_never_moves_stalls_without_claiming_no_source(self):
        p = self.stall(heirloom_world())
        self.assertEqual([b.quest for b in p.broken], [64])
        self.assertEqual(p.broken[0].reason, questers.STALLED)

    def test_a_quest_with_no_chest_read_still_says_unsourced(self):
        p = self.stall(heirloom_world(chests=False))
        self.assertEqual(p.broken[0].reason, questers.STALLED_UNSOURCED)

    def test_a_waiting_chest_quest_does_not_run_the_clock(self):
        # A quest with a chest to open waits its turn, as one with a creature
        # to hunt does; one with nothing to open has its clock run.
        working = questers._working(heirloom_world(), holder(), last_quest=0)
        self.assertNotIn(64, working)
        bare = questers._working(heirloom_world(chests=False), holder(), last_quest=0)
        self.assertIn(64, bare)

    def test_the_stall_reopens_when_a_chest_can_now_be_opened(self):
        held = {64: questers.STALLED}
        self.assertEqual(
            questers.stalled_holds_with_actionable_objectives(
                heirloom_world(), holder(), held
            ),
            frozenset({64}),
        )
        self.assertEqual(
            questers.stalled_holds_with_actionable_objectives(
                heirloom_world(chests=False), holder(), held
            ),
            frozenset(),
        )

    def test_the_hard_coded_heirloom_reason_is_gone(self):
        self.assertFalse(hasattr(questers, "FORGOTTEN_HEIRLOOM"))


def used(age, status="unchanged"):
    """A `use-gameobject 290` row of the quester's own, `age` minutes old."""
    return questers.Attempt(
        "Mirra", "use-gameobject %d" % WARDROBE, status, age_minutes=age
    )


class AChestThatOpenedNothingIsLeftForAWhile(unittest.TestCase):
    """A use the module read back as `unchanged` (the chest opened and nothing
    reached the quest log) was written again every pass: eight rows in
    forty-five minutes for one quester on the dev realm, each one a walk back
    to the same chest. Three such rows inside OBJECT_UNCHANGED_MINUTES leave
    the chest for that long."""

    def test_the_row_reads_which_chest_it_used(self):
        self.assertEqual(used(5).use_entry, WARDROBE)
        self.assertEqual(
            questers.Attempt(
                "Mirra", "walk-to-spawn gameobject:2290", "applied"
            ).use_entry,
            0,
        )

    def test_two_unchanged_uses_do_not_leave_the_chest(self):
        tried = (used(5), used(12))
        p = questers.plan(
            heirloom_world(), holder(), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual(p.move.kind, classquest.USE)

    def test_three_unchanged_uses_leave_the_chest(self):
        tried = (used(5), used(12), used(20))
        cat = heirloom_world()
        self.assertEqual(
            questers.unchanged_object_spawns(cat, "Mirra", tried), frozenset({2290})
        )
        p = questers.plan(cat, holder(), questers.Clock(), 0.0, tried=tried)
        self.assertTrue(p.move is None or p.move.kind != classquest.USE)

    def test_the_chest_is_tried_again_once_the_hold_is_over(self):
        old = questers.OBJECT_UNCHANGED_MINUTES + 1
        tried = (used(old), used(old + 5), used(old + 9))
        p = questers.plan(
            heirloom_world(), holder(), questers.Clock(), 0.0, tried=tried
        )
        self.assertEqual(p.move.kind, classquest.USE)

    def test_a_use_that_took_since_clears_the_count(self):
        tried = (used(2, "applied"), used(5), used(12), used(20))
        self.assertEqual(
            questers.unchanged_object_spawns(heirloom_world(), "Mirra", tried),
            frozenset(),
        )

    def test_another_quester_rows_do_not_count(self):
        other = [
            questers.Attempt(
                "Velo", "use-gameobject %d" % WARDROBE, "unchanged", age_minutes=a
            )
            for a in (5, 12, 20)
        ]
        self.assertEqual(
            questers.unchanged_object_spawns(heirloom_world(), "Mirra", other),
            frozenset(),
        )

    def test_a_refused_use_is_not_an_unchanged_one(self):
        # Moving, too far, held: the chest was never opened, so it says
        # nothing about the chest.
        tried = tuple(used(a, "error") for a in (5, 12, 20))
        self.assertEqual(
            questers.unchanged_object_spawns(heirloom_world(), "Mirra", tried),
            frozenset(),
        )

    def test_the_stall_clock_does_not_treat_a_left_chest_as_work(self):
        tried = (used(5), used(12), used(20))
        left = questers.unchanged_object_spawns(heirloom_world(), "Mirra", tried)
        working = questers._working(
            heirloom_world(), holder(), last_quest=0, object_left=left
        )
        self.assertIn(64, working)


class TheRescueWorksGameobjectObjectives(unittest.TestCase):
    def test_the_fixture_has_the_two_world_objectives_and_spawns(self):
        rescue = rescue_world().quest(RESCUE)
        self.assertEqual(rescue.objects, ((1721, 1), (1722, 1)))
        self.assertEqual(
            [(u.item, u.targets, [s.guid for s in u.spots]) for u in rescue.uses],
            [(0, (1721,), [9991]), (0, (1722,), [9992])],
        )

    def test_a_quester_can_take_use_both_objects_and_hand_in(self):
        cat = rescue_world()
        take = questers.plan(
            cat,
            mirra(level=22, race=ORC, zone_id=HILLSBRAD),
            questers.Clock(),
            0.0,
        )
        self.assertEqual((take.move.kind, take.move.quest), (classquest.TAKE, RESCUE))

        first = questers.plan(cat, rescue_holder(), questers.Clock(), 0.0)
        self.assertEqual((first.move.kind, first.move.quest), (classquest.USE, RESCUE))
        self.assertEqual(first.move.spot.entry, 1721)
        step = questers.step_for(rescue_holder(), first.move, 0, cat.quest(RESCUE))
        self.assertEqual(step.rows[0].command, "use-gameobject 1721")
        self.assertTrue(step.walk.command.startswith("walk-to-spawn gameobject:9991"))

        one_done = rescue_holder(
            quest_progress={RESCUE: 1},
            quest_objectives={RESCUE: {1721: 1, 1722: 0}},
        )
        second = questers.plan(cat, one_done, questers.Clock(), 0.0)
        self.assertEqual(
            (second.move.kind, second.move.quest), (classquest.USE, RESCUE)
        )
        self.assertEqual(second.move.spot.entry, 1722)

        complete = rescue_holder(
            quest_progress={RESCUE: 2},
            quest_objectives={RESCUE: {1721: 1, 1722: 1}},
        )
        hand_in = questers.plan(cat, complete, questers.Clock(), 0.0)
        self.assertEqual(
            (hand_in.move.kind, hand_in.move.quest), (classquest.TURN_IN, RESCUE)
        )
        self.assertEqual(hand_in.broken, ())

    def test_a_waiting_objective_does_not_run_the_stall_clock(self):
        self.assertNotIn(
            RESCUE,
            questers._working(rescue_world(), rescue_holder(), last_quest=0),
        )

    def test_a_worked_objective_stalls_without_claiming_no_objectives(self):
        clock = questers.Clock()
        for minute in range(0, 121, 5):
            plan = questers.plan(
                rescue_world(),
                rescue_holder(),
                clock,
                minute * 60.0,
                last_quest=RESCUE,
            )
        self.assertEqual(
            [(b.quest, b.reason) for b in plan.broken],
            [(RESCUE, questers.STALLED)],
        )

    def test_an_unspawned_objective_explains_the_missing_source(self):
        clock = questers.Clock()
        for minute in range(0, 121, 5):
            plan = questers.plan(
                rescue_world(spawned=False),
                rescue_holder(),
                clock,
                minute * 60.0,
                last_quest=RESCUE,
            )
        self.assertEqual(
            [(b.quest, b.reason) for b in plan.broken],
            [(RESCUE, questers.STALLED_UNSOURCED)],
        )

    def test_log_rows_keep_each_gameobject_objective_counter(self):
        _log, _progress, objectives, _items, _done = questers._logs_by_guid(
            [
                {
                    "guid": 1,
                    "quest": RESCUE,
                    "status": questers.STATUS_INCOMPLETE,
                    "progress": 1,
                    "npc1": -1721,
                    "npc2": -1722,
                    "mobcount1": 1,
                    "mobcount2": 0,
                }
            ],
            [],
        )
        self.assertEqual(objectives[1][RESCUE], {1721: 1, 1722: 0})


if __name__ == "__main__":
    unittest.main()
