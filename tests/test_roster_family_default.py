"""New roster rows carry a family before the schema default changes."""

import ast
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class _ProgrammingError(Exception):
    pass


class _Cursor:
    def __init__(self, missing_family=False):
        self.missing_family = missing_family
        self.calls = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def executemany(self, sql, rows):
        rows = list(rows)
        self.calls.append((sql, rows))
        if self.missing_family and "(name, family, note)" in sql:
            raise _ProgrammingError(1054, "Unknown column 'family' in 'field list'")
        self.rowcount = len(rows)


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


def _load_bridge_writer(cursor):
    tree = ast.parse((ROOT / "bridge.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_ensure_roster"
    )
    namespace = {
        "_connect": lambda: _Connection(cursor),
        "bonds": SimpleNamespace(head_of_family=lambda: "FamilyHead"),
        "log": SimpleNamespace(warning=lambda *_args: None),
        "pymysql": SimpleNamespace(
            err=SimpleNamespace(ProgrammingError=_ProgrammingError)
        ),
    }
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)
    return namespace["_ensure_roster"]


class BridgeRosterWriter(unittest.TestCase):
    def test_notable_rows_write_the_current_family(self):
        cursor = _Cursor()
        inserted = _load_bridge_writer(cursor)(["MemberA", "MemberB"])

        self.assertEqual(2, inserted)
        self.assertEqual(1, len(cursor.calls))
        self.assertIn("(name, family, note)", cursor.calls[0][0])
        self.assertEqual(
            [
                ("MemberA", "FamilyHead", "notable character"),
                ("MemberB", "FamilyHead", "notable character"),
            ],
            cursor.calls[0][1],
        )

    def test_old_schema_falls_back_to_the_legacy_insert(self):
        cursor = _Cursor(missing_family=True)
        inserted = _load_bridge_writer(cursor)(["MemberA"])

        self.assertEqual(1, inserted)
        self.assertEqual(2, len(cursor.calls))
        self.assertIn("(name, family, note)", cursor.calls[0][0])
        self.assertIn("(name, note)", cursor.calls[1][0])


class SeedRosterWriter(unittest.TestCase):
    def test_seed_rows_share_the_family_head(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "tools" / "seed_roster.py"),
                "--family",
                "dev",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        statements = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("INSERT IGNORE INTO overseer_roster")
        ]
        self.assertTrue(statements)
        pattern = re.compile(
            r"VALUES \('((?:[^']|'')*)', '((?:[^']|'')*)', '((?:[^']|'')*)'\);$"
        )
        rows = []
        for statement in statements:
            self.assertIn("(name, family, note)", statement)
            match = pattern.search(statement)
            self.assertIsNotNone(match)
            rows.append(match.groups())

        names = {name for name, _family, _note in rows}
        families = {family for _name, family, _note in rows}
        self.assertEqual(1, len(families))
        self.assertIn(next(iter(families)), names)


if __name__ == "__main__":
    unittest.main()
