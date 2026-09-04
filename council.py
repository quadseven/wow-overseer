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
from datetime import datetime, timedelta

import achievements
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


# --- the Council view (infra#2597) -------------------------------------------
#
# What the Council tab draws: the last sitting as a transcript, what it
# carried, and the places the family could go next. Rows in, JSON out; the
# page draws it and decides nothing.
#
# WHY THE TRANSCRIPT IS BUILT HERE AND NOT IN THE PAGE. Its ORDER is the whole
# point of the view and the order is a fact about the family, not about the
# markup. `speaking_order` exists because alphabetical put the seven-year-old
# first every time and the mother last, which read as a family nobody in it
# would recognise. A page that sorted these itself would be a second opinion
# about who speaks first, free to drift from the one the bridge already uses
# when it writes them.
#
# WHY THE HUE IS A TOKEN NAME. index.html owns what --green looks like, and it
# owns it TWICE - the site has a light theme and a dark one, and a hex chosen
# here would be mixed for one ground and wrong on the other. So a speaker
# carries the NAME of a role, and the stylesheet says what that name looks
# like on the surface it is actually drawn on.

COUNCIL_SOURCE = "council"

# Council lines this close together are one sitting. The bridge writes a whole
# council in a single pass - one line per speaker, each voiced by the model
# before it is written - so a sitting takes as long as the model does, and a
# gap larger than this is the NEXT council rather than a slow speaker.
SITTING_GAP = timedelta(minutes=20)

# The hues a speaker can be drawn in, handed out in the family's own order, so
# the father is always the same colour and the little one is always his.
# NAMES OF DESIGN TOKENS, never colours - see the note above.
SPEAKER_HUES = ("ink", "green", "cyan", "amber", "vermilion")
# Anyone who is not family. They have no place in the seniority order, so they
# get the quiet role rather than a colour that would rank them among people it
# knows nothing about.
OUTSIDER_HUE = "muted"

# WHERE THE FAMILY COULD GO, and the level this module says they should be
# before walking in. A RECOMMENDATION, not a claim about the world database:
# the core will let a level 10 into most of these, and the family would die at
# the door. The NAMES are not repeated here - achievements.dungeon_name is
# where the family's dungeons are written down, and a second copy would be a
# second answer able to disagree with it.
PLACES = {
    389: 15,   # Ragefire Chasm
    43: 17,    # Wailing Caverns
    36: 17,    # The Deadmines
    33: 22,    # Shadowfang Keep
    48: 24,    # Blackfathom Deeps
    34: 24,    # The Stockade
    90: 29,    # Gnomeregan
    47: 30,    # Razorfen Kraul
}

# Levels short the family would go in on anyway. Two is one bad pull; four is
# a wipe at the door, and the difference is what the gate exists to say.
NEAR_ENOUGH = 2

# How far above the family's weakest member a place is worth listing at all.
# Everything they have already been is listed whatever the number says: a
# place they have been to is a place they know, and dropping it would lose the
# only drops this view can honestly report.
HORIZON = 8

# Enough to say what the place gives up without turning the panel into a loot
# table. The Chronicle is where the whole list lives.
DROPS_SHOWN = 4

# Gate words. Status words, so the page sets them in the mono face and never
# has to work out what to call a family four levels short of somewhere.
READY = "READY"

# The hue a gate is drawn in. Here rather than in the page for the same reason
# the word is: "green means they can go" is a judgement about a gate, and the
# page's job is to know what green looks like on the ground it is painting.
READY_HUE = "green"
SHORT_HUE = "amber"


def _iso(when) -> str | None:
    """An ISO string, from either a datetime or something already stringy."""
    if when is None:
        return None
    return when.isoformat() if hasattr(when, "isoformat") else str(when)


def speaker_hue(name: str) -> str:
    """The token name this speaker is always drawn in.

    Keyed on the family's own order rather than on who happened to turn up, so
    a council Bork sat out does not shuffle everybody else's colour.
    """
    canonical = bonds.canon(name)
    if canonical is None:
        return OUTSIDER_HUE
    order = bonds.speaking_order(list(bonds.FAMILY))
    return SPEAKER_HUES[order.index(canonical) % len(SPEAKER_HUES)]


def sittings(rows: list[dict]) -> list[list[dict]]:
    """Council rows split into sittings, oldest sitting first.

    `rows` are overseer_thought rows in any order; only the family's are kept,
    because a council is a conversation between people who live together and a
    stray row from outside it is not part of one.
    """
    mine = [row for row in rows if bonds.canon(row.get("character_name", ""))]
    mine.sort(key=lambda row: row["created_at"])
    grouped: list[list[dict]] = []
    for row in mine:
        if grouped and row["created_at"] - grouped[-1][-1]["created_at"] <= SITTING_GAP:
            grouped[-1].append(row)
        else:
            grouped.append([row])
    return grouped


def transcript(rows: list[dict]) -> list[dict]:
    """The last sitting, oldest speaker first.

    OLDEST FIRST IS THE FAMILY'S ORDER, not the clock's: the father opens, the
    mother answers, and the seven-year-old is not the first voice a reader
    meets. That is `bonds.speaking_order`, which is the same fact the bridge
    uses when it decides who answers an overheard order - used twice rather
    than decided twice.

    A speaker who says more than one thing keeps those lines together, in the
    order they were said. Splitting them by clock would interleave five
    characters into something no reader could follow.
    """
    sitting = sittings(rows)[-1:] or [[]]
    lines = sitting[0]
    order = bonds.speaking_order({bonds.canon(row["character_name"])
                                  for row in lines})
    rank = {name: index for index, name in enumerate(order)}
    ordered = sorted(
        lines,
        key=lambda row: (rank[bonds.canon(row["character_name"])],
                         row["created_at"]),
    )
    return [{
        "who": bonds.canon(row["character_name"]),
        "hue": speaker_hue(row["character_name"]),
        "text": str(row.get("text") or ""),
        "at": _iso(row["created_at"]),
    } for row in ordered]


def decision_line(row: dict, quest_titles: dict | None = None) -> str:
    """What the council carried, as a sentence.

    Read off the goal the council persisted, which is the only part of a
    council that survives it: the ARGUMENT is written to overseer_thought in
    the model's words, and the outcome is written as a goal the supervisor can
    drive. So this reads the outcome and never tries to parse the argument.
    """
    who = str(row.get("character_name") or "").strip() or "The family"
    kind = str(row.get("kind") or "")
    if kind == "level":
        return "%s is to reach level %d." % (who, int(row.get("target") or 0))
    if kind == "quest":
        title = (quest_titles or {}).get(int(row.get("quest_id") or 0))
        if title:
            return "%s is to finish %s." % (who, title)
        return "%s is to finish the quest the council picked." % who
    if kind == "skill":
        return "%s is to learn %s." % (
            who, str(row.get("skill_name") or "a trade"))
    return "%s is to see to %s." % (who, kind or "what was agreed")


def consensus(goal_rows: list[dict], lines: list[dict],
              quest_titles: dict | None = None) -> dict | None:
    """The decision and the vote, or None when nothing is on record.

    THE VOTE IS WHO SPOKE, and it says so in those words. The tally itself is
    not written down anywhere - `hold` scores the proposals and then throws
    the numbers away, keeping only the winner - so a count of ayes here would
    be a number this module invented about a vote it did not see. How many of
    the family turned up to argue is a fact it does have.
    """
    active = [row for row in goal_rows
              if str(row.get("status") or "") == "active"]
    if not active:
        return None
    won = max(active, key=lambda row: row.get("created_at") or "")
    spoke = len({line["who"] for line in lines})
    return {
        "decision": decision_line(won, quest_titles),
        "beneficiary": str(won.get("character_name") or ""),
        "kind": str(won.get("kind") or ""),
        "spoke": spoke,
        "family": len(bonds.FAMILY),
        "vote": "%d OF %d SPOKE" % (spoke, len(bonds.FAMILY)),
        "at": _iso(won.get("created_at")),
    }


def _weakest(level_rows: list[dict]) -> tuple[str, int] | None:
    """Whoever is furthest behind, because the whole family walks in together.

    The gate is asked of the LOWEST level and not of the median: a party is
    gated by the member who dies at the door, and a median would report a
    family ready while one of them was four levels off it.
    """
    known = [(str(row["name"]), int(row.get("level") or 0))
             for row in level_rows if str(row.get("name") or "")]
    known = [row for row in known if row[1] > 0]
    if not known:
        return None
    return min(known, key=lambda row: (row[1], row[0]))


def gate_word(short: int) -> str:
    """READY, or how far off it is. A status word, so the page never spells one."""
    if short <= 0:
        return READY
    return "%d LEVEL%s SHORT" % (short, "" if short == 1 else "S")


def verdict(short: int, been: bool, drops: list[str], who: str) -> str:
    """Whether to go in anyway, which is the question a gate always raises.

    A gate on its own reads as a rule, and the family is not run by rules -
    they went into a dungeon under-levelled the first time and came out with
    the only loot this view can report. So the gate is always answered.
    """
    if short <= 0:
        if been and drops:
            return "They have been in and come out with something. Go again."
        if been:
            return "They have been in. Nothing came out of it, and nothing is stopping them trying again."
        return "Nothing is stopping them. Nobody has walked in yet."
    if short <= NEAR_ENOUGH:
        return ("Short, and near enough to try anyway: %s is the one who would "
                "be carried." % who)
    return ("Not yet. %s is %d levels short, and the family goes in together "
            "or not at all." % (who, short))


def _drops_seen(cards: list[dict]) -> dict:
    """map id -> what the family has actually watched drop there.

    Their OWN knowledge, and deliberately nothing else. A wiki would list what
    every boss in the game can drop; this lists what came out of the runs
    these five have actually done, which is the only thing they can be said to
    know. A place they have never been reports nothing, and that is the honest
    answer rather than an empty state.
    """
    found: dict = {}
    for card in cards:
        if card.get("kind") != "run":
            continue
        bucket = found.setdefault(int(card.get("map_id") or 0), {})
        for item in card.get("loot") or []:
            name = str(item.get("name") or "")
            if name:
                bucket[name] = max(bucket.get(name, -1),
                                   int(item.get("quality") or 0))
    return {
        map_id: [name for name, _ in sorted(bucket.items(),
                                            key=lambda pair: (-pair[1], pair[0]))]
        for map_id, bucket in found.items()
    }


def prospects(level_rows: list[dict], cards: list[dict]) -> list[dict]:
    """Every place worth an opinion, weakest gate first.

    A place the family has already been is listed however far past it they
    are: it is the only place they know anything about, and dropping it would
    take the drops with it.
    """
    weakest = _weakest(level_rows)
    if weakest is None:
        return []
    who, level = weakest
    drops = _drops_seen(cards)
    been = set(drops)
    out = []
    for map_id, wants in sorted(PLACES.items(), key=lambda pair: (pair[1], pair[0])):
        if map_id not in been and wants > level + HORIZON:
            continue
        short = wants - level
        seen = drops.get(map_id, [])
        out.append({
            "map_id": map_id,
            "place": achievements.dungeon_name(map_id),
            "wants": wants,
            "short": max(short, 0),
            "gate": gate_word(short),
            "hue": READY_HUE if short <= 0 else SHORT_HUE,
            "ready": short <= 0,
            "been": map_id in been,
            "drops": seen[:DROPS_SHOWN],
            "more_drops": max(len(seen) - DROPS_SHOWN, 0),
            "verdict": verdict(short, map_id in been, seen, who),
        })
    return out


def quiet_line(lines: list[dict]) -> str:
    """What to say when no council is on record. Empty when there is one."""
    if lines:
        return ""
    return ("No council is on record. They meet on their own cadence and only "
            "when somebody has something to raise; an empty transcript is a "
            "quiet week, not a broken page.")


def undecided_line(agreed: dict | None) -> str:
    """Why the consensus block is empty. Empty when it is not."""
    if agreed is not None:
        return ""
    return ("Nothing the supervisor can drive is on the table. A council that "
            "agrees on a quiet day has still decided something real - it is "
            "simply not written as a goal, so this block has nothing to show.")


def build_council(thought_rows: list[dict], goal_rows: list[dict],
                  level_rows: list[dict], cards: list[dict],
                  quest_titles: dict | None = None,
                  now: datetime | None = None) -> dict:
    """Rows in, the Council tab's JSON out.

    thought_rows  overseer_thought rows with source 'council', any order
    goal_rows     overseer_goal rows, any status
    level_rows    name -> level for the family, from `characters`
    cards         the Chronicle's cards, for what the family has seen drop
    quest_titles  quest id -> LogTitle, so a quest decision can be named
    now           the clock, injectable so the suite can stand still

    EVERY ONE OF THOSE MAY BE EMPTY, exactly as build_agenda's may. A realm
    whose schema predates a table hands in [] for it and gets a thinner view,
    never an exception.
    """
    now = now or datetime.now()
    lines = transcript(thought_rows)
    agreed = consensus(goal_rows, lines, quest_titles)
    return {
        "generated_at": _iso(now),
        "transcript": lines,
        "spoke": sorted({line["who"] for line in lines}),
        "consensus": agreed,
        "quiet": quiet_line(lines),
        "undecided": undecided_line(agreed),
        "prospects": prospects(level_rows, cards),
    }
