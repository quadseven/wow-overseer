"""Keep planner orchestration within Grug Elder's readability caps.

Refs #2189
"""

import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CAP = 15
COGNITIVE_CAP = 25


def _function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s has no top-level %s" % (path.name, name))


def _cyclomatic(function):
    score = 1
    for node in ast.walk(function):
        if isinstance(
            node,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.IfExp,
                ast.comprehension,
                ast.Assert,
            ),
        ):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.match_case):
            wildcard = isinstance(node.pattern, ast.MatchAs) and (
                node.pattern.pattern is None
            )
            score += 0 if wildcard else 1
    return score


def _cognitive(function):
    nesters = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)

    def walk(node, depth):
        total = 0
        for child in ast.iter_child_nodes(node):
            increment, child_depth = 0, depth
            if isinstance(child, nesters):
                increment, child_depth = 1 + depth, depth + 1
            elif isinstance(child, ast.BoolOp):
                increment = 1
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_depth = depth + 1
            total += increment + walk(child, child_depth)
        return total

    return walk(function, 0)


class ThePlannerStaysReadable(unittest.TestCase):
    PIECES = (
        ("guildjobs.py", "_plan_counters"),
        ("guildjobs.py", "_plan_trades"),
        ("guildjobs.py", "_all_plan_members"),
        ("guildjobs.py", "_plan_members"),
        ("guildjobs.py", "_plan_ordered_member"),
        ("guildjobs.py", "_plan_roster_member"),
        ("guildjobs.py", "_member_value"),
        ("guildjobs.py", "_member_map_keys"),
        ("guildjobs.py", "_member_room_offer"),
        ("guildjobs.py", "_commit_roster_step"),
        ("guildjobs.py", "_finish_plan"),
        ("bridge.py", "_job_pending_names"),
        ("bridge.py", "_job_map_ids"),
        ("bridge.py", "_family_job_members"),
    )

    def test_planning_entrypoint_stays_under_the_review_caps(self):
        function = _function(ROOT / "guildjobs.py", "plan")
        self.assertLessEqual(_cyclomatic(function), CAP)
        self.assertLessEqual(_cognitive(function), COGNITIVE_CAP)

    def test_job_row_adapter_stays_under_the_review_caps(self):
        function = _function(ROOT / "bridge.py", "_job_facts_from_rows")
        self.assertLessEqual(_cyclomatic(function), CAP)
        self.assertLessEqual(_cognitive(function), COGNITIVE_CAP)

    def test_extracted_steps_stay_under_the_review_caps(self):
        for filename, name in self.PIECES:
            with self.subTest(function=name):
                function = _function(ROOT / filename, name)
                self.assertLessEqual(_cyclomatic(function), CAP)
                self.assertLessEqual(_cognitive(function), COGNITIVE_CAP)


if __name__ == "__main__":
    unittest.main()
