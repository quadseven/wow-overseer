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
import guildjobs


SOURCE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def _persistent_owing():
    tree = ast.parse(SOURCE)
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "_PersistentOwing"
    )
    rows = {}
    writes = []

    def read(kind):
        return {
            name: (json.loads(json.dumps(value)), since)
            for (row_kind, name), (value, since) in rows.items()
            if row_kind == kind
        }

    def write(kind, subject, value, since, expires):
        # The real store keeps the value as JSON (_memo_upsert, _memo_read).
        rows[kind, subject] = (json.loads(json.dumps(value)), since)
        writes.append((kind, subject, since, expires))

    def delete(kind, subject):
        rows.pop((kind, subject), None)

    ns = {
        "classquest": classquest,
        "_memo_read": read,
        "_memo_upsert": write,
        "_memo_delete": delete,
        "OWED_MEMO_SECONDS": 7 * 24 * 3600,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
    ns["_PersistentOwing"].writes = writes
    return ns["_PersistentOwing"], rows


class OwedClockMemoTests(unittest.TestCase):
    def test_clock_releases_after_wall_time_across_restart(self):
        owing_type, rows = _persistent_owing()
        first = owing_type()
        first.idle("Member", "mark", 1000.0)
        restarted = owing_type()
        restarted.restore()
        self.assertTrue(
            restarted.expired(
                "Member",
                "mark",
                1000.0 + classquest.OWED_HOURS * 3600,
                classquest.OWED_HOURS,
            )
        )

    def test_changed_mark_starts_a_fresh_clock(self):
        owing_type, _ = _persistent_owing()
        first = owing_type()
        first.idle("Member", "old", 1000.0)
        restarted = owing_type()
        restarted.restore()
        self.assertEqual(0.0, restarted.idle("Member", "new", 2000.0))
        hours = classquest.OWED_HOURS
        self.assertFalse(
            restarted.expired("Member", "new", 2000.0 + hours * 3600 - 1, hours)
        )
        self.assertTrue(
            restarted.expired("Member", "new", 2000.0 + hours * 3600, hours)
        )

    def test_a_long_stall_keeps_its_memo_past_owed_hours(self):
        owing_type, _ = _persistent_owing()
        owing_type().idle("Member", "mark", 1000.0)
        _, _, since, expires = owing_type.writes[-1]
        self.assertGreaterEqual(expires - since, 7 * 24 * 3600)

    def test_an_unreadable_store_leaves_todays_in_memory_clock(self):
        owing_type, rows = _persistent_owing()
        owing_type().idle("Member", "mark", 1000.0)
        rows.clear()  # _memo_read returns {} when the database fails
        restarted = owing_type()
        restarted.restore()
        self.assertEqual(0.0, restarted.idle("Member", "mark", 5000.0))
        self.assertTrue(
            restarted.expired(
                "Member",
                "mark",
                5000.0 + classquest.OWED_HOURS * 3600,
                classquest.OWED_HOURS,
            )
        )


class OwedClockRestartTests(unittest.TestCase):
    """Every member's owed clock after a restart equals the one before it, with
    the real progress marks the job pass computes (#921)."""

    MEMBERS = (
        guildjobs.Member(
            "MemberA",
            "Guild",
            "dps",
            quests_done=frozenset({1, 2}),
            quest_log={1598: 1},
            quest_progress={1598: 3},
            known=frozenset({133}),
        ),
        guildjobs.Member(
            "MemberB",
            "Guild",
            "healer",
            quest_log={5621: 3, 5622: 1},
            quest_progress={5621: 0, 5622: 2},
        ),
        guildjobs.Member("MemberC", "Guild", "tank"),
    )

    def test_every_clock_equals_its_pre_restart_value(self):
        owing_type, _ = _persistent_owing()
        first = owing_type()
        for second, m in enumerate(self.MEMBERS):
            first.idle(m.name, guildjobs.progress_mark(m), 1000.0 + second)
        before = dict(first._by)
        restarted = owing_type()
        restarted.restore()
        self.assertEqual(before, restarted._by)
        self.assertEqual(list(before), list(restarted._by))
        later = 1000.0 + classquest.OWED_HOURS * 3600
        for m in self.MEMBERS:
            mark = guildjobs.progress_mark(m)
            self.assertEqual(
                first.idle(m.name, mark, later), restarted.idle(m.name, mark, later)
            )

    def test_a_member_owed_past_owed_hours_stays_released_after_restart(self):
        owing_type, _ = _persistent_owing()
        member = self.MEMBERS[0]
        mark = guildjobs.progress_mark(member)
        owing_type().idle(member.name, mark, 1000.0)
        restarted = owing_type()
        restarted.restore()
        hours = classquest.OWED_HOURS
        self.assertTrue(
            restarted.expired(member.name, mark, 1000.0 + hours * 3600, hours)
        )


class Wiring(unittest.TestCase):
    def test_the_bridge_uses_the_persistent_clock_and_restores_both_memos(self):
        self.assertIn("self._class_owing = _PersistentOwing()", SOURCE)
        tree = ast.parse(SOURCE)
        bridge = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Bridge"
        )
        ensure = next(
            n for n in bridge.body if getattr(n, "name", "") == "_ensure_stores"
        )
        text = ast.get_source_segment(SOURCE, ensure)
        self.assertIn("owing.restore", text)
        self.assertIn("_restore_bag_holds", text)


class BagHoldMemoTests(unittest.TestCase):
    def test_restore_brings_a_hold_back_and_it_still_releases(self):
        tree = ast.parse(SOURCE)
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_restore_bag_holds"
        )
        holds = {}
        memo = {
            "Member": (
                {
                    "best": [["Member", 0]],
                    "since": 4900.0,
                    "seen": 4950.0,
                    "released": False,
                },
                4900.0,
            )
        }
        ns = {
            "_memo_read": lambda kind: memo if kind == "bag_hold" else {},
            "_BAG_HOLD": holds,
            "bag_pressure": bag_pressure,
            "time": types.SimpleNamespace(time=lambda: 5000.0, monotonic=lambda: 200.0),
            "log": logging.getLogger("memo-test"),
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        ns["_restore_bag_holds"]()
        restored = holds[("Member",)]
        self.assertEqual((100.0, 200.0), (restored.since, restored.seen))
        for second in range(60, int(bag_pressure.BAG_HOLD_STUCK_SECONDS) + 1, 60):
            restored = bag_pressure.bag_hold_progress(
                restored, {"Member": 0}, 200.0 + second
            )
        self.assertTrue(restored.released)

    def test_memo_database_failure_helpers_fall_back_to_empty(self):
        tree = ast.parse(SOURCE)
        nodes = [
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef)
            and n.name in {"_memo_upsert", "_memo_read", "_memo_delete"}
        ]

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

        ns = {
            "_connect": lambda: BrokenConnection(),
            "pymysql": FakePyMySQL,
            "log": logging.getLogger("memo-test"),
            "json": json,
            "time": time,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        self.assertEqual({}, ns["_memo_read"]("class_owed"))
        ns["_memo_upsert"]("class_owed", "Member", "mark", 1.0, 2.0)
        ns["_memo_delete"]("class_owed", "Member")


if __name__ == "__main__":
    unittest.main()
