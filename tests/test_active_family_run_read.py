"""Execute the actual active-run reader with independent family ledger rows."""

import ast
import inspect
import os
from pathlib import Path
import sqlite3
import types
import unittest


class DatabaseError(Exception):
    pass


class ActiveFamilyRunReadTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.create_function(
            "FIND_IN_SET",
            2,
            lambda name, members: int(name in (members or "").split(",")),
        )
        self.db.executescript("""
CREATE TABLE overseer_roster(name TEXT PRIMARY KEY,family TEXT,enabled INTEGER);
INSERT INTO overseer_roster VALUES
 ('LeaderA','FamilyA',1),('MemberA','FamilyA',1),('LeaderB','FamilyB',1);
CREATE TABLE overseer_dungeon_run(
 id INTEGER PRIMARY KEY, family TEXT, leader_name TEXT, map_id INTEGER,
 state TEXT, members TEXT
);
INSERT INTO overseer_dungeon_run VALUES
 (1,'FamilyA','LeaderA',129,'active','LeaderA,MemberA'),
 (2,'FamilyB','LeaderB',129,'active','LeaderB');
""")
        self.calls = []
        self.fail_with = None
        subject = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params=()):
                subject.calls.append((sql, params))
                if subject.fail_with is not None:
                    raise DatabaseError(subject.fail_with, "fixture database failure")
                try:
                    self.rows = subject.db.execute(sql.replace("%s", "?"), params)
                except sqlite3.OperationalError as error:
                    if "no such table" in str(error):
                        code = 1146
                    elif "no such column" in str(error):
                        code = 1054
                    else:
                        raise
                    raise DatabaseError(code, str(error)) from error

            def fetchone(self):
                row = self.rows.fetchone()
                return dict(row) if row is not None else None

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def cursor(self):
                return Cursor()

        tree = ast.parse(
            Path(
                os.environ.get(
                    "OVERSEER_REPLAY_SOURCE",
                    Path(__file__).resolve().parents[1] / "bridge.py",
                )
            ).read_text()
        )
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_active_dungeon_run"
        )
        namespace = {
            "_connect": Connection,
            "pymysql": types.SimpleNamespace(
                err=types.SimpleNamespace(MySQLError=DatabaseError)
            ),
        }
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"),
            namespace,
        )
        self.subject = namespace["_active_dungeon_run"]

    def read(self, names):
        # Keep the original no-argument implementation runnable for the red
        # replay, so it fails on foreign ownership rather than argument arity.
        return (
            self.subject(names)
            if inspect.signature(self.subject).parameters
            else self.subject()
        )

    def test_newer_foreign_run_does_not_hide_the_requested_family(self):
        self.assertEqual(
            "LeaderA,MemberA", self.read(["LeaderA", "MemberA"])["members"]
        )
        self.assertEqual("LeaderB", self.read(["LeaderB"])["members"])

    def test_single_member_finds_the_family_run(self):
        self.assertEqual("LeaderA,MemberA", self.read(["MemberA"])["members"])

    def test_no_names_never_reads_a_global_run(self):
        self.assertIsNone(self.read([]))
        self.assertEqual([], self.calls)

    def test_older_schema_still_selects_recorded_members(self):
        self.db.execute("ALTER TABLE overseer_dungeon_run DROP COLUMN family")
        self.assertEqual("LeaderA,MemberA", self.read(["MemberA"])["members"])

    def test_a_renamed_legacy_row_does_not_claim_its_foreign_leader(self):
        self.db.execute("ALTER TABLE overseer_dungeon_run DROP COLUMN family")
        self.db.execute(
            "UPDATE overseer_dungeon_run SET leader_name='LeaderA' WHERE id=2"
        )
        self.assertEqual("LeaderA,MemberA", self.read(["LeaderA"])["members"])

    def test_missing_table_is_unknown(self):
        self.db.execute("DROP TABLE overseer_dungeon_run")
        self.assertIsNone(self.read(["LeaderA"]))

    def test_database_failure_is_not_reported_as_no_run(self):
        self.fail_with = 1205
        with self.assertRaises(DatabaseError):
            self.read(["LeaderA"])
        self.assertEqual(1, len(self.calls))


if __name__ == "__main__":
    unittest.main()
