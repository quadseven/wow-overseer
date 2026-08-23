"""Evan talking to the family in game, rather than through Discord.

Pure module. Chat rows in, a decision about whether the overseer was being
addressed out. bridge.py does the reading and the acting.

WHY. Evan kept asking the same question in different words - "how do i talk as
grug suggesting to go to a town and sell and upgrade gear", "i just asked for
the sword that dropped with +4 stamina and they arent listening". He was
typing into party chat and nothing was listening, because the only ear the
overseer had was a Discord channel. He is sitting at the keyboard playing one
of these characters; that is the natural place to talk to them.

WHAT COUNTS AS BEING ADDRESSED. A line typed by a HUMAN, in a channel the
family shares. `sender_is_bot` is the whole test: when Evan holds Grug the
character has no PlayerbotAI and the row says 0; when the AI holds him it says
1. So the family's own council speech can never be mistaken for an order, and
neither can the five hundred random bots.

WHAT THIS DELIBERATELY DOES NOT DO. Guess. A line the vocabulary cannot
express produces no command at all - the translation layer refuses and the
character says so. Inventing an approximation of an order nobody gave is worse
than admitting the order was not understood, especially when the orders move
five characters around a world.
"""

from __future__ import annotations

from dataclasses import dataclass

# Channels the family shares. `say` is in for the case where Evan is stood
# among them; `whisper` is not, because a whisper to one character is between
# those two and the overseer has no business fanning it out to everyone.
HEARD_ON = ("party", "say", "raid")

# One order at a time. Somebody typing three sentences of thought is having a
# conversation, not issuing three orders, and turning each line into a command
# would have the family thrash. The Discord path has the same shape.
COOLDOWN_SECONDS = 20.0

# Below this it is an exclamation, not an instruction.
MIN_WORDS = 2


@dataclass(frozen=True)
class Directive:
    """Something Evan said in game that the family should act on."""

    speaker: str
    text: str


def is_addressed(row: dict, *, family) -> bool:
    """Was the overseer being spoken to?

    Requires a HUMAN speaker on a shared channel. Being in the family matters
    too: a passing stranger in /say is not giving Evan's orders.
    """
    if row.get("sender_is_bot"):
        return False
    if (row.get("channel") or "") not in HEARD_ON:
        return False
    speaker = (row.get("sender_name") or "").strip()
    if not speaker:
        return False
    kin = {n.casefold() for n in family}
    if speaker.casefold() not in kin:
        return False
    text = (row.get("text") or "").strip()
    return len(text.split()) >= MIN_WORDS


def hear(rows: list, *, family, last_at: float | None, now: float) -> Directive | None:
    """The one order to act on from this batch, or None.

    The LAST qualifying line, not the first: if Evan typed twice while the
    relay was between ticks, the later line is the one he meant. Taking the
    first would act on a sentence he had already replaced.
    """
    if last_at is not None and (now - last_at) < COOLDOWN_SECONDS:
        return None
    heard = [r for r in rows if is_addressed(r, family=family)]
    if not heard:
        return None
    row = heard[-1]
    return Directive(speaker=row["sender_name"], text=(row["text"] or "").strip())


def audience(directive: Directive, *, family) -> list:
    """Who carries out the order: the family, minus whoever gave it.

    Evan is playing one of them. Ordering his own character to follow itself is
    the sort of thing that looks fine in a test and reads as a bug in game.
    """
    return sorted(n for n in family if n.casefold() != directive.speaker.casefold())
