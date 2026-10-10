"""The realm reader: the one way the site reads the realm.

Tested through its interface, `rows()` and `must()`, over both adapters: the
database one (a fake pymysql connection, raising the classes pymysql raises)
and the in-memory one the other suites use.
"""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    _err = types.ModuleType("pymysql.err")
    _err.MySQLError = type("MySQLError", (Exception,), {})
    sys.modules["pymysql"].err = _err
ERR = sys.modules["pymysql"].err
for _name in ("OperationalError", "ProgrammingError"):
    if not hasattr(ERR, _name):
        setattr(ERR, _name, type(_name, (ERR.MySQLError,), {}))

import realmread  # noqa: E402

MISSING_TABLE = ERR.ProgrammingError(1146, "Table doesn't exist")
# pymysql has no error_map entry for 1054, so a missing column arrives as
# OperationalError, not ProgrammingError.
MISSING_COLUMN = ERR.OperationalError(1054, "Unknown column")
LOST = ERR.OperationalError(2013, "Lost connection")


class Db:
    """A fake pymysql connection: `answers` maps SQL to rows or an error."""

    def __init__(self, answers):
        self.answers = answers
        self.executed = []
        self.opened = 0
        self.closed = 0

    def connect(self):
        self.opened += 1
        return self

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        answer = self.answers[sql]
        if isinstance(answer, Exception):
            raise answer
        self._rows = answer

    def fetchall(self):
        return tuple(self._rows)

    def close(self):
        self.closed += 1


class TheDatabaseReader(unittest.TestCase):
    def test_rows_are_the_statements_rows_with_its_values_bound(self):
        db = Db({"SELECT a FROM t WHERE b = %s": [{"a": 1}]})
        with realmread.Session(db.connect) as rd:
            got = rd.rows("SELECT a FROM t WHERE b = %s", (7,), what="t")
        self.assertEqual(got, [{"a": 1}])
        self.assertEqual(db.executed, [("SELECT a FROM t WHERE b = %s", (7,))])

    def test_a_missing_table_takes_the_fallback(self):
        db = Db({"wide": MISSING_TABLE, "thin": [{"a": 1}]})
        with realmread.Session(db.connect) as rd:
            got = rd.rows("wide", (), fallback="thin", what="t")
        self.assertEqual(got, [{"a": 1}])
        self.assertEqual([s for s, _ in db.executed], ["wide", "thin"])

    def test_a_missing_column_takes_the_fallback(self):
        db = Db({"wide": MISSING_COLUMN, "thin": [{"a": 1}]})
        with realmread.Session(db.connect) as rd:
            self.assertEqual(rd.rows("wide", (), fallback="thin"), [{"a": 1}])

    def test_no_fallback_left_is_an_empty_read(self):
        db = Db({"wide": MISSING_TABLE, "thin": MISSING_COLUMN})
        with realmread.Session(db.connect) as rd:
            self.assertEqual(rd.rows("wide", (), fallback="thin"), [])
            self.assertEqual(rd.rows("wide"), [])

    def test_any_other_error_still_raises(self):
        db = Db({"wide": LOST, "thin": [{"a": 1}]})
        with (
            realmread.Session(db.connect) as rd,
            self.assertRaises(ERR.OperationalError),
        ):
            rd.rows("wide", (), fallback="thin")
        self.assertEqual([s for s, _ in db.executed], ["wide"])

    def test_a_must_read_raises_a_missing_table_or_column_as_a_gap(self):
        db = Db({"core": MISSING_TABLE, "col": MISSING_COLUMN})
        with realmread.Session(db.connect) as rd:
            for sql, code in (("core", 1146), ("col", 1054)):
                with self.assertRaises(realmread.Gap) as caught:
                    rd.must(sql)
                self.assertEqual(caught.exception.code, code)
                self.assertIsInstance(caught.exception.__cause__, ERR.MySQLError)

    def test_a_must_read_raises_any_other_error_as_it_is(self):
        db = Db({"core": LOST})
        with (
            realmread.Session(db.connect) as rd,
            self.assertRaises(ERR.OperationalError),
        ):
            rd.must("core")

    def test_no_params_is_executed_without_any(self):
        """pymysql formats `sql % params` whenever params is not None, so a
        statement with a literal %% must keep the shape its caller gave it."""
        db = Db({"SELECT 1": [], "SELECT '<%%'": []})
        with realmread.Session(db.connect) as rd:
            rd.rows("SELECT 1")
            rd.must("SELECT '<%%'", ())
        self.assertEqual(db.executed, [("SELECT 1", None), ("SELECT '<%%'", ())])

    def test_one_connection_opened_late_and_closed_once(self):
        db = Db({"a": [], "b": []})
        with realmread.Session(db.connect) as rd:
            self.assertEqual(db.opened, 0)
            rd.rows("a")
            rd.must("b")
        self.assertEqual((db.opened, db.closed), (1, 1))

    def test_a_session_never_read_never_connects(self):
        db = Db({})
        with realmread.Session(db.connect):
            pass
        self.assertEqual((db.opened, db.closed), (0, 0))

    def test_the_connection_is_closed_when_a_read_fails(self):
        db = Db({"a": LOST})
        with (
            self.assertRaises(ERR.OperationalError),
            realmread.Session(db.connect) as rd,
        ):
            rd.rows("a")
        self.assertEqual(db.closed, 1)


class TheMemoryReader(unittest.TestCase):
    def test_a_known_query_is_answered(self):
        rd = realmread.Memory({"SELECT a FROM t": [{"a": 1}]})
        self.assertEqual(rd.rows("SELECT a FROM t"), [{"a": 1}])
        self.assertEqual(rd.must("SELECT a FROM t"), [{"a": 1}])

    def test_an_unknown_query_raises_and_names_it(self):
        rd = realmread.Memory({"SELECT a FROM t": []})
        with self.assertRaises(realmread.UnknownQuery) as caught:
            rd.rows("SELECT a FROM renamed", (), what="t")
        self.assertIn("SELECT a FROM renamed", str(caught.exception))

    def test_an_answer_may_depend_on_the_values(self):
        rd = realmread.Memory({"q": lambda params: [{"n": params[0] * 2}]})
        self.assertEqual(rd.rows("q", (21,)), [{"n": 42}])

    def test_a_missing_table_is_answered_like_the_database(self):
        rd = realmread.Memory({"wide": realmread.MISSING_TABLE, "thin": [{"a": 1}]})
        self.assertEqual(rd.rows("wide", (), fallback="thin"), [{"a": 1}])
        self.assertEqual(rd.rows("wide"), [])
        with self.assertRaises(realmread.Gap):
            rd.must("wide")

    def test_a_missing_column_is_answered_like_the_database(self):
        rd = realmread.Memory({"wide": realmread.MISSING_COLUMN, "thin": [{"a": 1}]})
        self.assertEqual(rd.rows("wide", (), fallback="thin"), [{"a": 1}])
        self.assertEqual(rd.rows("wide"), [])
        with self.assertRaises(realmread.Gap) as caught:
            rd.must("wide")
        self.assertEqual(caught.exception.code, realmread.MISSING_COLUMN)

    def test_every_statement_is_recorded_with_its_values(self):
        rd = realmread.Memory({"q": []})
        rd.rows("q", (1,))
        rd.must("q")
        self.assertEqual(rd.asked, [("q", (1,)), ("q", None)])

    def test_a_query_is_named_by_its_template(self):
        """A statement built by .format() is answered under the constant it was
        built from, whatever the fields were filled with; its fixed text must
        still match exactly."""
        template = "SELECT name FROM characters WHERE name IN ({holes}) LIMIT %s"
        rd = realmread.Memory({template: [{"name": "Grug"}]})
        for holes in ("%s", "%s, %s, %s"):
            sql = template.format(holes=holes)
            self.assertEqual(rd.rows(sql, ("Grug", 9)), [{"name": "Grug"}])
        with self.assertRaises(realmread.UnknownQuery):
            rd.rows("SELECT name FROM characters WHERE guid IN (%s) LIMIT %s")

    def test_an_exact_statement_wins_over_its_template(self):
        template = "SELECT a FROM t WHERE b IN ({holes})"
        one = template.format(holes="%s")
        rd = realmread.Memory({template: [{"a": "many"}], one: [{"a": "one"}]})
        self.assertEqual(rd.rows(one), [{"a": "one"}])
        self.assertEqual(rd.rows(template.format(holes="%s, %s")), [{"a": "many"}])

    def test_an_error_answer_is_raised(self):
        rd = realmread.Memory({"q": OSError("connection reset")})
        with self.assertRaises(OSError):
            rd.rows("q")


class TheServerOpensOneReaderPerRequest(unittest.TestCase):
    """Every /api/v2 handler reads through the request's one reader: one
    connection however many reads, closed when the request ends, and none
    at all for a request refused before its first read."""

    def serve(self, path, answers):
        from unittest import mock

        import map_server
        from tests.test_app_shell import get

        db = Db(answers)
        with mock.patch.object(map_server, "_connect", db.connect):
            handler = get(path)
        return handler, db

    def test_three_reads_are_one_connection_closed_once(self):
        from apiv2 import roll

        handler, db = self.serve(
            "/api/v2/roll",
            {roll.BUILD_SQL: [], roll.VERSION_SQL: [], roll.UPTIME_SQL: []},
        )
        self.assertEqual(handler.status(), 200)
        self.assertEqual(len(db.executed), 3)
        self.assertEqual((db.opened, db.closed), (1, 1))

    def test_a_failed_read_still_closes_the_connection(self):
        from apiv2 import roll

        handler, db = self.serve("/api/v2/roll", {roll.BUILD_SQL: LOST})
        self.assertEqual(handler.status(), 503)
        self.assertEqual((db.opened, db.closed), (1, 1))

    def test_a_request_refused_before_a_read_opens_nothing(self):
        handler, db = self.serve("/api/v2/run?id=nope", {})
        self.assertEqual(handler.status(), 400)
        self.assertEqual((db.opened, db.closed), (0, 0))


if __name__ == "__main__":
    unittest.main()
