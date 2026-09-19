"""Pure dungeon campaign progression decisions.

The dungeon coordinator records which portal a run used.  A map id is not
enough for Scarlet Monastery because all four wings share map 189.  This
module consumes that durable portal identity and chooses the first wing whose
successful run count is below the requested campaign size.

No database, HTTP, or world access belongs here.  The adapter is responsible
for reading the run ledger and handing rows to these functions.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence


# The order is a progression contract, not a level ranking.  The library key
# is deliberately kept as the same job keyword the C++ coordinator accepts.
SCARLET_WINGS = (
    ("scarlet", 28),
    ("scarlet-library", 33),
    ("scarlet-armory", 36),
    ("scarlet-cathedral", 39),
)

SUCCESS_OUTCOMES = frozenset({"complete"})


def successful_runs(rows: Iterable[Mapping]) -> dict[str, int]:
    """Count successful runs by durable portal keyword.

    Rows without a keyword or without the explicit completion outcome are not
    counted.  In particular, ``left``, ``wipe``, ``emptied`` and
    ``reset_failed`` are attempts, not proof that a wing was cleared.
    """
    counts = {keyword: 0 for keyword, _ in SCARLET_WINGS}
    for row in rows:
        keyword = str(row.get("portal_keyword") or "")
        outcome = str(row.get("outcome") or "")
        if keyword in counts and outcome in SUCCESS_OUTCOMES:
            counts[keyword] += 1
    return counts


def next_scarlet_wing(
    completed: Mapping[str, int] | None,
    wanted: int,
    *,
    wings: Sequence[tuple[str, int]] = SCARLET_WINGS,
) -> str | None:
    """Return the first Scarlet wing with fewer than ``wanted`` successes.

    ``None`` for ``completed`` means the durable ledger is unavailable.  The
    caller must withhold a progression decision in that case; guessing from
    the family's level would skip lower wings and make a 25-run-per-wing
    campaign impossible to audit.
    """
    target = int(wanted)
    if target <= 0 or completed is None:
        return None
    for keyword, _ in wings:
        if int(completed.get(keyword, 0) or 0) < target:
            return keyword
    return None

