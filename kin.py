"""Kin muster: one character calls for help, the family answers (infra#2600).

Pure module, same seam as voice.py and fanout.py - a chat line and a roster go
in, typed actions come out. bridge.py reads `overseer_chat`, calls in here, and
writes `overseer_command` and `overseer_thought` rows. No SQL, no Discord, no
LLM below this line, which is what lets the whole behaviour be tested as data.

WHAT THIS CAN AND CANNOT EXPRESS, because it shaped the design.

mod-playerbots resolves `follow` against the bot's MASTER
(Ai/Base/Strategy/FollowMasterStrategy.cpp), not against a named player - there
is no `follow <player>` in the chat grammar. So "everyone walk to Grog" is NOT
expressible as a bot command, and this module does not pretend otherwise by
inventing one. What IS expressible is "stop what you are doing and regroup",
and combined with WoW's native party assist - group members already fight,
heal and share quest credit together - that is what actually appears on screen
when the family answers.

Being precise about that matters more than it sounds: an invented command like
`follow Grog` would pass voice.is_raw_command's charset gate, reach the game,
and be silently ignored. The bridge would log a delivered command, the thought
store would record help that arrived, and nothing would happen in the world.
That is the exact failure shape this repo keeps meeting - a mechanism that
reports success while doing nothing - so the command set here is deliberately
small and every entry is asserted against voice.VOCABULARY by the tests.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

import voice

# Long enough that a bot repeating itself, or two members calling at once,
# cannot turn one situation into a stream of orders. Short enough that a real
# second emergency in the same fight still gets an answer.
COOLDOWN_SECONDS = 90.0

# A muster is a regroup, not a raid. Past a handful of responders the world
# just fills with running bodies, and fanout.py already exists for the
# deliberate "order everyone" case.
MAX_RESPONDERS = 6

# The command every responder gets. `follow` is in voice.VOCABULARY as "walk
# with and protect the speaker" - it drops the bot's current activity and
# returns it to the group. See the module docstring for why this is a regroup
# rather than a walk-to-the-caller.
MUSTER_COMMAND = "follow"

# A plea has to be someone asking for help FOR THEMSELVES, right now. The
# negative cases are the interesting ones: "I helped Ugga earlier" is a story,
# "should I help Bork?" is an offer, "no help needed" is the opposite of a
# plea, and "helpful little gnome" merely contains the letters.
# Every `help` carries a trailing \b. Without it "I need helpful directions to
# Orgrimmar" was a plea - the word `help` as a mere PREFIX was enough, which is
# the same trap the docstring claims to avoid with "helpful little gnome" (that
# one only stayed silent because no plea phrase preceded it).
_PLEA_RE = re.compile(
    r"""
    (?:^|\b)
    (?:
        i \s+ (?:need|want|could \s+ use) \s+ (?:some \s+ )? help \b
      | (?<! stop \s ) (?<! quit \s ) help \s+ me \b
      | (?: can | could ) \s+ (?: someone | anyone | somebody ) \s+ help \b
      | ^\s* help \s* [!?.]* \s* $
    )
    """,
    re.I | re.X,
)

# What the plea is about, when they say. Kept as free text for the memory line
# only - it never becomes part of a command.
# Someone being told to stop helping is not someone asking for help. The
# lookbehind in _PLEA_RE only reaches one word back, and "stop trying to help
# me" puts two between.
_DISMISS_RE = re.compile(r"\b(?:stop|quit|leave|enough)\b[^.!?]*?\bhelp\b", re.I)

_ABOUT_RE = re.compile(r"\bhelp\b\s*(?:me\s*)?(?:with\s+)?(.*)$", re.I)

# Negations, widened after review. The old set missed every contraction of
# "cannot" and capped the gap at two words, so "you can't help me now",
# "nobody can help me" and "I don't think I need help" all read as pleas.
# `nobody`/`no one`/`noone` are listed explicitly because \bno\b does not match
# inside "nobody".
_NEGATIVE_RE = re.compile(
    r"""\b(?:
        no | not | never | nobody | noone | none
      | don'?t | doesn'?t | didn'?t
      | can'?t | cannot | won'?t | wouldn'?t | couldn'?t | shouldn'?t
    )\b (?:\W+\w+){0,4}? \W+ help \b""",
    re.I | re.X,
)
# "no one can help me" - two words, so it needs its own alternative above via
# `none`? No: spelled with a space it is caught by \bno\b. Kept as a test.


@dataclass(frozen=True)
class Plea:
    caller: str
    about: str = ""


@dataclass(frozen=True)
class KinAction:
    character_name: str
    command: str


@dataclass(frozen=True)
class Muster:
    actions: list[KinAction] = field(default_factory=list)
    reason: str = ""
    caller_memory: str = ""
    responder_memories: dict[str, str] = field(default_factory=dict)


def parse_plea(speaker: str, text: str) -> Plea | None:
    """Is this line someone asking the family for help?

    Returns None for anything ambiguous. A false positive here pulls four
    characters off what they were doing, so the bar is deliberately high and
    the tests carry the near-misses.
    """
    speaker = (speaker or "").strip()
    line = (text or "").strip()
    if not speaker or not line:
        return None
    if _NEGATIVE_RE.search(line) or _DISMISS_RE.search(line):
        return None
    # An offer to help someone ELSE is not a request for help. Case-insensitive
    # on purpose: bots and people lowercase names constantly, and "can someone
    # help ugga" was becoming the SPEAKER's plea with about="ugga".
    # The negative lookahead lists what can legitimately follow `help` in a
    # plea. Without `with`, making this case-insensitive turned the commonest
    # plea of all - "I need help with my paladin quest" - into an offer.
    if re.search(
        r"\bhelp\s+(?!me\b|with\b|out\b|us\b|here\b|please\b|now\b)[a-z]+",
        line,
        re.I,
    ):
        return None
    if not _PLEA_RE.search(line):
        return None
    about = ""
    m = _ABOUT_RE.search(line)
    if m:
        about = re.sub(r"[!?.\s]+$", "", m.group(1).strip())
        # "I need help" leaves nothing useful; "help with my paladin quest"
        # leaves the part worth remembering.
        if about.lower() in {"me", "please", "out"}:
            about = ""
    return Plea(caller=speaker, about=about)


def memory_about(about: str) -> str:
    return f" with {about}" if about else ""


def plan_muster(
    plea: Plea,
    roster: list[dict],
    *,
    family: Collection[str],
    last_muster_at: float | None,
    now: float,
) -> Muster:
    """Decide who answers, and what each of them is told.

    `roster` is raw `overseer_snapshot` rows for everyone currently online -
    the same shape `fanout.resolve_targets` takes, and for the same reason:
    WHO COUNTS AS FAMILY IS A DECISION, so it belongs in the pure module where
    a test can hold it, not in bridge.py where it cannot.

    Taking `dict[str, int]` here was a real bug, not a style problem. That type
    structurally cannot express `is_bot`, so the filter was silently nobody's
    job: `_fetch_roster()` returns EVERY online character - seated humans, any
    guild, anywhere - and the six responders became the six alphabetically
    first characters on the realm. A player named "Evan" sorts ahead of "Grug"
    and was mustered every time. `fanout.py:141` already filters `is_bot` with
    a test behind it (`test_characters_without_bot_ai_are_never_mustered`),
    because mod_overseer.cpp writes `status='error'`, `detail="target has no
    bot AI"` for a character with no PlayerbotAI - a guaranteed error row, and
    a Discord line claiming help that never came.

    Family is an EXPLICIT SET OF NAMES, passed in by the caller. It was guild
    membership until the five characters actually existed and turned out to
    have no guild - at level 1 a WoW guild needs signatures, so scoping by one
    made the feature depend on an unrelated in-game chore. A named set is also
    simply more honest: the family IS five specific characters, not whoever
    shares a tabard, and `bonds.FAMILY` already had to define exactly that list
    to have opinions about them.

    An empty family musters nobody rather than falling back to "everyone",
    because the safe failure here is silence: a realm-wide muster is the one
    outcome worth never risking.
    """
    by_name = {r.get("name"): r for r in roster if r.get("name")}
    caller_row = by_name.get(plea.caller)
    if caller_row is None:
        return Muster(reason=f"{plea.caller} is not one of the family who are online")

    if last_muster_at is not None and (now - last_muster_at) < COOLDOWN_SECONDS:
        left = int(COOLDOWN_SECONDS - (now - last_muster_at))
        return Muster(reason=f"the family answered a call {left}s ago - cooldown")

    kin_names = {n.casefold() for n in family}
    if plea.caller.casefold() not in kin_names:
        return Muster(reason=f"{plea.caller} is not family - no one to call")

    # Sorted, so a plan is reproducible and a test can assert an order.
    others = sorted(
        n
        for n, r in by_name.items()
        if n != plea.caller and r.get("is_bot") and n.casefold() in kin_names
    )
    if not others:
        return Muster(reason=f"{plea.caller} is alone - nobody is online to answer")

    responders = others[:MAX_RESPONDERS]
    actions = [KinAction(character_name=n, command=MUSTER_COMMAND) for n in responders]

    helpers = ", ".join(responders)
    caller_memory = (
        f"I called for help{memory_about(plea.about)} and {helpers} regrouped."
    )
    responder_memories = {
        n: f"{plea.caller} called for help{memory_about(plea.about)}. I regrouped."
        for n in responders
    }
    return Muster(
        actions=actions,
        reason=f"{len(responders)} answered {plea.caller}",
        caller_memory=caller_memory,
        responder_memories=responder_memories,
    )


def muster_report(m: Muster, plea: Plea) -> str:
    """One line for Discord. Says what happened, never claims more."""
    if not m.actions:
        return f"**{plea.caller}** called for help - {m.reason}."
    who = ", ".join(a.character_name for a in m.actions)
    about = memory_about(plea.about)
    return f"**{plea.caller}** called for help{about} - {who} regrouped ({MUSTER_COMMAND})."
