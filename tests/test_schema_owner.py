"""One owner per table, and the site reads what the bridge owns (#740).

Bridge-owned tables were created in four places: the bridge's start-up list
(`Bridge._ensure_stores`), a pass that created its own store when it started
(`_now_loop`), and both of the site's Watcher doors, which ran the bridge's
`director.CREATE_SQL` before reading or writing `overseer_watch`. Two
processes holding DDL for one table is two owners, free to disagree about
its shape the day one of them changes it.

The rule these tests hold: every `_ensure_*_store` the bridge defines runs
from `_ensure_stores` and from nowhere else, and the site creates only the
table it owns (`overseer_stream`). A site reading a bridge table the bridge
has not created yet says so in its payload rather than creating it.

The issue's "four places" and "three ways" count the duplication this
removes, not tables or methods to add: the change adds no table and no new
way to count free bag slots. Its scope is giving each table one creator,
held here, and having the site count free bag slots by the bridge's
bag_pressure.general_bag_room, held in tests/test_wealth.py.
"""

import ast
import json
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    _err = types.ModuleType("pymysql.err")

    class _MySQLError(Exception):
        pass

    _err.MySQLError = _MySQLError
    sys.modules["pymysql"].err = _err

import map_server  # noqa: E402  (must follow the pymysql stub)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tree(name: str) -> ast.Module:
    return ast.parse((ROOT / name).read_text(encoding="utf-8"))


def _calls(node) -> set:
    """Every bare function name called anywhere under `node`."""
    return {
        n.func.id
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise AssertionError("no function %s" % name)


class TheBridgeOwnsItsTablesInOnePlace(unittest.TestCase):
    STORE = re.compile(r"^_ensure_[a-z_]+_store$")

    def setUp(self):
        self.tree = _tree("bridge.py")
        self.stores = {
            n.name
            for n in self.tree.body
            if isinstance(n, ast.FunctionDef) and self.STORE.match(n.name)
        }

    def test_every_store_is_created_at_start_up(self):
        owner = _function(self.tree, "_ensure_stores")
        named = {n.id for n in ast.walk(owner) if isinstance(n, ast.Name)}
        self.assertTrue(self.stores)
        self.assertEqual(set(), self.stores - named)

    def test_no_pass_creates_a_store_of_its_own(self):
        owner = _function(self.tree, "_ensure_stores")
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node is owner:
                continue
            with self.subTest(function=node.name):
                self.assertEqual(set(), _calls(node) & self.stores)


class TheSiteCreatesOnlyWhatItOwns(unittest.TestCase):
    def test_the_only_table_the_site_creates_is_the_stream_store(self):
        # The set is what the site still creates after the change, not a
        # target to grow: the site's other creates (overseer_watch, by
        # director.CREATE_SQL) moved to their one owner, the bridge.
        src = (ROOT / "map_server.py").read_text(encoding="utf-8")
        created = set(re.findall(r'"CREATE TABLE IF NOT EXISTS (\w+)', src))
        self.assertEqual({"overseer_stream"}, created)
        self.assertEqual(0, src.count("director.CREATE_SQL"))


class _Cursor:
    def __init__(self, missing=False):
        self.sql = []
        self.missing = missing

    def execute(self, sql, args=()):
        self.sql.append(sql)
        if self.missing:
            raise map_server.pymysql.err.MySQLError(1146, "no overseer_watch")

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _handler():
    h = map_server.Handler.__new__(map_server.Handler)
    h.sent = []
    h._send = lambda code, ctype, body, *a: h.sent.append((code, body))
    return h


class TheSiteReadsTheWatchItDoesNotOwn(unittest.TestCase):
    def state(self, cursor):
        h = _handler()
        with mock.patch.object(map_server, "_connect", lambda: _Conn(cursor)):
            h._director_state({})
        code, body = h.sent[-1]
        return code, json.loads(body)

    def test_the_state_read_runs_no_ddl(self):
        cursor = _Cursor()
        code, _payload = self.state(cursor)
        self.assertEqual(200, code)
        self.assertFalse([s for s in cursor.sql if "CREATE" in s.upper()])

    def test_a_watch_table_not_yet_created_reads_as_no_order(self):
        code, payload = self.state(_Cursor(missing=True))
        self.assertEqual(200, code)
        self.assertFalse(payload["active"])
        self.assertEqual("", payload["spec"])


if __name__ == "__main__":
    unittest.main()
