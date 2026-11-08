"""Leadership handoff keeps one dungeon campaign per family (#1688).

Executes the real `campaignhandoff.hand_over` against SQLite (`%s` -> `?`), and
checks that bridge._mark_party_leader calls it.
"""

import ast
import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import campaignhandoff  # noqa: E402

JOB = "dungeon:razorfen-downs"


class _Cur:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=()):
        c = self.db.execute(sql.replace("%s", "?"), params)
        self.rowcount = c.rowcount
        self._rows = [dict(r) for r in c.fetchall()] if c.description else []

    def fetchall(self):
        return self._rows


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE overseer_roster (name TEXT, family TEXT, enabled INT, "
        "job TEXT, dungeon_runs_done INT, dungeon_runs_wanted INT)"
    )
    rows = [("Grug", "cave", 1, JOB, 3, 13)]
    rows += [(n, "cave", 1, JOB, 0, 13) for n in ("Bork", "Grog", "Og", "Ugga")]
    rows += [("Zug", "other", 1, JOB, 5, 9)]
    db.executemany("INSERT INTO overseer_roster VALUES (?,?,?,?,?,?)", rows)
    return db


def _done(db, name):
    return db.execute(
        "SELECT dungeon_runs_done FROM overseer_roster WHERE name=?", (name,)
    ).fetchone()[0]


def _complete_run(db, leader):
    db.execute(
        "UPDATE overseer_roster SET dungeon_runs_done = dungeon_runs_done + 1 "
        "WHERE name = ?",
        (leader,),
    )


class HandOver(unittest.TestCase):
    def test_substitute_inherits_the_family_count(self):
        db = _db()
        campaignhandoff.hand_over(_Cur(db), "Bork", "cave")
        self.assertEqual(3, _done(db, "Bork"))
        self.assertEqual(5, _done(db, "Zug"))

    def test_run_finished_under_substitute_survives_the_return(self):
        db = _db()
        cur = _Cur(db)
        campaignhandoff.hand_over(cur, "Bork", "cave")
        _complete_run(db, "Bork")
        campaignhandoff.hand_over(cur, "Grug", "cave")
        self.assertEqual(4, _done(db, "Grug"))
        self.assertEqual(4, _done(db, "Bork"))

    def test_repeated_swaps_neither_reset_nor_double_count(self):
        db = _db()
        cur = _Cur(db)
        for head in ("Bork", "Grug", "Bork", "Grug", "Grug"):
            campaignhandoff.hand_over(cur, head, "cave")
        self.assertEqual(3, _done(db, "Grug"))
        self.assertEqual(3, _done(db, "Bork"))

    def test_stale_read_never_lowers_newer_progress(self):
        db = _db()
        cur = _Cur(db)
        real = cur.execute

        def interleave(sql, params=()):
            real(sql, params)
            if sql.startswith("SELECT"):
                # the module finishes a run after the read, before the write
                db.execute(
                    "UPDATE overseer_roster SET dungeon_runs_done = 9 "
                    "WHERE name = 'Bork'"
                )

        cur.execute = interleave
        campaignhandoff.hand_over(cur, "Bork", "cave")
        self.assertEqual(9, _done(db, "Bork"))

    def test_explicit_reset_still_starts_from_zero(self):
        db = _db()
        db.execute("UPDATE overseer_roster SET dungeon_runs_done = 0")
        campaignhandoff.hand_over(_Cur(db), "Bork", "cave")
        self.assertEqual(0, _done(db, "Grug"))
        self.assertEqual(0, _done(db, "Bork"))

    def test_other_job_and_disabled_rows_do_not_leak(self):
        db = _db()
        db.execute("UPDATE overseer_roster SET job='dungeon:other' WHERE name='Og'")
        db.execute(
            "UPDATE overseer_roster SET dungeon_runs_done=8, enabled=0 "
            "WHERE name='Ugga'"
        )
        campaignhandoff.hand_over(_Cur(db), "Bork", "cave")
        self.assertEqual(3, _done(db, "Bork"))
        self.assertEqual(0, _done(db, "Og"))
        self.assertEqual(8, _done(db, "Ugga"))

    def test_non_dungeon_head_changes_nothing(self):
        db = _db()
        db.execute("UPDATE overseer_roster SET job='quest' WHERE name='Bork'")
        self.assertEqual(0, campaignhandoff.hand_over(_Cur(db), "Bork", "cave"))
        self.assertEqual(0, _done(db, "Bork"))


class BridgeWiring(unittest.TestCase):
    def test_mark_party_leader_hands_over(self):
        tree = ast.parse((ROOT / "bridge.py").read_text(encoding="utf-8"))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_mark_party_leader"
        )
        calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
        self.assertIn("campaignhandoff.hand_over", calls)


if __name__ == "__main__":
    unittest.main()
