"""The operator talking to the family in game, rather than through Discord.

Pure module. Chat rows in, a decision about whether the overseer was being
addressed out. bridge.py does the reading and the acting.

WHY. The operator kept asking the same question in different words - "how do i talk as
grug suggesting to go to a town and sell and upgrade gear", "i just asked for
the sword that dropped with +4 stamina and they arent listening". He was
typing into party chat and nothing was listening, because the only ear the
overseer had was a Discord channel. He is sitting at the keyboard playing one
of these characters; that is the natural place to talk to them.

WHAT COUNTS AS BEING ADDRESSED. A line typed by a HUMAN, in a channel the
family shares. `sender_is_bot` is the whole test: when the operator holds Grug the
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

import re
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
# HOW A TYPED LINE IS TOLD APART, AND WHY THIS WAY. The bot flag alone cannot
# do it (selfbot, see is_addressed), and the chat row records nothing about
# where a line came from. What upstream says is not a mystery, though: its
# formulaic lines are templates in acore_playerbots.ai_playerbot_texts, with a
# default in code for a row the table lacks. A bot-flagged line that IS one of
# those sentences, placeholders filled in, was generated, not typed. That
# needs no module change and no redeploy. What it misses is any bot line that
# is not a template (an ollama reply, an acknowledgement upstream hard-codes):
# that still reads as typed. The complete answer is a module-side flag on
# overseer_chat set only for a line that came in from a client's socket.
#
# The defaults upstream falls back to when its table has no row. Copied from
# mod-playerbots src/Ai/Base/Util/GenericBuffUtils.cpp, the reagent notice.
UPSTREAM_DEFAULTS = (
    "I am out of reagents for %group_spell and am casting %base_spell instead.",
)

# A template with fewer words of its own than this is too thin to trust:
# "Using %item" or "Go in %instance_name?" would swallow orders the operator
# typed. Every placeholder matches anything, so the literal words are all
# that make a template recognisable.
MIN_LITERAL_WORDS = 3

_PLACEHOLDER = re.compile(r"%[A-Za-z_]+")
# Upstream writes typographic apostrophes and quotes (Let\u2019s go!), and a
# chat line may carry either form.
_PLAIN = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def _plain(text: str) -> str:
    return " ".join(text.translate(_PLAIN).split())


def bot_speech(templates) -> tuple:
    """Upstream's sentences, plus its in-code defaults, as patterns.

    Each placeholder becomes "anything"; the rest must match word for word,
    ignoring case and spacing. Templates too thin to trust are left out.
    """
    patterns = []
    seen = set()
    for template in (*UPSTREAM_DEFAULTS, *templates):
        plain = _plain(template or "")
        if not plain or plain.casefold() in seen:
            continue
        seen.add(plain.casefold())
        literal = _PLACEHOLDER.sub(" ", plain)
        if (
            sum(1 for w in literal.split() if any(c.isalnum() for c in w))
            < MIN_LITERAL_WORDS
        ):
            continue
        parts = [re.escape(p).replace(r"\ ", r"\s+") for p in _PLACEHOLDER.split(plain)]
        patterns.append(re.compile("(.+?)".join(parts), re.IGNORECASE | re.DOTALL))
    return tuple(patterns)


def is_bot_speech(text: str, patterns) -> bool:
    """Is this line one of upstream's sentences?"""
    plain = _plain(text)
    return any(p.fullmatch(plain) for p in patterns)


@dataclass(frozen=True)
class Directive:
    """Something the operator said in game that the family should act on."""

    speaker: str
    text: str


def is_addressed(row: dict, *, family, authored, bot_lines=()) -> bool:
    """Was the overseer being spoken to?

    NOT `sender_is_bot`. That was the first design and it is wrong the moment
    selfbot is on: with SelfBotLevel 3 the AI attaches to the operator's character the
    instant he logs in, so everything HE types comes back flagged as bot
    speech. The listener was built on a flag an earlier change had already
    broken - the live row read

        Grug  sender_is_bot=1  party  "everyone go sell your junk and repair"

    while he was sitting there typing it.

    So the test is authorship instead, and it is a better one anyway: the
    bridge knows every line it caused a character to say, because it inserted
    the command. A family line in a shared channel that the bridge did NOT
    author is somebody at a keyboard. That holds whether or not selfbot is on,
    and it cannot be fooled by a character the AI happens to be driving.

    Authorship has one blind spot: upstream playerbots speaks in the same
    channel and the bridge did not author that either (#347). `bot_lines`,
    from bot_speech(), names upstream's own sentences; a bot-flagged line that
    is one of them was generated, so it is not an order.
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
    # Upstream's own speech. Only for a bot-flagged row: a line with no AI
    # behind it was typed, whatever it says.
    return not (row.get("sender_is_bot") and is_bot_speech(text, bot_lines))


def hear(
    rows: list, *, family, authored, bot_lines, last_at: float | None, now: float
) -> Directive | None:
    """The one order to act on from this batch, or None.

    The LAST qualifying line, not the first: if the operator typed twice while the
    relay was between ticks, the later line is the one he meant. Taking the
    first would act on a sentence he had already replaced.

    `bot_lines` is required, unlike is_addressed's: the one caller that acts
    on the answer must say what upstream's speech looks like, or every
    reagent notice becomes an order again.
    """
    if last_at is not None and (now - last_at) < COOLDOWN_SECONDS:
        return None
    heard = [
        r
        for r in rows
        if is_addressed(r, family=family, authored=authored, bot_lines=bot_lines)
    ]
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
