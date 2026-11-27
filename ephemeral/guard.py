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
import math
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

# The judge queues an operator's order as the bridge writes it. A fixed
# statement with bound parameters, so nothing in a decree can reshape it.
COMMAND_TABLE = "overseer_command"
COMMAND_COLUMNS = ("target_name", "command", "kind", "source")
COMMAND_SQL = (
    "INSERT INTO `acore_characters`.`overseer_command` "
    "(`target_name`, `command`, `kind`, `source`) VALUES (%s, %s, %s, %s)"
)
COMMAND_SOURCE = "eph-judge"
COMMAND_KINDS = tuple(k for k in gamedata.COMMAND_KINDS if k != "gm")
# The semicolon is the playerbots `go x;y` separator; the row is bound as a parameter, never spliced.
_SAFE_COMMAND_TEXT = re.compile(r"^[A-Za-z0-9 _.,:;\-]{1,250}$")
_CHARACTER_NAME = re.compile(r"[A-Z][a-z]{1,11}")
_TRAVEL_GUARD_PREFIX = "guard:"
_TRAVEL_AIM_MAX_CHARS = 32
_TRAVEL_GUARD_READ = (
    "SELECT r.`travel_npc`, h.`mapId`, h.`posX`, h.`posY`, h.`posZ` "
    "FROM `acore_characters`.`overseer_roster` r "
    "JOIN `acore_characters`.`characters` c ON c.`name` = r.`name` "
    "AND CAST(c.`name` AS BINARY) = CAST(r.`name` AS BINARY) "
    "LEFT JOIN `acore_characters`.`character_homebind` h ON h.`guid` = c.`guid` "
    "WHERE r.`name` = %s AND CAST(r.`name` AS BINARY) = CAST(%s AS BINARY) "
    "AND r.`enabled` = 1"
)
_TRAVEL_GUARD_UPDATE = (
    "UPDATE `acore_characters`.`overseer_roster` SET `travel_npc` = %s "
    "WHERE `name` = %s AND CAST(`name` AS BINARY) = CAST(%s AS BINARY) "
    "AND `enabled` = 1 AND CAST(`travel_npc` AS BINARY) <=> CAST(%s AS BINARY)"
)


class GuardError(SeedError):
    """The guard refused; nothing was run."""


def _homebind_guard(map_id: int, x: float, y: float, z: float) -> str:
    coords = (x, y, z)
    if type(map_id) is not int or not 0 <= map_id <= 65535:
        raise GuardError("homebind map must be an unsigned small integer")
    if not all(
        type(value) in (float, int) and math.isfinite(value) for value in coords
    ):
        raise GuardError("homebind coordinates must be finite numbers")
    # Use the module's positional-aim precision within the roster column width.
    for precision in (1, 0):
        position = ",".join(f"{value:.{precision}f}" for value in coords)
        aim = f"{_TRAVEL_GUARD_PREFIX}{map_id}:{position}"
        if len(aim) <= _TRAVEL_AIM_MAX_CHARS:
            return aim
    raise GuardError("homebind guard exceeds the roster travel aim width")


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

    def end_read(self):
        """End the transaction a read opened, so the next read sees the world as it is now.

        MySQL's default REPEATABLE READ freezes what a connection sees at its first
        read. A judge that polls for the family to log in would read the empty world
        for ever (measured 2026-11-17: a start precondition read 0 for ten minutes
        while the rows were there). The seed must NOT call this: its reads and its
        writes are one transaction.
        """
        self._require_opened()
        self._conn.commit()

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
        """Queue one operator order (an overseer_command row).

        Never kind `gm` (bot sessions ignore it), only a kind the live schema
        and the module know, and only plain text, so a decree cannot smuggle
        anything else through this command path.
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

    def write_travel_guard(
        self, target: str, enabled: bool, *, expected: str | None = None
    ) -> str:
        """Set a homebind guard on an idle aim or clear this run's exact guard."""
        self._require_opened()
        if not isinstance(target, str) or _CHARACTER_NAME.fullmatch(target) is None:
            raise GuardError("travel guard needs a character name")
        if type(enabled) is not bool:
            raise GuardError("travel guard enabled must be boolean")
        if enabled and expected is not None:
            raise GuardError("setting a travel guard needs a blank travel aim")
        if not enabled and (
            not isinstance(expected, str)
            or not expected.startswith(_TRAVEL_GUARD_PREFIX)
            or not len(_TRAVEL_GUARD_PREFIX) < len(expected) <= _TRAVEL_AIM_MAX_CHARS
        ):
            raise GuardError("clearing a travel guard needs this run's exact guard")

        try:
            with contextlib.closing(self._conn.cursor()) as cur:
                cur.execute(_TRAVEL_GUARD_READ, (target, target))
                rows = cur.fetchall()
                if len(rows) != 1:
                    raise GuardError(
                        "travel guard needs exactly one enabled roster row"
                    )
                previous, map_id, x, y, z = rows[0]
                if enabled:
                    if previous not in (None, ""):
                        raise GuardError(
                            "setting a travel guard needs a blank travel aim"
                        )
                    if map_id is None:
                        raise GuardError("travel guard needs a current homebind")
                    aim = _homebind_guard(map_id, x, y, z)
                else:
                    if previous != expected:
                        raise GuardError(
                            "stored travel guard does not match this run's guard"
                        )
                    aim = ""
                cur.execute(_TRAVEL_GUARD_UPDATE, (aim, target, target, previous))
                if cur.rowcount != 1:
                    raise GuardError("travel aim changed before the guard write")
            self._conn.commit()
        except Exception:
            self._rollback_quietly()
            raise
        return aim

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
