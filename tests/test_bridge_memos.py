"""Bridge memo adapters preserve clocks without requiring a database."""

import ast
import json
import pathlib
import types
import logging
import time
import unittest

import bag_pressure
import classquest


SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def _persistent_owing():
    tree = ast.parse(SOURCE)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                and n.name == "_PersistentOwing")
    rows = {}

    def read(kind):
        return {name: row for (row_kind, name), row in rows.items() if row_kind == kind}

    def write(kind, subject, value, since, expires):
        rows[kind, subject] = (value, since)

    def delete(kind, subject):
        rows.pop((kind, subject), None)

    ns = {"classquest": classquest, "_memo_read": read,
          "_memo_upsert": write, "_memo_delete": delete}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"), ns)
    return ns["_PersistentOwing"], rows


class OwedClockMemoTests(unittest.TestCase):
    def test_clock_releases_after_wall_time_across_restart(self):
        owing_type, rows = _persistent_owing()
        first = owing_type()
        first.idle("Member", "mark", 1000.0)
        restarted = owing_type()
        restarted.restore()
        self.assertTrue(restarted.expired(
            "Member", "mark", 1000.0 + classquest.OWED_HOURS * 3600, classquest.OWED_HOURS
        ))

    def test_changed_mark_starts_a_fresh_clock(self):
        owing_type, _ = _persistent_owing()
        first = owing_type()
        first.idle("Member", "old", 1000.0)
        restarted = owing_type()
        restarted.restore()
        self.assertEqual(0.0, restarted.idle("Member", "new", 2000.0))
        self.assertFalse(restarted.expired("Member", "new", 2000.0))


class BagHoldMemoTests(unittest.TestCase):
    def test_hold_record_round_trips_between_clock_epochs(self):
        clock = types.SimpleNamespace(monotonic=lambda: 200.0, time=lambda: 5000.0)
        record = bag_pressure.BagHoldProgress((('Member', 0),), 100.0, 150.0, False)
        persisted = {"best": record.best, "since": 4900.0, "seen": 4950.0,
                     "released": False}
        restored = bag_pressure.BagHoldProgress(
            best=tuple(persisted["best"]),
            since=clock.monotonic() - (clock.time() - persisted["since"]),
            seen=clock.monotonic(),
            released=persisted["released"],
        )
        self.assertEqual((100.0, 200.0), (restored.since, restored.seen))
        for second in range(60, int(bag_pressure.BAG_HOLD_STUCK_SECONDS) + 1, 60):
            restored = bag_pressure.bag_hold_progress(
                restored, {"Member": 0}, clock.monotonic() + second)
        self.assertTrue(restored.released)

    def test_memo_database_failure_helpers_fall_back_to_empty(self):
        tree = ast.parse(SOURCE)
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"_memo_upsert", "_memo_read", "_memo_delete"}]

        class DatabaseError(Exception):
            pass

        class BrokenConnection:
            def __enter__(self):
                raise DatabaseError("database unavailable")

            def __exit__(self, *args):
                return False

        class FakePyMySQL:
            class err:
                MySQLError = DatabaseError

        ns = {"_connect": lambda: BrokenConnection(), "pymysql": FakePyMySQL,
              "log": logging.getLogger("memo-test"), "json": json, "time": time}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), ns)
        self.assertEqual({}, ns["_memo_read"]("class_owed"))
        ns["_memo_upsert"]("class_owed", "Member", "mark", 1.0, 2.0)
        ns["_memo_delete"]("class_owed", "Member")


if __name__ == "__main__":
    unittest.main()
