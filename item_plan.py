"""Is a decision an earlier poll made about an item still true? (infra#3330)

MEASURED ON THE DEV REALM, 2026-09-05, over twenty-four hours of vendor sales:
2865 rows carrying only 409 distinct (character, item) requests, 822 of them
refused `item not carried`. 819 of those 822 were written AFTER that exact
item had already been sold. The executor was right every time; the planner
kept re-issuing decisions the world had already answered.

WHY A FRESH READ IS NOT ENOUGH, which is the reason this module exists. The
vendor pass does read live holdings before it plans. But `character_inventory`
and `item_instance` are the world's SAVE FILE, not its memory: a sale leaves
the bags immediately and reaches MySQL only on the next player save, so a poll
five minutes later can legitimately still see the sold item. Reading harder
does not fix that. The one record never behind is the one the executor itself
wrote, so the finished `overseer_command` row, and not the inventory table,
decides whether a plan may be re-issued.

WHAT THE WORLD ALREADY TELLS US, and what nobody was reading. Every refusal
carries its own retry classification from `SellRefusalRetry`
(overseer_decisions.cpp), in the result payload:

    {"reason":"count exceeds stack","retry":"never",
     "request":"guid:1501282 count:6","item":{"count":6,"stack":3}}

`retry` is authoritative about whether the SAME row could ever work. It is
honoured first; the literal lists below are the fallback for rows written by
an older world image, because the C++ and the Python ship as separate images
and both directions of a split deploy have to keep working (infra#2819).

TWO SCOPES, because they are different facts. `item not carried` says the ITEM
is gone and no request brings it back. `count exceeds stack` says only that
this COUNT was wrong, and the world hands back the true stack beside it, so
the answer is a corrected request rather than a permanent refusal. Collapsing
them would either leak a retry storm or strand every partly-sold stack.

FAIL OPEN, DELIBERATELY, and it is the opposite choice to disposition.py. An
attempt this cannot parse is not treated as terminal: getting that wrong
re-queues one row, while getting it wrong the other way silently stops selling
an item forever. Safety about WHAT may be sold belongs to bag_pressure and
disposition, and is settled before anything reaches here.

GENERAL ON PURPOSE. Nothing here knows what a sale is. It wants candidates
carrying `holder`, `item_guid` and `count`, and attempts carrying what the
world answered, which is the shape the bank pass (infra#3329) writes too: its
executor refuses with `item not carried` and `item not in bank` from the same
classifier.

PURE MODULE: no MySQL, no core, no clock.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from dataclasses import dataclass, field

# The world's own words for whether a row could ever work (SellRetryWord).
RETRY_NEVER = "never"

# "This row can work, but not from where the character is standing."
# mod-overseer#230 classifies `vendor not in range` and `vendor refuses item`
# as ELSEWHERE and carries the word out in `result` precisely so that the side
# which DECIDES re-queues a fresh row, rather than the executor re-attempting
# the same one: twenty rows that kept their place at the head of the queue
# livelocked the drain for half an hour, which is why that change was made.
#
# NOTHING ON THIS SIDE READ IT (infra#3464). `terminal_scope` honoured only
# `never`, so an ELSEWHERE refusal was indistinguishable from `later` and the
# same row was proposed again on the next cycle, from the same spot, for ever.
# Measured over three hours on the live realm: 1,950 sell rows answered, 1,860
# of them `vendor not in range`, and 10 sales.
RETRY_ELSEWHERE = "elsewhere"

# How many ELSEWHERE refusals before this stops offering an item and says so.
#
# The caller's own gate is the first line and the bigger one: the vendor pass
# now writes nothing unless a vendor is within reach of the seller. This is
# what catches the case that gate cannot see - a vendor IS standing there and
# will not deal. `GetNPCIfCanInteractWith` refuses an unfriendly vendor with
# the same "vendor not in range" it gives an absent one, so distance and
# hostility are indistinguishable from this side, and only the repetition
# tells them apart. On this realm that is not hypothetical: the innkeeper
# nearest the family's instance is the other faction's and was correctly
# refusing them.
#
# THREE, and it is a judgement rather than a measurement. Two is a plausible
# pair of near misses while a bot drifts in and out of five yards, and the
# cost of being wrong is one item held for the rest of the memory window
# rather than an item lost. The same shape as materials.GIVE_UP_AFTER.
ELSEWHERE_GIVE_UP = 3

# How far a terminal refusal reaches.
ITEM = "item"  # the item is gone or unsellable: never ask for it again
REQUEST = "request"  # this exact guid+count is wrong; a corrected one may work

# The `SellRefusalRetry` NEVER literals, split by scope. Only consulted when a
# row carries no `retry` word of its own. `item not in bank` is the bank pass's
# sibling refusal (mod_overseer.cpp DoBank) and costs nothing to honour now.
TERMINAL_ITEM = frozenset(
    {
        "item not carried",
        "item is a quest item",
        "item cannot be sold",
        "item not in bank",
    }
)
TERMINAL_REQUEST = frozenset(
    {
        "count exceeds stack",
        "malformed sell: want guid:<item_instance.guid>[ count:<n>]",
    }
)

# A row the world finished successfully. The item left the bags, so it is as
# gone as one the world says is not carried.
SUCCESS_STATUSES = frozenset({"delivered", "applied"})
# A row nobody has answered yet. Queueing a second one is the duplicate.
OPEN_STATUSES = frozenset({"pending", "claimed", "verifying"})

_REQUEST_RE = re.compile(r"guid:(\d+)(?:\s+count:(\d+))?")


@dataclass(frozen=True)
class Attempt:
    """One finished or in-flight command, as the world answered it."""

    holder: str
    item_guid: int
    status: str = ""
    detail: str = ""
    retry: str = ""  # the world's own verdict, when it wrote one
    count: int = 0  # the count that was asked for
    stack: int | None = None  # the true stack the world reported, if it did
    remaining: int | None = None  # what a sale left in the stack, if reported


@dataclass(frozen=True)
class Plan:
    """What may be written now, and what was dropped and why."""

    write: tuple = ()
    skipped: dict = field(default_factory=dict)


def parse_request(command) -> tuple | None:
    """Pull (guid, count) out of a `guid:N count:M` command string."""
    match = _REQUEST_RE.search(str(command or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def attempt_from_row(row) -> Attempt | None:
    """One `overseer_command` row as an Attempt, or None if it says nothing.

    The adapter hands rows over exactly as MySQL returned them; every field
    that might be absent on a legacy row is read defensively, because a row
    this cannot read must not be able to stop the pass.
    """
    try:
        request = parse_request(row.get("command"))
    except (AttributeError, TypeError, ValueError):
        return None
    if not request:
        return None
    guid, count = request
    if guid <= 0:
        return None
    retry, stack, remaining = "", None, None
    raw = row.get("result") or ""
    if raw:
        try:
            payload = json.loads(raw)
            retry = str(payload.get("retry") or "")
            item = payload.get("item") or {}
            if "stack" in item:
                stack = int(item["stack"])
            if payload.get("remaining") is not None:
                remaining = int(payload["remaining"])
        except (TypeError, ValueError, AttributeError):
            # A garbled payload costs us the world's verdict, not the row:
            # the detail literals still classify it.
            retry, stack, remaining = "", None, None
    return Attempt(
        holder=str(row.get("target_name") or ""),
        item_guid=guid,
        status=str(row.get("status") or ""),
        detail=str(row.get("detail") or ""),
        retry=retry,
        count=count,
        stack=stack,
        remaining=remaining,
    )


def left_a_remainder(attempt) -> bool:
    """True for a delivered sale the world says left part of the stack behind.

    A PARTIAL SALE DOES NOT REMOVE THE ITEM. The sold row names the stack by
    guid and carries `remaining`; a stack that kept 9 of 16 is the same guid
    afterwards and grows again as more of it is looted. Reading the delivery as
    "the item left the bags" held that guid back for the whole memory window,
    so a member at the bag floor could not sell the stack that would make room.
    """
    return (
        attempt.status in SUCCESS_STATUSES
        and attempt.remaining is not None
        and attempt.remaining > 0
    )


def terminal_scope(attempt) -> str:
    """How far this attempt's answer reaches: ITEM, REQUEST, or not at all."""
    if left_a_remainder(attempt):
        # Only that request is answered; the rest of the stack may be asked for.
        return REQUEST
    if attempt.status in SUCCESS_STATUSES:
        return ITEM
    if attempt.detail in TERMINAL_ITEM:
        return ITEM
    if attempt.detail in TERMINAL_REQUEST:
        return REQUEST
    if attempt.retry == RETRY_NEVER:
        # The world says never but this side does not know the literal, so
        # take the narrower scope: a corrected request stays possible, and a
        # refusal literal added later cannot strand an item permanently.
        return REQUEST
    return ""


def settled(attempts) -> tuple:
    """The (holder, item) and (holder, item, count) keys already answered."""
    items, requests = {}, {}
    for attempt in attempts:
        scope = terminal_scope(attempt)
        if not scope:
            continue
        reason = attempt.detail or attempt.status or "already done"
        if scope == ITEM:
            items.setdefault((attempt.holder, attempt.item_guid), reason)
        else:
            requests.setdefault(
                (attempt.holder, attempt.item_guid, attempt.count), reason
            )
    return items, requests


def refused_here(attempts, give_up=ELSEWHERE_GIVE_UP, at_vendor=False) -> dict:
    """(holder, item) -> reason, for items the world keeps refusing on PLACE.

    An ELSEWHERE refusal is not terminal, and must not be treated as one: the
    row would work somewhere else, and the honest answer to it is to move
    rather than to give up. But nothing on this side can make anybody move,
    and answering it by asking again from the same spot is the retry storm
    this module exists to prevent in its other form. So repetition settles it:
    asked `give_up` times, refused `give_up` times, hold it and say why.

    Keyed on the ITEM and never on the request, because where a character is
    standing is a fact about the character and not about the count.

    THE HOLD ENDS WHEN THE PLACE CHANGES, NOT ONLY WHEN THE WINDOW DOES
    (#149). It used to expire only with the caller's memory window, which is
    24 hours, and the docstring promised that reaching a vendor would clear
    it. It did not: measured on the dev realm 2026-09-22, the leader was
    logged reaching a vendor 27 times in two hours while all eight of his
    sales stayed held on three `vendor not in range` refusals from the
    evening before. Two facts now end it:

      * `at_vendor`, the caller's own reading that a vendor is within reach
        of this holder right now. A range refusal is about where the holder
        stood; standing somewhere else is exactly what makes it stale.
      * a DELIVERED sale by the same holder after the refusals. The world
        dealt with that holder since, so the refusals no longer describe
        where it stands. `attempts` are read in the order the world wrote
        them (the caller sorts by row id), which is what "after" means here.

    A refusal for any other reason is not an ELSEWHERE refusal and never
    reaches this function's tally, so it still holds for the full window.
    """
    if at_vendor:
        return {}
    tally: dict = {}
    for attempt in attempts:
        if attempt.status in SUCCESS_STATUSES:
            # The holder was served since; its older range refusals no
            # longer say anything about where it stands.
            for key in [k for k in tally if k[0] == attempt.holder]:
                del tally[key]
            continue
        if attempt.retry != RETRY_ELSEWHERE:
            continue
        key = (attempt.holder, attempt.item_guid)
        tally[key] = tally.get(key, 0) + 1
    least = max(1, int(give_up))
    return {
        key: "refused %d times for want of a reachable vendor" % count
        for key, count in tally.items()
        if count >= least
    }


# A MEMBER JUST REFUSED `vendor not in range` IS LEFT ALONE FOR A WHILE
# (wow-overseer#1962). The bridge's counter read can say "in reach" while the
# core's own interaction check says otherwise, and a refused member was then
# written a fresh pass of rows every cycle. One refusal must not become a
# retry storm: no sell row is written for the member until it has moved more
# than RANGE_BACKOFF_MOVED_YARDS from where the refused rows were written, or
# RANGE_BACKOFF_SECONDS have gone by. A judgement (ten minutes, five yards),
# not a measurement; a sale served after the refusal ends it at once.
RANGE_BACKOFF_SECONDS = 600
RANGE_BACKOFF_MOVED_YARDS = 5.0
RANGE_REFUSAL_DETAIL = "vendor not in range"


def _moved_yards(then, now) -> float | None:
    """Yards between two (map, x, y, z) readings, None when not comparable.

    A different map is returned as infinity: it is certainly not the same spot.
    """
    if not then or not now:
        return None
    if then[0] != now[0]:
        return math.inf
    try:
        return math.dist([float(v) for v in then[1:4]], [float(v) for v in now[1:4]])
    except (TypeError, ValueError):
        return None


def range_backoff(
    refused_age,
    served_age,
    then,
    now,
    hold_seconds=RANGE_BACKOFF_SECONDS,
    moved_yards=RANGE_BACKOFF_MOVED_YARDS,
) -> str:
    """Why a member's sell rows wait after a range refusal, or "" if they may go.

    `refused_age` and `served_age` are seconds since the member's latest
    `vendor not in range` answer and latest served sale (None for neither).
    `then` is where the refused rows were written (None after a bridge
    restart) and `now` where the member stands. Unknown positions fall back to
    the clock alone, which is the cautious direction: a hold, then a retry.
    """
    if refused_age is None or refused_age >= hold_seconds:
        return ""
    if served_age is not None and served_age <= refused_age:
        return ""
    moved = _moved_yards(then, now)
    if moved is not None and moved > moved_yards:
        return ""
    return "refused %r %ds ago and has not moved (%s), so no row for %ds more" % (
        RANGE_REFUSAL_DETAIL,
        refused_age,
        "position unknown" if moved is None else "%.1f yards" % moved,
        max(0, hold_seconds - int(refused_age)),
    )


def sale_reading(holder, position, offsets, refused_age) -> str:
    """One line for the sale pass: where the seller stands and the nearest counter.

    `offsets` is the nearest vendor's (dx, dy, dz) from the seller. It names the
    straight-line distance beside the per-axis box the bridge gates on, so the
    next burst shows whether that box is wider than the core's 5 yards.
    """
    where = (
        "map=%s at %.1f,%.1f,%.1f"
        % (position[0], float(position[1]), float(position[2]), float(position[3]))
        if position
        else "position unknown"
    )
    if offsets:
        dx, dy, dz = (abs(float(v)) for v in offsets)
        counter = "nearest vendor euclid=%.1f 2d=%.1f per-axis=%.1f/%.1f/%.1f" % (
            math.sqrt(dx * dx + dy * dy + dz * dz),
            math.hypot(dx, dy),
            dx,
            dy,
            dz,
        )
    else:
        counter = "no counter read"
    answer = (
        "refused %ds ago" % refused_age
        if refused_age is not None
        else "no refusal on record"
    )
    return "%s %s, %s, last range answer: %s" % (holder, where, counter, answer)


def open_requests(attempts) -> set:
    """Keys with a row nobody has answered yet, which must not be doubled."""
    return {(a.holder, a.item_guid) for a in attempts if a.status in OPEN_STATUSES}


def true_stacks(attempts) -> dict:
    """The real stack size the world last reported, per (holder, item)."""
    stacks = {}
    for attempt in attempts:
        if left_a_remainder(attempt):
            # The stack the sale read is the size BEFORE it; the stack has
            # since shrunk and grown, so it is no measure of what is carried.
            continue
        if attempt.stack is not None and attempt.stack >= 0:
            stacks[(attempt.holder, attempt.item_guid)] = int(attempt.stack)
    return stacks


def reasons(skipped) -> str:
    """The skipped tally as one readable clause for the pass log.

    Emitted every cycle, including when it is empty, for the same reason the
    event pass logs its quiet cycles: a pass that has silently stopped
    proposing anything must not look identical to a pass with nothing to do.
    """
    if not skipped:
        return "nothing"
    return ", ".join(
        "%d %s" % (count, reason)
        for reason, count in sorted(skipped.items(), key=lambda kv: (-kv[1], kv[0]))
    )


def plan(candidates, attempts, at_vendor=False) -> Plan:
    """Keep only the candidates the world has not already answered.

    `at_vendor` is whether a vendor is within reach of these candidates'
    holder right now; see `refused_here` for why it ends a range hold.

    Candidates keep their order and their type: a corrected count comes back
    as the same frozen dataclass with a new `count`, so the caller's insert
    path does not have to know this module exists beyond the one call.
    """
    attempts = tuple(attempts)
    done_items, done_requests = settled(attempts)
    stuck_here = refused_here(attempts, at_vendor=at_vendor)
    already_open = open_requests(attempts)
    stacks = true_stacks(attempts)
    write, skipped, seen = [], {}, set()

    def drop(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for candidate in candidates:
        key = (candidate.holder, candidate.item_guid)
        if key in done_items:
            drop(done_items[key])
            continue
        if key in already_open:
            drop("already queued")
            continue
        if key in stuck_here:
            drop(stuck_here[key])
            continue
        if key in seen:
            # Two rows for one stack in a single pass is the duplicate this
            # side controls completely, so it is dropped without asking the
            # world about it.
            drop("duplicate in this pass")
            continue
        count = int(candidate.count)
        stack = stacks.get(key)
        if stack is not None and count > stack:
            # The world measured the stack while refusing; believe it over an
            # inventory table that had not caught up yet.
            count = stack
        if count <= 0:
            drop("nothing left in the stack")
            continue
        request_key = (candidate.holder, candidate.item_guid, count)
        if request_key in done_requests:
            drop(done_requests[request_key])
            continue
        seen.add(key)
        write.append(
            candidate
            if count == candidate.count
            else dataclasses.replace(candidate, count=count)
        )
    return Plan(write=tuple(write), skipped=skipped)


def all_answered(candidates, attempts) -> bool:
    """True when the world has already answered every one of these candidates.

    Asked as if the holder stood at a vendor, so a range refusal does not
    count as an answer, and an open row does not either: a queued sale still
    needs its holder at a counter. What is left is a stack already sold or
    refused for good, which no vendor visit can change (#1261).
    """
    candidates = tuple(candidates)
    if not candidates:
        return False
    answer = plan(candidates, attempts, at_vendor=True)
    return not answer.write and "already queued" not in answer.skipped
