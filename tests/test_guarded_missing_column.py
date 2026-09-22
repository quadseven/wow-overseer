"""_guarded falls back on a missing column, which pymysql raises as
OperationalError rather than ProgrammingError.

Measured on the dev realm: the loot story's read named four columns a
not-yet-migrated overseer_event lacked, pymysql raised OperationalError 1054,
_guarded caught only ProgrammingError, and /api/loot answered 503 instead of
the thinner list its fallback exists to serve.

Tickets: #187.
"""

import sys
import types
import unittest

# The same stub other suites install when pymysql is absent (CI installs
# nothing). It must carry the real hierarchy, because the point of this file is
# which CLASS a missing column arrives as: OperationalError and
# ProgrammingError are both MySQLError subclasses.
try:
    import pymysql  # noqa: F401  (the real library, when this machine has it)

    REAL_PYMYSQL = hasattr(pymysql, "connect")
except ImportError:
    REAL_PYMYSQL = False
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
if not hasattr(sys.modules["pymysql"], "err"):
    _err = types.ModuleType("pymysql.err")

    class _MySQLError(Exception):
        pass

    _err.MySQLError = _MySQLError
    sys.modules["pymysql"].err = _err

import map_server  # noqa: E402  (must follow the pymysql stub)

ERR = map_server.pymysql.err
for _name in ("OperationalError", "ProgrammingError"):
    if not hasattr(ERR, _name):
        setattr(ERR, _name, type(_name, (ERR.MySQLError,), {}))


class AMissingColumnFallsBack(unittest.TestCase):
    def setUp(self):
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
        err = ERR.OperationalError(1054, "Unknown column 'e.item_guid'")
        cur, calls = self._cursor(err)
        rows = self.ms._guarded(cur, "wide", (), fallback="thin", what="t")
        self.assertEqual(rows, [("row",)])
        self.assertEqual(calls, ["wide", "thin"])

    def test_a_missing_table_still_takes_the_fallback(self):
        err = ERR.ProgrammingError(1146, "Table doesn't exist")
        cur, calls = self._cursor(err)
        self.assertEqual(self.ms._guarded(cur, "wide", (), fallback="thin"), [("row",)])
        self.assertEqual(calls, ["wide", "thin"])

    def test_any_other_error_still_raises(self):
        err = ERR.OperationalError(2013, "Lost connection")
        cur, _ = self._cursor(err)
        with self.assertRaises(ERR.OperationalError):
            self.ms._guarded(cur, "wide", (), fallback="thin")


@unittest.skipUnless(REAL_PYMYSQL, "needs the real pymysql to read its error map")
class ThePremiseHoldsInTheRealLibrary(unittest.TestCase):
    """The whole fix rests on pymysql raising 1054 as OperationalError. Asked
    of the real library's own raise path, not of a stub built to agree."""

    def _raised(self, errno, text):
        import struct

        import pymysql.err as real

        packet = b"\xff" + struct.pack("<H", errno) + b"#42S22" + text.encode()
        with self.assertRaises(real.MySQLError) as ctx:
            real.raise_mysql_exception(packet)
        return type(ctx.exception)

    def test_a_missing_column_is_an_operational_error(self):
        import pymysql.err as real

        self.assertIs(self._raised(1054, "Unknown column"), real.OperationalError)

    def test_a_missing_table_is_a_programming_error(self):
        import pymysql.err as real

        self.assertIs(self._raised(1146, "Table missing"), real.ProgrammingError)


if __name__ == "__main__":
    unittest.main()
