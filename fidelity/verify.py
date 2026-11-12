"""Accept a fixture only if its claims re-derive from its own capture (#2281).

Run before a recorded fixture is kept, and again by the suite on every
scenario, so a claim edited after capture, or left behind when the capture
changed, is refused.
"""

from __future__ import annotations

from fidelity import derive, replay


def problems(fx) -> list:
    """Why `fx` is not acceptable; [] when its stored claims are the ones
    its capture's credited record gives."""
    try:
        derived = derive.claims(fx)
    except derive.NoCreditedRecord as err:
        return [str(err)]
    return replay.compare(
        derived, fx.expect, ("the capture derives", "the fixture stores")
    )
