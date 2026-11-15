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
from test_questers import WESTFALL, giver, mirra, quest

WATCH, WARDROBE = 841, 290


def chest_spawn(guid, entry, x, y, map_id=0):
    return {
        "guid": guid,
        "entry": entry,
        "map_id": map_id,
        "x": x,
        "y": y,
        "name": "Wardrobe",
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
        self.assertTrue(questers._chested(quest64))

    def test_with_no_chest_rows_the_quest_has_no_use(self):
        self.assertEqual(heirloom_world(chests=False).quest(64).uses, ())


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
            questers.chest_spots(member, 64, heirloom_world().quest(64)), ()
        )

    def test_a_chest_on_another_map_is_not_walked_to(self):
        cat = heirloom_world()
        far = holder(map_id=1)
        self.assertIsNone(questers._nearest_chest(far, 64, cat.quest(64)))

    def test_a_chest_the_walk_left_is_passed_over(self):
        cat = heirloom_world()
        self.assertIsNone(
            questers._nearest_chest(holder(), 64, cat.quest(64), frozenset({2290}))
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


if __name__ == "__main__":
    unittest.main()
