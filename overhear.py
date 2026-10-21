"""The operator talking to the family in game, rather than through Discord.

Pure module. Chat rows in, a decision about whether the overseer was being
addressed out. bridge.py does the reading and the acting.

WHY. The operator kept asking the same question in different words - "how do i talk as
grug suggesting to go to a town and sell and upgrade gear", "i just asked for
the sword that dropped with +4 stamina and they arent listening". He was
typing into party chat and nothing was listening, because the only ear the
overseer had was a Discord channel. He is sitting at the keyboard playing one
of these characters; that is the natural place to talk to them.

WHAT COUNTS AS BEING ADDRESSED. A line in a channel the family shares, from a
family member, that the bridge did not author, with no AI behind it
(`sender_is_bot` 0). A bot-flagged line is never an order: see is_addressed
for why, and for what that costs while selfbot is on (#347).

WHAT THIS DELIBERATELY DOES NOT DO. Guess. A line the vocabulary cannot
express produces no command at all - the translation layer refuses and the
character says so. Inventing an approximation of an order nobody gave is worse
than admitting the order was not understood, especially when the orders move
five characters around a world.
"""

from __future__ import annotations

from dataclasses import dataclass

# Channels the family shares. `say` is in for the case where the operator is stood
# among them; `whisper` is not, because a whisper to one character is between
# those two and the overseer has no business fanning it out to everyone.
HEARD_ON = ("party", "say", "raid")

# One order at a time. Somebody typing three sentences of thought is having a
# conversation, not issuing three orders, and turning each line into a command
# would have the family thrash. The Discord path has the same shape.
COOLDOWN_SECONDS = 20.0

# Below this it is an exclamation, not an instruction.
MIN_WORDS = 2


# THE FAMILY'S OWN PLAYERBOTS SPEECH (#347). Infra's playerbots patch 0020
# sends a bot's party and raid lines through the same chat hook a typed line
# takes, so mod-overseer records both the same way: a row from a family member,
# in party, that the bridge did not author. On 2026-09-26 Ugga said
#
#     Ugga  sender_is_bot=1  party  "I am out of reagents for prayer of
#                                    shadow protection and am casting shadow
#                                    protection instead."
#
# and the voice queued `follow` for Grug and `reset ai` for Og and Bork. Over
# that week such lines queued `reset ai` 164 times, `follow` 89 and `stay` 63.
#
# A first fix matched bot-flagged lines against upstream's text templates
# (acore_playerbots.ai_playerbot_texts). It caught the reagent notice and
# nothing else: an ollama reply or an acknowledgement upstream hard-codes is
# no template, and it still read as an order. So the bot flag decides now,
# see is_addressed.


@dataclass(frozen=True)
class Directive:
    """Something the operator said in game that the family should act on."""

    speaker: str
    text: str


def is_addressed(row: dict, *, family, authored) -> bool:
    """Was the overseer being spoken to?

    Two tests, and both must pass.

    AUTHORSHIP. The bridge knows every line it caused a character to say,
    because it inserted the command. A family line in a shared channel that
    the bridge authored is its own echo (council lines, muster reports, its
    own replies), never an order.

    THE BOT FLAG. The bridge did not author upstream playerbots' speech
    either, and that speaks in the same channel (#347). Authorship alone read
    it as the operator typing. Matching upstream's text templates caught only
    its formulaic lines. Nothing in the row tells a bot's line from the
    operator's under selfbot: with SelfBotLevel 3 the AI attaches to his
    character the instant he logs in, so the live row read

        Grug  sender_is_bot=1  party  "everyone go sell your junk and repair"

    while he was sitting there typing it. So a bot-flagged line is refused,
    whatever it says.

    WHAT THAT COSTS. While selfbot is on, the operator's own typed line is
    flagged too and is not heard here; he can say it again in Discord. That is
    the trade on purpose: a missed order can be repeated, a `reset ai` or a
    `stay` nobody gave cannot be taken back. Giving him his in-game voice back
    needs the row to say where a line came from (a module-side flag set only
    for a line a client typed), and then that flag, not this one, decides.
    """
    if (row.get("channel") or "") not in HEARD_ON:
        return False
    speaker = (row.get("sender_name") or "").strip()
    if not speaker:
        return False
    kin = {n.casefold() for n in family}
    if speaker.casefold() not in kin:
        return False
    text = (row.get("text") or "").strip()
    if len(text.split()) < MIN_WORDS:
        return False
    # Everything the bridge put in their mouths - council lines, muster
    # reports, its own replies. Compared on the text alone: the same sentence
    # from the same family is the bridge's own echo whoever the row names.
    if text in authored:
        return False
    # An AI is behind it: upstream's speech, or the operator under selfbot,
    # and the row cannot say which (#347). Never an order.
    return not row.get("sender_is_bot")


def hear(
    rows: list, *, family, authored, last_at: float | None, now: float
) -> Directive | None:
    """The one order to act on from this batch, or None.

    The LAST qualifying line, not the first: if the operator typed twice while the
    relay was between ticks, the later line is the one he meant. Taking the
    first would act on a sentence he had already replaced.
    """
    if last_at is not None and (now - last_at) < COOLDOWN_SECONDS:
        return None
    heard = [r for r in rows if is_addressed(r, family=family, authored=authored)]
    if not heard:
        return None
    row = heard[-1]
    return Directive(speaker=row["sender_name"], text=(row["text"] or "").strip())


def audience(directive: Directive, *, family) -> list:
    """Who carries out the order: the family, minus whoever gave it.

    The operator is playing one of them. Ordering his own character to follow itself is
    the sort of thing that looks fine in a test and reads as a bug in game.
    """
    return sorted(n for n in family if n.casefold() != directive.speaker.casefold())
