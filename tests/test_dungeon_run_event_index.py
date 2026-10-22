"""The bridge ensures the (leader_name, kind) index on the worldserver's
overseer_dungeon_run_event so the newest-boss-credit read is an index lookup,
not a full table scan (T1333)."""

import sys
import types
import unittest
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


def _make_conn(table_exists, index_exists, altered):
    """A connection whose information_schema answers the two lookups."""

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, args=()):
            if "information_schema.TABLES" in sql:
                self.row = {"n": 1 if table_exists else 0}
            elif "information_schema.STATISTICS" in sql:
                self.row = {"n": 1 if index_exists else 0}
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

    return Conn()


class EnsureIndex(unittest.TestCase):
    def test_adds_index_when_table_exists_and_index_missing(self):
        altered = []
        conn = _make_conn(True, False, altered)
        with mock.patch.object(bridge, "_connect", return_value=conn):
            bridge._ensure_dungeon_run_event_store()
        self.assertEqual(
            altered,
            [
                "ALTER TABLE overseer_dungeon_run_event "
                "ADD KEY idx_leader_kind (leader_name, kind)"
            ],
        )

    def test_skips_when_index_already_exists(self):
        altered = []
        conn = _make_conn(True, True, altered)
        with mock.patch.object(bridge, "_connect", return_value=conn):
            bridge._ensure_dungeon_run_event_store()
        self.assertEqual(altered, [])

    def test_skips_when_table_missing(self):
        altered = []
        conn = _make_conn(False, False, altered)
        with mock.patch.object(bridge, "_connect", return_value=conn):
            bridge._ensure_dungeon_run_event_store()
        self.assertEqual(altered, [])


if __name__ == "__main__":
    unittest.main()
