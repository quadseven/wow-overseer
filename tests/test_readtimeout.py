"""A timed-out database read is named in one line, not a traceback (#1664)."""

import logging
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import readtimeout  # noqa: E402


class _Driver(Exception):
    """Stands in for pymysql.err.OperationalError (same args shape)."""


TIMEOUT = _Driver(2013, "Lost connection to MySQL server during query (timed out)")


class _Cursor:
    def __init__(self, exc=None):
        self.exc, self.sql = exc, None

    def execute(self, sql, params=()):
        self.sql = sql
        if self.exc:
            raise self.exc
        return 3


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 10.0
        return self.t


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _log():
    log = logging.getLogger("test-readtimeout")
    log.handlers = [_Capture()]
    log.propagate = False
    return log, log.handlers[0]


class TimedExecute(unittest.TestCase):
    def test_a_good_read_returns_the_driver_result(self):
        self.assertEqual(readtimeout.timed_execute(_Cursor(), "x", "SELECT 1"), 3)

    def test_a_timeout_is_tagged_with_the_read_and_reraised_unchanged(self):
        exc = _Driver(*TIMEOUT.args)
        with self.assertRaises(_Driver) as ctx:
            readtimeout.timed_execute(
                _Cursor(exc), "answered share rows", "S", clock=_Clock()
            )
        self.assertIs(ctx.exception, exc)
        self.assertEqual(exc.read_name, "answered share rows")
        self.assertEqual(exc.read_seconds, 10.0)

    def test_other_errors_are_not_tagged(self):
        for exc in (
            _Driver(1146, "no such table"),
            _Driver(2013, "gone away"),
            ValueError("x"),
        ):
            with self.assertRaises(type(exc)):
                readtimeout.timed_execute(_Cursor(exc), "r", "S")
            self.assertFalse(hasattr(exc, "read_name"))


class LogPassFailure(unittest.TestCase):
    def _run(self, exc):
        log, cap = _log()
        try:
            raise exc
        except Exception:
            readtimeout.log_pass_failure(
                log, "questers", "questers: pass failed; retrying next cycle"
            )
        return cap.records

    def test_a_tagged_timeout_logs_one_summary_line_without_a_traceback(self):
        exc = _Driver(*TIMEOUT.args)
        exc.read_name, exc.read_seconds = "answered share rows", 10.04
        (rec,) = self._run(exc)
        self.assertEqual(rec.levelno, logging.WARNING)
        self.assertIsNone(rec.exc_info)
        self.assertEqual(
            rec.getMessage(),
            "questers: pass failed; the 'answered share rows' read timed out after 10.0s; "
            "retrying next cycle",
        )

    def test_any_other_failure_keeps_the_traceback(self):
        (rec,) = self._run(ValueError("boom"))
        self.assertEqual(rec.levelno, logging.ERROR)
        self.assertIsNotNone(rec.exc_info)
        self.assertEqual(rec.getMessage(), "questers: pass failed; retrying next cycle")


class TheBridgeIsWired(unittest.TestCase):
    src = (ROOT / "bridge.py").read_text(encoding="utf-8")

    def test_the_slow_reads_run_through_timed_execute(self):
        self.assertIn("readtimeout.timed_execute(cur, what, sql, params)", self.src)
        self.assertIn('cur, "answered share rows",', self.src)

    def test_the_three_pass_loops_log_through_the_summary(self):
        for name in ("questers", "quest sharing", "guild jobs"):
            self.assertIn("readtimeout.log_pass_failure(\n", self.src)
            self.assertRegex(
                self.src, r'log, "%s", "[^"]*pass failed; retrying next cycle"\)' % name
            )

    def test_the_module_ships_in_the_image(self):
        self.assertIn(
            "readtimeout.py", (ROOT / "Dockerfile").read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
