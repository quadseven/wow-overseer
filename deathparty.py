"""A filled death-loop ask becomes a two-member party start (#2277).

WHY THIS EXISTS. The death-loop pool never drains: the escape step works
per member, and a looper who escapes alone returns to the same content at
the same strength and loops again. The help route built for that (deathask)
posts a deathloop ask, draws one yes from a mate in reach and marks the ask
filled. This module is the next beat: which filled asks seat a party now.

THE START. One PartyStart per filled deathloop ask, in ask-id order: the
asker leads, the one helper whose standing yes the ask holds follows, and
the meeting place is the asker's loop place (the ask's own target label
names the same place in guild chat). The ask wants one helper, so a start
holds exactly one: the first standing yes by answer id.

PROVEN FROM THE ROWS, OR NO START. A start is emitted only when every part
is proven from the pass's own reads: the ask is filled and of the deathloop
kind, its asker still stands in a loop (a recovered asker seats nothing),
a standing yes stands on it, and the asker and that helper are both free
this pass and not already taken by an earlier start or another party. A
member seats at most one party a pass, as leader or as helper.

PURE: rows in, party starts out. No MySQL, no clock, no sleeping. The
bridge reads the starts this planner emits in its social pass and seats
each new one on the StartBook below, which is also the runner's act-time
gate: a start the book already holds is not seated (or logged) twice,
and a seated start is acted on only while start_still_valid proves it
against the newest reads. The bridge's runner (bridge._run_death_party)
walks the helper to the meeting place, sees both members stand there
(together), forms the party and ends it; the DEATH_ASK switch keeps its
own gate in deathask.
No levels, gear or skills are granted here or anywhere in the route: help
is another member's time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import guildsocial
from guildsocial import FILLED, YES

# The corps source the runner's own rows carry; the party rows themselves
# ride the party verbs' registered source (classparty.SOURCE), as the
# class party runner's rows do.
SOURCE = "deathparty"

# Seconds the helper has to reach the leader, and the reads of the
# snapshot after the walk before a member that arrived counts as not
# seen beside the leader (the class party meeting's shape).
MEET_SECONDS = 600.0
MEET_READS = 3
MEET_READ_SECONDS = 10.0
# Yards a helper may stand from the leader and still count as beside it:
# the seat range the other asks use (classask.SEAT_RANGE_YARDS).
MEET_RANGE_YARDS = 90.0
# The watch: one re-check of the start every WATCH_SECONDS, and the
# party's own ceiling, the class party's PARTY_SECONDS shape.
WATCH_SECONDS = 30.0
PARTY_SECONDS = 1680.0


def meet_command(start) -> str:
    """The walk one helper makes to the leader it helps."""
    return "walk-to-member %s" % start.leader


def together(stands, start) -> bool:
    """Whether the snapshot shows both members standing together at the
    meeting place: the leader seen, and the helper seen within
    MEET_RANGE_YARDS of it on the same map. `stands` is name ->
    (map, x, y), as the bridge's snapshot read gives it; a member it
    does not show is not there."""
    lead = (stands or {}).get(start.leader)
    if lead is None:
        return False
    for name in start.helpers:
        at = stands.get(name)
        if at is None or at[0] != lead[0]:
            return False
        if math.hypot(at[1] - lead[1], at[2] - lead[2]) > MEET_RANGE_YARDS:
            return False
    return True


@dataclass
class PartyStart:
    """One death-loop party to form: a leader, its one helper, and where
    they meet. `answers` is helper name -> the id of its yes row."""

    ask_id: int
    leader: str
    helpers: tuple
    place: str
    answers: dict = field(default_factory=dict)

    def names(self) -> tuple:
        return (self.leader,) + tuple(self.helpers)


def _yes_by_ask(answers) -> dict:
    """ask id -> its standing yes rows, in answer-id order."""
    out: dict = {}
    for a in sorted(answers or (), key=lambda a: a.id):
        if a.state == YES:
            out.setdefault(a.ask_id, []).append(a)
    return out


def plan_starts(asks, answers, loops, free, taken=frozenset()) -> tuple:
    """The party starts to form now, one per filled deathloop ask.

    asks     every overseer_guild_ask row; only filled deathloop asks read
    answers  the overseer_guild_answer rows; only standing yeses read
    loops    name -> deathloop.Loop, the planning pass's death-loop read
    free     names free to a party this pass (held members are absent)
    taken    names already seated by another party this pass
    """
    loops = loops or {}
    free = set(free or ())
    taken = set(taken or ())
    yes_by_ask = _yes_by_ask(answers)
    starts = []
    death_asks = [
        a
        for a in asks or ()
        if a.kind == guildsocial.KIND_DEATHLOOP and a.state == FILLED
    ]
    for ask in sorted(death_asks, key=lambda a: a.id):
        loop = loops.get(ask.asker)
        if loop is None or ask.asker not in free or ask.asker in taken:
            continue
        helper = next(
            (
                y
                for y in yes_by_ask.get(ask.id, [])
                if y.member in free and y.member not in taken and y.member != ask.asker
            ),
            None,
        )
        if helper is None:
            continue
        start = PartyStart(
            ask_id=ask.id,
            leader=ask.asker,
            helpers=(helper.member,),
            place=loop.place,
            answers={helper.member: helper.id},
        )
        taken.update(start.names())
        starts.append(start)
    return tuple(starts)


class StartBook:
    """The starts seated and not yet finished, one per ask.

    The social pass plans the same filled ask on every pass until the
    runner consumes it, so seating is by ask id: seat() returns False for
    an ask already on the book and the caller neither re-seats nor
    re-logs it. release() frees the ask when its party ends, however it
    ends, so a later filled ask can seat again.
    """

    def __init__(self) -> None:
        self._by_ask: dict = {}

    def seat(self, start) -> bool:
        if start.ask_id in self._by_ask:
            return False
        self._by_ask[start.ask_id] = start
        return True

    def release(self, ask_id) -> None:
        self._by_ask.pop(ask_id, None)

    def seated(self) -> tuple:
        return tuple(self._by_ask[k] for k in sorted(self._by_ask))

    def refresh(self, loops, free) -> tuple:
        """Release each seated start the newest reads no longer prove
        (start_still_valid) and return the ones released, in ask order."""
        gone = tuple(s for s in self.seated() if not start_still_valid(s, loops, free))
        for start in gone:
            self.release(start.ask_id)
        return gone


def start_still_valid(start, loops, free) -> bool:
    """The act-time re-check: a seated start may be acted on only while
    its asker still stands in the loop the start was seated from, at the
    same meeting place, and every member of the start is still free."""
    loop = (loops or {}).get(start.leader)
    if loop is None or loop.place != start.place:
        return False
    free = set(free or ())
    return all(name in free for name in start.names())
