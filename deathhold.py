"""The flag that holds a death-looping member off its own wandering (#2152).

WHY THIS EXISTS. Most of the realm's deaths are guild members with no job,
dying on their own playerbot AI in a zone they keep going back to. The guild
jobs pass judges the loop (deathloop.judge) and its escape hearths the member
out, but a member with its hearth cooling, or bound inside the loop's zone,
stays there, and its own rpg status walks it straight back to what keeps
killing it. The module (quadseven/mod-overseer, `Overseer.DeathLoopHold.*`)
holds such a member off that wandering while it stands in the zone; this
module decides the row the bridge writes so the module knows who and where.

THE ROW. One overseer_bridge_memo row per flagged member: kind KIND, subject
the member's name, value {"map": <map id>, "zone": <zone id>, "level": <the
loop's level>}, `since` the time this loop was first flagged in this zone, and
`expires` since + HOLD_SECONDS + REST_SECONDS. The module holds for at most
its own bound (default HOLD_SECONDS) counted from `since`, and only while the
row is unexpired, so the hold is bounded twice.

BOUNDED. A row is written only for a loop the pass judged, in a zone the
member has no unexpired row for. While that row stands it is never rewritten,
so `since` never moves and the hold cannot be renewed by the next pass: after
the hold, the member gets REST_SECONDS of its own AI in that zone before a
loop there can flag it again. A level gained since the flag drops the row (the
loop's rule clears on a level gain too). A roster or family member is never
flagged: the module never holds one, and its own levelling owns it.

PURE: loops, members and memos in, rows out. No MySQL, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass

# overseer_bridge_memo's kind for the flag. The module reads exactly this
# string (OverseerDecisions::DEATH_LOOP_FLAG_KIND).
KIND = "death_loop_zone"
# The module's default bound on one hold (Overseer.DeathLoopHold.Seconds).
HOLD_SECONDS = 3 * 3600
# After the hold, how long the same zone is left to the member before a loop
# there flags it again.
REST_SECONDS = 3 * 3600


@dataclass(frozen=True)
class Write:
    """One row to upsert."""

    name: str
    value: dict
    since: float
    expires: float


@dataclass(frozen=True)
class Plan:
    """The rows to write and the names whose row is dropped."""

    writes: tuple = ()
    drops: tuple = ()


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def value_of(loop) -> dict:
    """The row's value for a deathloop.Loop."""
    return {
        "map": _int(loop.map_id),
        "zone": _int(loop.zone),
        "level": _int(loop.level),
    }


def _same_zone(old, loop) -> bool:
    return (
        isinstance(old, dict)
        and _int(old.get("zone"), -1) == _int(loop.zone)
        and _int(old.get("map"), -1) == _int(loop.map_id)
    )


def plan(loops, levels, memos, now, roster=()) -> Plan:
    """What to write for the members this pass judged.

    `loops` name -> deathloop.Loop; `levels` name -> the member's level now,
    for every member this pass read (only those are touched, so another
    cohort's rows are left alone); `memos` name -> (value, since) for this
    KIND's unexpired rows; `roster` the roster and family names."""
    loops = loops or {}
    memos = memos or {}
    roster = set(roster or ())
    writes = []
    drops = []
    for name in sorted(levels or {}):
        old = memos.get(name)
        old_value = old[0] if old else None
        if name in roster:
            if old is not None:
                drops.append(name)
            continue
        loop = loops.get(name)
        if old is not None:
            gained = isinstance(old_value, dict) and _int(levels.get(name)) > _int(
                old_value.get("level"), 1 << 30
            )
            if gained:
                drops.append(name)
                old = None
            elif loop is None or _same_zone(old_value, loop):
                # The standing row is kept as it is: its `since` never moves.
                continue
            # A loop in another zone: the new zone's row replaces it.
        if loop is None or _int(loop.zone) <= 0 or getattr(loop, "run", 0):
            continue
        writes.append(
            Write(
                name=name,
                value=value_of(loop),
                since=float(now),
                expires=float(now) + HOLD_SECONDS + REST_SECONDS,
            )
        )
    return Plan(
        writes=tuple(writes),
        drops=tuple(d for d in drops if d not in {w.name for w in writes}),
    )
