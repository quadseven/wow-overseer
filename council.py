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

import functools
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import achievements
import bonds
import crossing
import dungeonprogression
import jobs

log = logging.getLogger(__name__)

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
    # PUBLIC, like level: a race is read off a portrait. 0 is "not read".
    # Carried so the bridge can hand the council the family's faction, which
    # decides whether a door inside a capital is one they can walk to (#202).
    race: int = 0
    # PUBLIC: where a character stands is what the map shows. None is "not
    # read", never map 0, which is the Eastern Kingdoms. `lead` is the roster's
    # lead flag. Together they say which continent the family is on, which
    # decides whether a door is one they can reach without a crossing (#205).
    map_id: int | None = None
    lead: bool = False


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
    # Only meaningful for kind='dungeon'; "" everywhere else, same discipline
    # as quest_id above. Carries the job keyword mod-overseer's DoJob reads
    # for job='dungeon:<keyword>' (mod-overseer#426/#432) - for example
    # 'scarlet-library'. "" means the bare 'dungeon' job, which the module
    # treats as its own default rather than naming a specific wing.
    keyword: str = ""


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
    # Carried through from the winning Proposal, same discipline as quest_id.
    # Only meaningful for kind='dungeon' - the job keyword to send, or "" for
    # the bare 'dungeon' job.
    keyword: str = ""


@dataclass(frozen=True)
class Council:
    lines: list = field(default_factory=list)
    plan: Plan | None = None
    reason: str = ""


def _more_levels(n: int) -> str:
    """ "I want 1 more levels" is the sort of thing that breaks the spell."""
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
                proposer=me.name,
                kind="level",
                beneficiary=who,
                target=min(median, level + BEHIND_BY),
                weight=100 - level,
                said=f"{who} is still {level}. We should not leave them behind.",
            )

    # What they are actually doing outranks what they might do. The family was
    # holding conversations about levels while stood in a field killing
    # murlocs, because levels were the only thing the council could see.
    if me.quest:
        return Proposal(
            proposer=me.name,
            kind="quest",
            beneficiary=me.name,
            target=me.quest_left,
            quest_id=me.quest_id,
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
            proposer=me.name,
            kind="trades",
            beneficiary=me.name,
            target=TRADES_EXPECTED,
            weight=40,
            said=(
                f"Family need {me.trade_wanted}. {me.name} go find "
                f"{me.trade_wanted} teacher."
            ),
        )

    if me.trades < TRADES_EXPECTED:
        return Proposal(
            proposer=me.name,
            kind="trades",
            beneficiary=me.name,
            target=TRADES_EXPECTED,
            weight=40,
            said="I have no trade to speak of. I should learn one.",
        )

    if me.level >= SAVING_FROM_LEVEL and me.gold < POOR_BELOW:
        return Proposal(
            proposer=me.name,
            kind="coin",
            beneficiary=me.name,
            target=POOR_BELOW,
            weight=50,
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
            proposer=me.name,
            kind="idle",
            beneficiary=FAMILY_AT_LARGE,
            target=me.level,
            weight=5,
            said="Nothing needs doing. I am going fishing.",
        )
    return Proposal(
        proposer=me.name,
        kind="level",
        beneficiary=me.name,
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
        key = (
            (p.kind, "self", p.target, p.quest_id)
            if p.beneficiary == p.proposer
            else (p.kind, p.beneficiary, p.target, p.quest_id)
        )
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
            verdict = bonds.decide(
                p.proposer, _Plea(p.beneficiary, p.kind), history=history
            )
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
    lines.extend(f"{who}: {line}" for who, line in backing if who not in said_already)
    lines.append(f"{won.proposer}: Then it is settled. {won.said}")
    return lines


def hold(
    members: list,
    *,
    history: list,
    level_rows: list[dict] | None = None,
    cards: list[dict] | None = None,
    completed_runs: dict[str, int] | None = None,
) -> Council:
    """Run one council. Members in, a conversation and one plan out.

    Deterministic: the same state produces the same plan every time, so the
    supervisor cannot be surprised and a test can pin the outcome. The voice
    layer decorates these lines later; it never changes the decision.

    `level_rows` and `cards` are additive and default to nothing, so every
    existing caller is untouched. They are what prospects() already reasons
    over for the Council tab's own readiness panel, and they are handed in
    here rather than threaded through `assess()` on purpose: a dungeon run is
    a decision about the WHOLE family (like `idle`, which speaks for
    FAMILY_AT_LARGE), never one member's own want, so it does not belong in
    the one-member-at-a-time seam `assess()` guards. Extending `assess()`'s
    signature to carry family-wide dungeon data would have every member
    quietly gain the power to reason about the whole family's business, which
    is exactly the privacy contract this module's docstring says `assess()`
    is built to prevent.
    """
    speakers = [m for m in members if bonds.member(m.name)]
    if len(speakers) < 2:
        return Council(reason="nobody to confer with")

    public_levels = {m.name: m.level for m in speakers}
    # One member at a time, and only public levels alongside. Passing the whole
    # list here is what would quietly let a member reason about everyone
    # else's gold.
    raw = [
        p
        for p in (assess(m, public_levels=public_levels) for m in speakers)
        if p is not None
    ]
    # The one proposal not spoken for by assess(). See the docstring above
    # for why it lives here instead.
    dungeon = _dungeon_proposal(speakers, level_rows or [], cards or [], completed_runs)
    if dungeon is not None:
        raw.append(dungeon)
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
        plan=Plan(
            kind=won.kind,
            beneficiary=won.beneficiary,
            target=won.target,
            reason=won.said,
            quest_id=won.quest_id,
            keyword=won.keyword,
        ),
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
#
# EXTENDED 2026-09-12 (infra dungeon-decision gap): the table topped out at
# Razorfen Kraul (30) while the family sat at 41-42, so `prospects()` had
# nothing to say for the level range they were actually IN. Scarlet Monastery
# is the operator's own stated priority; Razorfen Downs, Uldaman and
# Zul'Farrak are added alongside it on the same judgment - they are already
# named in achievements.DUNGEONS (someone anticipated the family reaching
# them), and they fill the run of levels between Razorfen Kraul and Scarlet
# Monastery's cathedral rather than leaving a gap prospects() cannot speak to.
PLACES = {
    389: 15,  # Ragefire Chasm
    43: 17,  # Wailing Caverns
    36: 17,  # The Deadmines
    33: 22,  # Shadowfang Keep
    48: 24,  # Blackfathom Deeps
    34: 24,  # The Stockade
    90: 29,  # Gnomeregan
    47: 30,  # Razorfen Kraul
    # ONE NUMBER PER MAP ID, and Scarlet Monastery is four wings on one map
    # (189). This entry is the GRAVEYARD's level - the wing met first, at the
    # door - because that is what "wants" means for every other entry here:
    # the level that gets the family in, not the level that clears the whole
    # place. Which of the four wing job keywords the council actually sends
    # once it settles on Scarlet Monastery is a narrower question, answered by
    # SCARLET_WINGS below rather than by trying to force four rows onto one
    # map id.
    189: 28,  # Scarlet Monastery (Graveyard: Interrogator Vishas, Bloodmage Thalnos)
    129: 33,  # Razorfen Downs
    70: 34,  # Uldaman
    209: 36,  # Zul'Farrak
    # EXTENDED AGAIN 2026-09-19 (infra#4247), for the same reason and one level
    # range further on: the table topped out at Zul'Farrak (36) while all five
    # of the family sat at 60, so the hardest place `prospects()` could name
    # was 21 levels below them and the council re-proposed it every hour.
    #
    # 52 is this module's own recommendation and NOT the core's gate, exactly
    # like every number above it: `dungeon_access_template` row 14 lets a level
    # 40 walk in, and what is spawned on map 230 on this pinned core is trash
    # at 48 to 60 and rare elites at 52 to 56. See dungeonprogression.py, where
    # the same number is quoted beside the world rows it was read from.
    230: 52,  # Blackrock Depths
    # EXTENDED 2026-09-22 (#202): the three classic doors mod-overseer gained a
    # portal row for (quadseven/mod-overseer#581) that this table did not
    # name, at the Dungeons page's own floors (dungeonpath.PATH), so the
    # council and that page agree about when a family is ready for them.
    109: 50,  # Sunken Temple
    229: 55,  # Blackrock Spire (the Lower Spire; the Upper Spire has no portal)
    329: 58,  # Stratholme
}

# The four wings of Scarlet Monastery (map 189, PLACES above), by the level
# that opens them, lowest first - a second, narrower table used ONLY to pick
# which job keyword (mod-overseer#426/#432, already live) the council sends
# once it has decided Scarlet Monastery is the target. PLACES cannot hold this
# itself: it is one number per map id, and all four wings share map 189.
SCARLET_MAP_ID = 189
SCARLET_WINGS = (
    ("scarlet", 28),  # graveyard: Interrogator Vishas, Bloodmage Thalnos
    ("scarlet-library", 33),  # Houndmaster Loksey, Arcanist Doan
    ("scarlet-armory", 36),  # Herod
    ("scarlet-cathedral", 39),  # Whitemane, Mograine
)

# What the operator set by hand the night these wings went live. Not derived
# from anything below - it is a fact about how big a campaign this family runs
# once it decides to go, and reusing the number the operator actually used is
# more honest than inventing a formula for it.
DUNGEON_RUNS_WANTED = 25

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
    order = bonds.speaking_order({bonds.canon(row["character_name"]) for row in lines})
    rank = {name: index for index, name in enumerate(order)}
    ordered = sorted(
        lines,
        key=lambda row: (rank[bonds.canon(row["character_name"])], row["created_at"]),
    )
    return [
        {
            "who": bonds.canon(row["character_name"]),
            "hue": speaker_hue(row["character_name"]),
            "text": str(row.get("text") or ""),
            "at": _iso(row["created_at"]),
        }
        for row in ordered
    ]


# WHICH PLACE A DUNGEON GOAL NAMES. The goal row carries the job keyword in
# `skill_name` (the same keyword mod-overseer's DoJob reads for
# job='dungeon:<keyword>'), and a keyword is not something a reader should
# have to decode. The map's own name comes from achievements.dungeon_name, the
# one table that names dungeons; only the WING is written here, because four
# of these keywords share one map.
#
# ORDER IS LOAD-BEARING (#202): where a map has more than one door, its FRONT
# door is listed first, and front_door() below answers with it.
DUNGEON_KEYWORDS = {
    "deadmines": (36, ""),
    "shadowfang": (33, ""),
    "stockades": (34, ""),
    "wailing": (43, ""),
    "scarlet": (189, "the Graveyard"),
    "scarlet-library": (189, "the Library"),
    "scarlet-armory": (189, "the Armory"),
    "scarlet-cathedral": (189, "the Cathedral"),
    "blackrock-depths": (230, ""),
    "blackfathom": (48, ""),
    "razorfen-kraul": (47, ""),
    "razorfen-downs": (129, ""),
    "gnomeregan": (90, ""),
    "gnomeregan-depot": (90, "the train depot door"),
    "uldaman": (70, ""),
    "uldaman-back": (70, "the Badlands door"),
    "zulfarrak": (209, ""),
    "sunken-temple": (109, ""),
    "lower-blackrock-spire": (229, "the Lower Spire"),
    "stratholme-live": (329, "the main gate"),
    "stratholme-undead": (329, "the service entrance"),
    "ragefire": (389, ""),
    "maraudon-orange": (349, "the orange wing"),
    "maraudon-purple": (349, "the purple wing"),
    "scholomance": (289, ""),
    "dire-maul-east-east": (429, "the East wing, east door"),
    "dire-maul-east-west": (429, "the East wing, west door"),
    "dire-maul-east-south": (429, "the East wing, south door"),
    "dire-maul-west-north": (429, "the West wing, north door"),
    "dire-maul-west-south": (429, "the West wing, south door"),
    "dire-maul-north": (429, "the North wing"),
}


def keyword_place(keyword: str) -> str:
    """A dungeon job keyword as a reader would say the place.

    "" is the bare `dungeon` job, whose place belongs to mod-overseer, so it
    reads as "a dungeon" rather than a guess. An unknown keyword is shown as
    written rather than dropped: a new portal row the site has not heard of is
    still a real place.
    """
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return "a dungeon"
    known = DUNGEON_KEYWORDS.get(keyword)
    if known is None:
        return keyword.replace("-", " ")
    map_id, wing = known
    name = achievements.dungeon_name(map_id)
    return "%s (%s)" % (name, wing) if wing else name


def front_door(map_id: int) -> str:
    """The job keyword for a map's front door, or "" when it has no portal.

    "" here means "the overseer cannot send a family there", NOT the bare
    `dungeon` job: that job runs the Deadmines, so writing it for any other
    map sends the family to the wrong place (#202). A caller that gets ""
    must refuse, never write a goal.

    A door in dungeonpath.WITHHELD_DOORS is skipped the same way (#205): the
    module can stage a party there, but the party may never walk back out.
    """
    import dungeonpath

    for keyword, (door_map, _) in DUNGEON_KEYWORDS.items():
        if (
            door_map == int(map_id)
            and keyword in jobs.PORTAL_KEYWORDS
            and keyword not in dungeonpath.WITHHELD_DOORS
        ):
            return keyword
    return ""


def _withheld_door(keyword: str) -> bool:
    import dungeonpath

    return keyword in dungeonpath.WITHHELD_DOORS


def _withheld(map_id: int) -> str:
    """dungeonpath.WITHHELD_DOORS's reason when every door into the map is
    withheld, "" otherwise."""
    import dungeonpath

    doors = [
        keyword
        for keyword, (door_map, _) in DUNGEON_KEYWORDS.items()
        if door_map == int(map_id) and keyword in jobs.PORTAL_KEYWORDS
    ]
    if doors and all(keyword in dungeonpath.WITHHELD_DOORS for keyword in doors):
        return dungeonpath.WITHHELD_DOORS[doors[0]]
    return ""


# The continents, by the map id a character stands on there.
CONTINENT_NAMES = {
    0: "the Eastern Kingdoms",
    1: "Kalimdor",
    530: "Outland",
    571: "Northrend",
}


@functools.lru_cache(maxsize=1)
def _entrances() -> dict:
    """entrances.json, the committed instance doors: map id -> {map, x, y}."""
    with open(Path(__file__).resolve().parent / "entrances.json") as f:
        return json.load(f)


def continent_of(map_id: int | None) -> int | None:
    """The continent a map is, or the one its entrance stands on; None when
    unread or unplaced. A character inside Zul'Farrak is on Kalimdor."""
    import dungeonplan

    return dungeonplan._continent_of(map_id, _entrances())


def _home_continent(level_rows: list[dict]) -> int | None:
    """The continent the family is on: its leader's, read off the leader's
    map. With no leader row readable, the one continent every readable member
    shares. None when nothing says, or the family stands on two."""
    named = [row for row in level_rows if str(row.get("name") or "")]
    lead = next((row for row in named if row.get("lead")), None)
    if lead is not None:
        home = continent_of(lead.get("map_id"))
        if home is not None:
            return home
    seen = {continent_of(row.get("map_id")) for row in named}
    seen.discard(None)
    return seen.pop() if len(seen) == 1 else None


def _no_crossing() -> bool:
    """True while crossing.py says a continent crossing cannot be made."""
    return crossing.first_blocked_leg() is not None


def _inside_capital() -> dict:
    """map id -> the faction whose capital the entrance stands inside.

    Read off dungeonpath.PATH's `Step.inside`, the same fact the Dungeons page
    marks a step OFF by, so the council and that page cannot disagree about
    which doors a family can walk to. Imported here rather than at the top
    because dungeonpath imports this module for PLACES.
    """
    import dungeonpath

    return {step.map_id: step.inside for step in dungeonpath.PATH if step.inside}


def _other_capital(map_id: int, faction: str) -> bool:
    """True when the door is inside a capital this family cannot walk into.

    An unknown faction ("", a mixed or unread roster) counts as the other
    one: a door nobody can show is reachable is not one to send them to.
    """
    inside = _inside_capital().get(int(map_id), "")
    return bool(inside) and inside != faction


def _runs(target: int) -> str:
    return "1 run" if target == 1 else "%d runs" % target


def _level_sentence(who: str, row: dict, _titles: dict) -> str:
    return "The family will help %s reach level %d." % (
        who,
        int(row.get("target") or 0),
    )


def _quest_sentence(who: str, row: dict, titles: dict) -> str:
    title = titles.get(int(row.get("quest_id") or 0))
    if title:
        return "The family will help %s finish %s." % (who, title)
    return "The family will help %s finish a quest the world could not name." % who


def _skill_sentence(who: str, row: dict, _titles: dict) -> str:
    skill = str(row.get("skill_name") or "").strip() or "a trade"
    target = int(row.get("target") or 0)
    if target:
        return "%s will train %s to %d." % (who, skill, target)
    return "%s will learn %s." % (who, skill)


def _dungeon_sentence(who: str, row: dict, _titles: dict) -> str:
    place = keyword_place(str(row.get("skill_name") or ""))
    target = int(row.get("target") or 0)
    runs = ", %s" % _runs(target) if target else ""
    return "%s will lead the family into %s%s." % (who, place, runs)


_SENTENCES = {
    "level": _level_sentence,
    "quest": _quest_sentence,
    "skill": _skill_sentence,
    "dungeon": _dungeon_sentence,
}


def decision_line(row: dict, quest_titles: dict | None = None) -> str:
    """What the goal asks for, as a plain sentence with a subject and a verb.

    Read off the goal the council persisted, which is the only part of a
    council that survives it: the ARGUMENT is written to overseer_thought in
    the model's words, and the outcome is written as a goal the supervisor can
    drive. So this reads the outcome and never tries to parse the argument.

    EVERY KIND THE TABLE CAN HOLD HAS ITS OWN SENTENCE. The old fallback was
    "<who> is to see to <kind>", which is what every dungeon goal fell into:
    "Grug is to see to dungeon." named neither the place nor the size of the
    campaign, and the operator could not read it.
    """
    who = str(row.get("character_name") or "").strip() or "The family"
    kind = str(row.get("kind") or "")
    sentence = _SENTENCES.get(kind)
    if sentence is not None:
        return sentence(who, row, quest_titles or {})
    return "%s will work on a %s goal." % (who, kind or "new")


def _names(names: list) -> str:
    """ "Ugga", "Ugga and Og", "Ugga, Og and Bork"."""
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def ago(seconds: float | None) -> str:
    """How long ago, in the words a person would use. "" when unknown."""
    if seconds is None:
        return ""
    seconds = max(int(seconds), 0)
    if seconds < 90:
        return "just now"
    minutes = seconds // 60
    if minutes < 90:
        return "%d minutes ago" % minutes
    hours = minutes // 60
    if hours < 36:
        return "%d hours ago" % hours
    days = hours // 24
    return "1 day ago" if days == 1 else "%d days ago" % days


def deciding_sitting(rows: list[dict], decided_at) -> list[dict]:
    """The council rows of the sitting that produced a goal, or [].

    THE SITTING THAT DECIDED IT, NOT THE LAST ONE. The bridge persists the plan
    in the same pass that writes the sitting's lines, so the goal's
    created_at lands on or just after that sitting's last line. The page used
    to count the speakers of the LAST sitting instead, and on the dev realm
    that was a one-line sitting about a robe held a day after the dungeon
    decision it was printed under.

    [] means no sitting ended within SITTING_GAP before the goal: it was set
    some other way (an order in Discord, the operator), or the sitting has
    scrolled out of the rows this view reads. Both say "no council to show",
    and the caller says so rather than borrowing a different sitting.
    """
    if not isinstance(decided_at, datetime):
        return []
    found: list[dict] = []
    for sitting in sittings(rows):
        last = sitting[-1]["created_at"]
        if (
            last <= decided_at + timedelta(minutes=1)
            and decided_at - last <= SITTING_GAP
        ):
            found = sitting
    return found


def _in_effect(row: dict, standing: dict | None) -> tuple[bool | None, str]:
    """Whether a decided goal is being acted on, and the sentence saying so.

    ONLY A DUNGEON GOAL CAN BE CHECKED, because it is the only kind with a
    column to check it against: the run coordinator starts a campaign when the
    family leader's `overseer_roster.job` reads `dungeon` or
    `dungeon:<keyword>`, and reads nothing else. A level, quest or skill goal
    is steered by the bridge's goal loop and has no column of its own, so the
    sentence says what happens next rather than claiming it happened.

    `standing` is {"leader": name, "job": text, "done": n, "wanted": n} for
    the goal's family, or None when the roster could not be read.
    """
    kind = str(row.get("kind") or "")
    who = str(row.get("character_name") or "") or "the family"
    if kind != "dungeon":
        return None, (
            "Next: the goal loop steers %s toward it until it is done "
            "or cancelled." % who
        )
    place = keyword_place(str(row.get("skill_name") or ""))
    if not standing or not standing.get("job"):
        return None, (
            "Whether the family is on its way to %s could not be "
            "read this time." % place
        )
    keyword = str(row.get("skill_name") or "").strip().lower()
    job = str(standing["job"]).strip().lower()
    leader = str(standing.get("leader") or "") or who
    wanted = {"dungeon:%s" % keyword} if keyword else {"dungeon"}
    if job in wanted:
        done = standing.get("done")
        of = standing.get("wanted")
        tally = " %d of %d runs done." % (done, of) if done is not None and of else ""
        return True, (
            "In effect: %s's job reads %s, so the run coordinator is "
            "working on it.%s" % (leader, job, tally)
        )
    return False, (
        "Not in effect yet: %s's job still reads %s, and the run "
        "coordinator starts %s only when it reads %s. Nobody is "
        "heading there." % (leader, job, place, sorted(wanted)[0])
    )


def _older(
    active: list[dict], won: dict, quest_titles: dict | None, now: datetime | None
) -> list[str]:
    """Every other goal still marked active, newest first, one line each."""
    out = []
    for row in sorted(active, key=lambda r: r.get("created_at") or "", reverse=True):
        if row is won:
            continue
        since = _since(now, row.get("created_at"))
        out.append(decision_line(row, quest_titles) + (" " + since if since else ""))
    return out


def _since(now: datetime | None, when) -> str:
    """ "Set 3 hours ago." off two datetimes, or "" when either is missing."""
    if now is None or not hasattr(when, "year"):
        return ""
    return "Set %s." % ago((now - when).total_seconds())


def _rows_of(lines: list[dict]) -> list[dict]:
    """Transcript lines back into thought rows, for callers without rows.

    A line whose time cannot be read is left out rather than allowed to take
    the whole card down: it cannot be placed in a sitting either way.
    """
    rows = []
    for line in lines:
        try:
            at = datetime.fromisoformat(str(line.get("at") or ""))
        except ValueError:
            continue
        rows.append(
            {"character_name": line["who"], "text": line["text"], "created_at": at}
        )
    return rows


def _who_line(proposer: str, spoke: list[str], silent: list[str]) -> str:
    """Who proposed it, who else spoke, who did not, and that no vote exists."""
    line = "%s proposed it." % proposer
    others = [name for name in spoke if name != proposer]
    if others:
        line += " %s also spoke." % _names(others)
    if silent:
        line += " %s did not speak at that sitting." % _names(silent)
    return line + (
        " The council does not record a vote; the proposal with "
        "the most backing carries."
    )


OUTSIDE_LABEL = "SET OUTSIDE THE COUNCIL"
OUTSIDE_LINE = (
    "No council sitting ended just before this goal was set, so it came from "
    "somewhere else: an order in Discord or from the operator. Nobody voted "
    "on it."
)


def _active(goal_rows: list[dict], members: list[str] | None) -> list[dict]:
    """The goals still marked active, narrowed to one family when named."""
    active = [row for row in goal_rows if str(row.get("status") or "") == "active"]
    if members is None:
        return active
    allowed = set(members)
    return [row for row in active if str(row.get("character_name") or "") in allowed]


def consensus(
    goal_rows: list[dict],
    lines: list[dict],
    quest_titles: dict | None = None,
    *,
    thought_rows: list[dict] | None = None,
    members: list[str] | None = None,
    standing: dict | None = None,
    now: datetime | None = None,
) -> dict | None:
    """The newest decision, in plain words, or None when nothing is on record.

    WHAT A READER NEEDS FROM THE CARD, in the order they need it: what was
    decided, who proposed it, who else spoke and who did not, when, and
    whether it is in effect. Every one of those is a sentence here.

    WHO PROPOSED IT IS STRUCTURAL, NOT PARSED. council._script always closes a
    sitting with the winner's proposer saying "Then it is settled", so the
    speaker of the deciding sitting's LAST line is the proposer, whatever words
    the voice layer put in their mouth.

    WHO AGREED IS NOT RECORDED, and the card does not pretend it is. hold()
    scores the backing and keeps only the winner, and the backing lines are
    voiced by a language model, so reading "yes" out of them would be parsing
    an argument this module promised never to parse. What IS known is who
    spoke at that sitting and who did not, and that is what the card says.

    `lines` is kept for the callers that still hand in only a transcript: with
    no `thought_rows`, the deciding sitting is looked for in those lines.
    """
    active = _active(goal_rows, members)
    if not active:
        return None
    won = max(active, key=lambda row: row.get("created_at") or "")
    decided_at = won.get("created_at")
    family = list(members) if members is not None else list(bonds.FAMILY)

    source = thought_rows if thought_rows is not None else _rows_of(lines)
    sitting = deciding_sitting(source, decided_at)
    said = transcript(sitting) if sitting else []
    spoke = list(dict.fromkeys(line["who"] for line in said))
    proposer = (bonds.canon(sitting[-1]["character_name"]) or "") if sitting else ""
    silent = [name for name in bonds.speaking_order(family) if name not in spoke]
    acted, next_line = _in_effect(won, standing)
    return {
        "label": "DECIDED BY THE COUNCIL" if sitting else OUTSIDE_LABEL,
        "decision": decision_line(won, quest_titles),
        "beneficiary": str(won.get("character_name") or ""),
        "kind": str(won.get("kind") or ""),
        "proposer": proposer,
        "spoke": len(spoke),
        "speakers": spoke,
        "silent": silent,
        "family": len(family),
        "who_line": _who_line(proposer, spoke, silent) if sitting else OUTSIDE_LINE,
        "when_line": _since(now, decided_at),
        "in_effect": acted,
        "next_line": next_line,
        "sitting": said,
        "older": _older(active, won, quest_titles, now),
        "at": _iso(decided_at),
    }


def _weakest(level_rows: list[dict]) -> tuple[str, int] | None:
    """Whoever is furthest behind, because the whole family walks in together.

    The gate is asked of the LOWEST level and not of the median: a party is
    gated by the member who dies at the door, and a median would report a
    family ready while one of them was four levels off it.
    """
    known = [
        (str(row["name"]), int(row.get("level") or 0))
        for row in level_rows
        if str(row.get("name") or "")
    ]
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
        return (
            "Short, and near enough to try anyway: %s is the one who would "
            "be carried." % who
        )
    return (
        "Not yet. %s is %d levels short, and the family goes in together "
        "or not at all." % (who, short)
    )


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
                bucket[name] = max(bucket.get(name, -1), int(item.get("quality") or 0))
    return {
        map_id: [
            name
            for name, _ in sorted(bucket.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
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
    # A door inside the other faction's capital is not a place this family
    # can go (#202). Only skipped when the faction is KNOWN: this list is
    # also what the Council tab draws, and a roster whose races were not
    # read is shown everything rather than guessed at. _dungeon_proposal
    # holds the stricter line before anything is written.
    faction = _faction(level_rows, [str(row.get("name") or "") for row in level_rows])
    out = []
    for map_id, wants in sorted(PLACES.items(), key=lambda pair: (pair[1], pair[0])):
        if map_id not in been and wants > level + HORIZON:
            continue
        if faction and _other_capital(map_id, faction):
            continue
        short = wants - level
        seen = drops.get(map_id, [])
        out.append(
            {
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
            }
        )
    return out


# --- the one proposal `assess()` cannot make (infra dungeon-decision gap) ---
#
# prospects() above already knows everything a dungeon decision needs - the
# weakest member's level, the gate word, what has been seen to drop - and
# until now it fed only the website's display. This is the wiring that lets
# the council actually ACT on its own readiness panel instead of just showing
# it.


def _scarlet_keyword(level: int) -> str:
    """Which of Scarlet Monastery's four wings this family should be sent to.

    The HIGHEST wing the family is ready (or NEAR_ENOUGH short) for, same gate
    prospects() uses everywhere else - a family ready for the cathedral is not
    sent back to the graveyard, and one only ready for the graveyard is not
    sent past its door.

    Kept as a named function after infra#4247 generalized the rule, because
    `_wing_rated_prospects` below asks a question that really is about Scarlet
    Monastery and nowhere else: PLACES carries one number per map id and map
    189 has four doors behind it.
    """
    return dungeonprogression.frontier_stage(SCARLET_WINGS, level, slack=NEAR_ENOUGH)


def _wing_rated_prospects(
    level_rows: list[dict], cards: list[dict], level: int
) -> list[dict]:
    """prospects(), with Scarlet Monastery re-rated to the wing this family
    can actually reach.

    Scarlet Monastery's entry in PLACES carries only the graveyard's level -
    one number per map id, and it is the LOWEST of the four wings. Comparing
    that number straight against every other dungeon would have the council
    always undersell Scarlet Monastery once the family outgrows its door,
    proposing Zul'Farrak over the cathedral for a family strong enough for
    both. So the map-189 row is re-rated here to whichever wing the family
    can ACTUALLY reach, before the frontier is chosen - the same
    short/ready arithmetic prospects() uses, just aimed at the wing instead
    of the doorway.
    """
    wing_wants = dict(SCARLET_WINGS)[_scarlet_keyword(level)]
    rated = []
    for p in prospects(level_rows, cards):
        if p["map_id"] == SCARLET_MAP_ID:
            short = wing_wants - level
            p = dict(p, wants=wing_wants, short=max(short, 0), ready=short <= 0)
        rated.append(p)
    return rated


def _campaign_keyword(
    map_id: int, level: int, completed_runs: dict[str, int] | None
) -> str:
    """The job keyword for the dungeon the frontier picked, or "" when the
    overseer has no portal for that map and the family must not be sent.

    THE FRONTIER PICKS THE DUNGEON AND THIS PICKS THE DOOR, and getting those
    two the wrong way round is infra#4247 in one sentence. The run ledger used
    to outrank the frontier outright - "the first unfinished Scarlet wing is
    the only target eligible for this campaign" - so a family that had walked
    past Scarlet Monastery entirely could never be sent anywhere else. At level
    60, 21 levels above the cathedral, that is what the council actually did,
    every hour, for as long as it was asked.

    A campaign the ledger says is FINISHED falls through to the frontier stage
    of the same map rather than to None, and that is deliberate: the operator's
    ask for Blackrock Depths is "over and over ... incrementally get better
    gear", so a campaign at its target means run it again, not stand down. The
    repeat was never the defect; the dungeon being 21 levels stale was.

    A MAP WITH NO CAMPAIGN GETS ITS FRONT DOOR, NOT THE BARE `dungeon` JOB
    (#202). The bare job runs the Deadmines, so answering "" here used to
    send a family that chose Blackfathom Deeps to the Deadmines instead.

    THE LEDGER CANNOT PUSH PAST THE FAMILY'S LEVEL. The first unfinished
    stage is only taken when the weakest member is within NEAR_ENOUGH of it;
    otherwise the family keeps to the highest stage it can walk into, which
    is the same gate prospects() holds every place to.
    """
    stages = dungeonprogression.campaign_stages(map_id)
    if not stages:
        return front_door(map_id)
    if completed_runs is not None:
        ordered = dungeonprogression.next_stage(
            completed_runs,
            DUNGEON_RUNS_WANTED,
            stages=stages,
        )
        if ordered and dict(stages)[ordered] <= level + NEAR_ENOUGH:
            return ordered
    return dungeonprogression.frontier_stage(stages, level, slack=NEAR_ENOUGH)


def _refusal(p: dict, faction: str, home: int | None) -> str:
    """Why the family cannot be sent to prospect `p`, or "" when it can.

    Said to the family, so a reader of the council's reasoning line learns
    why a harder place was passed over (#205).
    """
    map_id = int(p["map_id"])
    if _other_capital(map_id, faction):
        return "inside the other faction's capital"
    withheld = _withheld(map_id)
    if withheld:
        return "withheld, since " + withheld
    if not front_door(map_id):
        log.info(
            "council: not proposing %s (map %d) - no dungeon portal "
            "answers for it, so no job could send the family there",
            p["place"],
            map_id,
        )
        return "no door the overseer can use"
    door = continent_of(map_id)
    if home is None:
        return "nothing says which continent we are on"
    if door != home and _no_crossing():
        return "on %s while we are on %s, with no way across yet" % (
            CONTINENT_NAMES.get(door, "another continent"),
            CONTINENT_NAMES.get(home, "another continent"),
        )
    return ""


def _door_floor(keyword: str, map_id: int) -> int:
    """The level a door wants: the Scarlet wing's own, PLACES' number for the
    map, or the Dungeons page's floor for a map PLACES does not name."""
    import dungeonpath

    wing = dict(SCARLET_WINGS).get(keyword)
    if wing is not None:
        return wing
    if map_id in PLACES:
        return PLACES[map_id]
    step = next((s for s in dungeonpath.PATH if s.map_id == map_id), None)
    return step.low if step is not None else 0


def door_refusal(keyword: str, level_rows: list[dict]) -> str:
    """Why this family cannot be sent through `keyword`'s door, or "".

    The same rules the council proposes by (#202, #204, #205, #207), asked of
    one named door rather than of a map: a portal keyword mod-overseer runs,
    not a withheld door, not inside the other faction's capital, not more
    than NEAR_ENOUGH levels above the weakest member, and on the family's
    continent or across a crossing that can be made. The campaign queue
    (#209) asks this of every entry before a row is written.
    """
    import dungeonpath

    if keyword not in jobs.PORTAL_KEYWORDS:
        return "no dungeon portal answers to %r" % keyword
    if keyword in dungeonpath.WITHHELD_DOORS:
        return "withheld, since " + dungeonpath.WITHHELD_DOORS[keyword]
    map_id = int(dungeonpath.PORTAL_MAPS[keyword])
    names = [str(row.get("name") or "") for row in level_rows]
    faction = _faction(level_rows, names)
    if _other_capital(map_id, faction):
        return (
            "inside the other faction's capital"
            if faction
            else "inside a capital, and nothing says which faction this family is"
        )
    weakest = _weakest(level_rows)
    if weakest is None:
        return "nobody's level can be read"
    who, level = weakest
    floor = _door_floor(keyword, map_id)
    if level + NEAR_ENOUGH < floor:
        return "%s is level %d and it wants %d" % (who, level, floor)
    home = _home_continent(level_rows)
    door = continent_of(map_id)
    if home is None:
        return "nothing says which continent we are on"
    if door != home and _no_crossing():
        return "on %s while we are on %s, with no way across yet" % (
            CONTINENT_NAMES.get(door, "another continent"),
            CONTINENT_NAMES.get(home, "another continent"),
        )
    return ""


def _sendable(rated: list[dict], level_rows: list[dict]) -> tuple[list, list]:
    """(the ready prospects the family can be sent to, [(prospect, why not)]
    for the ready ones it cannot). Unready prospects are in neither."""
    faction = _faction(level_rows, [str(row.get("name") or "") for row in level_rows])
    home = _home_continent(level_rows)
    ready: list = []
    passed: list = []
    for p in rated:
        if p["short"] > NEAR_ENOUGH:
            continue
        why = _refusal(p, faction, home)
        if why:
            passed.append((p, why))
        else:
            ready.append(p)
    if not ready and home is None and passed:
        log.info(
            "council: not proposing a dungeon - the family's continent "
            "is unread, so no door can be shown reachable"
        )
    return ready, passed


def _dungeon_said(best: dict, who: str) -> str:
    place = best["place"]
    if best["ready"]:
        return f"{place} will not trouble us now. We should go in."
    return (
        f"{place} is close enough to try. {who} would be carried, "
        f"and I would rather we went than waited."
    )


def _passed_over(best: dict, passed: list) -> str:
    """The reasoning line's account of every harder place passed over for
    `best`, grouped by reason, hardest first. "" when none was."""
    grouped: dict[str, list[str]] = {}
    for p, why in sorted(passed, key=lambda pair: -pair[0]["wants"]):
        if p["wants"] > best["wants"] and p["place"] not in grouped.get(why, []):
            grouped.setdefault(why, []).append(p["place"])
    return "".join(
        " Not %s: %s." % (_either(places), why) for why, places in grouped.items()
    )


def _either(names: list) -> str:
    """ "Ugga", "Ugga or Og", "Ugga, Og or Bork"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def _frontier(ready: list[dict]) -> dict:
    """The hardest ready prospect; ties favour Scarlet Monastery, then a door
    outside any capital. See _dungeon_proposal for why."""
    inside = _inside_capital()
    return max(
        ready,
        key=lambda p: (
            p["wants"],
            p["map_id"] == SCARLET_MAP_ID,
            p["map_id"] not in inside,
        ),
    )


@dataclass(frozen=True)
class Door:
    """One dungeon the council could send the family to now, by its door."""

    place: str
    map_id: int
    keyword: str
    wants: int
    ready: bool


def dungeon_doors(
    level_rows: list[dict],
    cards: list[dict],
    completed_runs: dict[str, int] | None = None,
) -> tuple:
    """(doors, pick): every dungeon the council may send this family to now,
    one door each, and the one its frontier rule picks (None when no door).

    THE OPTIONS ARE THE PROPOSAL'S OWN. The same prospects, the same
    `_sendable` filter, the same door per map (`_campaign_keyword`) and the
    same `door_refusal` rules (#204, #207): a second judge (Jev, #95) may be
    asked to choose among these, and never among a door the council itself
    would refuse. `pick` is `_dungeon_proposal`'s choice of place, by door.
    """
    weakest = _weakest(level_rows) if level_rows else None
    if weakest is None:
        return (), None
    _who, level = weakest
    ready, _passed = _sendable(
        _wing_rated_prospects(level_rows, cards, level), level_rows
    )
    if not ready:
        return (), None
    best = _frontier(ready)
    doors, pick = [], None
    for p in sorted(ready, key=lambda p: (p["wants"], p["place"])):
        keyword = _campaign_keyword(int(p["map_id"]), level, completed_runs)
        if (
            not keyword
            or jobs.dungeon_job(keyword) is None
            or _withheld_door(keyword)
            or door_refusal(keyword, level_rows)
        ):
            continue
        door = Door(
            place=str(p["place"]),
            map_id=int(p["map_id"]),
            keyword=keyword,
            wants=int(p["wants"]),
            ready=bool(p["ready"]),
        )
        doors.append(door)
        if p is best:
            pick = door
    return tuple(doors), pick


def _dungeon_proposal(
    speakers: list,
    level_rows: list[dict],
    cards: list[dict],
    completed_runs: dict[str, int] | None = None,
) -> Proposal | None:
    """A family-wide proposal to run a dungeon, when one is actually ready.

    Built from prospects() - the exact readiness gate the Council tab already
    draws - so the council can never argue for a target the page would call
    unready in the same breath. Only a READY or NEAR_ENOUGH-short place is
    worth raising here; anything further off is idle noise, and there is
    always a dungeon further off.

    RAISED BY THE WEAKEST MEMBER, per _weakest() - the family is gated on
    whoever is furthest behind, so that is whose voice this naturally is, and
    it is also who a dungeon goal is persisted against (overseer_goal has no
    row for FAMILY_AT_LARGE). If that member is not sitting at THIS council
    (offline, or not yet bonded) there is nobody to put the sentence in, and
    proposing on their behalf would put words in an absent mouth - so the
    proposal is withheld for the sitting rather than reassigned to someone
    else's voice.
    """
    if not level_rows:
        return None
    weakest = _weakest(level_rows)
    if weakest is None:
        return None
    who, level = weakest
    voice = next((m for m in speakers if m.name == who), None)
    if voice is None:
        return None

    rated = _wing_rated_prospects(level_rows, cards, level)
    # WHERE THE FAMILY CAN ACTUALLY BE SENT (#202). prospects() skips the
    # other faction's capital only when the faction is known; a proposal is
    # stricter, because it becomes a job. A door with no portal row is
    # refused here rather than written as the bare `dungeon` job, which is
    # the Deadmines whatever the council meant.
    #
    # AND ONLY WHERE THEY CAN WALK (#205). A door on another continent from
    # the family's leader is refused while crossing.py says no crossing can
    # be made, and a door dungeonpath.WITHHELD_DOORS names is refused
    # outright. A family whose continent is unread is sent nowhere: a door
    # nobody can show is reachable is not one to send them to.
    ready, passed = _sendable(rated, level_rows)
    if not ready:
        return None
    # The FRONTIER, not the first entry: prospects() lists everything the
    # family has already been to as well, however far past it they now are,
    # and the honest next target is the hardest one they can currently walk
    # into - not the easiest. Ties favour Scarlet Monastery, the operator's
    # own stated priority, then a door outside any capital: Blackfathom
    # Deeps and the Stockade both want 24, and the city door is the one a
    # family of the other faction could never have taken.
    best = _frontier(ready)
    # AND THE DOOR ONLY AFTER THE PLACE (infra#4247). The run ledger used to be
    # consulted first and allowed to narrow `ready` to Scarlet Monastery, which
    # is why a level 60 family could never be sent past a level 39 wing. It now
    # answers the question it can actually answer: given the dungeon the
    # frontier picked, which of ITS doors is next.
    keyword = _campaign_keyword(int(best["map_id"]), level, completed_runs)
    if jobs.dungeon_job(keyword) is None or not keyword or _withheld_door(keyword):
        # Unreachable after the filter above, and kept so a future table edit
        # cannot quietly turn a missing keyword back into the Deadmines, or a
        # campaign stage into a withheld door.
        log.warning(
            "council: refusing a dungeon proposal for %s - keyword %r has no "
            "portal row or is withheld",
            best["place"],
            keyword,
        )
        return None
    said = _dungeon_said(best, who) + _passed_over(best, passed)
    return Proposal(
        proposer=voice.name,
        kind="dungeon",
        beneficiary=voice.name,
        # target is DUNGEON_RUNS_WANTED, not a level or a map id: it is the
        # one number the persisted goal actually needs to drive a campaign,
        # the same way a quest proposal's target is objectives remaining
        # rather than the quest's own id.
        target=DUNGEON_RUNS_WANTED,
        # Above a half-finished quest (60): the whole family being gated on
        # one dungeon is a bigger fact than one character's errand, and it is
        # the fact the operator's own priority named. Below a laggard rescue, whose
        # weight (100 - level) reflects how far behind somebody actually is -
        # nobody left behind outranks anywhere the family could go next. See
        # the PR for the full argument.
        weight=70,
        said=said,
        keyword=keyword,
    )


def quiet_line(lines: list[dict]) -> str:
    """What to say when no council is on record. Empty when there is one."""
    if lines:
        return ""
    return (
        "No council is on record. They meet on their own cadence and only "
        "when somebody has something to raise; an empty transcript is a "
        "quiet week, not a broken page."
    )


def undecided_line(agreed: dict | None) -> str:
    """Why the consensus block is empty. Empty when it is not."""
    if agreed is not None:
        return ""
    return (
        "Nothing the supervisor can drive is on the table. A council that "
        "agrees on a quiet day has still decided something real - it is "
        "simply not written as a goal, so this block has nothing to show."
    )


# Race -> faction, 3.3.5a, the same two sets core.py counts a census by.
_ALLIANCE_RACES = frozenset({1, 3, 4, 7, 11})
_HORDE_RACES = frozenset({2, 5, 6, 8, 10})


def _faction(level_rows: list[dict], names: list[str]) -> str:
    """ "Alliance", "Horde" or "" off the family's own races."""
    races = {
        int(row.get("race") or 0)
        for row in level_rows
        if str(row.get("name") or "") in set(names)
    }
    if races and races <= _ALLIANCE_RACES:
        return "Alliance"
    if races and races <= _HORDE_RACES:
        return "Horde"
    return ""


def families_of(roster_rows: list[dict] | None) -> list[tuple[str, list[str]]]:
    """[(family, [names, leader first])] off overseer_roster, bonds' first.

    THE ROSTER, NOT bonds, says who is in the world: bonds holds personas for
    ONE family, and the second family (the Horde five) is enrolled in
    overseer_roster with no persona at all. With no roster rows the answer
    degrades to bonds' own family, which is what this view always showed.
    """
    grouped: dict[str, list[tuple[int, str]]] = {}
    for row in roster_rows or []:
        fam = str(row.get("family") or "").strip()
        name = str(row.get("name") or "").strip()
        if not fam or not name:
            continue
        grouped.setdefault(fam, []).append(
            (0 if int(row.get("lead") or 0) else 1, name)
        )
    if not grouped:
        roster = bonds.speaking_order(list(bonds.FAMILY))
        return [(roster[0] if roster else "", roster)]
    out = [
        (fam, [name for _, name in sorted(members)]) for fam, members in grouped.items()
    ]
    # The family bonds knows first, so the tab opens on the one that holds
    # councils; then by name, so the order does not move between polls.
    out.sort(key=lambda pair: (not any(bonds.canon(n) for n in pair[1]), pair[0]))
    return out


def _standing(roster_rows: list[dict] | None, names: list[str]) -> dict | None:
    """The family leader's job and campaign counter, or None if unread."""
    rows = [
        row
        for row in roster_rows or []
        if str(row.get("name") or "") in set(names) and int(row.get("enabled", 1) or 0)
    ]
    if not rows or "job" not in rows[0]:
        return None
    lead = next((row for row in rows if int(row.get("lead") or 0)), rows[0])

    def number(key):
        value = lead.get(key)
        return None if value is None else int(value)

    return {
        "leader": str(lead["name"]),
        "job": str(lead.get("job") or "quest"),
        "done": number("dungeon_runs_done"),
        "wanted": number("dungeon_runs_wanted"),
    }


NO_COUNCIL = (
    "%s's family does not hold councils. A council needs every speaker to "
    "have a written persona, and only one family has them, so nothing on "
    "this tab was decided for %s's family. Where they could go next is still "
    "worked out from their levels below."
)


def _family_view(
    fam: str,
    names: list[str],
    thought_rows: list[dict],
    goal_rows: list[dict],
    level_rows: list[dict],
    cards: list[dict],
    quest_titles: dict | None,
    roster_rows: list[dict] | None,
    now: datetime,
) -> dict:
    """One family's half of the tab."""
    holds = any(bonds.canon(name) for name in names)
    mine = [row for row in level_rows if str(row.get("name") or "") in set(names)]
    if holds:
        lines = transcript(thought_rows)
        agreed = consensus(
            goal_rows,
            lines,
            quest_titles,
            thought_rows=thought_rows,
            members=names,
            standing=_standing(roster_rows, names),
            now=now,
        )
        quiet = quiet_line(lines)
        undecided = undecided_line(agreed)
        note = ""
    else:
        lines, agreed, quiet, undecided = [], None, "", ""
        note = NO_COUNCIL % (fam, fam)
    # What has been SEEN to drop comes from the Chronicle's cards, which are
    # built for the family bonds knows. Handing them to the other family
    # would credit it with runs it never did.
    faction = _faction(level_rows, names)
    return {
        "family": fam,
        "title": ("%s's family, %s" % (fam, faction))
        if faction
        else "%s's family" % fam,
        "faction": faction,
        "members": names,
        "holds_council": holds,
        "note": note,
        "transcript": lines,
        "spoke": sorted({line["who"] for line in lines}),
        "consensus": agreed,
        "quiet": quiet,
        "undecided": undecided,
        "prospects": prospects(mine, cards if holds else []),
    }


def build_council(
    thought_rows: list[dict],
    goal_rows: list[dict],
    level_rows: list[dict],
    cards: list[dict],
    quest_titles: dict | None = None,
    now: datetime | None = None,
    roster_rows: list[dict] | None = None,
) -> dict:
    """Rows in, the Council tab's JSON out.

    thought_rows  overseer_thought rows with source 'council', any order
    goal_rows     overseer_goal rows, any status
    level_rows    name, level and race for every rostered character
    cards         the Chronicle's cards, for what the family has seen drop
    quest_titles  quest id -> LogTitle, so a quest decision can be named
    now           the clock, injectable so the suite can stand still
    roster_rows   overseer_roster rows: who is in which family, and the
                  leader's job, which is how a dungeon decision is checked

    EVERY ONE OF THOSE MAY BE EMPTY, exactly as build_agenda's may. A realm
    whose schema predates a table hands in [] for it and gets a thinner view,
    never an exception.

    `families` is the tab: one entry per family, both factions. The top-level
    keys repeat the first family's for any older reader of this payload.
    """
    now = now or datetime.now()
    families = [
        _family_view(
            fam,
            names,
            thought_rows,
            goal_rows,
            level_rows,
            cards,
            quest_titles,
            roster_rows,
            now,
        )
        for fam, names in families_of(roster_rows)
    ]
    first = families[0]
    return {
        "generated_at": _iso(now),
        "families": families,
        "transcript": first["transcript"],
        "spoke": first["spoke"],
        "consensus": first["consensus"],
        "quiet": first["quiet"],
        "undecided": first["undecided"],
        "prospects": first["prospects"],
    }
