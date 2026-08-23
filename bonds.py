"""Family bonds: who answers a plea depends on who they are to the caller.

Pure module, same seam as kin.py - a plea, a roster-derived muster and a
history of who has helped whom go in, a narrowed muster comes out. bridge.py
reads the history and writes the rows.

WHERE THESE RULES COME FROM. Evan described the family, and every rule below
traces to a clause of it rather than to a general idea of what families do:

  "grug is the dad and should always help his family unless he is mad at ugga
   getting helped by og too much, and bork is gonna constantly need help he is
   a little dumb kid always getting in trouble lol the younger brother to grog"

Which is: Grug answers unconditionally; the ONE exception is Ugga, and only
once Og has been the one answering her too often. Bork calls constantly and
that is characterisation, not a fault - but the sentence names Grog as well,
and it is Grog who carries it. The rest of the family does eventually tire of
Bork; his father and his big brother never do. Bork was briefly exempt from
fatigue outright, which read the first half of the clause and dropped the
second, and made the little-brother rule decoration: it could not change an
outcome, because the only caller it applied to was already exempt.

Every threshold counts a PAIR - how often this responder answered this caller.
Counting every answer to a caller instead looks equivalent and is not: one plea
writes one memory row per responder, so the same number meant two pleas with
the family online and five with one member online. Worse, it starved the
jealousy rule, which needs Og to keep answering Ugga: Og tired out at two, one
short of the three that makes Grug sulk, so the rule Evan actually asked for
could never fire.

WHY THE HISTORY IS NOT NEW STATE. `kin` already writes a `reflection` row for
every responder - "Grog called for help with X. I regrouped." - so who helped
whom is already recorded. `history_from_thoughts` reads those rows back rather
than keeping a second tally that could disagree with the store. If a memory is
not there, the help did not happen as far as this module is concerned, which is
the same rule the rest of the overseer uses.

WHAT THIS DOES NOT DO. It never ADDS a responder. `kin.plan_muster` decides who
is eligible - online, a bot, in the caller's guild - and this only ever narrows
that set. A bond cannot conjure a character who is not there, and a refusal
here is a character choosing not to go, never a scoping bug wearing a story.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

import kin

# Og answering Ugga this many times is where Grug stops being reasonable.
# Two is fine, three is a pattern.
JEALOUSY_THRESHOLD = 3

# How many times one character may be answered before the family tires of it.
# Bork is exempt; see the docstring.
FATIGUE_THRESHOLD = 5


@dataclass(frozen=True)
class Bond:
    role: str
    blood: bool
    # Higher is older. Only meaningful between blood relatives; it is what
    # makes Grog the big brother and Bork the little one.
    seniority: int


FAMILY: dict[str, Bond] = {
    "Grug": Bond(role="father", blood=True, seniority=100),
    "Ugga": Bond(role="mother", blood=True, seniority=99),
    "Grog": Bond(role="elder son", blood=True, seniority=50),
    "Bork": Bond(role="younger son", blood=True, seniority=10),
    # Lives by the river. Good guy. Helps Ugga rather a lot.
    "Og": Bond(role="neighbour", blood=False, seniority=60),
}

_BY_LOWER = {name.lower(): name for name in FAMILY}


@dataclass(frozen=True)
class Verdict:
    will_answer: bool
    reason: str


def member(name: str) -> Bond | None:
    """Case-insensitive, because chat is. Returns None for anyone outside."""
    canonical = _BY_LOWER.get((name or "").strip().lower())
    return FAMILY[canonical] if canonical else None


def head_of_family() -> str:
    """Who leads. The father, by the seniority already in FAMILY.

    Not a constant: the family table is the one place these relationships are
    written down, and a second answer here could disagree with it. Whoever is
    most senior is who the party follows.
    """
    return max(FAMILY, key=lambda n: FAMILY[n].seniority)


def canon(name: str) -> str | None:
    """The FAMILY spelling of `name`, or None for anyone outside it."""
    return _BY_LOWER.get((name or "").strip().lower())


def _count(history: list[tuple[str, str]], helper: str, called: str) -> int:
    """How many times `helper` has answered `called`.

    Canonicalised on both sides. The rows come from free text an LLM wrote, so
    "og" and "Og" both turn up; comparing them raw let any casing drift silently
    zero a count, which reads as a rule that simply never fires.
    """
    h_want, c_want = canon(helper), canon(called)
    return sum(
        1 for h, c in history if canon(h) == h_want and canon(c) == c_want
    )


def decide(
    responder: str,
    plea,
    *,
    history: list[tuple[str, str]],
) -> Verdict:
    """Will `responder` answer this plea?

    Anyone outside the family answers - this module has opinions about five
    characters and no business narrowing anyone else.

    Every count here is PER PAIR: how often this responder answered this
    caller. Counting per caller instead looks equivalent and is not, because
    one plea writes one memory row per responder - so a "five answers"
    threshold fired after two pleas with the family online and after five with
    one member online. The rule silently meant something different depending
    on who happened to be logged in, and it starved the jealousy rule below of
    the very rows it counts.
    """
    me, them = canon(responder), canon(plea.caller)
    if me is None or them is None:
        return Verdict(True, "no bond either way")
    bond, caller = FAMILY[me], FAMILY[them]

    # The father answers. Checked before every counter, because "should always
    # help his family" outranks a tally.
    if bond.role == "father":
        if caller.role == "mother":
            rival = _count(history, "Og", them)
            if rival >= JEALOUSY_THRESHOLD:
                return Verdict(
                    False, f"Og has answered {them} {rival} times. Let Og go."
                )
            return Verdict(True, "she is his wife")
        return Verdict(True, "his family called")

    # The big brother turns up for the little one, and keeps turning up after
    # the rest of the family has started rolling its eyes. This is the only
    # thing standing between Bork and nobody coming, so it is exempt from
    # fatigue rather than merely ahead of it in the function.
    if bond.role == "elder son" and caller.role == "younger son":
        return Verdict(True, f"{them} is his little brother")

    tired = _count(history, me, them)
    if tired >= FATIGUE_THRESHOLD:
        return Verdict(False, f"{me} has answered {them} {tired} times already.")
    return Verdict(True, "family")


def apply(muster, plea, *, history: list[tuple[str, str]]):
    """Narrow a muster to the responders whose bonds say they will go.

    Rebuilds the memories from the survivors, so a character who stayed behind
    never remembers going and the caller never remembers them coming. Getting
    that wrong would put a lie in the thought store, which is the one place the
    characters treat as true.
    """
    if not muster.actions:
        return muster

    kept, refused = [], []
    for action in muster.actions:
        verdict = decide(action.character_name, plea, history=history)
        (kept if verdict.will_answer else refused).append((action, verdict))

    if len(kept) == len(muster.actions):
        return muster

    actions = [a for a, _ in kept]
    names = [a.character_name for a in actions]
    responder_memories = {
        a.character_name: muster.responder_memories[a.character_name]
        for a in actions
        if a.character_name in muster.responder_memories
    }

    if not actions:
        why = "; ".join(f"{a.character_name}: {v.reason}" for a, v in refused)
        return replace(
            muster,
            actions=[],
            reason=f"nobody came - {why}",
            caller_memory="",
            responder_memories={},
        )

    # Rebuild from plea.about, never by re-parsing muster.caller_memory. The
    # old code split that string on " and " to recover the subject, which
    # cannot tell the separator kin inserted from one the speaker said:
    # "help with my warrior quest and the boars" came back as "help with my
    # warrior quest", quietly dropping the boars from what the character
    # believes happened. The thought store is the one place these characters
    # treat as true, so a lossy round-trip there is a fabricated memory.
    helpers = ", ".join(names)
    caller_memory = (
        f"I called for help{kin.memory_about(plea.about)} and {helpers} regrouped."
    )
    stayed = ", ".join(a.character_name for a, _ in refused)
    return replace(
        muster,
        actions=actions,
        reason=f"{len(actions)} of {len(muster.actions)} came ({stayed} stayed behind)",
        caller_memory=caller_memory,
        responder_memories=responder_memories,
    )


# "<Caller> called for help[ with X]. I regrouped." - written by kin for every
# responder. Anchored so the caller's own first-person memory ("I called for
# help and ... regrouped.") can never match: that row records being helped, not
# helping, and counting it would let a character's own plea inflate the tally.
_REFLECTION_RE = re.compile(r"^(?!I\b)(\w[\w'-]{0,11})\s+called for help\b", re.I)


def history_from_thoughts(rows: list[dict]) -> list[tuple[str, str]]:
    """(helper, called) pairs, oldest first, from `reflection` rows.

    A row that does not parse is skipped rather than guessed at - an
    unrecognised memory must not become a helping event that never happened.
    """
    pairs: list[tuple[str, str]] = []
    for row in rows:
        helper = (row.get("character_name") or "").strip()
        m = _REFLECTION_RE.match((row.get("text") or "").strip())
        if helper and m:
            pairs.append((helper, m.group(1)))
    return pairs
