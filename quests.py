"""What the family is actually working on, in words they can say out loud.

Pure module. Quest rows and quest metadata in, a readable statement of who
needs what out. bridge.py does the reading.

WHY THIS EXISTS. The council could talk about levels and nothing else, so five
characters grinding murlocs held a conversation about levels. Evan asked for
the obvious thing: "they are killing murlocs right now they should talk about
that and how many more they need to do and whats next".

The counts are REAL. character_queststatus carries mobcount1..4 and
itemcount1..4, quest_template carries the targets, and the difference is how
many more of something a character needs. Nothing here is generated, guessed
or rounded - if a line says four more, four more is what the row says. That
matters more here than anywhere else in this service: a character inventing
its own progress is a character the overseer can no longer be believed about.
"""

from __future__ import annotations

from dataclasses import dataclass

# Objective slots. WoW allows four of each, and a quest may mix them.
SLOTS = 4


@dataclass(frozen=True)
class Objective:
    """One thing still to do, and how much of it."""

    what: str
    have: int
    need: int

    @property
    def left(self) -> int:
        return max(0, self.need - self.have)


@dataclass(frozen=True)
class Progress:
    character: str
    quest_id: int
    title: str
    objectives: tuple

    @property
    def left(self) -> int:
        return sum(o.left for o in self.objectives)

    @property
    def done(self) -> bool:
        return self.left == 0

    @property
    def started(self) -> bool:
        """Any progress at all. An untouched quest is not what the family is
        'working on' - it is what one of them happens to be carrying."""
        return any(o.have > 0 for o in self.objectives)


def read(row: dict, meta: dict) -> Progress | None:
    """One quest row plus its template into a Progress, or None.

    None when the quest has no countable objective - plenty are "go and speak
    to someone", which has nothing to say about how many more.
    """
    objectives = []
    for i in range(1, SLOTS + 1):
        need = int(meta.get("RequiredNpcOrGoCount%d" % i) or 0)
        if need:
            objectives.append(Objective(
                what=meta.get("npc_name%d" % i) or "them",
                have=int(row.get("mobcount%d" % i) or 0),
                need=need,
            ))
        need = int(meta.get("RequiredItemCount%d" % i) or 0)
        if need:
            objectives.append(Objective(
                what=meta.get("item_name%d" % i) or "it",
                have=int(row.get("itemcount%d" % i) or 0),
                need=need,
            ))
    if not objectives:
        return None
    return Progress(
        character=row["character_name"],
        quest_id=int(row["quest"]),
        title=meta.get("LogTitle") or "something",
        objectives=tuple(objectives),
    )


def say_remaining(p: Progress) -> str:
    """The sentence a character would say about their own quest.

    Deliberately plain: the voice layer makes it sound like them. Writing it
    in character here would put the words in two places and let them drift.
    """
    if p.done:
        return f"{p.title} is done. I need to hand it in."
    worst = max(p.objectives, key=lambda o: o.left)
    return f"I need {worst.left} more {worst.what} for {p.title}."


def focus(progress: list) -> Progress | None:
    """Which quest the family should put its weight behind.

    The one CLOSEST to finishing that somebody has actually started. Helping
    finish a nearly-done quest is worth more than starting a fresh one, and it
    is what a real group does - clear the thing in front of you.

    Ties break on the lowest quest id so the same state always picks the same
    quest; a council that changed its mind every hour on identical facts would
    be noise, not deliberation.
    """
    live = [p for p in progress if p.started and not p.done]
    if not live:
        return None
    return min(live, key=lambda p: (p.left, p.quest_id))


def shared_with(progress: list, quest_id: int) -> list:
    """Who else is carrying that quest, in name order.

    The family is a party, so a quest several of them hold is the one worth
    doing together - the kills count for everyone at once.
    """
    return sorted({p.character for p in progress if p.quest_id == quest_id})
