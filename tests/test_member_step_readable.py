"""The member step stays an orchestration under the review cap (Refs #962).

The review check flagged `_member_step` in guildjobs.py at cyclomatic 24
against a cap of 15 when #961 moved it from 21 to 24. Its rungs are now three
pieces: the quest rungs ahead of upkeep (_quest_first), the upkeep rungs
(_upkeep_first), and the outings and ordinary job it still runs itself. The
rung order and the notes each rung returns are pinned by the behavior tests
that call _member_step (test_classquest, test_hunterpet, test_guild_rest_supply
and others); this file pins only the shape, so the next rung added has a home
that is not the orchestrator.
"""

import ast
import pathlib
import unittest

import member_rungs

CAP = 15
SOURCE = pathlib.Path(__file__).resolve().parents[1] / "guildjobs.py"


def _function(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("guildjobs.py has no top-level %s" % name)


def _cyclomatic(fn) -> int:
    """McCabe's count as the review check reads it: one, plus one per branch
    (if, conditional expression, loop, except, match case), per extra operand
    of an and/or, and per comprehension and its filters. Nested functions are
    their own count and are not walked."""
    count = 1
    todo = list(ast.iter_child_nodes(fn))
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(
            node,
            (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler),
        ):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            count += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            count += 1
        todo.extend(ast.iter_child_nodes(node))
    return count


class TheMemberStepStaysReadable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))

    def test_the_orchestrator_is_under_the_cap(self):
        fn = _function(self.tree, "_member_step")
        self.assertLessEqual(_cyclomatic(fn), CAP)

    def test_each_piece_is_its_own_function_under_the_cap(self):
        for name in ("_quest_first", "_upkeep_first"):
            with self.subTest(name=name):
                self.assertLessEqual(_cyclomatic(_function(self.tree, name)), CAP)

    def test_the_orchestrator_calls_the_pieces_in_rung_order(self):
        """Quest rungs, then upkeep, then PvP, the post, the level walk and
        the ordinary job."""
        body = ast.get_source_segment(
            SOURCE.read_text(encoding="utf-8"), _function(self.tree, "_member_step")
        )
        order = [
            body.index(call)
            for call in (
                "_quest_first(",
                "_upkeep_first(",
                "_pvp_first(",
                "_collect_first(",
                "level_step(",
                "_plan_member(",
            )
        ]
        self.assertEqual(order, sorted(order))

    def test_every_rung_keeps_its_place_through_the_pieces(self):
        """The whole ladder as _member_step's docstring gives it, read
        through the helpers (tests/member_rungs.py)."""
        names = member_rungs.names()
        ladder = (
            "stalled_level_first",
            "class_step",
            "_pet_first",
            "stood_still_step",
            "_supply_first",
            "_full_bags_first",
            "_inn_first",
            "riding_step",
            "_gear_first",
            "_pvp_first",
            "_collect_first",
            "level_step",
            "_plan_member",
        )
        order = [names.index(rung) for rung in ladder]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()
