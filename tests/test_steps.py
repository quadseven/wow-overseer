import unittest
import os
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
