"""Automatic dismissal of a death dialog that has persisted across two checks.

Pure module - no clock, no pixels, no subprocess. The client that owns the
screen runs its own detector (it measures the dialog button's click point
from the captured frame) and hands each check's result to verdict() here;
this module owns only the decision.

WHY TWO CHECKS
--------------
A dialog seen once may be legitimate: the character really did just die and
the release is still the server's business. A dialog seen on two consecutive
checks, after the server already released and resurrected the character, is
the stuck client-side widget from the ticket - the picture is wrong while the
character is fine. The first check proves presence; the second proves
persistence. Only then may the client be clicked.

WHY THE MEASURED POINT
----------------------
verdict() returns the current check's measured (fx, fy) - image fractions,
never pixel counts - so the click follows the dialog across resolutions and
window sizes instead of trusting coordinates that were true on one machine
on one night.

NEVER RAISES
------------
This decision runs inside the poll loop that holds a client. A malformed
detector result is treated as "no dialog", and anything unexpected anywhere
in the gate returns None: a blind check is a reason to look again next
tick, never a reason to take down the loop.
"""

from __future__ import annotations

import math


def _measured(value: object) -> tuple[float, float] | None:
    """The value as a well-formed (fx, fy) click point, or None.

    A detector result that is not a pair of finite image fractions is not a
    sighting - it is a reason to do nothing this check.
    """
    try:
        fx, fy = value  # type: ignore[misc]
    except (TypeError, ValueError):
        return None
    if not all(
        isinstance(v, (int, float)) and math.isfinite(v) and 0.0 <= v <= 1.0
        for v in (fx, fy)
    ):
        return None
    return (float(fx), float(fy))


def verdict(previous: object, current: object) -> tuple[float, float] | None:
    """Where to click to dismiss the death dialog, or None.

    previous: the detector's measured click point on the last check, or None.
    current: the detector's measured click point on this check, or None.

    Returns the current check's measured point when the dialog was seen on
    both checks, None otherwise. Never raises.
    """
    try:
        if _measured(previous) is None or _measured(current) is None:
            return None
        return _measured(current)
    except Exception:  # noqa: BLE001 - a blind check looks again next tick
        return None
