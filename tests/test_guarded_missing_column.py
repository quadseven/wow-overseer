"""_guarded falls back on a missing column, which pymysql raises as
OperationalError rather than ProgrammingError.

Measured on the dev realm: the loot story's read named four columns a
not-yet-migrated overseer_event lacked, pymysql raised OperationalError 1054,
_guarded caught only ProgrammingError, and /api/loot answered 503 instead of
the thinner list its fallback exists to serve.

Tickets: #187.
"""

import unittest

try:
    import pymysql  # noqa: F401
except ImportError:  # pragma: no cover - CI installs it; a bare checkout may not
    pymysql = None


@unittest.skipIf(pymysql is None, "pymysql is not installed")
class AMissingColumnFallsBack(unittest.TestCase):
    def setUp(self):
        import map_server

        self.ms = map_server

    def _cursor(self, fail_first_with):
        calls = []

        class Cur:
            def execute(self, sql, params=()):
                calls.append(sql)
                if len(calls) == 1 and fail_first_with is not None:
                    raise fail_first_with

            def fetchall(self):
                return [("row",)]

        return Cur(), calls

    def test_a_missing_column_takes_the_fallback(self):
        err = pymysql.err.OperationalError(1054, "Unknown column 'e.item_guid'")
        cur, calls = self._cursor(err)
        rows = self.ms._guarded(cur, "wide", (), fallback="thin", what="t")
        self.assertEqual(rows, [("row",)])
        self.assertEqual(calls, ["wide", "thin"])

    def test_a_missing_table_still_takes_the_fallback(self):
        err = pymysql.err.ProgrammingError(1146, "Table doesn't exist")
        cur, calls = self._cursor(err)
        self.assertEqual(self.ms._guarded(cur, "wide", (), fallback="thin"), [("row",)])
        self.assertEqual(calls, ["wide", "thin"])

    def test_any_other_error_still_raises(self):
        err = pymysql.err.OperationalError(2013, "Lost connection")
        cur, _ = self._cursor(err)
        with self.assertRaises(pymysql.err.OperationalError):
            self.ms._guarded(cur, "wide", (), fallback="thin")


if __name__ == "__main__":
    unittest.main()
