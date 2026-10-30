import unittest
import os
import pathlib
import sys

import classquest

sys.path.insert(0, os.path.dirname(__file__))
import test_orders  # noqa: E402,F401
import orders  # noqa: E402
import steps  # noqa: E402


def move(kind, **values):
    return classquest.Move(kind, said="Example does a class quest", **values)


class ClassQuestStepsTests(unittest.TestCase):
    def sent(self, quest_move):
        store = orders.MemoryStore()
        result = steps.run(quest_move, store)
        rows = list(store.rows.values())
        return result, [
            (r["target_name"], r["command"], r["kind"], r["source"]) for r in rows
        ]

    def test_take_sends_quest_order(self):
        result, rows = self.sent(move(classquest.TAKE, quest=42))
        self.assertEqual(
            result,
            [
                orders.Order(
                    "Example", "take quest:42", "guildjobs:classquest:Example", "quest"
                )
            ],
        )
        self.assertEqual(
            rows,
            [("Example", "take quest:42", "quest", "guildjobs:classquest:Example")],
        )

    def test_hunt_sends_hunt_job(self):
        spot = classquest.Spawn(1, 123, 1, 0, 0, "Target")
        result, rows = self.sent(move(classquest.HUNT, quest=42, spot=spot))
        expected = orders.Order(
            "Example",
            "hunt-spawn creature:123 max:480",
            "guildjobs:classquest:Example",
            "job",
        )
        self.assertEqual(result, [expected])
        self.assertEqual(rows, [("Example", expected.command, "job", expected.source)])

    def test_turnin_sends_quest_order(self):
        result, rows = self.sent(move(classquest.TURN_IN, quest=42))
        expected = orders.Order(
            "Example", "turnin quest:42", "guildjobs:classquest:Example", "quest"
        )
        self.assertEqual(result, [expected])
        self.assertEqual(
            rows, [("Example", expected.command, "quest", expected.source)]
        )

    def test_use_sends_quest_order(self):
        spot = classquest.Spawn(1, 123, 1, 0, 0, "Target")
        use = classquest.Use(classquest.USE_OBJECT, targets=(123,))
        result, rows = self.sent(move(classquest.USE, quest=42, spot=spot, use=use))
        expected = orders.Order(
            "Example",
            classquest.use_command(use, spot),
            "guildjobs:classquest:Example",
            "quest",
        )
        self.assertEqual(result, [expected])
        self.assertEqual(
            rows, [("Example", expected.command, "quest", expected.source)]
        )

    def test_cross_sends_crossing_job(self):
        result, rows = self.sent(move(classquest.CROSS, quest=42, to_map=1))
        expected = orders.Order(
            "Example", "cross-to-map map:1", "guildjobs:classquest:Example", "job"
        )
        self.assertEqual(result, [expected])
        self.assertEqual(rows, [("Example", expected.command, "job", expected.source)])

    def test_abandon_sends_quest_order(self):
        result, rows = self.sent(move(classquest.ABANDON, quest=42))
        expected = orders.Order(
            "Example", "abandon quest:42", "guildjobs:classquest:Example", "quest"
        )
        self.assertEqual(result, [expected])
        self.assertEqual(
            rows, [("Example", expected.command, "quest", expected.source)]
        )

    def test_blocked_move_sends_nothing_and_returns_reason(self):
        blocked = move(classquest.BLOCKED, quest=42, why="missing trainer")
        result, rows = self.sent(blocked)
        self.assertEqual(result, "missing trainer")
        self.assertEqual(rows, [])

    def test_move_missing_its_target_or_quest_or_spot_fails_and_sends_nothing(self):
        spot = classquest.Spawn(1, 123, 1, 0, 0)
        cases = (
            classquest.Move(classquest.TAKE, quest=42, said=None),
            classquest.Move(classquest.TAKE, quest=42, said=""),
            move(classquest.TURN_IN, quest=None),
            move(classquest.HUNT, quest=42, spot=None),
            move(classquest.HUNT, quest=None, spot=spot),
        )
        for quest_move in cases:
            with self.subTest(move=quest_move):
                store = orders.MemoryStore()
                with self.assertRaises(ValueError):
                    steps.run(quest_move, store)
                self.assertEqual(store.rows, {})

    def test_sent_orders_do_not_grant_items_gold_or_xp(self):
        from test_natural_only import GRANT_VERBS, _command_verb

        cases = (
            move(classquest.TAKE, quest=42),
            move(classquest.HUNT, quest=42, spot=classquest.Spawn(1, 123, 1, 0, 0)),
            move(classquest.TURN_IN, quest=42),
            move(
                classquest.USE,
                quest=42,
                spot=classquest.Spawn(1, 123, 1, 0, 0),
                use=classquest.Use(classquest.USE_OBJECT, targets=(123,)),
            ),
            move(classquest.CROSS, quest=42, to_map=1),
            move(classquest.ABANDON, quest=42),
        )
        verbs = set()
        for quest_move in cases:
            with self.subTest(kind=quest_move.kind):
                sent, _rows = self.sent(quest_move)
                self.assertIsInstance(sent, list)
                self.assertTrue(sent, "the move sent no order to check")
                for order in sent:
                    # _command_verb reads only a bare word or a dotted GM
                    # command; an order carries arguments, so read its verb.
                    verb = _command_verb(order.command.split(" ", 1)[0])
                    self.assertIsNotNone(verb, order.command)
                    self.assertNotIn(verb, GRANT_VERBS, order.command)
                    verbs.add(verb)
        self.assertEqual(
            verbs,
            {
                "take",
                "hunt-spawn",
                "turnin",
                "use-gameobject",
                "cross-to-map",
                "abandon",
            },
        )


if __name__ == "__main__":
    unittest.main()


# SHADOW MODE (quadseven/wow-overseer#739): the bridge asks the executor what it
# would send for each class quest step and logs it beside the rows it writes.
import logging  # noqa: E402
from unittest import mock  # noqa: E402

from test_guildsocial_bridge import bridge  # noqa: E402
import guildcorps  # noqa: E402
from test_classquest import class_plan, class_steps, who  # noqa: E402


def planned_step(**over):
    over.setdefault("quests_done", frozenset({1505}))
    steps_ = class_steps(class_plan([who(**over)]))
    assert len(steps_) == 1
    return steps_[0]


class TheShadowMode(unittest.TestCase):
    def test_the_step_carries_the_move_it_carries_out(self):
        step = planned_step()
        self.assertEqual(step.move.kind, classquest.TAKE)
        self.assertEqual(step.move.quest, 1498)

    def test_a_take_matches_the_row_the_bridge_writes(self):
        step = planned_step()
        self.assertEqual(
            steps.shadow_line(step.move, step.rows),
            "classquest executor: Bigzug take match=true"
            " new=quest/take quest:1498 old=quest/take quest:1498",
        )

    def test_a_hunt_that_writes_a_walk_does_not_match_and_says_so(self):
        step = planned_step(quest_log={1498: 3})
        line = steps.shadow_line(step.move, step.rows)
        self.assertIn("Bigzug hunt match=false", line)
        self.assertIn("new=job/hunt-spawn creature:", line)
        self.assertIn("old=job/walk-to-spawn creature:", line)

    def test_a_blocked_move_names_no_order_on_either_side(self):
        line = steps.shadow_line(move(classquest.BLOCKED, why="no spawn"), ())
        self.assertEqual(
            line,
            "classquest executor: Example blocked match=true new=- old=-",
        )

    def test_the_comparison_writes_nothing_to_the_realm(self):
        step = planned_step()
        with mock.patch.object(orders.MySqlStore, "insert") as insert:
            steps.shadow_line(step.move, step.rows)
        insert.assert_not_called()

    def test_the_mode_is_shadow_unless_the_variable_says_otherwise(self):
        self.assertEqual(steps.mode({}), steps.SHADOW)
        self.assertEqual(steps.mode({"CLASSQUEST_EXECUTOR": "shadow"}), steps.SHADOW)
        self.assertEqual(steps.mode({"CLASSQUEST_EXECUTOR": "off"}), steps.OFF)
        self.assertEqual(steps.mode({"CLASSQUEST_EXECUTOR": "live"}), steps.OFF)


class TheBridgeLogsTheComparison(unittest.TestCase):
    def setUp(self):
        bridge._SHADOW_FAILED = False

    def test_a_class_step_logs_one_line(self):
        step = planned_step()
        with self.assertLogs(bridge.log, logging.INFO) as logged:
            bridge._shadow_class_step(step)
        self.assertEqual(len(logged.records), 1)
        self.assertIn("classquest executor: Bigzug take match=true", logged.output[0])

    def test_off_logs_nothing(self):
        step = planned_step()
        with mock.patch.dict(os.environ, {"CLASSQUEST_EXECUTOR": "off"}):
            with self.assertNoLogs(bridge.log, logging.INFO):
                bridge._shadow_class_step(step)

    def test_a_step_that_is_not_a_class_step_logs_nothing(self):
        other = guildcorps.Step("Bigzug", "farm", 1, "farms")
        with self.assertNoLogs(bridge.log, logging.INFO):
            bridge._shadow_class_step(other)

    def test_a_failure_is_logged_once_and_never_raised(self):
        step = planned_step()
        with mock.patch.object(
            bridge.classquest_steps, "shadow_line", side_effect=RuntimeError("boom")
        ):
            with self.assertLogs(bridge.log, logging.ERROR) as logged:
                bridge._shadow_class_step(step)
                bridge._shadow_class_step(step)
        self.assertEqual(len(logged.records), 1)

    def test_the_bridge_asks_for_the_comparison_as_a_step_starts(self):
        source = pathlib.Path(bridge.__file__).read_text(encoding="utf-8")
        start = source[source.index("def _start_guild_job_steps") :]
        start = start[: start.index("async def _job_fields")]
        self.assertLess(
            start.index("_shadow_class_step(step)"), start.index("create_task")
        )
