"""The decree console reads what the module can cross before planning.

On the dev realm the module reported `crossing = boards`, but the console
refused a Scarlet Monastery queue for a Kalimdor family with "on the Eastern
Kingdoms while we are on Kalimdor, with no way across yet": only the bridge
process ever told crossing.py, and the console is map_server, a separate
process with its own copy.
"""

import pathlib
import unittest

from test_decree_order import FakeConn  # noqa: F401  sets up the pymysql stub

import crossing  # noqa: E402
import map_server  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql):
        self.sql = sql

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)

    def close(self):
        pass


class ConsoleReadsModuleCrossing(unittest.TestCase):
    def tearDown(self):
        crossing.note_module_crossing("")

    def _with_rows(self, rows):
        saved = map_server._connect
        map_server._connect = lambda: _Conn(rows)
        try:
            map_server._note_module_crossing()
        finally:
            map_server._connect = saved

    def test_a_boards_row_lets_a_door_across_the_sea_through(self):
        crossing.note_module_crossing("")
        self._with_rows([{"value": "boards"}])
        self.assertTrue(crossing.module_boards())
        self.assertFalse(crossing.dungeon_door_blocked())

    def test_no_row_reads_as_before(self):
        self._with_rows([])
        self.assertFalse(crossing.module_boards())

    def test_the_post_handler_reads_it_before_planning(self):
        src = (ROOT / "map_server.py").read_text()
        start = src.index("def _decree_post(")
        body = src[start : src.index("\n    def ", start + 10)]
        self.assertIn("_note_module_crossing()", body)
        self.assertLess(
            body.index("_note_module_crossing()"), body.index("decree.plan_order(")
        )


if __name__ == "__main__":
    unittest.main()
