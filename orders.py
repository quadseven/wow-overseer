"""The command queue as one module: send an order, follow it, ask if a verb is known.

bridge.py writes `overseer_command` from dozens of INSERT sites, reads it back
from bespoke follow loops, and checks MySQL error codes by hand at each. This
module is the small interface those callers move to, one verb at a time
(quadseven/wow-overseer#736):

  send(store, order)                  -> the new row id, 0 when the realm
                                         has no machinery for the verb
  follow(store, row_id, judge, ...)   -> the last judged answer, bounded
  supports(store, verb)               -> True when the realm knows the verb

Two adapters sit behind the same four methods (insert, read, kinds): the
MySQL one the bridge uses and a memory one tests use. Nothing here decides
WHICH order to give; that stays with the callers. It only moves rows.

Stdlib only. The MySQL adapter takes the bridge's connect function, so this
file never imports pymysql.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

# A missing column, a missing table, a truncated ENUM value: the three errors
# a realm that has not run a migration yet raises. They mean "this realm does
# not know the verb", not "the database is broken".
MISSING_MACHINERY = (1054, 1146, 1265)

PENDING_STATUSES = ("", "pending", "claimed", "verifying")


@dataclass(frozen=True)
class Order:
    """One row to write. `kind` is the verb; '' is the plain playerbot command."""

    target: str
    command: str
    source: str
    kind: str = ""
    target_arg: Optional[str] = None
    channel: Optional[str] = None


@dataclass(frozen=True)
class Answer:
    """What `follow` returns: the last judged value and whether it was final."""

    value: object
    final: bool
    row: Optional[dict] = None


class MemoryStore:
    """An in-memory queue with the MySQL adapter's behaviour, for tests."""

    def __init__(self, kinds=None):
        self._kinds = None if kinds is None else frozenset(kinds)
        self.rows: dict[int, dict] = {}
        self._next = 1

    def insert(self, order: Order) -> int:
        if self._kinds is not None and order.kind and order.kind not in self._kinds:
            return 0
        row_id = self._next
        self._next += 1
        self.rows[row_id] = {
            "id": row_id,
            "target_name": order.target,
            "command": order.command,
            "kind": order.kind,
            "source": order.source,
            "target_arg": order.target_arg,
            "channel": order.channel,
            "status": "pending",
            "detail": "",
            "result": "",
        }
        return row_id

    def read(self, row_id: int) -> Optional[dict]:
        row = self.rows.get(int(row_id))
        return dict(row) if row else None

    def kinds(self) -> Optional[frozenset]:
        return self._kinds

    def answer(
        self, row_id: int, status: str, detail: str = "", result: str = ""
    ) -> None:
        """Stand in for the worldserver finishing a row."""
        self.rows[row_id].update(status=status, detail=detail, result=result)


class MySqlStore:
    """overseer_command through a connect function that returns a pymysql-style
    connection (context manager, cursor() context manager, DictCursor rows)."""

    def __init__(self, connect: Callable):
        self._connect = connect
        self._kinds_cache: Optional[frozenset] = None

    def insert(self, order: Order) -> int:
        cols = ["target_name", "command"]
        vals: list = [order.target, order.command]
        if order.kind:
            cols.append("kind")
            vals.append(order.kind)
        if order.target_arg is not None:
            cols.append("target_arg")
            vals.append(order.target_arg)
        if order.channel is not None:
            cols.append("channel")
            vals.append(order.channel)
        cols.append("source")
        vals.append(order.source)
        sql = "INSERT INTO overseer_command (%s) VALUES (%s)" % (  # noqa: S608 - column names are fixed literals above; every value is bound
            ", ".join(cols),
            ", ".join(["%s"] * len(cols)),
        )
        with self._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute(sql, tuple(vals))
            except (
                Exception
            ) as exc:  # pymysql.err.MySQLError, kept out of this file's imports
                if exc.args and exc.args[0] in MISSING_MACHINERY:
                    return 0
                raise
            return int(cur.lastrowid or 0)

    def read(self, row_id: int) -> Optional[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT target_name, status, detail, result FROM overseer_command WHERE id = %s",
                    (int(row_id),),
                )
            except Exception as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    return None
                raise
            row = cur.fetchone()
            return dict(row) if row else None

    def kinds(self) -> Optional[frozenset]:
        """The verbs the `kind` ENUM holds, or None when it cannot be read."""
        if self._kinds_cache is not None:
            return self._kinds_cache
        with self._connect() as conn, conn.cursor() as cur:
            try:
                cur.execute("SHOW COLUMNS FROM overseer_command LIKE 'kind'")
            except Exception as exc:
                if exc.args and exc.args[0] in (1054, 1146):
                    return None
                raise
            row = cur.fetchone()
        if not row:
            return None
        found = parse_enum(str(row.get("Type") or row.get("type") or ""))
        if found is not None:
            self._kinds_cache = found
        return found


def parse_enum(column_type: str) -> Optional[frozenset]:
    """The members of an `enum('a','b')` column type, or None for any other type."""
    if not column_type.lower().startswith("enum("):
        return None
    return frozenset(re.findall(r"'((?:[^']|'')*)'", column_type))


def supports(store, verb: str) -> bool:
    """True when the realm knows `verb`. The empty verb (a plain command) always is.

    An unreadable ENUM answers True: not knowing is not a reason to stop
    writing, and `send` still returns 0 for a verb the realm turns away.
    """
    if not verb:
        return True
    kinds = store.kinds()
    return True if kinds is None else verb in kinds


def send(store, order: Order) -> int:
    """Write one order. The row id, or 0 when the realm has no machinery for it."""
    return store.insert(order)


def follow(
    store,
    row_id: int,
    judge: Callable[[dict], tuple],
    deadline: float,
    poll: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Answer:
    """Read a row until `judge` calls it final or `deadline` seconds pass.

    `judge(row)` returns `(value, final)`. A row that cannot be read ends the
    follow at once with final=True and value=None, the way every bespoke loop
    treated it. Reads happen after each wait, never before, matching the
    existing loops: a row written this instant is never answered this instant.
    """
    end = clock() + float(deadline)
    last = Answer(None, False)
    while clock() < end:
        sleep(poll)
        row = store.read(row_id)
        if row is None:
            return Answer(None, True)
        value, final = judge(row)
        last = Answer(value, bool(final), row)
        if final:
            break
    return last


def settled(row: dict) -> tuple:
    """A ready-made judge: final once the status leaves pending/claimed/verifying."""
    status = str(row.get("status") or "")
    return status, status not in PENDING_STATUSES
