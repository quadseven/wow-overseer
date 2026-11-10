"""The decree console's newest-job-per-character read is index-backed (#2051).

`SELECT target_name, MAX(id) FROM overseer_command WHERE kind = 'job' GROUP BY
target_name` took 7.0 s on a realm with 877k command rows, because the only
index that leads with kind (idx_kind_status_updated) covers neither
target_name nor id: a scan with row lookups and a temp table, past the 10 s
read timeout, so GET /api/decree answered 503. The bridge now ensures
(kind, target_name, id), which answers the statement as a loose index scan.
"""

import re
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import, stub_modules
import source_utils


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    return fresh_import("bridge", discord=stub, pymysql=PYMYSQL)


bridge = _import_bridge()

with stub_modules(pymysql=PYMYSQL):
    import map_server


def _run_ensure(table_exists=1, index_exists=0):
    altered = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, args=()):
            if "information_schema.TABLES" in sql:
                self.row = {"n": table_exists}
            elif "information_schema.STATISTICS" in sql:
                self.row = {"n": index_exists}
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
        bridge._ensure_command_store()
    return altered


class TheJobReadIsIndexBacked(unittest.TestCase):
    def test_the_bridge_ensures_the_covering_index(self):
        self.assertEqual(
            _run_ensure(),
            [
                "ALTER TABLE overseer_command ADD KEY idx_kind_target_id "
                "(kind, target_name, id)"
            ],
        )

    def test_an_existing_index_or_missing_table_alters_nothing(self):
        self.assertEqual(_run_ensure(index_exists=1), [])
        self.assertEqual(_run_ensure(table_exists=0), [])

    def test_the_index_matches_the_decree_statement(self):
        src = source_utils.function_source(map_server._fetch_decree)
        flat = re.sub(r'"\s*"', "", src)
        self.assertIn(
            "SELECT target_name, MAX(id) AS id FROM overseer_command "
            "WHERE kind = 'job' GROUP BY target_name",
            flat,
        )
        index = re.search(r"\(([^)]*)\)$", _run_ensure()[0]).group(1)
        self.assertEqual(
            [c.strip() for c in index.split(",")], ["kind", "target_name", "id"]
        )

    def test_the_index_is_ensured_at_start_up_and_never_stops_it(self):
        src = source_utils.function_source(bridge.Bridge._ensure_stores)
        self.assertRegex(src, r"_ensure_event_store,\s+_ensure_command_store,")
        self.assertRegex(src, r"_ensure_event_store,\s+_ensure_command_store,\s+\):")


if __name__ == "__main__":
    unittest.main()
