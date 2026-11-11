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

from dataclasses import dataclass

import classic

DEFAULT_SECONDS = 1200

START = "start"
HOLD = "hold"
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


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    remaining: float = 0.0


def seconds(raw) -> int:
    """TRADE_TURN_SECONDS: whole seconds, 0 turns the rule off, junk gets the
    default, a negative value turns the rule off."""
    text = str(raw if raw is not None else "").strip()
    if not text:
        return DEFAULT_SECONDS
    try:
        return max(0, int(text))
    except ValueError:
        return DEFAULT_SECONDS


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
) -> Decision:
    """Start, hold, end or skip a trade turn, or do nothing.

    A live turn is judged by itself: it holds until its length is spent, and a
    later run row cannot start a second one. One turn follows each finished
    run. A run in progress is never interrupted.
    """
    if turn is not None and not turn.over:
        left = turn.started + setting - now
        if setting <= 0:
            return Decision(END, "TRADE_TURN_SECONDS is 0, so the turn is over")
        if left <= 0:
            return Decision(END, "the %d second turn is spent" % setting)
        return Decision(
            HOLD, "%d seconds of the turn remain" % int(left), remaining=left
        )
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
    )
