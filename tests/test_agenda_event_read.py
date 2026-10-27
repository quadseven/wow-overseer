"""The agenda banner's newest-event-per-kind read is index-backed (#1333).

The old statement grouped overseer_event by kind alone. A family's names are
an IN range, so no index could answer it and MySQL walked a whole kind index,
every family's rows, on each agenda read: about 170 ms of the endpoint's time
on a live realm with 60k events. The read now groups by (character_name, kind)
and takes MAX(last_seen), which the bridge's idx_character_kind_last_seen
answers with a loose index scan, and folds those rows to one per kind in
Python, so the banner sees the same rows as before.
"""

import re
import sys
import types
import unittest
from datetime import datetime
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()

import map_server  # noqa: E402
import realmread  # noqa: E402

T = datetime

# One family's raw event rows: (character_name, kind, last_seen).
RAW = [
    ("Ana", "quest_done", T(2026, 10, 20, 9, 0)),
    ("Ana", "quest_done", T(2026, 10, 20, 11, 0)),
    ("Bo", "quest_done", T(2026, 10, 20, 10, 0)),
    ("Bo", "level", T(2026, 10, 19, 8, 0)),
    ("Cy", "level", T(2026, 10, 21, 7, 30)),
    ("Cy", "death", T(2026, 10, 21, 8, 0)),
]


def _old_statement(rows):
    """What `SELECT kind, MAX(last_seen) ... GROUP BY kind` returned."""
    out = {}
    for _name, kind, seen in rows:
        out[kind] = max(out.get(kind, seen), seen)
    return out


def _new_statement(rows):
    """What _EVENT_NEWEST_SQL returns: one row per (character, kind)."""
    out = {}
    for name, kind, seen in rows:
        key = (name, kind)
        out[key] = max(out.get(key, seen), seen)
    return [
        {"character_name": n, "kind": k, "last_seen": s}
        for (n, k), s in sorted(out.items())
    ]


class _Reader(realmread.Reader):
    """Answers the event statement from RAW and every other read empty."""

    def __init__(self):
        self.asked = []

    def _run(self, sql, params):
        self.asked.append(sql)
        if "FROM overseer_event " in sql:
            return _new_statement(RAW)
        return []


def _index_columns():
    """The columns of the index the bridge ensures on overseer_event."""
    altered = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, args=()):
            if "information_schema.TABLES" in sql:
                self.row = {"n": 1}
            elif "information_schema.STATISTICS" in sql:
                self.row = {"n": 0}
            elif sql.startswith("ALTER TABLE"):
                altered.append(sql)

        def fetchone(self):
            return getattr(self, "row", None)

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return Cursor()

    with mock.patch.object(bridge, "_connect", return_value=Conn()):
        bridge._ensure_event_store()
    return altered


class TheReadIsIndexBacked(unittest.TestCase):
    def test_the_bridge_ensures_the_covering_index(self):
        self.assertEqual(
            _index_columns(),
            [
                (
                    "ALTER TABLE overseer_event ADD KEY idx_character_kind_last_seen "
                    "(character_name, kind, last_seen)"
                )
            ],
        )

    def test_the_statement_is_a_loose_index_scan_of_that_index(self):
        """MySQL answers MAX(col) GROUP BY a1..ak from the index alone (a
        loose index scan) when a1..ak is a leftmost prefix of the index and
        col is the column right after it. Grouping by kind alone, with the
        names as an IN range, never qualifies, which is the full walk the
        live EXPLAIN showed."""
        sql = map_server._EVENT_NEWEST_SQL
        index = re.search(r"\(([^)]*)\)$", _index_columns()[0]).group(1)
        columns = [c.strip() for c in index.split(",")]
        group = re.search(r"GROUP BY (.*)$", sql).group(1)
        grouped = [c.strip() for c in group.split(",")]
        self.assertEqual(columns[: len(grouped)], grouped)
        self.assertIn(f"MAX({columns[len(grouped)]})", sql)
        self.assertIn("WHERE character_name IN ({holes})", sql)

    def test_the_bridge_skips_an_index_that_exists(self):
        altered = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, args=()):
                self.row = {"n": 1}
                if sql.startswith("ALTER TABLE"):
                    altered.append(sql)

            def fetchone(self):
                return self.row

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return Cursor()

        with mock.patch.object(bridge, "_connect", return_value=Conn()):
            bridge._ensure_event_store()
        self.assertEqual(altered, [])

    def test_the_index_is_ensured_at_start_up_and_never_stops_it(self):
        import inspect

        src = inspect.getsource(bridge.Bridge._ensure_stores)
        self.assertIn("_ensure_event_store,", src)
        self.assertIn(
            "if ensure in (_ensure_dungeon_run_event_store, _ensure_event_store):", src
        )


class TheBannerSeesTheSameRows(unittest.TestCase):
    def test_the_fold_is_what_the_old_statement_returned(self):
        folded = map_server._newest_per_kind(_new_statement(RAW))
        self.assertEqual(
            {r["kind"]: r["last_seen"] for r in folded}, _old_statement(RAW)
        )
        self.assertEqual(len(folded), len({k for _n, k, _s in RAW}))
        for row in folded:
            self.assertEqual(set(row), {"kind", "last_seen"})

    def test_no_rows_is_no_rows(self):
        self.assertEqual(map_server._newest_per_kind([]), [])

    def test_fetch_agenda_reads_the_event_table_once_and_folds_it(self):
        reader = _Reader()
        with mock.patch.object(realmread, "Session", lambda connect: reader):
            rows = map_server._fetch_agenda(["Ana", "Bo", "Cy"])
        event_reads = [s for s in reader.asked if "FROM overseer_event " in s]
        self.assertEqual(len(event_reads), 1)
        self.assertIn("GROUP BY character_name, kind", event_reads[0])
        self.assertEqual(
            {r["kind"]: r["last_seen"] for r in rows["event_rows"]},
            _old_statement(RAW),
        )


if __name__ == "__main__":
    unittest.main()
