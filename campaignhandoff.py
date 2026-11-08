"""One dungeon campaign per family, whoever currently leads it (#1688).

mod-overseer counts a finished run on the LEADER's roster row only, and reads
the campaign cap from it too. `bridge._mark_party_leader` moves the lead flag
for a temporary leader (a profession errand traveller) and used to leave the
count behind: the substitute led with zero, so the coordinator opened run one
of the queue again.

`hand_over` runs on the same connection as the lead write. It raises every
enabled member who shares the new leader's dungeon job to the family's highest
recorded count and cap. It only ever raises, so repeated swaps are idempotent,
a stale read cannot overwrite newer progress, and a run finished while the
substitute led is carried back when the original leader returns. An explicit
new queue entry still resets every row to zero first, and rows on another
family, another job or a disabled row are never read or written.
"""

from typing import Optional

import jobs

_RAISE = {
    "dungeon_runs_done": (
        "UPDATE overseer_roster SET dungeon_runs_done = %s "
        "WHERE name = %s AND dungeon_runs_done < %s"
    ),
    "dungeon_runs_wanted": (
        "UPDATE overseer_roster SET dungeon_runs_wanted = %s "
        "WHERE name = %s AND dungeon_runs_wanted < %s"
    ),
}
_COLUMNS = tuple(_RAISE)


def _num(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _same_job(a, b) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def hand_over(cur, head: str, cohort: Optional[str]) -> int:
    """Share the governing count and cap with `head`'s dungeon-job family.

    Returns the number of roster rows raised; 0 when `head` is not on a
    dungeon job or nothing was behind.
    """
    scope = " AND family = %s" if cohort else ""
    cur.execute(
        "SELECT name, enabled, job, dungeon_runs_done, dungeon_runs_wanted "
        "FROM overseer_roster WHERE 1 = 1" + scope,  # noqa: S608 - fixed clause, values bound
        (cohort,) if cohort else (),
    )
    rows = cur.fetchall() or []
    lead = next((r for r in rows if r.get("name") == head), None)
    if lead is None or not jobs.is_dungeon_job(lead.get("job")):
        return 0
    members = [
        r
        for r in rows
        if _num(r.get("enabled")) and _same_job(r.get("job"), lead.get("job"))
    ]
    if lead not in members:
        return 0
    best = {col: max(_num(r.get(col)) for r in members) for col in _COLUMNS}
    raised = 0
    for row in members:
        for col in _COLUMNS:
            if _num(row.get(col)) >= best[col]:
                continue
            # `<` in the statement as well: a count the module wrote since the
            # read above is never lowered or overwritten.
            cur.execute(_RAISE[col], (best[col], row["name"], best[col]))
            raised += cur.rowcount or 0
    return raised
