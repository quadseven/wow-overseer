"""Who is in the world now, and alive, dead or a ghost: one reading for every page.

    of(cur, names) -> {name: {"online": bool,
                              "life": "alive" | "dead" | "ghost" | None,
                              "fresh_at": int | None}}

ONLINE MEANS A FRESH SNAPSHOT. The module writes every character in the world
to overseer_snapshot every few seconds and deletes a row a minute after its
last write, so a row written in the last FRESH_SECONDS is a character the
world is holding now. characters.online is the save's flag and it lags. On
the dev realm, sampled every 30 seconds, 56 to 69 characters at a time were in
the world (a fresh snapshot, health changing) with online 0, every one a
random bot logged back in minutes before, and in steady play no character had
online 1 without a fresh snapshot. So the saved flag is not read for online at
all. The snapshot's own error is bounded by its minute: when the world stops,
its rows still read online for up to FRESH_SECONDS.

LIFE. A fresh snapshot with no health is a corpse ("dead"); with exactly one
point out of more than one it is a released spirit ("ghost"): the core sets a
ghost's health to 1 on release. Otherwise it is "alive". Without a fresh
snapshot the save is all there is, and it says only one thing: the ghost flag
in characters.playerFlags. A member offline with no flag has no reading
(None), never a guess.

`fresh_at` is the fresh snapshot's write time (unix seconds), None offline.

Two bounded reads, every name a bound parameter: the snapshot for the fresh
minute, then the saved flags of the names it did not answer for. Nothing is
written. The caller passes names, not the character rows it may already hold:
the gear table's read selects no playerFlags, and a row without them would
read every offline ghost as None. One small read of the offline names is the
price of a rule no caller can feed the wrong columns.
"""

from __future__ import annotations

# A snapshot younger than this is a character in the world. The module's own
# sweep deletes rows at the same age.
FRESH_SECONDS = 60
# PLAYER_FLAGS_GHOST: the saved flag a released spirit carries.
GHOST_FLAG = 0x10

_SNAP_SQL = (
    "SELECT name, health, max_health, UNIX_TIMESTAMP(updated_at) AS at "
    "FROM overseer_snapshot WHERE updated_at > NOW() - INTERVAL %s SECOND "
    "AND name IN ({holes})"
)
_FLAGS_SQL = "SELECT name, playerFlags AS flags FROM characters WHERE name IN ({holes})"


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


def _rows(cur, sql: str, names: list, *before) -> list:
    # S608: `holes` is a run of placeholders; every value is bound.
    cur.execute(sql.format(holes=_holes(len(names))), (*before, *names))  # noqa: S608
    return list(cur.fetchall())


def _life_in_world(snap: dict) -> str:
    health = int(snap.get("health") or 0)
    if health <= 0:
        return "dead"
    if health == 1 and int(snap.get("max_health") or 0) > 1:
        return "ghost"
    return "alive"


def _life_saved(flags) -> str | None:
    return "ghost" if int(flags or 0) & GHOST_FLAG else None


def _reading(snap: dict | None, flags) -> dict:
    if snap is None:
        return {"online": False, "life": _life_saved(flags), "fresh_at": None}
    at = snap.get("at")
    return {
        "online": True,
        "life": _life_in_world(snap),
        "fresh_at": int(at) if at is not None else None,
    }


def of(cur, names) -> dict:
    """Each name's reading: online, life and fresh_at (see the module doc)."""
    names = list(dict.fromkeys(names or ()))
    if not names:
        return {}
    snaps = {r["name"]: r for r in _rows(cur, _SNAP_SQL, names, FRESH_SECONDS)}
    away = [n for n in names if n not in snaps]
    flags = {}
    if away:
        flags = {r["name"]: r.get("flags") for r in _rows(cur, _FLAGS_SQL, away)}
    return {n: _reading(snaps.get(n), flags.get(n)) for n in names}
