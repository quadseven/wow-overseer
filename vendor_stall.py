"""Pure recovery rule for a vendor trip that stopped moving.

The bridge supplies observations from the live snapshot and executes the
returned action. This module deliberately does not know how positions are
read or how a travel aim is released.
"""
from __future__ import annotations

import dataclasses
import math


STALL_AFTER_SECONDS = 1200.0

HOLD = "hold"
RELEASE = "release"


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


def progress(previous: Movement | None, current: tuple | None,
             now: float, movement_epsilon: float = 1.0) -> Progress:
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


def decide(*, pressure: bool, at_counter: bool, sales_outstanding: int,
           movement_readable: bool, movement_progressed: bool,
           stalled_seconds: float,
           stall_after_seconds: float = STALL_AFTER_SECONDS) -> Decision:
    """Decide whether a stalled vendor aim may be handed back.

    A release requires every positive fact: pressure still exists, the leader
    is not at the counter, the sell queue is drained, movement was readable,
    and no position progress has occurred for the bounded interval. Unknown
    queue or movement state always holds. The caller must still release with
    its exact ``travel_npc = 'vendor'`` compare-and-swap.
    """
    if not pressure:
        return Decision(HOLD, "no bag pressure")
    if at_counter:
        return Decision(HOLD, "leader is at the vendor counter")
    if sales_outstanding != 0:
        return Decision(HOLD, "vendor sale queue is outstanding or unreadable")
    if not movement_readable:
        return Decision(HOLD, "leader movement state is unreadable")
    if movement_progressed:
        return Decision(HOLD, "vendor travel is still progressing")
    if stalled_seconds < max(0.0, float(stall_after_seconds)):
        return Decision(HOLD, "vendor travel has not reached its stall window")
    return Decision(RELEASE, "vendor travel stalled beyond the bounded window")

