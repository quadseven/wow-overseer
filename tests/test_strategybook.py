"""Operator strategy orders survive a worldserver roll (#1553).

ResetStrategies runs on every login, so a runtime `nc +...` the operator sent
through the bridge is lost on a restart. The bridge records it (strategybook)
and replays it once per member after a new worldserver start.
"""

import ast
import pathlib
import unittest

import strategybook

HERE = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


def _memo(*orders):
    """The memo rows a sequence of (name, command) orders leaves behind."""
    memo = {}
    for i, (name, command) in enumerate(orders):
        for subject, sign in strategybook.rows(name, command):
            memo[subject] = (sign, float(i))
    return memo


class Parse(unittest.TestCase):
    def test_a_strategy_order_parses(self):
        self.assertEqual(
            ("nc", {"grind": "+", "loot": "-"}), strategybook.parse("nc +grind,-loot")
        )
        self.assertEqual(
            ("co", {"retreat from danger": "+"}),
            strategybook.parse("  CO  +retreat from danger "),
        )

    def test_anything_else_does_not(self):
        for command in ("follow", "stay", "nc", "nc ~grind", "say hi", "", None):
            self.assertIsNone(strategybook.parse(command), command)

    def test_a_toggle_item_is_skipped(self):
        self.assertEqual(("nc", {"loot": "+"}), strategybook.parse("nc ~grind,+loot"))

    def test_only_operator_orders_are_recorded(self):
        self.assertTrue(strategybook.is_operator("discord:123"))
        for source in ("overseer:life", strategybook.REAPPLY_SOURCE, "", None):
            self.assertFalse(strategybook.is_operator(source))


class Book(unittest.TestCase):
    def test_the_last_word_on_each_strategy_wins(self):
        memo = _memo(
            ("Ana", "nc +grind,+loot"),
            ("Ana", "nc -grind"),
            ("Ana", "co +flee"),
            ("Bo", "nc +gather"),
        )
        pages = strategybook.book(memo)
        self.assertEqual(
            {"nc": {"grind": "-", "loot": "+"}, "co": {"flee": "+"}}, pages["Ana"]
        )
        self.assertEqual(
            ["nc -grind,+loot", "co +flee"], strategybook.replay(pages["Ana"])
        )
        self.assertEqual(["nc +gather"], strategybook.replay(pages["Bo"]))

    def test_a_malformed_row_is_skipped(self):
        memo = {
            "Ana|nc|grind": ("+", 0.0),
            "junk": ("+", 0.0),
            "Ana|xx|grind": ("+", 0.0),
            "Ana|nc|loot": ("?", 0.0),
        }
        self.assertEqual({"Ana": {"nc": {"grind": "+"}}}, strategybook.book(memo))


def _pay(r, start, book, in_world):
    """One pass where every row is written: what was sent."""
    commands = r.due(start, book, in_world)
    for name in {n for n, _ in commands}:
        r.paid(name)
    return commands


class Reapply(unittest.TestCase):
    BOOK = {"Ana": {"nc": {"grind": "+"}}, "Bo": {"co": {"flee": "-"}}}

    def test_a_recorded_strategy_is_sent_again_after_a_restart(self):
        r = strategybook.Reapplier(seen=1000)
        commands = _pay(r, 2000, self.BOOK, ["Ana", "Bo"])
        self.assertEqual([("Ana", "nc +grind"), ("Bo", "co -flee")], commands)
        self.assertEqual(2000, r.settled())

    def test_nothing_is_sent_when_no_restart_happened(self):
        r = strategybook.Reapplier(seen=1000)
        self.assertEqual([], _pay(r, 1000, self.BOOK, ["Ana", "Bo"]))
        self.assertIsNone(r.settled())

    def test_it_is_not_sent_twice_for_one_restart(self):
        r = strategybook.Reapplier(seen=1000)
        _pay(r, 2000, self.BOOK, ["Ana", "Bo"])
        self.assertEqual([], _pay(r, 2000, self.BOOK, ["Ana", "Bo"]))

    def test_it_waits_until_the_member_is_back_in_world(self):
        r = strategybook.Reapplier(seen=1000)
        self.assertEqual([("Ana", "nc +grind")], _pay(r, 2000, self.BOOK, ["Ana"]))
        self.assertEqual({"Bo"}, r.owed())
        self.assertEqual([("Bo", "co -flee")], _pay(r, 2000, self.BOOK, ["Ana", "Bo"]))
        self.assertEqual(set(), r.owed())

    def test_a_first_look_only_seeds(self):
        r = strategybook.Reapplier(seen=None)
        self.assertEqual([], _pay(r, 2000, self.BOOK, ["Ana", "Bo"]))
        self.assertEqual(2000, r.settled())
        self.assertEqual(2, len(_pay(r, 3000, self.BOOK, ["Ana", "Bo"])))

    def test_an_unreadable_start_changes_nothing(self):
        r = strategybook.Reapplier(seen=1000)
        self.assertEqual([], _pay(r, None, self.BOOK, ["Ana", "Bo"]))
        self.assertEqual(1000, r.seen)
        self.assertIsNone(r.settled())


class OwedSurvivesABridgeRestart(unittest.TestCase):
    """#1584: the owed set is in memory only, so the start must not be saved
    while anyone is still owed, or a bridge restart loses their replay."""

    BOOK = Reapply.BOOK

    def test_the_start_is_saved_only_once_nobody_is_owed(self):
        r = strategybook.Reapplier(seen=1000)
        _pay(r, 2000, self.BOOK, ["Ana"])
        self.assertIsNone(r.settled())
        _pay(r, 2000, self.BOOK, ["Ana", "Bo"])
        self.assertEqual(2000, r.settled())
        self.assertIsNone(r.settled())

    def test_a_bridge_restart_before_a_member_is_back_still_replays_it(self):
        saved = 1000
        r = strategybook.Reapplier(seen=saved)
        _pay(r, 2000, self.BOOK, ["Ana"])
        saved = r.settled() or saved
        # The bridge restarts here; Bo logs in only afterwards.
        r = strategybook.Reapplier(seen=saved)
        self.assertIn(("Bo", "co -flee"), _pay(r, 2000, self.BOOK, ["Ana", "Bo"]))
        self.assertEqual(2000, r.settled())

    def test_a_row_not_written_is_offered_again(self):
        r = strategybook.Reapplier(seen=1000)
        first = r.due(2000, self.BOOK, ["Ana", "Bo"])
        r.paid("Ana")  # Bo's row was refused
        self.assertEqual({"Bo"}, r.owed())
        self.assertIsNone(r.settled())
        again = r.due(2000, self.BOOK, ["Ana", "Bo"])
        self.assertEqual([("Bo", "co -flee")], again)
        self.assertIn(("Bo", "co -flee"), first)


class NameCase(unittest.TestCase):
    """core accepts `@grug` as readily as `@Grug`; the replay side reads the
    name back from overseer_snapshot in the worldserver's spelling (#1553)."""

    def test_an_order_given_in_another_case_is_replayed_once(self):
        pages = strategybook.book(_memo(("grug", "nc +grind")))
        r = strategybook.Reapplier(seen=1000)
        self.assertEqual([("Grug", "nc +grind")], _pay(r, 2000, pages, ["Grug"]))
        self.assertEqual(set(), r.owed())
        self.assertEqual([], _pay(r, 2000, pages, ["Grug"]))

    def test_spellings_of_one_member_share_one_page(self):
        pages = strategybook.book(
            _memo(("GRUG", "nc +grind"), ("grug", "nc -grind,+loot"))
        )
        self.assertEqual({"Grug": {"nc": {"grind": "-", "loot": "+"}}}, pages)
        r = strategybook.Reapplier(seen=1000)
        self.assertEqual([("Grug", "nc -grind,+loot")], _pay(r, 2000, pages, ["Grug"]))

    def test_a_row_kept_under_an_old_spelling_still_replays(self):
        # Rows written before the book folded case keep their raw subject.
        pages = strategybook.book({"grug|nc|grind": ("+", 0.0)})
        r = strategybook.Reapplier(seen=1000)
        self.assertEqual([("Grug", "nc +grind")], _pay(r, 2000, pages, ["Grug"]))


class TheBridgeWiresIt(unittest.TestCase):
    def _function(self, name):
        tree = ast.parse(BRIDGE)
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name
            ):
                return ast.get_source_segment(BRIDGE, node)
        self.fail(f"bridge.py has no {name}")

    def test_an_order_is_recorded_after_its_row_is_written(self):
        body = self._function("_insert_command")
        self.assertIn("_record_strategy(cmd)", body)
        self.assertLess(
            body.index("INSERT INTO overseer_command"),
            body.index("_record_strategy(cmd)"),
        )

    def test_only_operator_orders_reach_the_book(self):
        body = self._function("_record_strategy")
        self.assertIn("strategybook.is_operator(cmd.source)", body)

    def test_the_replay_is_a_registered_pass(self):
        self.assertIn('_Pass("_reapply_strategies_loop")', BRIDGE)

    def test_the_replay_carries_its_own_source(self):
        body = self._function("_reapply_strategies")
        self.assertIn("strategybook.REAPPLY_SOURCE", body)
        self.assertIn("_bot_held_names", body)


if __name__ == "__main__":
    unittest.main()
