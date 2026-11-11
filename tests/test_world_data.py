import ast
from pathlib import Path
import unittest

import world_data


def _target_names(target):
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in target.elts))
    return set()


def _file_derived(node, aliases):
    if isinstance(node, ast.Name):
        return node.id == "__file__" or node.id in aliases
    return any(_file_derived(child, aliases) for child in ast.iter_child_nodes(node))


def _has_json_filename(node):
    return any(
        isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and child.value.endswith(".json")
        for child in ast.walk(node)
    )


def _is_path_join(node):
    if isinstance(node, ast.BinOp):
        return isinstance(node.op, ast.Div)
    if isinstance(node, ast.JoinedStr):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"join", "joinpath"}
    )


def _file_relative_json_joins(tree):
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        or (isinstance(node, ast.AnnAssign) and node.value is not None)
    ]
    aliases = set()
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            value = assignment.value
            if not _file_derived(value, aliases):
                continue
            targets = (
                assignment.targets
                if isinstance(assignment, ast.Assign)
                else [assignment.target]
            )
            for target in targets:
                new_aliases = _target_names(target) - aliases
                if new_aliases:
                    aliases.update(new_aliases)
                    changed = True

    return [
        node
        for node in ast.walk(tree)
        if _is_path_join(node)
        and _has_json_filename(node)
        and _file_derived(node, aliases)
    ]


class WorldDataRootTests(unittest.TestCase):
    def test_data_root_is_the_repository_root(self):
        repository_root = Path(__file__).resolve().parents[1]

        self.assertEqual(world_data.DATA_ROOT, repository_root)
        self.assertTrue((world_data.DATA_ROOT / "craftbook.json").is_file())

    def test_production_json_paths_use_the_shared_data_root(self):
        repository_root = Path(__file__).resolve().parents[1]
        violations = []

        for path in repository_root.rglob("*.py"):
            relative = path.relative_to(repository_root)
            if relative.parts[0] in {"tests", "mod-overseer"}:
                continue
            if relative.parts[0].startswith(".") or path.name == "world_data.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            violations.extend(
                f"{relative}:{node.lineno}" for node in _file_relative_json_joins(tree)
            )

        self.assertEqual(
            violations,
            [],
            "production JSON paths must use world_data.DATA_ROOT",
        )


if __name__ == "__main__":
    unittest.main()
