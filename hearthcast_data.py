"""The reads behind hearthcast: stone, cooldown and pulse (#2333).

The SQL and the pure readers of its rows are here; `read` runs the three
statements on a cursor the bridge hands it and writes nothing.

WHERE EACH FACT COMES FROM.

  the stone      `STONES_SQL`: a hearthstone in the backpack or in a worn bag.
                 The bank is not counted, because the core's own lookup for
                 an item to use does not look there.
  the cooldown   `COOLDOWNS_SQL`: the character's saved cooldown for the
                 hearthstone, by its item or its spell, still running. This
                 is the only place a cast the bridge did not write shows up.
  the pulse      `PULSE_SQL`: the live snapshot's health and whether a corpse
                 lies somewhere, read the way guildrun reads a ghost.

HOW FRESH. The inventory and the cooldown table are written on the player
save timer and can be minutes behind. A stale "on cooldown" only drops a hub
that could have been kept. A cast the bridge wrote is covered by its own
command row (bridge._movement_reads), whatever the table says.

EACH FACT IS READ ON ITS OWN. A read that fails never raises and never takes
another down: its field stays None, which hearthcast reads as "cannot cast",
and the failure is logged once per fact for the life of the process.
"""

from __future__ import annotations

from dataclasses import dataclass

# The hearthstone and the spell its use casts, in 3.3.5a.
HEARTHSTONE_ITEM = 6948
HEARTHSTONE_SPELL = 8690

STONES_SQL = (
    "SELECT c.name AS name, COUNT(*) AS stones "
    "FROM characters c "
    "JOIN character_inventory ci ON ci.guid = c.guid "
    "JOIN item_instance ii ON ii.guid = ci.item "
    "WHERE c.name IN (%s) AND ii.itemEntry = %%s "
    "AND ((ci.bag = 0 AND ci.slot BETWEEN 23 AND 38) "
    "OR ci.bag IN (SELECT bag.item FROM character_inventory bag "
    "WHERE bag.guid = ci.guid AND bag.bag = 0 AND bag.slot BETWEEN 19 AND 22)) "
    "GROUP BY c.name"
)

COOLDOWNS_SQL = (
    "SELECT c.name AS name, MAX(sc.time) AS ends_at, "
    "UNIX_TIMESTAMP() AS read_at "
    "FROM characters c "
    "JOIN character_spell_cooldown sc ON sc.guid = c.guid "
    "WHERE c.name IN (%s) AND (sc.item = %%s OR sc.spell = %%s) "
    "AND sc.time > UNIX_TIMESTAMP() "
    "GROUP BY c.name"
)

PULSE_SQL = (
    "SELECT s.name AS name, s.health AS health, "
    "EXISTS (SELECT 1 FROM corpse k WHERE k.guid = s.guid) AS has_corpse "
    "FROM overseer_snapshot s "
    "WHERE s.name IN (%s) AND s.updated_at > NOW() - INTERVAL 60 SECOND"
)


@dataclass(frozen=True)
class Facts:
    """What was read. A field is None when its read failed."""

    stones: frozenset | None = None  # the names that carry a hearthstone
    cooldowns: dict | None = None  # name -> seconds left, only when running
    alive: dict | None = None  # name -> bool, only for a fresh snapshot


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def stones_from_rows(rows) -> frozenset:
    """The names with at least one carried hearthstone."""
    return frozenset(
        str(r.get("name"))
        for r in rows or ()
        if r.get("name") and _int(r.get("stones")) > 0
    )


def cooldowns_from_rows(rows) -> dict:
    """name -> whole seconds the hearthstone is still on cooldown.

    A row with no usable clock still means "on cooldown": the statement only
    returns a cooldown that is running, and one second is enough to say so.
    """
    out = {}
    for r in rows or ():
        name = r.get("name")
        if not name:
            continue
        left = _int(r.get("ends_at")) - _int(r.get("read_at"))
        out[str(name)] = float(max(left, 1))
    return out


def alive_from_rows(rows) -> dict:
    """name -> alive, for each fresh snapshot row.

    A released ghost reports a health of 1 and has a corpse, and the core
    does not count it alive. A corpse alone is not death: a member raised
    before its corpse turned to bones keeps the row at full health.
    """
    out = {}
    for r in rows or ():
        name = r.get("name")
        if not name:
            continue
        health = _int(r.get("health"))
        out[str(name)] = health > 1 or (health == 1 and not r.get("has_corpse"))
    return out


# The facts whose failed read was already logged, so a broken read says so
# once and not on every errand start.
_SAID_FAILED: set = set()


def _say_failed(what: str, exc: Exception, log) -> None:
    """Log a failed read of `what`, the first time since it last worked."""
    if what in _SAID_FAILED:
        return
    _SAID_FAILED.add(what)
    if log is not None:
        log.warning(
            "hearth cast: %s could not be read (%s); no hearthstone hub is kept on it",
            what,
            type(exc).__name__,
        )


def _rows(cur, what: str, sql: str, args: tuple, log):
    """The statement's rows as dicts, or None when the read failed."""
    try:
        cur.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # a failed read must not reach the errand
        _say_failed(what, exc, log)
        return None
    _SAID_FAILED.discard(what)
    return rows


def read(cur, names, log=None) -> Facts:
    """Read the three facts for `names` on `cur`. Reads only."""
    names = tuple(sorted(names or ()))
    if not names:
        return Facts(frozenset(), {}, {})
    marks = ", ".join(["%s"] * len(names))
    stones = _rows(
        cur,
        "the carried hearthstone",
        STONES_SQL % marks,
        (*names, HEARTHSTONE_ITEM),
        log,
    )
    cooldowns = _rows(
        cur,
        "the hearthstone cooldown",
        COOLDOWNS_SQL % marks,
        (*names, HEARTHSTONE_ITEM, HEARTHSTONE_SPELL),
        log,
    )
    pulse = _rows(cur, "the live pulse", PULSE_SQL % marks, names, log)
    return Facts(
        stones=None if stones is None else stones_from_rows(stones),
        cooldowns=None if cooldowns is None else cooldowns_from_rows(cooldowns),
        alive=None if pulse is None else alive_from_rows(pulse),
    )


# What a connection that could not be opened is called in the log.
_REALM = "the realm"


def read_from(connect, names, log=None) -> Facts:
    """`read` on a connection `connect()` opens, closed again here.

    A connection that cannot be opened is a failed read of all three facts:
    every field stays None, it is logged once, and nothing raises.
    """
    try:
        with connect() as conn, conn.cursor() as cur:
            facts = read(cur, names, log)
    except Exception as exc:  # a realm that is away must not reach the errand
        _say_failed(_REALM, exc, log)
        return Facts()
    _SAID_FAILED.discard(_REALM)
    return facts
