"""A family's trade turn between dungeon runs (#2262, part of #2261).

A family with a standing campaign queue never did trade work: the queue owns
the family's job while it holds an entry, and the game casts a craft only
while the job is craft. So after a queued run ends, the queue yields the
family's job for one turn, then takes it back and admits its next entry under
the usual rules.

PURE MODULE: no MySQL, no clock of its own. `decide` takes the last finished
run, the recorded turn, the time, the setting and the members' trade values,
and returns what to do and why. The record of a turn lives beside the queue's
own state (campaignqueue.TURN_CREATE_SQL), so a restart resumes the turn.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import classic

DEFAULT_SECONDS = 1200
# How long a turn waits out a job the trade passes do not act on (a town
# errand) before it frees the family; time on such a job is not counted. It
# outlasts an errand's walk, its wait and its sale (townerrand: 1200 + 300 +
# 480), or the turn would free a family whose bags are still full, and it stays
# inside the 45 minutes a campaign may be held. A test pins both bounds.
DEFAULT_TOWN_SECONDS = 2400

# What the leader's job is, for the turn's clock: one the crafting passes act
# on, a town errand holding the family, or anything else (a dungeon, a raid).
ON_TRADE = "trade"
TOWN = "town"
OTHER = "other"

START = "start"
HOLD = "hold"
RELEASE = "release"
END = "end"
SKIP = "skip"
NONE = "none"


@dataclass(frozen=True)
class Turn:
    """One recorded turn: the run it follows, when it began, whether it is
    finished (a skipped turn is recorded finished, so it is said once)."""

    run_ended: int
    started: float
    over: bool = False
    counted: float = 0.0  # seconds on a trade job (or past the allowance)
    off: float = 0.0  # allowance used: seconds off a trade job, not counted
    released: bool = False  # a town errand was already released once


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    remaining: float = 0.0
    turn: Turn | None = None  # the turn to record after this decision


def _whole(raw, default: int) -> int:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return default
    try:
        return max(0, int(text))
    except ValueError:
        return default


def seconds(raw) -> int:
    """TRADE_TURN_SECONDS: whole seconds, 0 turns the rule off, junk gets the
    default, a negative value turns the rule off."""
    return _whole(raw, DEFAULT_SECONDS)


def town_seconds(raw) -> int:
    """TRADE_TURN_TOWN_SECONDS: the allowance for time off a trade job, read
    as `seconds` is; 0 allows none."""
    return _whole(raw, DEFAULT_TOWN_SECONDS)


def trade_changes(before: dict, after: dict) -> list:
    """`name trade before->after` for each trade below the cap at the start."""
    return [
        "%s %s %d->%d"
        % (name, trade, value, int(((after or {}).get(name) or {}).get(trade, value)))
        for name, trade, value in below_cap(before)
    ]


def below_cap(trades: dict) -> list:
    """(member, trade, value) for each trade under the profession cap."""
    return sorted(
        (name, trade, int(value))
        for name, held in (trades or {}).items()
        for trade, value in (held or {}).items()
        if int(value or 0) < classic.MAX_PROFESSION_SKILL
    )


def needs_facts(last_run_end, turn: Turn | None) -> bool:
    """Whether a new turn could start, so the caller must read the run state
    and the trades. False while a turn is live or already taken."""
    if last_run_end is None:
        return False
    if turn is None:
        return True
    return turn.over and int(last_run_end) > turn.run_ended


def decide(
    last_run_end,
    turn: Turn | None,
    now: float,
    setting: int,
    trades: dict,
    mid_run: bool,
    kind: str = ON_TRADE,
    elapsed: float = 0.0,
    town_setting: int = DEFAULT_TOWN_SECONDS,
) -> Decision:
    """Start, hold, release, end or skip a trade turn, or do nothing.

    A live turn is judged by itself: a later run row cannot start a second
    one. One turn follows each finished run. A run in progress is never
    interrupted.

    A live turn counts only the time its leader spent on a trade job. Time on
    any other job is off the clock up to `town_setting` seconds, after which
    it counts again, so a turn never outlasts setting + town_setting plus the
    gap between two passes. `kind` is the leader's job this pass and `elapsed`
    the seconds since the last pass.
    """
    if turn is not None and not turn.over:
        return _live(turn, setting, kind, elapsed, town_setting)
    if last_run_end is None:
        return Decision(NONE, "no run has finished")
    if turn is not None and int(last_run_end) <= turn.run_ended:
        return Decision(NONE, "the turn for this run is already taken")
    if mid_run:
        return Decision(NONE, "a run is in progress")
    if setting <= 0:
        return Decision(SKIP, "TRADE_TURN_SECONDS is 0")
    low = below_cap(trades)
    if not low:
        return Decision(
            SKIP,
            "every trade of every member is at the cap of %d"
            % classic.MAX_PROFESSION_SKILL,
        )
    name, trade, value = low[0]
    return Decision(
        START,
        "%d trade(s) below the cap, first %s %s at %d" % (len(low), name, trade, value),
        remaining=float(setting),
        turn=Turn(int(last_run_end), now, False),
    )


def _live(
    turn: Turn, setting: int, kind: str, elapsed: float, town_setting: int
) -> Decision:
    if setting <= 0:
        return Decision(
            END,
            "TRADE_TURN_SECONDS is 0, so the turn is over",
            turn=replace(turn, over=True),
        )
    elapsed = max(0.0, float(elapsed))
    if kind == ON_TRADE:
        counted, off = turn.counted + elapsed, turn.off
    else:
        used = min(elapsed, max(0.0, town_setting - turn.off))
        counted, off = turn.counted + elapsed - used, turn.off + used
    now_turn = replace(turn, counted=counted, off=off)
    if counted >= setting:
        return Decision(
            END,
            "the %d second turn is spent" % setting,
            turn=replace(now_turn, over=True),
        )
    if kind == TOWN and off >= town_setting and not turn.released:
        return Decision(
            RELEASE,
            "a town errand held the family for the %d second allowance" % town_setting,
            remaining=setting - counted,
            turn=replace(now_turn, released=True),
        )
    return Decision(
        HOLD,
        "%d seconds of the turn remain" % int(setting - counted),
        remaining=setting - counted,
        turn=now_turn,
    )
