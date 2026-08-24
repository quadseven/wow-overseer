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
    # Who they actually are in the world, verified against the live characters.
    #
    # They are all CAVEMEN - that is why the parents are human, and why the two
    # boys are a dwarf and a gnome: those models are SHORT, so they read as
    # children. The race is a sight gag, not a culture. Nobody has a dwarven or
    # gnomish accent; they all talk like Grug, which is its own accent and the
    # only one this family has.
    #
    # The CLASS is real and worth voicing: Ugga is the priest keeping them all
    # alive, Bork is a rogue getting into places he should not.
    race: str = ""
    char_class: str = ""
    gender: str = ""
    # Which talent tree this character spends points in, as a DBC tabpage:
    # 0, 1 or 2 in the in-game left-to-right order. -1 leaves talents alone.
    #
    # WHY THIS LIVES WITH THE FAMILY AND NOT WITH THE MODULE. mod-overseer knows
    # a character's class and level and nothing about who it is. A spec is a
    # ROLE, and the roles here come from the family: Grug tanks because he is the
    # father who goes first into everything, and Ugga heals because keeping them
    # all alive is the whole of who she is. Picking at random from
    # RandomClassSpecProb - which is what mod-playerbots does for a bot nobody
    # knows - would have given a party with no tank and no healer about half the
    # time, and no way to ask for one.
    #
    # The numbers are the DBC tabpage, verified against the mod-playerbots enums
    # rather than remembered: warrior 0=arms 1=fury 2=protection, paladin 0=holy
    # 1=protection 2=retribution, priest 0=discipline 1=holy 2=shadow, rogue
    # 0=assassination 1=combat 2=subtlety, mage 0=arcane 1=fire 2=frost.
    spec_tab: int = -1
    # How this one differs from the others WITHIN the grug voice. The register
    # is shared, so this is what stops five characters saying one sentence -
    # which is exactly what happened when the personas differed only in role.
    persona: str = ""


FAMILY: dict[str, Bond] = {
    "Grug": Bond(
        role="father", blood=True, seniority=100,
        race="human", char_class="warrior", gender="male",
        # Protection. He is the one who goes first, so he is the one who
        # gets hit; this is the tank the family has never had.
        spec_tab=2,
        persona=(
            "The father, and a warrior. Fewest words of anyone, and the most "
            "certain. Says what the family will do, not what it might. Goes "
            "first into everything because that is where the family is not. "
            "Watches Og around Ugga more than he admits, and has no words for "
            "why that sits badly."
        ),
    ),
    "Ugga": Bond(
        role="mother", blood=True, seniority=99,
        race="human", char_class="priest", gender="female",
        # Holy. She is already described as the priest keeping every one of
        # them alive - this is that sentence made true in the talent tree.
        spec_tab=1,
        persona=(
            "The mother, and the priest keeping every one of them alive. Warm "
            "and practical - talks about who is hurt, who has eaten, who is "
            "cold. Fond of Og and careless about how that looks. Never says "
            "anything untrue, which is not the same as saying everything."
        ),
    ),
    "Grog": Bond(
        role="elder son", blood=True, seniority=50,
        race="dwarf", char_class="paladin", gender="male",
        # Retribution. Copying his father into melee, one step behind him.
        spec_tab=2,
        persona=(
            "The older boy, and a paladin. A CHILD - older than Bork and "
            "nowhere near grown, however much he would like to be. Copies his "
            "father's way of talking and puts one word too many in, so it "
            "comes out almost right and not quite. Announces things he has "
            "decided, in case anyone missed that he decided them. Says he is "
            "not tired. Steadier than his brother and very proud of it, which "
            "rather gives the game away. Turns up for Bork every single time, "
            "then grumbles about it after."
        ),
    ),
    "Bork": Bond(
        role="younger son", blood=True, seniority=10,
        race="gnome", char_class="rogue", gender="male",
        # Combat. The straightforward one, which suits a boy who has never
        # had a subtle thought.
        spec_tab=1,
        persona=(
            "The youngest, and a rogue. A SMALL CHILD, and sounds it. Loudest "
            "of the family and uses the most words to say the least. Blurts "
            "the first thing he thinks and then the second thing before anyone "
            "answers the first. Everything is the best thing that has ever "
            "happened until roughly one minute later. Says WOW and YES and "
            "AGAIN. Excited about everything, in trouble constantly, cheerful "
            "about both. Asks for help without a shred of embarrassment. "
            "Worships Grog and shows it by pestering him."
        ),
    ),
    "Og": Bond(
        role="neighbour", blood=False, seniority=60,
        race="human", char_class="mage", gender="male",
        # Frost. The careful spec, for the one who is careful about
        # everything including what he says.
        spec_tab=2,
        persona=(
            "The neighbour from by the river, and a mage. Reaches for slightly "
            "better words than the rest of the family and is careful not to "
            "make that obvious. Helpful, especially to Ugga, and more often "
            "than a neighbour needs to be. Easy around everyone except Grug."
        ),
    ),
}


# The thing nobody says out loud. Bonds already made Grug refuse to answer
# Ugga once Og had answered her too often - the sulk was in the rules before
# it had a reason. This is the reason, written down so the voice layer can
# ground on it and so a reader is not left guessing why the father counts.
#
# It is never stated as fact to the model. Grug SUSPECTS; that is all he has,
# and a suspicion he cannot prove is a better engine than a confirmed affair.
SUSPICION = {
    "who": "Grug",
    "about": "Ugga",
    "with": "Og",
    "note": (
        "Grug suspects there is something between Ugga and Og. He has no proof "
        "and would not know what to do with it. He notices when she smiles at "
        "him. He never accuses anyone."
    ),
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


def spec_tabs() -> dict[str, int]:
    """Name -> talent tree, for every member who has one chosen.

    Derived from FAMILY rather than repeated, for the same reason
    head_of_family is: the family table is where these decisions are written
    down, and a second copy here is a second answer that can disagree.

    Members left at -1 are omitted entirely. The column already defaults to -1,
    so writing them would be writing the default back over itself, and leaving
    them out keeps "no role chosen" distinguishable from "chose nothing".
    """
    return {name: bond.spec_tab for name, bond in FAMILY.items() if bond.spec_tab >= 0}


def canon(name: str) -> str | None:
    """The FAMILY spelling of `name`, or None for anyone outside it."""
    return _BY_LOWER.get((name or "").strip().lower())


def speaking_order(names) -> list[str]:
    """`names`, oldest first, for when the whole family answers at once.

    WHY ORDER MATTERS NOW. Every member of the audience answers an overheard
    order in their own words (infra#2597), so four chat lines are written in
    one go and mod-overseer delivers them in id order, twenty per two-second
    poll - which means the order they are WRITTEN in is the order Evan reads
    them in. Alphabetical, which is what overhear.audience returns, put the
    seven-year-old first every single time and the mother last.

    Seniority is already the family table's answer to who comes first - it is
    what head_of_family reads - so this is that same fact used twice rather
    than a second opinion about the family that could disagree with it.

    Anyone outside the family sorts after, alphabetically: this module has no
    opinion about their standing and guessing one would be an invention.
    """
    names = list(names)
    return sorted(
        names,
        key=lambda n: (
            0 if canon(n) else 1,
            -FAMILY[canon(n)].seniority if canon(n) else 0,
            n,
        ),
    )


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
