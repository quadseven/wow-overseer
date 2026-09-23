"""Which quest should be handed to whom, by whom, and in what order.

Pure module, the same seam as questbook.py and bonds.py: facts in, judgements
out. No pymysql, no network, nothing fetched in here. bridge.py builds the
questbook.Member and questbook.Quest records, calls plan(), and turns each
Grant into one overseer_command row; mod-overseer performs the act.

WHY THIS EXISTS. Five characters quest together and hold five different quest
logs, so the same fight pays two of them nothing:

    Og 17    Grug 13    Bork 13    Ugga 3    Grog 3

Grog and Ugga stand within three yards of the others and kill the same mobs.
They simply do not hold the quests those kills count towards. The operator's
requirement is that nobody in the family falls behind, and the only way five
people get paid for one kill is for all five to be carrying the quest.

WHY THE DECISION IS HERE AND THE ACT IS IN C++. The act has to be C++ because
the chat path is dead for these bots: mod-playerbots' `share quest` returns
early on `!GetMaster()` (ShareQuestAction.cpp:16) and in an all-bot party
`partyNeedsQuest` never becomes true, so nothing is ever pushed. The decision
has to be here because it is the half that can be wrong in ways that look like
working code, and this is the half that can be tested.

WHAT ORDER MEANS, AND WHY THIS DEFERS TO questbook. Nothing about eligibility
is re-derived here. questbook.blockers() already knows that AllowableClasses
is a bitmask while `characters.class` is an ID, that AllowableRaces=1101 is
the Alliance mask and restricts nobody in this family, that a positive
PrevQuestID needs the prior quest REWARDED rather than merely held, and that
Bork's Coldridge Valley rows are a continent away. questbook.order_for() does
the chain walk. This module answers only the two questions questbook does not:
who is CARRYING the quest right now (questbook is a ledger of who has finished
what), and whether the server will let it be handed over at all.

SHARABILITY IS A REAL GATE. Player::CanShareQuest (core PlayerQuest.cpp:
1517-1536) refuses any quest without QUEST_FLAGS_SHARABLE, so proposing one
would produce a command row the worldserver can only refuse. It is checked
here so the queue is not filled with doomed rows, and checked AGAIN in the
module because this side is working from a catalog and the module is working
from the live Player. A quest whose Flags column never reached us defaults to
0 - not sharable - and that fails CLOSED. That is the safe direction, but a
silently empty plan is exactly the failure this project keeps repeating, so
the refusal is reported as NOT_SHARABLE and counted in say(): if it turns out
the whole zone lacks the flag, one log line says so.

ONE PASS PROPOSES ONLY WHAT CAN LAND TODAY. A quest whose prerequisite is not
yet REWARDED cannot be added to anyone's log, however far down the chain they
are, so it is refused with questbook's PREREQUISITE rather than granted and
left to fail in the worldserver. It becomes a grant on a later pass, once the
prior quest is turned in. That is what "nobody is handed 37 before 35" means
in practice: not that they arrive in one batch in the right order, but that 37
is never proposed while 35 is undone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import questbook

# core src/server/game/Entities/Player/Player.h: MAX_QUEST_LOG_SIZE is 25.
# SatisfyQuestLog refuses beyond it, so proposing past it is proposing a
# refusal.
MAX_QUEST_LOG_SIZE = 25

# QuestDef.h QUEST_FLAGS_SHARABLE. The bit Player::CanShareQuest tests.
QUEST_FLAGS_SHARABLE = 0x8

# Refusal reasons this module adds. Everything else in a Refusal comes
# verbatim from questbook (CLASS, RACE, TOO_LOW, TOO_HIGH, PREREQUISITE,
# EXCLUSIVE, ELSEWHERE), so the two halves never describe the same family in
# two vocabularies.
NOT_SHARABLE = "not-sharable"
LOG_FULL = "log-full"
UNKNOWN = "unknown-quest"


def is_sharable(quest: questbook.Quest) -> bool:
    """Will the server let this quest be handed to a party member?

    Flags defaults to 0 on a Quest built without the column, and 0 means NO
    here - the opposite convention to the allowable masks, and deliberately
    so: this bit is a permission, not a restriction. Said out loud because a
    quiet False is how a whole feature does nothing.
    """
    return bool(int(quest.flags or 0) & QUEST_FLAGS_SHARABLE)


@dataclass(frozen=True)
class Grant:
    """One quest, moving from one family member's log into another's."""

    holder: str
    taker: str
    quest_id: int
    title: str = ""

    @property
    def command(self) -> str:
        """What mod-overseer parses out of overseer_command.command."""
        return "quest:%d" % int(self.quest_id)


@dataclass(frozen=True)
class Refusal:
    """A share that was considered and not proposed, and every reason why.

    PLURAL reasons, like questbook.blockers: "Grog is too low AND has not done
    the prior quest" is a more useful line than whichever check happened to
    run first, and an operator reading one reason would fix it and find the
    share still refused.
    """

    taker: str
    quest_id: int
    title: str = ""
    reasons: tuple = ()


@dataclass(frozen=True)
class Plan:
    """Everything the pass decided, both halves of it.

    Refusals are carried rather than dropped because "nothing to share" and
    "everything was refused" are different states with the same empty grant
    list, and this project's defining bug is the two being indistinguishable.
    """

    grants: tuple = ()
    refusals: tuple = ()


def holders(quest_id: int, members) -> tuple:
    """Names currently CARRYING this quest, sorted.

    Carrying, not finished: only a member with the quest in their log passes
    Player::CanShareQuest, which looks the id up in m_QuestStatus.
    """
    return tuple(sorted(m.name for m in members if int(quest_id) in m.held))


def donor(quest_id: int, members) -> str:
    """Which holder should be named as the one handing it over.

    Any of them would do - the family stands within three yards of itself and
    AddQuestAndCheckCompletion does not care which Player is passed as the
    quest giver. Lowest name wins so that identical facts produce an identical
    command row, and a plan recomputed every few minutes does not churn the
    queue with a different giver each time.
    """
    found = holders(quest_id, members)
    return found[0] if found else ""


def candidates(member: questbook.Member, members) -> tuple:
    """Quest ids somebody else is carrying that this member is not, sorted.

    Rewarded quests are excluded here rather than left to questbook's DONE
    blocker, so a quest the whole family finished last week never appears as a
    refusal on every pass forever.
    """
    mine = set(member.held) | set(member.rewarded)
    others = {
        qid for other in members if other.name != member.name for qid in other.held
    }
    return tuple(sorted(others - mine))


def _order(member: questbook.Member, ids, catalog) -> tuple:
    """`ids` in questbook's chain-correct order, with nothing added.

    order_for() pulls prerequisites into its walk so that the order it emits
    is followable; those extra ids are not candidates here (nobody is carrying
    them, or the member already has them) and are filtered back out. What is
    kept is questbook's ORDERING, which is the part worth reusing.
    """
    wanted = set(int(i) for i in ids)
    ordered = [
        q.id for q in questbook.order_for(member, wanted, catalog) if q.id in wanted
    ]
    # Anything the walk could not place - it should not happen once blockers
    # have already been checked, but a plan that silently loses a grant is
    # worse than one that appends it in id order.
    ordered += sorted(wanted - set(ordered))
    return tuple(ordered)


def _takers(members) -> list:
    """The family, the ones furthest behind first.

    Rewarded count is the same number the operator reads off the server (Og 17, Grog
    3), so the pass serves the characters he can see are behind before it
    serves the ones he can see are ahead. Ties break on name, so the order is
    stable on identical facts.
    """
    return sorted(members, key=lambda m: (len(m.rewarded), m.name))


def plan(members, catalog) -> Plan:
    """Every share worth making right now, and every one that was refused."""
    members = list(members)
    grants = []
    refusals = []

    for taker in _takers(members):
        grantable = []
        for quest_id in candidates(taker, members):
            quest = (catalog or {}).get(quest_id)
            if quest is None:
                refusals.append(
                    Refusal(taker=taker.name, quest_id=quest_id, reasons=(UNKNOWN,))
                )
                continue
            reasons = []
            if not is_sharable(quest):
                reasons.append(NOT_SHARABLE)
            # questbook's own verdict, unedited. DONE cannot occur - a
            # rewarded quest is not a candidate - so nothing is filtered out
            # of it here.
            reasons.extend(questbook.blockers(taker, quest, catalog=catalog))
            if reasons:
                refusals.append(
                    Refusal(
                        taker=taker.name,
                        quest_id=quest_id,
                        title=quest.title,
                        reasons=tuple(reasons),
                    )
                )
                continue
            grantable.append(quest_id)

        room = MAX_QUEST_LOG_SIZE - len(taker.held)
        ordered = _order(taker, grantable, catalog)
        for position, quest_id in enumerate(ordered):
            quest = catalog[quest_id]
            if position >= max(room, 0):
                refusals.append(
                    Refusal(
                        taker=taker.name,
                        quest_id=quest_id,
                        title=quest.title,
                        reasons=(LOG_FULL,),
                    )
                )
                continue
            grants.append(
                Grant(
                    holder=donor(quest_id, members),
                    taker=taker.name,
                    quest_id=quest_id,
                    title=quest.title,
                )
            )

    return Plan(grants=tuple(grants), refusals=tuple(refusals))


def say(result: Plan) -> str:
    """One line for the log, with BOTH counts and the reasons behind them.

    Deliberately never silent about an empty plan. "0 grant(s)" with a
    breakdown of what was refused is a diagnosis; an empty plan with no line
    at all is the shape of every bug this epic has chased.
    """
    tally: dict = {}
    for refusal in result.refusals:
        for reason in refusal.reasons:
            tally[reason] = tally.get(reason, 0) + 1
    detail = ", ".join("%s %d" % (r, n) for r, n in sorted(tally.items()))
    return "quest sharing: %d grant(s), %d refused%s" % (
        len(result.grants),
        len(result.refusals),
        (" (%s)" % detail) if detail else "",
    )


# The worldserver's share gates in the order DoShare tests them
# (mod_overseer.cpp), each named by the describe() literal it writes into
# overseer_command.result.reason. The ORDER is load-bearing: a refusal at
# one gate proves every gate before it passed at that moment, which is how
# a stale permanent refusal is told apart from a live one below. The tuple
# is pinned against the mod source by tests/test_questshare.py, so a gate
# added or moved in C++ fails a test here rather than silently proving the
# wrong thing. "delivered" passed all of them.
SHARE_GATES = (
    "malformed request",
    "no taker",
    "taker offline",
    "same character",
    "no such quest",
    "holder cannot share it (not held, or not flagged sharable)",
    "not in the same party",
    "not on the same map",
    "taker already turned it in",
    "taker already holds it",
    "taker cannot take it in its current state",
    "taker quest log is full",
    "taker is not eligible (level, race, class, prerequisite or exclusive group)",
    "no bag space for the quest starting item",
    "the quest did not land in the taker log",
)
_GATE_RANK = {reason: rank for rank, reason in enumerate(SHARE_GATES)}

# The gates waiting cannot change the answer of: the family regrouping,
# freeing a log slot or logging in makes none of these succeed. "holder
# cannot share it" is infra#2892's Bork row - a quest held at status 0 that
# the read now excludes - and the reason this exists at all: 167 hourly
# retries of a share that could never land. Every other gate is transient
# ("taker offline", "not in the same party", "not on the same map", a full
# log, "taker already holds it" - the next
# pass recomputes from live rows and simply stops proposing that one). A
# reason not in SHARE_GATES at all proves nothing and counts for nothing.
PERMANENT_REFUSALS = frozenset(
    {
        "holder cannot share it (not held, or not flagged sharable)",
        "no such quest",
        "malformed request",
        "same character",
        "taker already turned it in",
        # #170. Measured on wow-dev 2026-09-22: Bork -> Ugga quest:4861 was
        # refused for eligibility 21 times in a day, hourly, and three quest
        # 5082 shares 4 times each. Level, race, class, a prerequisite or an
        # exclusive group do not change in an hour; a level can in a day, and
        # the doubling (capped at a week) offers it again once it might.
        "taker is not eligible (level, race, class, prerequisite or exclusive group)",
    }
)


def history_depth(base_minutes: int, cap_hours: int) -> int:
    """How many of a triple's youngest answers, per outcome, backed_off()
    can ever need: the streak length at which the doubling reaches the cap.

    Past that length another refusal changes nothing, so a reader that keeps
    only this many youngest rows per (triple, status, reason) decides
    identically to one that reads the whole memory window - the property
    tests/test_questshare.py checks against random histories. It is what
    lets the bridge's five-minute read stay bounded by the number of triples
    rather than by ninety days of hourly transient retries (Codex's fifth
    round: an unbounded read that outgrows its ten-second timeout stops
    every share, not just the backed-off ones).
    """
    if base_minutes <= 0 or cap_hours <= 0:
        return 1
    n = 0
    while base_minutes * 60 * 2**n < cap_hours * 3600:
        n += 1
    return max(n, 1)


def backed_off(attempts, base_minutes: int, cap_hours: int) -> frozenset:
    """(holder, taker, command) triples still inside their backoff after
    the worldserver refused them for a PERMANENT reason.

    attempts: (holder, taker, command, status, result, age_seconds) rows
    for every share the worldserver has answered - status 'delivered' or
    'error' - with result the JSON it wrote (None for a row that never got
    one: the sweeper's timeouts are not refusals and count for nothing, and
    so does JSON we cannot read - giving up on the strength of a row we
    cannot parse would be the status-less read this issue started with)
    and age_seconds how long ago the worldserver answered (the row's last
    write, not its creation: a queued ask is not yet a refusal), as the
    database measures it, so no clock of ours is compared against theirs.

    A permanent refusal counts only while nothing younger has got PAST its
    gate. A delivery got past every gate, so it resets the whole streak: it
    proves whatever was permanent about the refusals before it has changed
    (the holder re-picked the quest, the read was corrected) and a later
    need for the same share starts from a clean slate rather than inheriting
    up to a week of wait from a solved problem - Codex's third finding on
    this change. A later refusal at a LATER gate resets it too - Codex's
    fifth: "holder cannot share it" five times, then the holder re-picks the
    quest and the next attempt is refused for "not on the same map". That
    refusal came from a gate the worldserver only reaches after
    CanShareQuest passed, so the holder problem is over, and when the party
    regroups the share is offered within the hour instead of a week. A
    refusal at an EARLIER gate ("taker offline" is tested before the holder
    is) proves nothing about the gates after it and resets nothing.

    The quiet time after the n-th permanent refusal in the streak is
    base_minutes * 2**n, capped at cap_hours: 2h, 4h, 8h, 16h, 32h, 64h,
    128h, then a week for as long as the refusals keep coming. A
    rolling-window threshold was the first shape here and Codex showed it
    does not stop anything: once the window is full, every row that ages
    out admits a fresh hourly retry, so the loop merely pauses and resumes.
    Doubling never resumes - the gaps only grow - and it never gives up for
    good either, so a share the world later allows is offered again within
    the cap with nobody resetting anything.

    Transient refusals never accumulate here. A taker who was offline five
    times is offered the quest again the moment they are back, which the
    first draft of this got wrong by counting every error row alike.
    """
    answers: dict = {}
    for holder, taker, command, status, result, age_s in attempts:
        key = (holder, taker, command)
        if status == "delivered":
            answers.setdefault(key, []).append((age_s, len(SHARE_GATES), False))
            continue
        if status != "error" or not result:
            continue
        try:
            reason = json.loads(result).get("reason")
        except (ValueError, AttributeError):
            continue
        if reason not in _GATE_RANK:
            continue
        answers.setdefault(key, []).append(
            (age_s, _GATE_RANK[reason], reason in PERMANENT_REFUSALS)
        )
    held = set()
    for key, rows in answers.items():
        n, youngest, furthest = 0, None, -1
        for age_s, rank, permanent in sorted(rows):
            if permanent and rank >= furthest:
                n += 1
                youngest = age_s if youngest is None else youngest
            furthest = max(furthest, rank)
        if n == 0:
            continue
        quiet_s = min(cap_hours * 3600, base_minutes * 60 * 2 ** min(n, 30))
        if youngest < quiet_s:
            held.add(key)
    return frozenset(held)
