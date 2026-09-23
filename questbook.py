"""Who is behind on quests, on what, and whether they can still do it.

Pure module, the same seam as quests.py and bonds.py: facts in, judgements
out. No pymysql, no network, nothing fetched in here. bridge.py runs the
queries against acore_world.quest_template / quest_template_addon and the two
per-character tables, builds Member and Quest records, and hands them in.

WHY THIS EXISTS. The operator's requirement is that all five quest equally and nobody
falls behind. They do not. Turn-ins, read live:

    Og 17    Bork 13    Grug 13    Grog 3    Ugga 3

Grog and Ugga are miles back. The cause is not that they are slower - it is
that the five hold DIFFERENT quest logs (Grug 5 held, Bork 12, Grog 8, Og 9,
Ugga 7). They stand together and fight together, so the kills count for
everyone, but only the ones actually holding the quest get the turn-in. Same
mobs, a quarter of the experience.

WHY "EVERYONE TAKES EVERY QUEST" IS THE WRONG FIX, and the reason this module
is a ledger rather than a scheduler:

  - Some quests are class-locked. 1638 "A Warrior's Training" is
    AllowableClasses=1, which is Grug and only ever Grug. 5624 "Garments of
    the Light" is 16, which is Ugga. Handing those round is impossible, and a
    catch-up metric that counted them would report four characters permanently
    behind on something they can never do.
  - Some quests are chains. 11 of the family's 41 held rows have PrevQuestID
    set: Ugga holds 35 "Further Concerns" (prev 40), Grog holds 37 "Find the
    Lost Guards" (prev 35). You cannot hand someone 37 before 35, so catching
    up is ORDERED, not a set.
  - Some quests are dead weight. Bork holds 218 "The Stolen Journal", 234
    "Coldridge Valley Mail Delivery", 400 "Tools for Steelgrill" and 3361 "A
    Refugee's Quandary" - Coldridge Valley and Dun Morogh, the DWARF starting
    zone. The family is in Elwynn Forest, on another continent. The right move
    is for Bork to drop them. A scheduler that read those as "Bork is ahead,
    the others are behind" would march five characters across the world to fix
    a bookkeeping artefact.

So the output is a ledger the family council can read out: who is behind, on
what, in what order they can do it, and what should simply be abandoned.

THE ALLIANCE-MASK TRAP. AllowableRaces=1101 is on ALL 41 held rows and
restricts NOBODY here: 1101 is human 1 + dwarf 4 + night elf 8 + gnome 64 +
draenei 1024, i.e. "Alliance", and every one of the five is Alliance. Counting
non-zero AllowableRaces as a restriction yields "41 race-locked quests", which
is wrong in every case. A mask is only a restriction when it excludes somebody
who is actually here; see restricted_for() and its test.

THE OTHER BITMASK TRAP. `characters.class` stores a class ID (1 warrior,
2 paladin, 4 rogue, 5 priest, 8 mage), while AllowableClasses stores a
BITMASK. Rogue is id 4 and bit 8; priest is id 5 and bit 16. Comparing the two
directly is a bug that reads as working code, so the conversion is a named
function with its own test rather than an inline shift at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Class ID (characters.class) -> AllowableClasses bit. The bit is
# 1 << (id - 1) throughout, but it is written out because the two numbers are
# confusable and a table can be read against the wiki; see module docstring.
CLASS_BIT = {
    1: 1,  # warrior   - Grug
    2: 2,  # paladin   - Grog
    3: 4,  # hunter
    4: 8,  # rogue     - Bork
    5: 16,  # priest    - Ugga
    6: 32,  # death knight
    7: 64,  # shaman
    8: 128,  # mage      - Og
    9: 256,  # warlock
    11: 1024,  # druid     (there is no class id 10)
}

# Race ID (characters.race) -> AllowableRaces bit, same relationship.
RACE_BIT = {
    1: 1,  # human
    2: 2,  # orc
    3: 4,  # dwarf
    4: 8,  # night elf
    5: 16,  # undead
    6: 32,  # tauren
    7: 64,  # gnome
    8: 128,  # troll
    10: 512,  # blood elf
    11: 1024,  # draenei
}

# What AllowableRaces=1101 actually is. Named so a test can pin it and nobody
# re-reads it as a restriction: it is every Alliance race, and the whole
# family is Alliance.
ALLIANCE_MASK = RACE_BIT[1] | RACE_BIT[3] | RACE_BIT[4] | RACE_BIT[7] | RACE_BIT[11]

# Reasons a quest is closed to somebody. Short, stable strings: they end up in
# a council prompt as grounded facts, so they have to render as a clause.
CLASS = "class"
RACE = "race"
TOO_LOW = "too-low"
TOO_HIGH = "too-high"
PREREQUISITE = "prerequisite"
EXCLUSIVE = "exclusive"
DONE = "already-done"
ELSEWHERE = "elsewhere"


def class_bit(class_id: int) -> int:
    """characters.class -> the AllowableClasses bit for that class."""
    return CLASS_BIT.get(int(class_id), 0)


def race_bit(race_id: int) -> int:
    """characters.race -> the AllowableRaces bit for that race."""
    return RACE_BIT.get(int(race_id), 0)


def mask_allows(mask: int, bit: int) -> bool:
    """Does a WoW allowable-mask admit this bit?

    Zero means NO restriction, not "nobody" - 39 of the family's 41 held
    quests have AllowableClasses=0. Reading 0 as an empty set would lock every
    one of them out of nearly everything.
    """
    mask = int(mask or 0)
    if mask == 0:
        return True
    return bool(mask & int(bit or 0))


@dataclass(frozen=True)
class Member:
    """One character, as the family knows them.

    `rewarded` is character_queststatus_rewarded - turned in, experience
    banked. `held` is character_queststatus - in the log, not yet handed in.
    They are different questions and the ledger needs both: held-but-stuck is
    the Coldridge case, and only a rewarded quest satisfies a prerequisite.
    """

    name: str
    class_id: int
    race_id: int
    level: int
    rewarded: frozenset = frozenset()
    held: frozenset = frozenset()
    # Where this character can actually reach. Empty means "unknown", and
    # unknown never blocks anything - a guess is worse than silence here.
    zones: frozenset = frozenset()


@dataclass(frozen=True)
class Quest:
    """A quest_template row joined to its quest_template_addon row.

    Field names are deliberately snake_case copies of the verified DB columns,
    and from_row() below is the only place the column spellings appear, so a
    schema change lands in one spot.
    """

    id: int
    title: str = ""
    quest_level: int = 0
    min_level: int = 0
    max_level: int = 0
    allowable_classes: int = 0
    allowable_races: int = 0
    prev_quest_id: int = 0
    next_quest_id: int = 0
    exclusive_group: int = 0
    # quest_template.Flags. Carried because bit 0x8, QUEST_FLAGS_SHARABLE, is
    # the server's own answer to "may this quest be handed to a party member",
    # and Player::CanShareQuest refuses without it (core PlayerQuest.cpp:
    # 1517-1536). questshare.py asks that question; the column spelling lives
    # here with every other column spelling. 0 is the honest default for a
    # quest built without the column - see questshare.is_sharable, which says
    # out loud that it means "not sharable, as far as we know".
    flags: int = 0
    # Which zone this belongs to, as the bridge can determine it. 0 means
    # unknown; see Member.zones - unknown never blocks. This is what separates
    # Bork's Coldridge Valley set from work the family can really do, and it
    # is the ONE fact here that quest_template alone cannot answer, which is
    # why it arrives as an ordinary input rather than being inferred.
    zone: int = 0

    @classmethod
    def from_row(cls, row: dict) -> "Quest":
        """Build from a joined quest_template + quest_template_addon row.

        Column names verified live against the server, not remembered:
        quest_template carries ID/LogTitle/QuestLevel/MinLevel/AllowableRaces/
        Flags, quest_template_addon carries MaxLevel/AllowableClasses/
        PrevQuestID/NextQuestID/ExclusiveGroup.
        """
        return cls(
            id=int(row["ID"]),
            title=row.get("LogTitle") or "",
            quest_level=int(row.get("QuestLevel") or 0),
            min_level=int(row.get("MinLevel") or 0),
            max_level=int(row.get("MaxLevel") or 0),
            allowable_classes=int(row.get("AllowableClasses") or 0),
            allowable_races=int(row.get("AllowableRaces") or 0),
            prev_quest_id=int(row.get("PrevQuestID") or 0),
            next_quest_id=int(row.get("NextQuestID") or 0),
            exclusive_group=int(row.get("ExclusiveGroup") or 0),
            flags=int(row.get("Flags") or 0),
            zone=int(row.get("zone") or 0),
        )


@dataclass(frozen=True)
class Stall:
    """A quest somebody is carrying that they cannot finish."""

    quest_id: int
    title: str
    reason: str


def restricted_for(quest: Quest, members) -> tuple:
    """Which of THESE members a quest's masks actually shut out, by name.

    The point of the function. AllowableRaces=1101 is non-zero on every held
    row and excludes none of the five, so "has a race mask" and "is race
    locked" are different statements; only the second is worth reporting.
    """
    out = []
    for m in members:
        if not mask_allows(quest.allowable_classes, class_bit(m.class_id)):
            out.append(m.name)
        elif not mask_allows(quest.allowable_races, race_bit(m.race_id)):
            out.append(m.name)
    return tuple(sorted(out))


def _prev_satisfied(member: Member, quest: Quest, done) -> bool:
    """Is this quest's PrevQuestID accounted for?

    Positive PrevQuestID: AzerothCore requires that quest REWARDED. That is
    the case all 11 of the family's chained rows are in, and the case this is
    built around - Ugga's 35 (prev 40), Grog's 37 (prev 35).

    Negative PrevQuestID: AC's SatisfyQuestPrevQuest also accepts the prior
    quest merely being in the log for that form, so it is treated here as
    rewarded-OR-held. It does not occur in the family's current data, so it
    comes from the server's rule rather than from anything observed - said out
    loud rather than folded in silently.
    """
    prev = int(quest.prev_quest_id or 0)
    if prev == 0:
        return True
    if prev > 0:
        return prev in done
    return abs(prev) in done or abs(prev) in member.held


def _exclusive_blocks(member: Member, quest: Quest, catalog, done) -> bool:
    """Has a sibling in this quest's ExclusiveGroup already shut it out?

    DELIBERATELY ONE-SIDED, and this is the judgement call in the module.
    AC's Player::SatisfyQuestExclusiveGroup returns true immediately for any
    ExclusiveGroup <= 0 - only a POSITIVE group is a "pick one of these"
    lockout, and it fires when a sibling is already started or rewarded. A
    NEGATIVE group is not an availability check there at all; it is the
    "any one of these prior quests" form, which the server resolves inside the
    prev-quest logic. So a negative group is treated here as no blocker.

    Guessing the negative case would silently mark quests unreachable and drop
    them out of the behind() count, which is exactly the failure this module
    exists to prevent - so the limit is stated instead of assumed.
    """
    group = int(quest.exclusive_group or 0)
    if group <= 0:
        return False
    for other in (catalog or {}).values():
        if other.id == quest.id or int(other.exclusive_group or 0) != group:
            continue
        if other.id in done or other.id in member.held:
            return True
    return False


def blockers(member: Member, quest: Quest, *, catalog=None) -> tuple:
    """Every reason this member cannot take this quest right now, sorted.

    Plural on purpose: "Grog is too low AND has not done the prior quest" is a
    more useful sentence for the council than whichever reason happened to be
    checked first.
    """
    done = member.rewarded
    reasons = []
    if quest.id in done:
        reasons.append(DONE)
    if not mask_allows(quest.allowable_classes, class_bit(member.class_id)):
        reasons.append(CLASS)
    if not mask_allows(quest.allowable_races, race_bit(member.race_id)):
        reasons.append(RACE)
    if member.level < int(quest.min_level or 0):
        reasons.append(TOO_LOW)
    # MaxLevel 0 is "no cap", the same convention as the allowable masks.
    if quest.max_level and member.level > int(quest.max_level):
        reasons.append(TOO_HIGH)
    if not _prev_satisfied(member, quest, done):
        reasons.append(PREREQUISITE)
    if _exclusive_blocks(member, quest, catalog, done):
        reasons.append(EXCLUSIVE)
    if quest.zone and member.zones and quest.zone not in member.zones:
        reasons.append(ELSEWHERE)
    return tuple(sorted(reasons))


def eligible(member: Member, quest: Quest, *, catalog=None) -> bool:
    """Could this member pick this quest up and finish it today?"""
    return not blockers(member, quest, catalog=catalog)


def reachable(member: Member, quest: Quest, *, catalog=None) -> bool:
    """Could this member EVER do this quest - chain aside?

    eligible() answers "today"; this answers "at all". The difference is the
    prerequisite, and it matters because a chain quest is still a FAMILY
    quest: Grog can do 37 "Find the Lost Guards", he just has to do 35 first.
    Judging sharedness with eligible() would drop every chain quest out of the
    ledger the moment one member was a step behind on it - which is precisely
    the state the ledger is for.

    A quest whose prerequisite is itself out of reach stays out anyway: the
    catch-up walk never manages to schedule it, and unreachable() reports it.
    """
    ignored = {DONE, PREREQUISITE}
    return not (set(blockers(member, quest, catalog=catalog)) - ignored)


def participants(quest: Quest, members, *, catalog=None) -> tuple:
    """Names who can do this quest or already have, sorted.

    "Already have" counts: a quest four of them finished last week is still
    the family's quest, not one member's, and excluding the finishers would
    make every completed quest look personal.
    """
    return tuple(
        sorted(
            m.name
            for m in members
            if quest.id in m.rewarded or reachable(m, quest, catalog=catalog)
        )
    )


def shared_quests(members, catalog) -> tuple:
    """Quests every member can do or has done, by id.

    These are the family's quests - the ones where standing together actually
    pays, and the only ones anybody can meaningfully be behind on.
    """
    names = {m.name for m in members}
    return tuple(
        q
        for q in sorted(catalog.values(), key=lambda q: q.id)
        if set(participants(q, members, catalog=catalog)) == names
    )


def personal_quests(members, catalog) -> tuple:
    """(quest, owner) for quests exactly one member can ever touch, by id.

    1638 for Grug, 5624 for Ugga. Nobody catches up on these and nobody should
    be reported as behind on them; the family's role is to escort, not to
    participate.
    """
    out = []
    for q in sorted(catalog.values(), key=lambda q: q.id):
        who = participants(q, members, catalog=catalog)
        if len(who) == 1:
            out.append((q, who[0]))
    return tuple(out)


def behind(member: Member, members, catalog) -> tuple:
    """The shared quests this member has missed and can still do, by id.

    The honest catching-up metric, and every clause is load-bearing:
      - SHARED, so class-locked work never counts against four people;
      - somebody else already REWARDED it, so it is a real gap rather than
        work nobody in the family has got to yet;
      - still ELIGIBLE, so a stale or out-of-reach quest cannot smuggle
        itself in.
    """
    others = [m for m in members if m.name != member.name]
    out = []
    for q in shared_quests(members, catalog):
        if q.id in member.rewarded:
            continue
        if not any(q.id in o.rewarded for o in others):
            continue
        if not eligible(member, q, catalog=catalog):
            continue
        out.append(q)
    return tuple(out)


def _chain_reachable(member: Member, quest: Quest, catalog, seen=None) -> bool:
    """Is this quest reachable, and is everything it hangs off reachable too?

    An unknown prerequisite - one the catalog does not carry - counts as fine.
    Same rule as an unknown zone: this module reports what the facts support
    and stays quiet otherwise, because a false "drop it" costs a character
    real work.
    """
    seen = seen or set()
    if quest.id in seen:
        return True
    seen.add(quest.id)
    if not reachable(member, quest, catalog=catalog):
        return False
    prev = abs(int(quest.prev_quest_id or 0))
    if not prev or prev in member.rewarded:
        return True
    parent = (catalog or {}).get(prev)
    if parent is None:
        return True
    return _chain_reachable(member, parent, catalog, seen)


def unreachable(member: Member, catalog) -> tuple:
    """Stalls: quests in this member's log that cannot go anywhere.

    Bork's four Coldridge Valley rows land here with reason ELSEWHERE. They
    must never appear in behind(): the family's answer to a stall is "drop
    it", and its answer to being behind is "come and help". Mixing the two is
    how five characters end up walking to Dun Morogh.

    Merely being a step down a chain is NOT a stall. Grog holding 37 while 35
    is undone is a character with homework, not a character carrying rubbish,
    and telling him to abandon it would break the chain he is on.
    """
    out = []
    for quest_id in sorted(member.held):
        q = catalog.get(quest_id)
        if q is None:
            continue
        if _chain_reachable(member, q, catalog):
            continue
        reasons = [r for r in blockers(member, q, catalog=catalog) if r != DONE] or [
            PREREQUISITE
        ]
        out.append(Stall(quest_id=q.id, title=q.title, reason=reasons[0]))
    return tuple(out)


def _replaying(member: Member, done) -> Member:
    """The same member as if `done` were their rewarded set.

    Used to walk a chain forward without pretending anything about the real
    character; every other fact about them is carried through untouched.
    """
    return Member(
        name=member.name,
        class_id=member.class_id,
        race_id=member.race_id,
        level=member.level,
        rewarded=frozenset(done),
        held=member.held,
        zones=member.zones,
    )


def _missed_shared_ids(member: Member, members, catalog) -> set:
    """Shared quests somebody else has already been rewarded for and this
    member has not.

    The raw "you are behind on these" set, before any prerequisite of theirs
    is pulled in.
    """
    others = [m for m in members if m.name != member.name]
    return {
        q.id
        for q in shared_quests(members, catalog)
        if q.id not in member.rewarded and any(q.id in o.rewarded for o in others)
    }


def _with_prerequisites(wanted, member: Member, catalog) -> set:
    """`wanted` plus the prerequisites of everything in it, transitively.

    Nobody would call those "missed", but they are the steps that make the
    missed ones possible, so a plan without them is a plan that cannot be
    followed. A prerequisite already rewarded is skipped, which is also what
    stops the walk on a chain the member has partly done.
    """
    wanted = set(wanted)
    frontier = list(wanted)
    while frontier:
        q = catalog.get(frontier.pop())
        if q is None:
            continue
        prev = abs(int(q.prev_quest_id or 0))
        if prev and prev not in member.rewarded and prev not in wanted:
            wanted.add(prev)
            frontier.append(prev)
    return wanted


def _next_ready(member: Member, done, remaining, catalog):
    """The lowest quest id left in `remaining` with nothing blocking it, once
    `done` is taken as the member's rewarded set - or None if the walk is
    stuck and everything still left is genuinely out of reach.

    Lowest id rather than any available one, so the same family state always
    produces the same plan and the council does not reverse itself on
    identical facts.
    """
    replayed = _replaying(member, done)
    ready = [
        qid
        for qid in remaining
        if qid in catalog and not blockers(replayed, catalog[qid], catalog=catalog)
    ]
    return min(ready) if ready else None


def order_for(member: Member, wanted, catalog) -> tuple:
    """`wanted` quest ids for one member, IN AN ORDER THAT WORKS.

    The ordering walk, on its own, because two callers need it and a second
    copy of it would be a second, quieter answer to the same question.
    catch_up_plan() feeds it the shared quests this member has missed;
    questshare.plan() feeds it the quests somebody else is CARRYING that this
    member could be handed. The rule is identical in both cases and it is the
    module's whole contribution: pull in prerequisites, then hand out ids only
    once nothing blocks them, replaying each reward as it would land, so 35
    "Further Concerns" always comes out before 37 "Find the Lost Guards".

    Anything still blocked when the walk runs out is genuinely out of reach
    and is left out; unreachable() is where that gets reported instead.
    """
    remaining = _with_prerequisites(set(wanted), member, catalog)

    done = set(member.rewarded)
    plan = []
    while (qid := _next_ready(member, done, remaining, catalog)) is not None:
        plan.append(qid)
        remaining.discard(qid)
        done.add(qid)
    return tuple(catalog[qid] for qid in plan)


def catch_up_plan(member: Member, members, catalog) -> tuple:
    """The quests this member should do, IN AN ORDER THAT WORKS.

    behind() is only what they can take today. A chain hides the rest: Grog
    cannot be handed 37 "Find the Lost Guards" until 35 "Further Concerns" is
    done, so 37 is not "behind" - it is behind a door. order_for() walks the
    chain, replaying rewards as they would land, so 35 comes out before 37.
    """
    return order_for(member, _missed_shared_ids(member, members, catalog), catalog)


@dataclass(frozen=True)
class Ledger:
    """Everything the council needs, in one small object.

    Small and explicit on purpose: this goes to an LLM as grounded facts, so
    each field has to render as a sentence without any further arithmetic.
    """

    shared: tuple = ()
    personal: tuple = ()
    behind: dict = field(default_factory=dict)
    stalled: dict = field(default_factory=dict)
    plans: dict = field(default_factory=dict)
    rewarded_counts: dict = field(default_factory=dict)

    @property
    def furthest_behind(self) -> str:
        """Who needs the help most. Ties break on name so it is stable."""
        if not self.behind:
            return ""
        return sorted(self.behind, key=lambda n: (-len(self.behind[n]), n))[0]


def build(members, catalog) -> Ledger:
    """The whole ledger. One pass, so every field agrees with the others."""
    return Ledger(
        shared=shared_quests(members, catalog),
        personal=personal_quests(members, catalog),
        behind={m.name: behind(m, members, catalog) for m in members},
        stalled={m.name: unreachable(m, catalog) for m in members},
        plans={m.name: catch_up_plan(m, members, catalog) for m in members},
        rewarded_counts={m.name: len(m.rewarded) for m in members},
    )


def say(ledger: Ledger, name: str) -> str:
    """One plain sentence about one member, for the council to build on.

    Plain, like quests.say_remaining - the voice layer makes it sound like
    them, and writing it in character here would put the words in two places
    and let them drift.
    """
    missed = ledger.behind.get(name, ())
    stalls = ledger.stalled.get(name, ())
    parts = []
    if missed:
        first = ledger.plans.get(name) or missed
        parts.append(
            "%s is behind on %d quest%s the rest of us have done; next is %s."
            % (
                name,
                len(missed),
                "" if len(missed) == 1 else "s",
                first[0].title or "quest %d" % first[0].id,
            )
        )
    else:
        parts.append("%s is not behind on anything we can help with." % name)
    if stalls:
        parts.append(
            "%s should drop %d quest%s that cannot be finished from here: %s."
            % (
                name,
                len(stalls),
                "" if len(stalls) == 1 else "s",
                ", ".join(s.title or "quest %d" % s.quest_id for s in stalls),
            )
        )
    return " ".join(parts)


def aimable(held, beneficiary: str, leader: str) -> frozenset:
    """The quests an aim can actually drive on the beneficiary's behalf.

    THIS USED TO BE AN INTERSECTION WITH THE LEADER AND MUST NOT BE AGAIN.
    While only the party leader could be aimed, a quest the leader did not
    hold was undriveable however badly somebody needed it, so the candidate
    set was `held[leader] & held[beneficiary]`. mod-overseer now aims EVERY
    roster member that holds the quest (infra#2801), so the travellers ARE
    the holders and the leader has no special standing in this choice.

    Leaving the intersection in place after that change is what kept Ugga
    stuck. Measured live on 2026-08-24: she needed one more Large Candle for
    quest 60, she held it, Og and Grog held it, and Grug - the leader, and
    the only one of the five who did NOT hold it - emptied the intersection.
    `chosen=0` every hour for three hours, so nothing was ever persisted and
    the council re-staged the identical scene at 21:06, 22:06 and 23:07 while
    three of them were already carrying the quest.

    THE BENEFICIARY HALF IS STILL LOAD-BEARING, for the reason it always was:
    if she does not hold it, _observe_goal can never see progress and the
    goal sits active forever against a completion nobody can report.

    `leader` is still taken, and is still used - it is the fallback when the
    council named no beneficiary at all, where "whoever travels" is the only
    honest reading.
    """
    holdings = held or {}
    who = beneficiary or leader
    return frozenset(holdings.get(who, frozenset()))


def drive_target(
    ledger: Ledger, *, held_by_traveller, wanted: int = 0, beneficiary: str = ""
) -> int:
    """The ONE quest id the family should be aimed at, or 0.

    `held_by_traveller` MEANS "held by whoever will actually be aimed", which
    is no longer a single character. The family used to have exactly one
    traveller - the leader kept `new rpg` and the other four were on
    `nc +follow`, because handing an unaimed follower the wander strategy
    measured a 937-yard spread (goals.life_strategies). mod-overseer now aims
    every roster member HOLDING the chosen quest (infra#2801), so cohesion
    comes from the shared destination instead: "help Ugga" can finally mean
    sending the three of them who are carrying her quest.

    Callers should get this set from `aimable`, which owns the rule.

    THE HARD PRECONDITION, and why `held_by_traveller` is a required argument
    rather than a nicety. Upstream's NewRpgDoQuestAction reads
    `bot->GetQuestStatus(questId)` and dispatches only on INCOMPLETE or
    COMPLETE; anything else falls through to ChangeToIdle(). Aim the traveller
    at a quest it does not hold and it idles on the very next tick, having
    moved nowhere - the "delivered, and nothing happened" failure this epic
    keeps repeating. A quest the traveller does not hold is therefore not a
    candidate, however badly somebody needs it.

    The order of preference:

      1. `wanted` - the quest the council actually named - if the traveller
         holds it. The council already deliberated; second-guessing a decision
         the traveller can carry out would make the scene a decoration.
      2. The beneficiary's catch_up_plan, in ITS order. That order is the
         module's whole contribution: it is chain-correct (35 before 37), it
         is prerequisite-complete, and it is stable on identical facts. Taking
         the first entry the traveller holds is a filter on that plan, never a
         re-ranking of it.
      3. behind(), for the case where the plan is empty because the missed
         work has no chain to walk.

    Returns 0 for "nothing driveable", which is an honest answer and not a
    failure: it means the work the family should do is work that NOBODY who
    can be aimed is carrying, and the fix for that is quest sharing, not a
    different aim. It is a much rarer answer than it was - it used to fire
    whenever the leader alone happened not to hold the quest.
    """
    candidates = drive_candidates(
        ledger,
        held_by_traveller=held_by_traveller,
        wanted=wanted,
        beneficiary=beneficiary,
    )
    return candidates[0].id if candidates else 0


def drive_candidates(
    ledger: Ledger, *, held_by_traveller, wanted: int = 0, beneficiary: str = ""
) -> tuple:
    """Every quest `drive_target` could aim at, in its order of preference.

    `drive_target` is the first of these, always; the rest are the quests it
    passed over, each once. A second judge (Jev, #95) is shown exactly this
    list, so it can only ever be asked to choose among quests somebody who
    can be aimed is holding. A `wanted` quest the ledger does not describe is
    carried by id alone.
    """
    held = frozenset(int(q) for q in (held_by_traveller or ()))
    who = beneficiary or ledger.furthest_behind
    known = {}
    for quests in list(ledger.plans.values()) + list(ledger.behind.values()):
        for quest in quests:
            known.setdefault(quest.id, quest)
    out: dict = {}
    if wanted and int(wanted) in held:
        out[int(wanted)] = known.get(int(wanted), Quest(id=int(wanted)))
    if who:
        for quest in tuple(ledger.plans.get(who, ())) + tuple(
            ledger.behind.get(who, ())
        ):
            if quest.id in held:
                out.setdefault(quest.id, quest)
    return tuple(out.values())
