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
bridge runner that walks the two members to the meeting place, forms the
party and ends it is the next slice; until it lands, a start is a decision
nothing executes, and the DEATH_ASK switch keeps its own gate in deathask.
No levels, gear or skills are granted here or anywhere in the route: help
is another member's time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import guildsocial
from guildsocial import FILLED, YES


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
