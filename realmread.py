"""The realm reader: the one way the site reads the realm (#731).

    with realmread.Session(connect) as rd:
        rows = rd.rows(SQL, params, fallback=THINNER_SQL, what="overseer_x")
        core = rd.must(CORE_SQL, params)

A reader is opened once for a piece of work and read through as often as it
needs. It owns everything a read used to repeat at each call site:

- the connection. A Session connects on its first read, never before, keeps
  one cursor, and closes on exit, so a request refused before any read opens
  nothing.
- the degraded-schema rule. The realms are rolled one at a time, so a module
  table or column can be absent on the oldest realm. `rows()` treats exactly
  two errors as "this realm predates it": a missing table (1146) and a missing
  column (1054). It then tries `fallback`, a thinner statement, and then gives
  an empty read. Every other error raises, so a network blip still reaches the
  handler's 503 instead of rendering as an empty page.
- the logging of each such step.

`must()` is the strict read, for a table every realm has: any error raises,
and the two schema errors raise as Gap (the driver's error is its cause), so
a read with its own answer for "this realm cannot say" catches exactly that.

THE TWO ERRORS ARRIVE AS DIFFERENT CLASSES. pymysql raises 1146 as
ProgrammingError, and has no error_map entry for 1054, so a missing column
arrives as OperationalError. Only their base class, MySQLError, covers both,
and the code is what decides.

Two adapters sit behind the interface:

- Session, the database: pymysql, as the map server connects.
- Memory, for tests: it answers the statements it was given (by exact text,
  or by the template constant a statement is built from) and RAISES
  UnknownQuery on any other. A renamed or reworded statement therefore fails
  its test instead of reading as an empty result.

`params` is passed through as given, and None means none: pymysql formats
`sql % params` whenever params is not None, so `'<%%'` in a statement depends
on whether the caller passed `()`.

Read-only by contract: nothing here commits, and a write does not belong in a
reader.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

import pymysql

log = logging.getLogger("wow-map.realmread")

MISSING_TABLE = 1146
MISSING_COLUMN = 1054
_SCHEMA_GAPS = (MISSING_TABLE, MISSING_COLUMN)


class Gap(Exception):
    """A statement named a table or column this realm does not have."""

    def __init__(self, code: int, sql: str = "") -> None:
        super().__init__(code, sql)
        self.code = code


class UnknownQuery(BaseException):
    """The in-memory reader was asked a statement it was not given.

    A BaseException, not an Exception, on purpose: read paths catch Exception
    to degrade (a 503, a thinner page), and a test's unknown statement must
    fail the test, not degrade into a passing one.
    """


def _schema_gap(exc: BaseException) -> int | None:
    """1146 or 1054 when `exc` is pymysql reporting one, else None."""
    err = getattr(getattr(pymysql, "err", None), "MySQLError", None)
    if err is None or not isinstance(exc, err):
        return None
    code = exc.args[0] if exc.args else None
    return code if code in _SCHEMA_GAPS else None


class Reader:
    """`rows()` and `must()` over one adapter's `_run(sql, params)`.

    An adapter's `_run` returns the statement's rows as a list and raises Gap
    for a missing table or column; anything else it raises is passed on.
    """

    def _run(self, sql: str, params: Any) -> list:
        raise NotImplementedError

    def rows(
        self, sql: str, params: Any = None, *, fallback: str = "", what: str = ""
    ) -> list:
        """The statement's rows; on a missing table or column, `fallback`'s,
        then []. Any other error raises."""
        for attempt in (sql, fallback):
            if not attempt:
                break
            try:
                return self._run(attempt, params)
            except Gap as gap:
                log.info(
                    "%s unavailable (%s) - trying a thinner read",
                    what or "a read",
                    gap.code,
                )
        log.info("%s unavailable; using an empty read", what or "a read")
        return []

    def must(self, sql: str, params: Any = None) -> list:
        """The statement's rows. Every error raises: a missing table or column
        as Gap, so a caller that has its own answer for one can catch it."""
        return self._run(sql, params)

    def __enter__(self) -> Reader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Release what the reader holds (a Session: its connection)."""


class Session(Reader):
    """The database adapter: one connection, opened by the first read."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect
        self._conn = None
        self._cursor_cm = None
        self._cur = None

    def _cursor(self):
        if self._cur is None:
            self._conn = self._connect()
            self._cursor_cm = self._conn.cursor()
            self._cur = self._cursor_cm.__enter__()
        return self._cur

    def _run(self, sql: str, params: Any) -> list:
        cur = self._cursor()
        try:
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            return list(cur.fetchall())
        except Exception as exc:
            code = _schema_gap(exc)
            if code is None:
                raise
            raise Gap(code, sql) from exc

    def close(self) -> None:
        conn, cursor_cm = self._conn, self._cursor_cm
        self._conn = self._cursor_cm = self._cur = None
        if conn is None:
            return
        try:
            cursor_cm.__exit__(None, None, None)
        finally:
            conn.close()


class Memory(Reader):
    """The in-memory adapter: answers the statements it was given.

    `answers` maps a statement to its rows, to `f(params) -> rows`, to an
    exception to raise, or to MISSING_TABLE / MISSING_COLUMN for a realm
    without it. A key is matched by its exact text, or, when it is a template
    with `{fields}` (the constant a statement is built from with .format()),
    by its fixed text with any filling of the fields. An exact key wins over a
    template. Any statement that matches no key raises UnknownQuery. `asked`
    records every statement and its values, in order.
    """

    def __init__(self, answers: dict | None = None) -> None:
        self.answers = dict(answers or {})
        self.asked: list = []
        self._templates = [
            (re.compile(_template_pattern(key), re.DOTALL), key)
            for key in self.answers
            if _FIELD.search(key)
        ]

    def _answer_for(self, sql: str) -> Any:
        if sql in self.answers:
            return self.answers[sql]
        for pattern, key in self._templates:
            if pattern.fullmatch(sql):
                return self.answers[key]
        raise UnknownQuery("no answer for: %s" % sql)

    def _run(self, sql: str, params: Any) -> list:
        self.asked.append((sql, params))
        answer = self._answer_for(sql)
        if isinstance(answer, int) and answer in _SCHEMA_GAPS:
            raise Gap(answer, sql)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            answer = answer(params)
        return [dict(r) if isinstance(r, dict) else r for r in answer]


_FIELD = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def _template_pattern(template: str) -> str:
    """A regex for `template` with each `{field}` matching any text."""
    parts = _FIELD.split(template)
    return ".*?".join(re.escape(part) for part in parts)
