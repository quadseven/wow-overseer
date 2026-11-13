"""One bounded craft window for a family's crafter (#2369, slice 1 of #2368).

WHY THIS EXISTS. The operator wants the families to run in deliberate phases
(dungeon, craft, quest) instead of being interrupted all day (#2368). A
crafter's day today is whatever interrupts it: a dungeon pull, a town errand.
A craft errand that is always preempted looks the same as one that never
issues, which is why the trade stall on #774 could not be explained. One
bounded window for one family settles both: inside it the crafter is not
offered a dungeon group or a town errand, and the existing trade ladder and
gather errands are what it does. No new crafting verb lives here.

WHAT THIS DECIDES (`plan`), one family at a time, from facts and a clock:

  open     the family has a named crafter on the roster, none of the family is
           in a run, and the cool-down since its last window has passed (a
           family never run before opens at once). The window lasts at most
           MAX_WINDOW_SECONDS.
  close    the window ends itself by length. A crafter who left the roster
           ends it early. Nothing else can keep it open, so a stuck window
           ends by itself (`is_open` is a pure clock check and never trusts a
           stored flag).
  cool     COOLDOWN_SECONDS after a window ends, no new one opens.

Every open and every close is one log row: family, phase, start, end, reason.
The log is bounded (LOG_KEEP rows a family).

WHERE IT IS READ. The bridge keeps the state in the bridge memo store
(overseer_bridge_memo, kind MEMO_KIND, subject the family key), so no new
table; the site reads those rows beside /api/family (`page`). The memo row
expires, which is the safe direction: a lost row means no window.

THE SWITCH. CRAFT_PHASE defaults off; only an explicit on enables it, the way
DEATH_ASK does (deathask.py).

PURE: facts and `now` in, a decision and a log row out. No clock, no MySQL.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

ENV_SWITCH = "CRAFT_PHASE"
PHASE = "craft"
IDLE = "idle"

# The scheduled families: family key (the head's name) -> its crafter. Slice 1
# is one family, Cave, whose crafter mines and blacksmiths.
SCHEDULE = {"Grug": "Grug"}

MAX_WINDOW_SECONDS = 2 * 3600
COOLDOWN_SECONDS = 6 * 3600
LOG_KEEP = 10

MEMO_KIND = "craftphase"
# A memo row outlives a window and its cool-down, then drops by itself.
MEMO_KEEP_SECONDS = MAX_WINDOW_SECONDS + COOLDOWN_SECONDS + 3600
READ_SQL = (
    "SELECT subject, value, since FROM overseer_bridge_memo "
    "WHERE kind = %s AND expires > UNIX_TIMESTAMP()"
)

REASON_OPENED = "the cool-down passed and the crafter is free of runs"
REASON_LENGTH = "the window reached its maximum length"
REASON_GONE = "the crafter is no longer on the roster"


def enabled(environ=None) -> bool:
    """Off unless CRAFT_PHASE says on (explicit on only)."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


@dataclass(frozen=True)
class State:
    """One family's window: `started`/`ends` are set while a window stands,
    `last_end` is when the latest one ended (None: never run), `log` the
    bounded rows, newest last."""

    family: str
    crafter: str
    started: float | None = None
    ends: float | None = None
    last_end: float | None = None
    log: tuple = ()


@dataclass(frozen=True)
class Facts:
    """What the planner reads: the roster names and whether any of the family
    is in a run (a dungeon run, or a guild run the crafter is out in)."""

    roster: frozenset = frozenset()
    in_run: bool = False


@dataclass(frozen=True)
class Plan:
    """The next state and the log row this tick wrote (None: nothing)."""

    state: State
    row: dict | None = None


def is_open(state: State | None, now: float) -> bool:
    """Whether the window stands at `now`: a clock check, never a flag."""
    return bool(
        state is not None
        and state.started is not None
        and state.ends is not None
        and now < state.ends
    )


def _row(state: State, start: float, end: float, reason: str) -> dict:
    return {
        "family": state.family,
        "phase": PHASE,
        "start": start,
        "end": end,
        "reason": reason,
    }


def _logged(state: State, row: dict) -> tuple:
    return (tuple(state.log) + (row,))[-LOG_KEEP:]


def plan(state: State, facts: Facts, now: float) -> Plan:
    """The window's next state at `now`, and the log row it wrote."""
    if state.started is not None:
        over = state.ends is None or now >= state.ends
        gone = state.crafter not in facts.roster
        if not over and not gone:
            return Plan(state)
        end = min(now, state.ends) if state.ends is not None else now
        reason = REASON_LENGTH if over else REASON_GONE
        row = _row(state, state.started, end, reason)
        closed = State(
            state.family, state.crafter, last_end=end, log=_logged(state, row)
        )
        return Plan(closed, row)
    if state.crafter not in facts.roster or facts.in_run:
        return Plan(state)
    if state.last_end is not None and now - state.last_end < COOLDOWN_SECONDS:
        return Plan(state)
    ends = now + MAX_WINDOW_SECONDS
    row = _row(state, now, ends, REASON_OPENED)
    opened = State(
        state.family,
        state.crafter,
        started=now,
        ends=ends,
        last_end=state.last_end,
        log=_logged(state, row),
    )
    return Plan(opened, row)


def protected(states, now: float) -> frozenset:
    """The crafters inside an open window at `now`."""
    return frozenset(s.crafter for s in states or () if is_open(s, now))


def barred(crafters, names) -> bool:
    """Whether a family's `names` hold a protected crafter: the family's town
    errand and its campaign admission wait (the crafter is the family's
    walker or its head, so a family-wide start would pull it)."""
    return bool(set(crafters or ()) & set(names or ()))


def encode(state: State) -> dict:
    """The memo value for a state (JSON-safe)."""
    return {
        "crafter": state.crafter,
        "started": state.started,
        "ends": state.ends,
        "last_end": state.last_end,
        "log": list(state.log),
    }


def decode(family: str, value) -> State:
    """A state from a memo value; anything unreadable is a fresh state."""
    fresh = State(family, SCHEDULE.get(family, ""))
    if not isinstance(value, dict):
        return fresh

    def num(key):
        got = value.get(key)
        return float(got) if isinstance(got, (int, float)) else None

    rows = value.get("log")
    log = ()
    if isinstance(rows, list):
        log = tuple(r for r in rows if isinstance(r, dict))[-LOG_KEEP:]
    return State(
        family,
        SCHEDULE.get(family, ""),
        started=num("started"),
        ends=num("ends"),
        last_end=num("last_end"),
        log=log,
    )


def page(memo_rows, now: float) -> list:
    """The read the site shows: one entry per scheduled family the bridge
    wrote, sorted, each with its current phase and its log rows."""
    out = []
    for row in sorted(memo_rows or (), key=lambda r: str(r.get("subject"))):
        family = str(row.get("subject") or "")
        if family not in SCHEDULE:
            continue
        try:
            value = json.loads(row.get("value") or "{}")
        except (TypeError, ValueError):
            continue
        state = decode(family, value)
        open_now = is_open(state, now)
        out.append(
            {
                "family": family,
                "crafter": state.crafter,
                "phase": PHASE if open_now else IDLE,
                "since": state.started if open_now else None,
                "ends": state.ends if open_now else None,
                "log": list(state.log),
            }
        )
    return out
