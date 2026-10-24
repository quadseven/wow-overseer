"""Whether an auction house is worth listing in (wow-overseer#778).

A house with no buyers still shows a live listing, so a price read from the
live listings alone makes every stack routed there wait for a sale that never
comes, and a stack routed to the house is left out of the vendor's sale. The
house's own history says whether anything sells: `overseer_auction_history`
holds one row per finished lot, `sold` or `expired`.

A house is CLOSED when its last `RECENT` finished lots include none that
sold. Fewer than `RECENT` finished lots is not enough to judge, and a house
with no history at all stays open: a new house has not failed yet.
"""

RECENT = 20
SOLD = "sold"
EXPIRED = "expired"


def closed(outcomes, recent: int = RECENT) -> tuple:
    """(closed, sold, total) for `outcomes`, the newest finished lots first.

    Only `sold` and `expired` lots count; anything else is not a verdict.
    """
    verdicts = [str(o) for o in outcomes or () if str(o) in (SOLD, EXPIRED)]
    window = verdicts[: max(1, int(recent))]
    sold = sum(1 for o in window if o == SOLD)
    return (len(window) >= recent and sold == 0), sold, len(window)


def closed_line(house: int, total: int) -> str:
    """The log line that says a house was closed this pass."""
    return "auction: %s closed (0 of %d sold)" % (house, total)
