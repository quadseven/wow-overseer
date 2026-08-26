"""The family works out what today is for.

Pure module, same seam as kin.py and bonds.py: state in, a conversation and a
plan out. bridge.py reads the rows and writes the results.

WHAT EVAN ASKED FOR. "I really want them to sort of be like a team that
collectively talks together, talking about what they need to focus on today...
sometimes they just log in and just fish." So the council must be able to
decide on something unambitious, and it must be able to disagree - a council
where everyone always agrees is an announcement wearing a costume.

WHAT IS PUBLIC AND WHAT IS PRIVATE. This is the load-bearing rule, and it is
what makes the conversation worth having.

  PUBLIC   level, class, race, where they are. You can read a level off a
           character's portrait in the game, so a member may reason about
           anyone's level without being told.
  PRIVATE  gold, skills, and every thought. A member reasons about its OWN
           only. Bork does not know Og is broke unless Og says so out loud.

Enforced by construction rather than by discipline: `assess` takes ONE
member's row and cannot see the others, and the only cross-member fact it is
given is a list of public levels. A future reader who wants to use another
member's gold has to change a signature to do it, which is the point.

WHY THE LLM DOES NOT PICK. Proposals come from real rows and the winner is
chosen by rules, so the same state always produces the same plan and a dead
LLM costs voice, not the plan. The model's job is to say the line in
character; the decision is already made when it is asked. This is the epic's
rule - the LLM is never asked to restate data we hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import bonds

# A member this far below the family's median level is visibly struggling and
# the family notices. Two is ordinary spread between people playing different
# amounts; three is someone being left behind.
BEHIND_BY = 3

# Professions a character is expected to be picking up by now. Below this and
# there is a real gap worth a day.
TRADES_EXPECTED = 2

# Copper. Mounts are the first thing anyone actually saves for, and at level 20
# being this poor is the difference between riding and walking everywhere.
POOR_BELOW = 10000
SAVING_FROM_LEVEL = 16

# Nobody grinds forever. When the family has no pressing need, doing something
# pointless together is a legitimate outcome and not a failure to decide.
IDLE_LEVEL_STEP = 5

# Beneficiary of a proposal that is nobody's in particular - an afternoon off,
# a day the family spends together. Empty rather than a name so bonds is never
# asked whether one character will turn out for a mood.
FAMILY_AT_LARGE = ""


@dataclass(frozen=True)
class Member:
    """One character as the council sees it.

    `gold` and `trades` are PRIVATE - present only on the member doing the
    assessing, never on the others in the same call.
    """

    name: str
    level: int
    class_name: str
    gold: int = 0
    trades: int = 0
    # A trade the family has agreed this character will take and that they have
    # not been to a trainer for yet (professions.plan). PRIVATE, like gold and
    # skills, and only ever this member's own.
    #
    # WHY IT IS NOT DERIVED FROM `trades`. It cannot be. `trades` is a COUNT,
    # and the family's problem is not that they hold too few professions - all
    # five hold two - it is that none of them is a TAILOR (infra#2757). A count
    # cannot express "the wrong ones", so the shortfall has to arrive as a
    # name. The count branch below is left in place for a character who
    # genuinely has none.
    trade_wanted: str = ""
    # What this character is part-way through. PRIVATE, like gold and trades -
    # a quest log is not something you read off a portrait. Only ever the
    # assessing member's own.
    quest: str = ""
    quest_left: int = 0
    # WHICH quest that sentence is about. Threaded because a plan the
    # supervisor can act on needs an id, not a sentence: mod-overseer aims a
    # bot with ChangeToDoQuest(questId, ...), and re-deriving the id from the
    # beneficiary's rows at persist time can pick a DIFFERENT quest than the
    # one the council actually talked about. 0 is "no quest in view".
    quest_id: int = 0


@dataclass(frozen=True)
class Proposal:
    """What one member thinks the family should do, and why.

    `weight` is how much the proposer cares, which is what lets a quiet need
    lose to an urgent one without anyone having to rank them by hand.
    """

    proposer: str
    kind: str
    beneficiary: str
    target: int
    weight: int
    said: str
    # Only meaningful for kind='quest'; 0 everywhere else. Additive and
    # defaulted on purpose, so every existing proposal shape is untouched.
    quest_id: int = 0


@dataclass(frozen=True)
class Plan:
    """The agreed outcome, in a shape the goal supervisor can act on."""

    kind: str
    beneficiary: str
    target: int
    reason: str
    # Carried through from the winning Proposal. For kind='quest' this is the
    # whole point of the plan - target is objectives REMAINING, which names no
    # quest at all - and it is what the persisted goal is driven by.
    quest_id: int = 0


@dataclass(frozen=True)
class Council:
    lines: list = field(default_factory=list)
    plan: Plan | None = None
    reason: str = ""


def _more_levels(n: int) -> str:
    """"I want 1 more levels" is the sort of thing that breaks the spell."""
    return "I want one more level." if n == 1 else f"I want {n} more levels."


def _median_level(levels: list) -> int:
    ordered = sorted(levels)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def assess(me: Member, *, public_levels: dict) -> Proposal | None:
    """What `me` wants the family to do today.

    Takes one member and a map of name -> level. That map is the ONLY thing it
    knows about anyone else, and level is public in the game, so nothing here
    reads another character's mind.

    Returns None when this member has nothing to push for; a member with
    nothing to say should say nothing rather than invent a want.
    """
    others = {n: lv for n, lv in public_levels.items() if n != me.name}

    # Somebody being left behind outranks anything I want for myself. This is
    # checked first on purpose: a family that grinds past its youngest is not
    # the family Evan described.
    if others:
        median = _median_level(list(public_levels.values()))
        laggards = sorted(
            (lv, n) for n, lv in others.items() if median - lv >= BEHIND_BY
        )
        if laggards:
            level, who = laggards[0]
            return Proposal(
                proposer=me.name, kind="level", beneficiary=who,
                target=min(median, level + BEHIND_BY),
                weight=100 - level,
                said=f"{who} is still {level}. We should not leave them behind.",
            )

    # What they are actually doing outranks what they might do. The family was
    # holding conversations about levels while stood in a field killing
    # murlocs, because levels were the only thing the council could see.
    if me.quest:
        return Proposal(
            proposer=me.name, kind="quest", beneficiary=me.name,
            target=me.quest_left, quest_id=me.quest_id,
            # Above trades and coin, below rescuing someone left behind. A
            # half-finished quest is the most concrete thing anyone at the
            # table has, and finishing it is cheap.
            weight=60,
            said=me.quest,
        )

    # Below the quest, above the coin, and for the same reason: a trade the
    # family has already agreed you will take is a concrete thing with your
    # name on it, and going to get it is cheap next to a mount.
    if me.trade_wanted:
        return Proposal(
            proposer=me.name, kind="trades", beneficiary=me.name,
            target=TRADES_EXPECTED, weight=40,
            said=(f"Family need {me.trade_wanted}. {me.name} go find "
                  f"{me.trade_wanted} teacher."),
        )

    if me.trades < TRADES_EXPECTED:
        return Proposal(
            proposer=me.name, kind="trades", beneficiary=me.name,
            target=TRADES_EXPECTED, weight=40,
            said="I have no trade to speak of. I should learn one.",
        )

    if me.level >= SAVING_FROM_LEVEL and me.gold < POOR_BELOW:
        return Proposal(
            proposer=me.name, kind="coin", beneficiary=me.name,
            target=POOR_BELOW, weight=50,
            said="I cannot afford a mount. I need coin more than levels.",
        )

    # Nothing pressing. Propose the next round number together, or - if even
    # that is not due - propose doing nothing much, which is a real answer.
    if me.level % IDLE_LEVEL_STEP == 0:
        # Beneficiary is the family, not the speaker. Five characters each
        # wanting an afternoon off is one idea, not five, and nobody needs
        # helping into a chair - a self-beneficiary here made the scene repeat
        # itself five times and had everyone volunteering to assist a man with
        # a fishing rod.
        return Proposal(
            proposer=me.name, kind="idle", beneficiary=FAMILY_AT_LARGE,
            target=me.level, weight=5,
            said="Nothing needs doing. I am going fishing.",
        )
    return Proposal(
        proposer=me.name, kind="level", beneficiary=me.name,
        target=me.level - (me.level % IDLE_LEVEL_STEP) + IDLE_LEVEL_STEP,
        weight=20,
        said=_more_levels(IDLE_LEVEL_STEP - (me.level % IDLE_LEVEL_STEP)),
    )


def _seniority(name: str) -> int:
    bond = bonds.member(name)
    return bond.seniority if bond else 0


def back(voter: str, proposal: Proposal, *, history: list) -> tuple:
    """Does `voter` support `proposal`, and how strongly?

    Returns (support, line-or-empty). Support is added to the proposal's own
    weight, so backing is what actually decides things rather than a headcount
    - one member who badly needs something can still lose to four who mildly
    want another, which is how a family works.

    Bonds do the deciding. bonds.decide already answers "will this character
    turn out for that one", which is exactly the question a proposal to help
    somebody asks, so the same rules are reused rather than restated - if Grug
    is sulking about Og and Ugga, that sulk shows up here too.
    """
    if voter == proposal.proposer:
        return 0, ""

    if proposal.beneficiary == FAMILY_AT_LARGE:
        # Nothing to volunteer for. Agreeing to a quiet day is agreement, not
        # assistance.
        return 15, "Aye, a quiet day."

    if proposal.beneficiary != voter and bonds.member(proposal.beneficiary):
        # A proposal to help someone IS a call for help, answered in advance.
        plea = _Plea(proposal.beneficiary, proposal.kind)
        verdict = bonds.decide(voter, plea, history=history)
        if not verdict.will_answer:
            return 0, f"{verdict.reason}"
        return 30, f"I will help {proposal.beneficiary}."

    if proposal.beneficiary == voter:
        # Being volunteered for. Accepting is not automatic - a character with
        # its own idea says so - but it is the common case.
        return 20, "Aye, that is what I need."

    return 10, ""


@dataclass(frozen=True)
class _Plea:
    """bonds.decide reads .caller and .about; a proposal is a plea in advance."""

    caller: str
    about: str


def _merge(proposals: list) -> list:
    """Collapse identical proposals into one raised by the senior member.

    Four characters independently reaching the same conclusion is realistic;
    four characters saying the identical sentence in a row is not a
    conversation, it is an echo. The rest become backers, which is what they
    actually were.
    """
    grouped: dict = {}
    for p in proposals:
        # Self-directed proposals group by what is wanted, NOT by who wants it.
        # Five characters each saying "I want 3 more levels" is one idea the
        # family shares; keying on the beneficiary made it five, and the scene
        # read as five people talking past each other and then all volunteering
        # to help whoever spoke first.
        # quest_id is part of the key, not decoration: two members each one
        # objective from finishing DIFFERENT quests share (kind, self, target)
        # exactly, and merging them would have the family agree to help with a
        # quest nobody at the table named. It is 0 for every other kind, so
        # nothing else groups differently than it did.
        key = ((p.kind, "self", p.target, p.quest_id) if p.beneficiary == p.proposer
               else (p.kind, p.beneficiary, p.target, p.quest_id))
        grouped.setdefault(key, []).append(p)

    merged = []
    for group in grouped.values():
        group.sort(key=lambda p: _seniority(p.proposer), reverse=True)
        spoken = group[0]
        # Everyone who reached it independently already agrees, so their
        # weight counts even though only one of them says it out loud.
        extra = sum(p.weight for p in group[1:])
        merged.append((spoken, [p.proposer for p in group[1:]], extra))
    return merged


def _withhold(proposals: list, *, history: list) -> tuple:
    """Split proposals into the ones that will be spoken and the ones withheld.

    A member cannot propose helping someone it would refuse to help. assess()
    deliberately cannot see the history - it gets one row and public levels -
    so the sulk is applied here instead. Without it Grug proposes to go to
    Ugga's aid in the same breath bonds has him refusing her, and the council
    says one thing while the muster does another.
    """
    speaking, withheld = [], []
    for p in proposals:
        if p.beneficiary != p.proposer and bonds.member(p.beneficiary):
            verdict = bonds.decide(p.proposer, _Plea(p.beneficiary, p.kind),
                                   history=history)
            if not verdict.will_answer:
                withheld.append((p.proposer, verdict.reason))
                continue
        speaking.append(p)
    return speaking, withheld


def _tally(proposals: list, speakers: list, *, history: list) -> list:
    """Score every proposal, best first.

    Highest backing wins and the elder's word breaks a tie. Sorting by
    seniority second is what stops the winner depending on dict order, which a
    supervisor acting on this would experience as a different day every time
    nothing changed.
    """
    rows = []
    for spoken, agreed, extra in _merge(proposals):
        score = spoken.weight + extra
        backing = []
        for voter in speakers:
            if voter.name in agreed:
                continue
            support, line = back(voter.name, spoken, history=history)
            score += support
            if line:
                backing.append((voter.name, line))
        rows.append((score, _seniority(spoken.proposer), spoken, agreed, backing))
    rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return rows


def _script(tally: list, withheld: list) -> list:
    """The conversation, in the order it happens.

    Losing proposals are spoken too: a council that records only the winner
    reads as an announcement, and the point is that the plan was argued for.
    """
    _, _, won, agreed, backing = tally[0]
    lines = [f"{p.proposer}: {p.said}" for _, _, p, _, _ in tally]

    # What was NOT said, and why. A council that hides its refusals is the
    # announcement this is meant not to be. Deduped against the backing lines:
    # a member who withheld its own proposal for a reason refuses to back the
    # same idea for the same reason, and saying it twice reads as a stutter.
    said_already = {who for who, _ in withheld}
    lines.extend(f"{who}: {why}" for who, why in withheld)

    # Members who reached the winning idea independently say so. They were
    # folded into one proposal so the scene would not repeat itself, but
    # silence from four characters who all agree reads as absence.
    lines.extend(f"{who}: Aye." for who in agreed)
    lines.extend(f"{who}: {line}" for who, line in backing
                 if who not in said_already)
    lines.append(f"{won.proposer}: Then it is settled. {won.said}")
    return lines


def hold(members: list, *, history: list) -> Council:
    """Run one council. Members in, a conversation and one plan out.

    Deterministic: the same state produces the same plan every time, so the
    supervisor cannot be surprised and a test can pin the outcome. The voice
    layer decorates these lines later; it never changes the decision.
    """
    speakers = [m for m in members if bonds.member(m.name)]
    if len(speakers) < 2:
        return Council(reason="nobody to confer with")

    public_levels = {m.name: m.level for m in speakers}
    # One member at a time, and only public levels alongside. Passing the whole
    # list here is what would quietly let a member reason about everyone
    # else's gold.
    raw = [p for p in (assess(m, public_levels=public_levels) for m in speakers)
           if p is not None]
    if not raw:
        return Council(reason="nobody had anything to say")

    speaking, withheld = _withhold(raw, history=history)
    if not speaking:
        return Council(
            lines=[f"{who}: {why}" for who, why in withheld],
            reason="everyone held their tongue",
        )

    tally = _tally(speaking, speakers, history=history)
    score, _, won, _, _ = tally[0]
    return Council(
        lines=_script(tally, withheld),
        plan=Plan(kind=won.kind, beneficiary=won.beneficiary,
                  target=won.target, reason=won.said, quest_id=won.quest_id),
        reason=f"{won.proposer}'s plan carried at {score}",
    )
