"""The seed guard: the emitted SQL can only reach the world's own local database.

Three layers, none of which relies on the caller being careful:

1. `open_guarded` is the only way to get a `GuardedConnection`. It refuses any
   MySQL host but the literal loopback address (no DNS name, no `localhost`, no
   socket path), refuses unless the namespace carries the ephemeral label and
   the harness says grants are enabled, and refuses unless the marker table
   holds exactly one row. It then connects with the loopback constant, never
   with the caller's string.
2. `GuardedConnection.run` re-verifies every statement with
   `sqlgen.verify_statement` before executing it, so a hand-built string cannot
   skip the builder.
3. `apply_plan` accepts only a `GuardedConnection`.

The marker row is written by the forge when it builds the template, so a
database that did not come from a template (the long-running realm's, or a copy of it) has none.
Nothing here names a cluster host; the label value and the loopback address are
the only literals, and the label key is supplied by the pod's own spec.
"""

import contextlib
import re
import weakref
from dataclasses import dataclass

from . import gamedata
from .sqlgen import SeedError, verify_statement

LOOPBACK = "127.0.0.1"
WORLD_PORT = (
    3306  # the world pod's own MySQL; any other local port could be a different service
)
WORLD_LABEL_VALUE = "ephemeral"
GRANTS_ENABLED = "grants: enabled"
MARKER_TABLE = "ephemeral_world"
MARKER_SQL = "SELECT COUNT(*) FROM `acore_characters`.`ephemeral_world`"

# The judge's one write: an operator's order, as the bridge writes it. A fixed
# statement with bound parameters, so nothing in a decree can reshape it.
COMMAND_TABLE = "overseer_command"
COMMAND_COLUMNS = ("target_name", "command", "kind", "source")
COMMAND_SQL = (
    "INSERT INTO `acore_characters`.`overseer_command` "
    "(`target_name`, `command`, `kind`, `source`) VALUES (%s, %s, %s, %s)"
)
COMMAND_SOURCE = "eph-judge"
COMMAND_KINDS = tuple(k for k in gamedata.COMMAND_KINDS if k != "gm")
_SAFE_COMMAND_TEXT = re.compile(r"^[A-Za-z0-9 _.,:\-]{1,250}$")


class GuardError(SeedError):
    """The guard refused; nothing was run."""


@dataclass(frozen=True)
class GuardInputs:
    mysql_host: str
    world_label: str  # the namespace's own world label value, read from the pod
    harness_grants: str  # the harness ConfigMap's grants line
    mysql_port: int = 3306


def check_inputs(inputs):
    """Every reason the guard refuses, from the facts that need no connection."""
    why = []
    if inputs.mysql_host != LOOPBACK:
        why.append(f"MySQL host must be {LOOPBACK}, got {inputs.mysql_host!r}")
    if inputs.world_label != WORLD_LABEL_VALUE:
        why.append(
            f"namespace world label must be {WORLD_LABEL_VALUE!r}, got {inputs.world_label!r}"
        )
    if inputs.mysql_port != WORLD_PORT:
        why.append(f"MySQL port must be {WORLD_PORT}, got {inputs.mysql_port!r}")
    if (inputs.harness_grants or "").strip() != GRANTS_ENABLED:
        why.append(f"harness must say {GRANTS_ENABLED!r}")
    return why


# Connections that came out of open_guarded. A GuardedConnection built any other
# way (wrapping an arbitrary connection by hand) is not in this set and is
# refused by `run`, `query` and `apply_plan`.
_OPENED = weakref.WeakSet()
_MINT = object()  # module-private; open_guarded is the only holder
_READ_ONLY_FORBIDDEN = re.compile(
    r"(;|--|/\*|#|\b(INTO|OUTFILE|DUMPFILE|SLEEP|BENCHMARK|GET_LOCK|LOAD_FILE|FOR\s+UPDATE|LOCK\s+IN)\b)",
    re.I,
)


class GuardedConnection:
    """A connection that has passed the guard. Only `open_guarded` makes one."""

    def __init__(self, conn, schema, token):
        if token is not _MINT:
            raise GuardError("a GuardedConnection comes from open_guarded only")
        self._conn = conn
        self._schema = schema

    def _require_opened(self):
        if self not in _OPENED:
            raise GuardError("this connection did not come out of open_guarded")

    def use_schema(self, schema):
        """Verify statements against the world's live schema from here on."""
        self._schema = schema

    def query(self, sql, params=()):
        """Read-only helper for resolution: SELECT only."""
        self._require_opened()
        if not sql.lstrip().upper().startswith("SELECT") or _READ_ONLY_FORBIDDEN.search(
            sql
        ):
            raise GuardError("query() runs one plain SELECT only")
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params or None)  # no params: a literal % stays a %
            return list(cur.fetchall())
        finally:
            cur.close()

    def set_query_timeout(self, seconds):
        """Cap every later SELECT on this session (the server kills it past the cap)."""
        ms = int(seconds * 1000)
        if ms <= 0:
            raise GuardError("a query timeout must be positive")
        self._require_opened()
        cur = self._conn.cursor()
        try:
            cur.execute(f"SET SESSION max_execution_time = {ms}")
        finally:
            cur.close()

    def insert_command(self, target, kind, text, source=COMMAND_SOURCE):
        """Queue one operator order (an overseer_command row); the judge's only write.

        Never kind `gm` (bot sessions ignore it), only a kind the live schema
        and the module know, and only plain text, so a decree cannot smuggle
        anything else through the one path that writes.
        """
        self._require_opened()
        if kind not in COMMAND_KINDS:
            raise GuardError(f"command kind {kind!r} is not one a judge may queue")
        cols = self._schema.columns(COMMAND_TABLE, "acore_characters")
        if cols is None or any(c not in cols for c in COMMAND_COLUMNS):
            raise GuardError(f"{COMMAND_TABLE} lacks a column the judge writes")
        for label, value in (("target", target), ("text", text), ("source", source)):
            if not isinstance(value, str) or not _SAFE_COMMAND_TEXT.match(value):
                raise GuardError(f"command {label} {value!r} is not plain text")
        cur = self._conn.cursor()
        try:
            cur.execute(COMMAND_SQL, (target, text, kind, source))
            self._conn.commit()
            return cur.lastrowid
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def run(self, statements):
        """Verify every statement, then execute them in one transaction."""
        self._require_opened()
        statements = list(statements)
        for stmt in statements:
            verify_statement(stmt.sql, self._schema)
        cur = self._conn.cursor()
        try:
            for stmt in statements:
                cur.execute(stmt.sql)
            cur.close()  # before the commit: a failure here must still roll back
            self._conn.commit()
        except Exception:
            self._rollback_quietly()
            raise
        return len(statements)

    def _rollback_quietly(self):
        """Roll back; if that fails too, keep the original error (closing ends the transaction)."""
        with contextlib.suppress(Exception):
            self._conn.rollback()

    def close(self):
        self._conn.close()


def open_guarded(inputs, connect, schema, **connect_kwargs):
    """Pass the guard, connect to loopback, and return a GuardedConnection.

    `connect` is a DB-API style factory (for example pymysql.connect) taking
    host and port keywords. `schema` is the schema statements are verified
    against (the live one inside a world).
    """
    why = check_inputs(inputs)
    if why:
        raise GuardError("; ".join(why))
    conn = connect(host=LOOPBACK, port=inputs.mysql_port, **connect_kwargs)
    try:
        cur = conn.cursor()
        try:
            cur.execute(MARKER_SQL)
            (count,) = cur.fetchone()
        finally:
            cur.close()
        if count != 1:
            raise GuardError(f"{MARKER_TABLE} must hold exactly one row, found {count}")
    except Exception:
        conn.close()
        raise
    guarded = GuardedConnection(conn, schema, _MINT)
    _OPENED.add(guarded)
    return guarded


def apply_plan(plan, guarded):
    """Execute a compiled plan. Only a guarded connection is accepted."""
    if not isinstance(guarded, GuardedConnection):
        raise GuardError("apply_plan needs a GuardedConnection from open_guarded")
    return guarded.run(plan.statements)
