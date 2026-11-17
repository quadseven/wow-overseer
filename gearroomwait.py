"""How long a routed hand-off may wait on its wearer's bags (#2245).

The gear routing executor (gearroutingexec.py) leaves a move waiting when the
wearer stands beside the holder with no free bag slot and no slot could be
freed. Nothing ended that wait: the same wearer was planned every pass, and a
piece another member could wear stayed in its holder's bags for as long as the
first wearer's bags stayed full.

This is the clock for it, and nothing else. `observe` starts a clock the first
pass a move is blocked for room and keeps it while the block lasts. Past the
bound the wearer is BARRED for that piece: `barred` hands the pairs to
`gearrouting.plan`, which plans the piece for the next member it is an upgrade
for. `release` lifts a bar once the wearer's bags have room again. Each change
returns one plain line, so the drop and the return are both on record.

Pure: the caller supplies the clock (a dict it keeps between passes), the
time and the bag read. The clock lives in the bridge process, so a restart
starts every wait again; a bar is a convenience, never a lost item.
"""

from dataclasses import dataclass, replace

import gearroutingexec

# The default bound, in minutes: long enough for a town errand or a sale pass
# to make the room, short enough that a piece does not sit a whole evening.
ROOM_WAIT_MINUTES = 60


@dataclass(frozen=True)
class Wait:
    """One move's wait on its wearer's bags."""

    since: float  # when the move was first blocked for room
    item: str  # the piece's name, for the lines
    barred: bool = False  # past the bound: not planned for this wearer


def _key(step) -> tuple:
    route = step.route
    return (str(route.holder), int(route.guid), str(route.wearer))


def observe(clock, result, now, bound_seconds) -> tuple:
    """(the clock after this pass, the lines to log).

    `clock` is {(holder, item guid, wearer): Wait}; `result` is the executor's
    Result for this pass. A move blocked for room keeps its first `since`; a
    move no longer blocked for room loses its clock. A bar is carried as it
    is: only `release` lifts one. `bound_seconds` of 0 or less bars nothing.
    """
    out, lines = {}, []
    for step in result.steps:
        if step.blocked != gearroutingexec.BLOCKED_ROOM:
            continue
        key = _key(step)
        old = clock.get(key)
        wait = old or Wait(since=float(now), item=str(step.route.item))
        waited = float(now) - wait.since
        if not wait.barred and 0 < float(bound_seconds) <= waited:
            wait = replace(wait, barred=True)
            holder, guid, wearer = key
            lines.append(
                "dropped: %s -> %s, %s (item %d): %s has had no free bag slot "
                "for %d minutes and no slot could be freed, so the piece is "
                "planned without %s until its bags have room"
                % (holder, wearer, wait.item, guid, wearer, waited // 60, wearer)
            )
        out[key] = wait
    for key, wait in clock.items():
        if wait.barred:
            out.setdefault(key, wait)
    return out, lines


def release(clock, free_slots) -> tuple:
    """(the clock with every bar lifted that can be, the lines to log).

    A bar holds only while the bag read says its wearer has no free slot. A
    wearer the read does not name is released too: an unread member is not
    known to be full, and a bar must not outlive the fact it stands on.
    """
    room = {str(k): int(v or 0) for k, v in dict(free_slots or {}).items()}
    out, lines = {}, []
    for key, wait in clock.items():
        _holder, guid, wearer = key
        if not wait.barred or (wearer in room and room[wearer] <= 0):
            out[key] = wait
            continue
        lines.append(
            "%s (item %d) is planned again for %s: %s"
            % (
                wait.item,
                guid,
                wearer,
                "its bags have room"
                if wearer in room
                else "its bags could not be read, so it is not held as full",
            )
        )
    return out, lines


def barred(clock) -> frozenset:
    """(wearer, item guid) for every bar, the shape gearrouting.plan takes."""
    return frozenset(
        (wearer, guid) for (_holder, guid, wearer), wait in clock.items() if wait.barred
    )


def barred_wearers(clock) -> list:
    """The barred wearers, whose bags `release` needs read."""
    return sorted({wearer for wearer, _guid in barred(clock)})
