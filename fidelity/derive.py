"""Derive a scenario's expected claims from its capture (#2281).

THIS MODULE IMPORTS NOTHING FROM THE OVERSEER, and a test pins that. The
expected outputs of a fixture must come from the realm's credited record at
capture time, never from the code under test; a module that called the
overseer's own functions to say what the realm credited would make every
fixture agree with the code by construction.

THE RULE, from the not-a-full-clear incident: trust credited encounter
records, never a run's own complete flag. A run is a clear only when it went
in, ended `cleared`, and its credited tally holds every encounter it expects.
The word `cleared` is necessary and never sufficient: the finder ends a
dungeon on its last boss with others still standing.

The credited record in a Chronicle capture is the run table's tally
(`bosses_done` of `bosses_total`). A run with no tally says nothing about
what was credited, so nothing is derived for it.
"""

from __future__ import annotations

CLEARED = "cleared"


class NoCreditedRecord(ValueError):
    """The capture holds no credited tally for a run it shows."""


def _is_run_row(row) -> bool:
    return (
        isinstance(row, dict)
        and "id" in row
        and "outcome" in row
        and "bosses_done" in row
        and "bosses_total" in row
    )


def claims(fx) -> dict:
    """The claims the capture's credited record supports, per run."""
    seen: dict = {}
    for read in fx.reads:
        for row in read.rows:
            if not _is_run_row(row):
                continue
            run = int(row["id"])
            done = int(row.get("bosses_done") or 0)
            total = int(row.get("bosses_total") or 0)
            if done <= 0 or total <= 0:
                raise NoCreditedRecord(
                    "run %d: the capture holds no credited tally" % run
                )
            seen[run] = {
                "run": run,
                "credited": done,
                "of": total,
                "clear": row["outcome"] == CLEARED and done >= total,
            }
    return {"runs": [seen[run] for run in sorted(seen)]}
