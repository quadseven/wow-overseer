"""THE SHARED RETRY GATE: a refused step is not asked again at full rate.

Every planner had its own cooldown, and none of them read why the last ask
failed, so a refusal that would come back the same (a walk refused as outside
the classic world, a shop walk refused in combat, a vendor walk across the
other side's ground) was asked again every cycle, hundreds of times a day. The
repeats also spent the member's hourly far walk budget, so a walk that might
have worked was refused at the cap.

Both step runners in the bridge (the guild jobs', which also runs the
questers' steps, and the corps', which also runs the raid supply's) ask this
gate before they write a step's first row. It reads that member's newest rows
of the same `source` and answers:

- a run of refusals the next moment may change (a fight, a move, a hold, a
  full bag): wait BASE_MINUTES, doubled for each refusal in the run, and after
  GIVE_UP_AFTER of them in a row give up until GIVE_UP_MINUTES have passed
  since the newest refusal (every wait is counted from the newest row);
- a refusal the module says will not pass (`retryable` or `retry` false, or
  the classic gate's Outland refusal): stop for PERMANENT_MINUTES.

A row that was applied or delivered ends the run. A pending row is not a
failure. The bridge logs one line when a member's hold starts or changes kind,
not once a cycle. Pure: the bridge reads the rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

BASE_MINUTES = 5
GIVE_UP_AFTER = 5
GIVE_UP_MINUTES = 3 * 60
PERMANENT_MINUTES = 6 * 60

# Rows read per (member, source): enough to see a full run to the give-up.
ROWS_READ = GIVE_UP_AFTER + 1

BACKOFF = "backoff"
GAVE_UP = "gave-up"
PERMANENT = "permanent"

FAILED = frozenset({"error", "unchanged"})

# Refusals the module calls retryable that do not pass while the member stays
# where it is. Matched on the module's literal text, so a reworded refusal
# upstream stops matching and must be updated here. The classic gate's sentence (mod-overseer's
# WalkRefusal::ExpansionContinent): the module marks it retryable and not
# transient, and a member standing there is refused the same way every ask.
LASTING_REASONS = frozenset(
    {"character stands in Outland or Northrend, outside the classic world"}
)


@dataclass(frozen=True)
class Tried:
    """One row of a step's history, as the gate reads it."""

    failed: bool
    age_minutes: int
    reason: str = ""
    retryable: object = None
    retry: object = None


def tried(row) -> Tried:
    """A command log row (status, age in minutes, result JSON) as a Tried."""
    status = str(row.get("status") or "")
    try:
        result = json.loads(row.get("result") or "{}")
    except (TypeError, ValueError):
        result = {}
    if not isinstance(result, dict):
        result = {}
    try:
        age = int(row.get("age") or 0)
    except (TypeError, ValueError):
        age = 0
    return Tried(
        failed=status in FAILED,
        age_minutes=age,
        reason=str(result.get("reason") or ""),
        retryable=result.get("retryable"),
        retry=result.get("retry"),
    )


def permanent(t: Tried) -> bool:
    """Whether the module said this refusal will not pass by waiting."""
    return t.reason in LASTING_REASONS or t.retryable is False or t.retry is False


@dataclass(frozen=True)
class Hold:
    """Why a step is not asked now, and for how much longer."""

    kind: str
    reason: str
    failures: int
    minutes_left: int

    def key(self, holder, source) -> tuple:
        """The state the bridge logs once: a new line when it changes."""
        return (holder, source, self.kind, self.reason)

    def line(self, holder, source) -> str:
        why = self.reason or "no reason given"
        if self.kind == PERMANENT:
            return "%s stops asking %s for %d minutes: refused for good (%s)" % (
                holder,
                source,
                self.minutes_left,
                why,
            )
        if self.kind == GAVE_UP:
            return (
                "%s gives up on %s for %d minutes after %d refusal(s) in a row: %s"
                % (holder, source, self.minutes_left, self.failures, why)
            )
        return (
            "%s waits %d minutes to ask %s again after %d refusal(s) in a row: %s"
            % (holder, self.minutes_left, source, self.failures, why)
        )


def hold(rows) -> Hold | None:
    """The hold on a step whose newest rows (any order) are `rows`, or None
    when it may be asked now."""
    history = sorted((tried(r) for r in rows or ()), key=lambda t: t.age_minutes)
    run = []
    for t in history:
        if not t.failed:
            break
        run.append(t)
    if not run:
        return None
    newest = run[0]
    if permanent(newest):
        kind, wait = PERMANENT, PERMANENT_MINUTES
    elif len(run) >= GIVE_UP_AFTER:
        kind, wait = GAVE_UP, GIVE_UP_MINUTES
    else:
        kind, wait = BACKOFF, BASE_MINUTES * 2 ** (len(run) - 1)
    left = wait - newest.age_minutes
    if left <= 0:
        return None
    return Hold(kind, newest.reason, min(len(run), GIVE_UP_AFTER), left)


def first_source(step) -> str:
    """The `source` of the first row a step writes: its walk's, else its first
    row's; "" for a step that writes nothing."""
    walk = getattr(step, "walk", None)
    if walk is not None:
        return str(getattr(walk, "source", "") or "")
    rows = getattr(step, "rows", ()) or ()
    return str(getattr(rows[0], "source", "") or "") if rows else ""
