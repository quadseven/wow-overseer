"""A class quest on the other continent is a crossing, not a blocker.

Measured on the dev realm on 2026-10-08: members were held by MAP blockers
because every giver or objective spawn of their class quest was a boat or
zeppelin away (a druid's Moonglade, a shaman's Call of Earth, a warrior's The
Affray, a hunter's Taming the Beast, a warlock's The Stone, a paladin's
Redemption), while the module already carried `cross-to-map map:<id>`
(quadseven/mod-overseer, kind='job', any bot). These tests hold the planner to
that row, to one crossing in flight per member, to the module's own refusals
(the verb off, no transport for the faction) as the honest blocker, and to the
members it must not move.
"""

import json
import pathlib
import unittest

import classquest
import guildjobs
from test_classquest import EASTERN, KALIMDOR, UNDEAD, book, class_plan, who

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

OFF = "crossing is off (Overseer.Cross.Enable)"
NO_ROUTE = (
    "no transport the module knows sails from this map to that map for this faction"
)


def eastern(name="Bigzug", **over):
    """An Undead warrior on Eastern Kingdoms whose chain starts on Kalimdor."""
    base = dict(
        race=UNDEAD,
        map_id=EASTERN,
        x=2300.0,
        y=400.0,
        quests_done=frozenset({1818}),
        quest_log={},
    )
    base.update(over)
    return who(name, **base)


def crossing_row(name, age, status="applied", dest=KALIMDOR, reason=None, retry=False):
    result = ""
    if reason:
        body = {"outcome": "refused", "reason": reason, "retryable": retry}
        result = json.dumps(body, separators=(",", ":"))
    row = {
        "id": 900,
        "target_name": name,
        "command": "cross-to-map map:%d" % dest,
        "source": guildjobs.source_for(classquest.CROSS_ACTION, name),
        "status": status,
        "age": age,
        "result": result,
    }
    return guildjobs.recent_from_rows([row])[0]


def cross_steps(result):
    return [
        s for s in result.steps if s.rows and classquest.is_cross_row(s.rows[0].command)
    ]


class TheMove(unittest.TestCase):
    def test_every_spawn_on_the_other_continent_is_a_crossing(self):
        move, blocked = classquest.next_move(book(), eastern())
        self.assertEqual((move.kind, move.to_map), (classquest.CROSS, KALIMDOR))
        self.assertEqual(blocked, [])
        self.assertIn("Kalimdor", move.said)

    def test_a_refused_crossing_keeps_a_named_blocker(self):
        m = eastern(no_crossing={KALIMDOR: NO_ROUTE})
        move, blocked = classquest.next_move(book(), m)
        self.assertIsNone(move)
        self.assertIn("Kalimdor", blocked[0])
        self.assertIn("no transport the module knows", blocked[0])

    def test_a_refusal_for_another_map_does_not_block_this_one(self):
        m = eastern(no_crossing={530: NO_ROUTE})
        move, _blocked = classquest.next_move(book(), m)
        self.assertEqual(move.kind, classquest.CROSS)

    def test_a_map_no_boat_reaches_stays_a_blocker(self):
        m = eastern(map_id=530, x=0.0, y=0.0)
        move, blocked = classquest.next_move(book(), m)
        self.assertIsNone(move)
        self.assertIn("map", blocked[0])

    def test_a_quest_with_a_spawn_on_the_members_map_is_walked_not_crossed(self):
        move, _blocked = classquest.next_move(book(), who())
        self.assertNotEqual(move.kind, classquest.CROSS)


class TheStep(unittest.TestCase):
    def test_the_step_is_one_cross_row_and_no_walk(self):
        steps = cross_steps(class_plan([eastern()]))
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertIsNone(step.walk)
        self.assertEqual(len(step.rows), 1)
        row = step.rows[0]
        self.assertEqual((row.kind, row.command), ("job", "cross-to-map map:1"))
        self.assertEqual(
            row.source, guildjobs.source_for(classquest.CROSS_ACTION, "Bigzug")
        )
        self.assertEqual(step.action, classquest.ACTION)

    def test_a_crossing_row_in_flight_holds_the_member_with_no_second_row(self):
        recent = (crossing_row("Bigzug", 5, status="verifying"),)
        result = class_plan([eastern()], recent=recent)
        self.assertEqual(cross_steps(result), [])
        self.assertIn(classquest.MARK, result.lines["Bigzug"])

    def test_the_member_crosses_again_after_the_cooldown(self):
        age = classquest.CROSS_COOLDOWN_MINUTES
        result = class_plan([eastern()], recent=(crossing_row("Bigzug", age),))
        self.assertEqual(len(cross_steps(result)), 1)

    def test_the_cooldown_is_longer_than_the_modules_own_backstop(self):
        self.assertGreater(classquest.CROSS_COOLDOWN_MINUTES, 30)

    def test_a_retryable_refusal_is_asked_again_sooner(self):
        full = "the realm already has as many crossings as it allows"
        row = crossing_row("Bigzug", 12, "error", reason=full, retry=True)
        self.assertEqual(len(cross_steps(class_plan([eastern()], recent=(row,)))), 1)
        young = crossing_row("Bigzug", 3, "error", reason=full, retry=True)
        self.assertEqual(cross_steps(class_plan([eastern()], recent=(young,))), [])

    def test_another_members_row_holds_nobody_else(self):
        result = class_plan([eastern()], recent=(crossing_row("Other", 5),))
        self.assertEqual(len(cross_steps(result)), 1)

    def test_a_dead_member_is_not_sent(self):
        result = class_plan([eastern(alive=False)])
        self.assertEqual(cross_steps(result), [])
        self.assertTrue(any("dead" in n for n in result.notes))

    def test_a_member_on_another_walk_or_run_is_not_sent(self):
        result = class_plan([eastern()], busy={"Bigzug"})
        self.assertEqual(cross_steps(result), [])

    def test_an_offline_or_fighting_member_is_not_sent(self):
        self.assertEqual(cross_steps(class_plan([eastern(online=False)])), [])
        self.assertEqual(cross_steps(class_plan([eastern(in_combat=True)])), [])

    def test_a_member_standing_in_an_instance_is_never_sent(self):
        # An instance has its own map id; only the two continents cross.
        self.assertEqual(cross_steps(class_plan([eastern(map_id=36)])), [])
        self.assertEqual(cross_steps(class_plan([eastern(map_id=389)])), [])

    def test_a_member_with_an_unread_position_is_not_sent(self):
        self.assertEqual(cross_steps(class_plan([eastern(map_id=None)])), [])


class TheWalls(unittest.TestCase):
    def test_the_modules_refusal_is_read_from_the_row(self):
        row = crossing_row("Bigzug", 20, "error", reason=NO_ROUTE)
        self.assertEqual(row.dest, KALIMDOR)
        self.assertEqual(guildjobs.class_walls("Bigzug", (row,)), {KALIMDOR: NO_ROUTE})

    def test_a_refused_crossing_is_not_asked_again_for_hours(self):
        recent = (crossing_row("Bigzug", 60, "error", reason=OFF),)
        result = class_plan([eastern()], recent=recent)
        self.assertEqual(cross_steps(result), [])
        self.assertTrue(any("Overseer.Cross.Enable" in n for n in result.notes))
        self.assertIn("Bigzug", result.owed)

    def test_the_wall_lapses(self):
        age = classquest.CROSS_WALL_MINUTES
        recent = (crossing_row("Bigzug", age, "error", reason=OFF),)
        self.assertEqual(guildjobs.class_walls("Bigzug", recent), {})
        self.assertEqual(len(cross_steps(class_plan([eastern()], recent=recent))), 1)

    def test_a_later_row_that_was_not_refused_lifts_the_wall(self):
        recent = (
            crossing_row("Bigzug", 400, "error", reason=NO_ROUTE),
            crossing_row("Bigzug", 100),
        )
        self.assertEqual(guildjobs.class_walls("Bigzug", recent), {})

    def test_a_passing_refusal_is_no_wall(self):
        for why in ("the character is in combat", "the character is dead"):
            row = crossing_row("Bigzug", 20, "error", reason=why, retry=True)
            self.assertEqual(guildjobs.class_walls("Bigzug", (row,)), {})

    def test_a_walk_row_is_no_crossing_row(self):
        walk = guildjobs.recent_from_rows(
            [
                {
                    "target_name": "Bigzug",
                    "command": "walk-to-spawn creature:1",
                    "source": guildjobs.source_for("classquest-walk", "Bigzug"),
                    "status": "error",
                    "age": 5,
                    "result": "",
                }
            ]
        )[0]
        self.assertEqual(walk.dest, 0)
        self.assertFalse(guildjobs.crossing_cooling("Bigzug", (walk,)))


class TheWiring(unittest.TestCase):
    def test_the_bridge_writes_the_row_once_and_does_not_follow_it_to_the_end(self):
        self.assertIn("classquest.is_cross_row(row.command)", BRIDGE)
        self.assertIn("async def _class_cross_row", BRIDGE)

    def test_the_verb_is_the_modules(self):
        self.assertEqual(classquest.cross_command(1), "cross-to-map map:1")
        self.assertTrue(classquest.is_cross_row("cross-to-map map:0"))
        self.assertFalse(classquest.is_cross_row("walk-to-spawn creature:1"))


if __name__ == "__main__":
    unittest.main()
