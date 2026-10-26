"""steps.run: one class quest Move in, the orders it sends out (#739).

The executor runs in shadow mode: it sends to a MemoryStore beside the writers
the bridge has, and a log line says whether the two agree. These tests hold
each Move kind to the exact orders, the blocked Move to none, every order to a
verb that grants nothing, and the planner's own steps to a match.
"""

import dataclasses
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import classquest  # noqa: E402
import guildcorps  # noqa: E402
import guildroute  # noqa: E402
import orders  # noqa: E402
import steps  # noqa: E402
import test_natural_only as nat  # noqa: E402
from test_classquest import class_plan, class_steps, who  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

NAME = "Bigzug"
SPAWN = classquest.Spawn(19732, 5810, 1, 186.0, -3597.0, "Veteran Uzzek")
SRC = "guildjobs:classquest:" + NAME
WALK_SRC = "guildjobs:classquest-walk:" + NAME
WALK = "walk-to-spawn creature:19732"


def move(kind, **over):
    fields = dict(quest=1498, klass=1, spot=SPAWN, said="Bigzug does a thing")
    fields.update(over)
    return classquest.Move(kind, **fields)


def order(kind, command, source):
    return orders.Order(
        target=NAME, command=command, source=source, kind=kind, target_arg=""
    )


def sent_by(mv, **kw):
    store = orders.MemoryStore()
    sent = steps.run(mv, store, NAME, **kw)
    rows = [(r["kind"], r["command"], r["source"]) for r in store.rows.values()]
    assert rows == [(o.kind, o.command, o.source) for o in sent], (rows, sent)
    return sent


class EachMoveKind(unittest.TestCase):
    def test_take_walks_to_the_giver_then_takes(self):
        self.assertEqual(
            sent_by(move(classquest.TAKE)),
            [
                order("job", WALK, WALK_SRC),
                order("quest", "take quest:1498", SRC),
            ],
        )

    def test_turnin_walks_to_the_ender_then_hands_in(self):
        self.assertEqual(
            sent_by(move(classquest.TURN_IN)),
            [
                order("job", WALK, WALK_SRC),
                order("quest", "turnin quest:1498", SRC),
            ],
        )

    def test_a_member_beside_the_giver_sends_no_walk(self):
        self.assertEqual(
            sent_by(move(classquest.TAKE), walk=False),
            [order("quest", "take quest:1498", SRC)],
        )

    def test_a_far_walk_asks_for_its_cap(self):
        walk = sent_by(move(classquest.TAKE), cap=5000)[0]
        self.assertEqual(walk.command, WALK + " max:5000")

    def test_hunt_walks_to_the_pack_then_hunts(self):
        hunt = "hunt-spawn creature:5810 count:5 max:600"
        self.assertEqual(
            sent_by(move(classquest.HUNT), hunt=hunt),
            [order("job", WALK, WALK_SRC), order("job", hunt, SRC)],
        )

    def test_a_hunt_with_no_row_is_the_walk_alone(self):
        self.assertEqual(sent_by(move(classquest.HUNT)), [order("job", WALK, SRC)])

    def test_use_walks_to_the_target_then_uses_the_item(self):
        use = classquest.Use(classquest.USE_ITEM, item=6486)
        self.assertEqual(
            sent_by(move(classquest.USE, use=use)),
            [
                order("job", WALK, WALK_SRC),
                order("quest", "use-item-on creature:5810 item:6486", SRC),
            ],
        )

    def test_use_of_an_object_walks_to_the_gameobject(self):
        use = classquest.Use(classquest.USE_OBJECT)
        chest = classquest.Spawn(77, 190584, 609, 1.0, 2.0, "Chest")
        self.assertEqual(
            sent_by(move(classquest.USE, use=use, spot=chest)),
            [
                order("job", "walk-to-spawn gameobject:77", WALK_SRC),
                order("quest", "use-gameobject 190584", SRC),
            ],
        )

    def test_cross_is_one_crossing_row_and_no_walk(self):
        self.assertEqual(
            sent_by(move(classquest.CROSS, to_map=530)),
            [
                order(
                    "job",
                    "cross-to-map map:530",
                    "guildjobs:classquest-cross:" + NAME,
                )
            ],
        )

    def test_abandon_is_one_quest_row_and_no_walk(self):
        self.assertEqual(
            sent_by(move(classquest.ABANDON, spot=None)),
            [order("quest", "abandon quest:1498", SRC)],
        )


class ABlockedMove(unittest.TestCase):
    def test_sends_nothing_and_returns_its_reason(self):
        blocked = move(
            classquest.BLOCKED,
            spot=None,
            blocker=classquest.GROUP,
            why="it asks for a group",
        )
        store = orders.MemoryStore()
        sent = steps.run(blocked, store, NAME)
        self.assertEqual(sent, [])
        self.assertEqual(store.rows, {})
        self.assertEqual(sent.reason, "it asks for a group")


class NothingIsGranted(unittest.TestCase):
    def test_no_order_run_sends_names_a_grant_verb(self):
        use = classquest.Use(classquest.USE_ITEM, item=6486)
        moves = [
            move(classquest.TAKE),
            move(classquest.TURN_IN),
            move(classquest.HUNT),
            move(classquest.USE, use=use),
            move(classquest.CROSS, to_map=530),
            move(classquest.ABANDON, spot=None),
        ]
        verbs = []
        for mv in moves:
            for sent in sent_by(mv, hunt="hunt-spawn creature:5810 max:600"):
                verbs.append(nat._command_verb(sent.command.split()[0]))
        self.assertGreaterEqual(len(verbs), len(moves))
        for verb in verbs:
            self.assertNotIn(verb, nat.GRANT_VERBS)


class TheShadowComparison(unittest.TestCase):
    def planned(self, **over):
        fields = dict(quest_log={}, quests_done=frozenset())
        fields.update(over)
        return class_steps(class_plan([who(NAME, **fields)]))

    def test_a_planned_take_matches_the_rows_the_planner_writes(self):
        (step,) = self.planned()
        self.assertEqual(step.move.kind, classquest.TAKE)
        match, new, old = steps.compare(step, guildroute.FAR_WALK_YARDS)
        self.assertTrue(match, (new, old))

    def test_a_planned_hunt_matches_the_rows_the_planner_writes(self):
        (step,) = self.planned(quest_log={1498: 3}, quests_done=frozenset({1505}))
        self.assertEqual(step.move.kind, classquest.HUNT)
        match, new, old = steps.compare(step, guildroute.FAR_WALK_YARDS)
        self.assertTrue(match, (new, old))

    def test_the_log_line_names_the_member_the_kind_and_the_match(self):
        (step,) = self.planned()
        text = steps.line(step, guildroute.FAR_WALK_YARDS)
        self.assertTrue(
            text.startswith("classquest executor: %s take match=true new=" % NAME),
            text,
        )
        self.assertIn(" old=", text)

    def test_a_row_that_differs_is_a_mismatch(self):
        (step,) = self.planned()
        other = guildcorps.Row("quest", "take quest:1", "", SRC)
        odd = dataclasses.replace(step, rows=(other,))
        self.assertFalse(steps.compare(odd, guildroute.FAR_WALK_YARDS)[0])
        self.assertIn("match=false", steps.line(odd, guildroute.FAR_WALK_YARDS))


class TheMode(unittest.TestCase):
    def mode(self, value):
        old = os.environ.get(steps.MODE_ENV)
        self.addCleanup(
            lambda: (
                os.environ.pop(steps.MODE_ENV, None)
                if old is None
                else os.environ.__setitem__(steps.MODE_ENV, old)
            )
        )
        if value is None:
            os.environ.pop(steps.MODE_ENV, None)
        else:
            os.environ[steps.MODE_ENV] = value
        return steps.mode()

    def test_shadow_is_the_default(self):
        self.assertEqual(self.mode(None), steps.SHADOW)

    def test_off_turns_it_off(self):
        self.assertEqual(self.mode("off"), steps.OFF)

    def test_an_unknown_word_is_an_error(self):
        with self.assertRaises(ValueError):
            self.mode("live")


class TheWiring(unittest.TestCase):
    def test_the_bridge_runs_the_comparison_beside_the_writers(self):
        self.assertIn("steps.line(step, cap)", BRIDGE)
        self.assertIn("self._run_job_step(step, cap)", BRIDGE)

    def test_the_image_carries_the_module(self):
        self.assertIn("steps.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
