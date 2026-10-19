"""Pure recovery rule for a vendor trip that stopped moving.

The bridge supplies observations from the live snapshot and executes the
returned action. This module deliberately does not know how positions are
read or how a travel aim is released.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping


STALL_AFTER_SECONDS = 1200.0
MAX_BAG_WAIT_SECONDS = 2 * 60 * 60.0

HOLD = "hold"
RELEASE = "release"
YIELD = "yield"


@dataclasses.dataclass(frozen=True)
class Decision:
    """The recovery action and the reason that made it safe."""

    action: str
    reason: str


@dataclasses.dataclass(frozen=True)
class Movement:
    """The minimum state the bridge keeps between snapshot polls."""

    map_id: int
    x: float
    y: float
    z: float
    steady_since: float


@dataclasses.dataclass(frozen=True)
class Progress:
    """A pure comparison of the current snapshot with the previous one."""

    readable: bool
    progressed: bool
    stalled_seconds: float
    current: Movement | None


@dataclasses.dataclass(frozen=True)
class FamilyMovement:
    """The last readable position set for the family."""

    positions: tuple[tuple[str, int, float, float], ...]
    steady_since: float
    split_since: float | None


@dataclasses.dataclass(frozen=True)
class FamilyProgress:
    """A pure observation of whether the party is persistently split."""

    readable: bool
    split: bool
    progressed: bool
    split_seconds: float
    current: FamilyMovement | None


FAMILY_COHESION_YARDS = 100.0

# The member states mod-overseer's intent book writes (members_state) for a
# member it holds where it stands until the leader comes back for it (#1046).
# The module will not start that walk back while the bridge's vendor errand is
# in the leader's column, so the member is fetched after the sale either way;
# counted as a split, it called the trip off every STALL_AFTER_SECONDS and the
# leader turned between the two walks for hours with neither finished.
HELD_FOR_THE_LEADER = frozenset(
    {
        "held too far to walk",
        "held off a deadly walk",
        "walking back to the leader",
    }
)


def following(names, states: Mapping[str, str]) -> tuple[str, ...]:
    """The members whose distance says whether the family follows the trip.

    `states` is member name -> its intent book state; a member with none, or
    with any state but a hold for the leader, is watched.
    """
    return tuple(n for n in names if states.get(n) not in HELD_FOR_THE_LEADER)


def progress(
    previous: Movement | None,
    current: tuple | None,
    now: float,
    movement_epsilon: float = 1.0,
) -> Progress:
    """Track movement without making the database adapter a policy layer."""
    if current is None or len(current) < 4:
        return Progress(False, False, 0.0, previous)
    try:
        observed = tuple(float(value) for value in current[:4])
        map_id = int(observed[0])
    except (TypeError, ValueError):
        return Progress(False, False, 0.0, previous)
    if not all(math.isfinite(value) for value in observed):
        return Progress(False, False, 0.0, previous)
    if previous is None:
        fresh = Movement(map_id, observed[1], observed[2], observed[3], now)
        return Progress(True, True, 0.0, fresh)
    distance = math.sqrt(
        (observed[1] - previous.x) ** 2
        + (observed[2] - previous.y) ** 2
        + (observed[3] - previous.z) ** 2
    )
    moved = map_id != previous.map_id or distance >= movement_epsilon
    steady_since = now if moved else previous.steady_since
    fresh = Movement(map_id, observed[1], observed[2], observed[3], steady_since)
    return Progress(True, moved, max(0.0, now - steady_since), fresh)


def _family_position_rows(positions: Mapping[str, Mapping], names: tuple[str, ...]):
    """Normalize fresh snapshot rows without assigning policy to the adapter."""
    normalized = []
    for name in names:
        row = positions.get(name)
        if not isinstance(row, Mapping):
            return None
        try:
            map_id = int(row["map_id"])
            x = float(row["pos_x"])
            y = float(row["pos_y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (x, y)):
            return None
        normalized.append((name, map_id, x, y))
    return tuple(normalized)


def family_progress(
    previous: FamilyMovement | None,
    positions: Mapping[str, Mapping],
    names: tuple[str, ...],
    now: float,
    cohesion_yards: float = FAMILY_COHESION_YARDS,
    movement_epsilon: float = 1.0,
) -> FamilyProgress:
    """Track persistent party separation from fresh snapshot rows.

    A family is split when a member is on another map or farther than the
    cohesion radius from the first member. The split clock resets only when
    the family becomes cohesive again; movement while still split does not
    hide a party separated beyond the bounded window. Missing or invalid rows
    are unreadable and never release anything.
    """
    if not names:
        return FamilyProgress(False, False, False, 0.0, previous)
    current_rows = _family_position_rows(positions, names)
    if current_rows is None:
        return FamilyProgress(False, False, False, 0.0, previous)
    anchor = current_rows[0]
    split = any(
        map_id != anchor[1] or math.hypot(x - anchor[2], y - anchor[3]) > cohesion_yards
        for _name, map_id, x, y in current_rows[1:]
    )
    if previous is None:
        current = FamilyMovement(current_rows, now, now if split else None)
        return FamilyProgress(True, split, True, 0.0, current)
    moved = len(previous.positions) != len(current_rows)
    if not moved:
        for before, after in zip(previous.positions, current_rows):
            if before[0] != after[0] or before[1] != after[1]:
                moved = True
                break
            if (
                math.hypot(before[2] - after[2], before[3] - after[3])
                >= movement_epsilon
            ):
                moved = True
                break
    steady_since = now if moved else previous.steady_since
    if split:
        split_since = previous.split_since if previous.split_since is not None else now
    else:
        split_since = None
    current = FamilyMovement(current_rows, steady_since, split_since)
    return FamilyProgress(
        True,
        split,
        moved,
        max(0.0, now - split_since) if split_since is not None else 0.0,
        current,
    )


def decide(
    *,
    pressure: bool,
    at_counter: bool,
    sales_outstanding: int,
    movement_readable: bool,
    movement_progressed: bool,
    stalled_seconds: float,
    family_readable: bool = True,
    family_split: bool = False,
    family_progressed: bool = True,
    family_split_seconds: float = 0.0,
    stall_after_seconds: float = STALL_AFTER_SECONDS,
    bag_wait_seconds: float = 0.0,
    max_bag_wait_seconds: float = MAX_BAG_WAIT_SECONDS,
) -> Decision:
    """Decide whether a stalled vendor aim may be handed back.

    A release requires every positive fact: pressure still exists, the leader
    is not at the counter, the sell queue is drained, movement was readable,
    and no position progress has occurred for the bounded interval. Unknown
    queue or movement state always holds. The caller must still release with
    its exact ``travel_npc = 'vendor'`` compare-and-swap.
    """
    if not pressure:
        return Decision(HOLD, "no bag pressure")
    if not at_counter and bag_wait_seconds >= max(0.0, float(max_bag_wait_seconds)):
        return Decision(
            YIELD, "bag room not freed within the bounded wait; yielding the walk"
        )
    if at_counter:
        return Decision(HOLD, "leader is at the vendor counter")
    if sales_outstanding != 0:
        return Decision(HOLD, "vendor sale queue is outstanding or unreadable")
    if not movement_readable:
        return Decision(HOLD, "leader movement state is unreadable")
    if movement_progressed:
        leader_stalled = False
    else:
        leader_stalled = stalled_seconds >= max(0.0, float(stall_after_seconds))
    family_stalled = (
        family_readable
        and family_split
        and family_split_seconds >= max(0.0, float(stall_after_seconds))
    )
    if not leader_stalled and not family_stalled:
        if movement_progressed:
            return Decision(HOLD, "vendor travel is still progressing")
        if family_split and family_readable and family_progressed:
            return Decision(HOLD, "family is still regrouping")
        return Decision(HOLD, "vendor travel has not reached its stall window")
    if family_stalled and not leader_stalled:
        return Decision(RELEASE, "family split beyond the bounded stall window")
    return Decision(RELEASE, "vendor travel stalled beyond the bounded window")


# THE CLOCKS ACROSS A BRIDGE RESTART (#817). The bridge keeps the last
# Movement and FamilyMovement per leader in its memo store so a deploy does not
# count a stuck trip from zero. Their clocks are monotonic, and the monotonic
# clock means nothing to the next process, so the memo holds them as wall time:
# `offset` is wall time minus monotonic time at the moment of the call. The
# time the bridge was down is time the trip spent too, exactly as if it had
# kept running. A memo that does not decode raises KeyError, TypeError or
# ValueError; the caller drops it, which is the old cold start.


def movement_memo(movement: Movement, offset: float) -> dict:
    """A Movement as JSON for the memo store, its clock in wall time."""
    return {
        "map_id": int(movement.map_id),
        "x": float(movement.x),
        "y": float(movement.y),
        "z": float(movement.z),
        "steady_since": float(movement.steady_since) + offset,
    }


def movement_from_memo(value: Mapping, offset: float) -> Movement:
    """The Movement `movement_memo` stored, its clock back in monotonic time."""
    return Movement(
        int(value["map_id"]),
        float(value["x"]),
        float(value["y"]),
        float(value["z"]),
        float(value["steady_since"]) - offset,
    )


def family_memo(movement: FamilyMovement, offset: float) -> dict:
    """A FamilyMovement as JSON for the memo store, its clocks in wall time."""
    split = movement.split_since
    return {
        "positions": [list(row) for row in movement.positions],
        "steady_since": float(movement.steady_since) + offset,
        "split_since": None if split is None else float(split) + offset,
    }


def family_from_memo(value: Mapping, offset: float) -> FamilyMovement:
    """The FamilyMovement `family_memo` stored, back in monotonic time.

    JSON reads every tuple back as a list, and `family_progress` compares the
    rows it is given with the rows it computes, so they are tuples again here.
    """
    split = value["split_since"]
    return FamilyMovement(
        tuple(
            (str(name), int(map_id), float(x), float(y))
            for name, map_id, x, y in value["positions"]
        ),
        float(value["steady_since"]) - offset,
        None if split is None else float(split) - offset,
    )
