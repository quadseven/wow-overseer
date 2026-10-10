"""GET /api/v2/run?id=N: one guild run, whenever it ran.

/api/guildruns answers the groups out now and the thirty that came back last,
which is all the Runs tab draws. The chronicle and a run's own links name older
runs too, and a run page that only looked in that window said "Not found" for
every one of them. This reads the one run by id (guildrun.by_id), shaped
exactly as /api/guildruns shapes a run, with its story for an ended run.

`id` must be a positive integer of at most 10 digits, else 400 before any
query. An id the table does not hold is 404. Read-only, one bounded row.
"""

from __future__ import annotations

import guildrun

_ID_MAX_DIGITS = 10


def run_id(value: str) -> int | None:
    """`value` as a run id, or None when it is not one."""
    value = (value or "").strip()
    if (
        not value
        or len(value) > _ID_MAX_DIGITS
        or not value.isascii()
        or not value.isdigit()
    ):
        return None
    n = int(value)
    return n if n > 0 else None


def run(query: dict, ctx) -> tuple[int, dict]:
    wanted = run_id((query.get("id") or [""])[0])
    if wanted is None:
        return 400, {"error": "id must be a positive whole number"}
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            view = guildrun.by_id(cur, wanted)
    finally:
        conn.close()
    if view is None:
        return 404, {"error": "no such run", "id": wanted}
    return 200, {"run": view}


ROUTES = {"/api/v2/run": run}
