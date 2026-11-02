"""Name the database read that timed out (#1664).

A bridge pass that reads the database can lose the connection mid-query
("Lost connection to MySQL server during query (timed out)", error 2013) when a
read runs past the connection's read timeout. The pass is dropped and retried
next cycle, which is right, but the log used to hold a forty-line traceback that
never said WHICH read was slow. `timed_execute` runs one named read and, when it
times out, tags the same exception with the read's name and how long it ran;
`log_pass_failure` then writes ONE summary line for a tagged timeout and keeps
the full traceback for every other failure.

Stdlib only: the exception is recognised by its MySQL error number, not by
importing the driver, and it is re-raised unchanged (same class, same args), so
every `except pymysql.err.OperationalError` around a caller still catches it.
"""

from __future__ import annotations

import sys
import time

LOST_CONNECTION = 2013


def is_read_timeout(exc: BaseException) -> bool:
    """True for the driver's lost-connection error that carries 'timed out'."""
    args = getattr(exc, "args", ())
    return bool(args) and args[0] == LOST_CONNECTION and "timed out" in str(exc)


def timed_execute(cur, what: str, sql: str, params=(), clock=time.monotonic):
    """cur.execute(sql, params); a read timeout is tagged with `what` and the
    seconds the read ran, then re-raised unchanged."""
    started = clock()
    try:
        return cur.execute(sql, params)
    except Exception as exc:
        if is_read_timeout(exc):
            exc.read_name = what
            exc.read_seconds = clock() - started
        raise


def summary(pass_name: str, exc: BaseException) -> str | None:
    """The one line for a tagged read timeout, None for any other failure."""
    name = getattr(exc, "read_name", None)
    if name is None or not is_read_timeout(exc):
        return None
    return "%s: pass failed; the %r read timed out after %.1fs; retrying next cycle" % (
        pass_name,
        name,
        getattr(exc, "read_seconds", 0.0),
    )


def log_pass_failure(log, pass_name: str, message: str) -> None:
    """Call inside an `except Exception:` block. A tagged read timeout logs one
    warning line; anything else logs `message` with its traceback as before."""
    line = summary(pass_name, sys.exc_info()[1])
    if line is None:
        log.exception(message)
    else:
        log.warning(line)
