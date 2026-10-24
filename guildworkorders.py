"""Guild work orders: requests, assignments, cooldowns.

Pure module: state in, a plan and sentences out. No MySQL, no clock.

THE ONE-DIRECTION GUILD. `guildshare.py` pushes the family's surplus outward.
This module is the other half: the guild ASKS. A consumable request ("the raid
needs 96 Greater Fire Protection Potion"), a farming assignment ("somebody go
get Firebloom in Searing Gorge"), and a profession cooldown (Mooncloth,
Arcanite) each start as a request, get assigned to somebody who can do it, are
tracked until complete, and then say so out loud. Nothing here grants or
teleports: every decision is a row the bridge can write and a sentence a person
can read.

REQUEST, ASSIGN, TRACK, COMPLETE. An order is requested when the guild names a
need, assigned when the plan names a taker, tracked while the taker still has
it, and complete when the world says the item or the cooldown is in hand. The
bridge persists each transition; this module only decides the next one from
what it is shown.

THREE KINDS, ONE WORKFLOW EACH.

  consumable   "need 96 GFPP for raid night" - a count of an item the raid
               consumes, assigned to whoever holds the craft that makes it.
  farming      "farm firebloom in Searing Gorge" - a zone and an item, assigned
               to a gatherer who holds the gathering trade for it.
  cooldown     "Mooncloth is up" / "Arcanite is ready" - a profession's shared
               cooldown, assigned to whoever holds the trade and is online.

A MEMBER CAN ONLY DO WHAT IT HOLDS. A consumable goes to a crafter of the
matching trade, a farming assignment to a gatherer of the matching trade, and a
cooldown to the trade's holder. When nobody online holds what is needed, the
order stays requested and the plan says so - "nobody can do this" is a real
finding and it is named rather than dropped.

ONLINE ONLY, AND SAID SO. An offline taker is the same as no taker: a row
written for a ghost is a row that waits forever. The plan only assigns to
members the world says are in it, and says why each order has no taker.

NOTHING IS INVENTED. An item no craft names, a trade nobody holds, a zone no
gathering trade covers - each is a gap the page names, never an assumption the
plan acts on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import goals

# ---------------------------------------------------------------------------
# THE KINDS AND STATUSES.

CONSUMABLE = "consumable"
FARMING = "farming"
COOLDOWN = "cooldown"
KINDS = (CONSUMABLE, FARMING, COOLDOWN)

REQUESTED = "requested"
ASSIGNED = "assigned"
IN_PROGRESS = "in_progress"
COMPLETE = "complete"
REFUSED = "refused"
STATUSES = (REQUESTED, ASSIGNED, IN_PROGRESS, COMPLETE, REFUSED)

# Which craft makes each consumable the guild might request. Deliberately
# small: an item not in the map matches no craft and is refused rather than
# guessed at. The ticket's own example, 96 Greater Fire Protection Potion, is
# alchemy.
CONSUMABLE_CRAFTS: dict[str, str] = {
    "Greater Fire Protection Potion": "alchemy",
    "Fire Protection Potion": "alchemy",
}

# Which gathering trade brings each farmed item. The ticket's example,
# Firebloom in Searing Gorge, is herbalism.
FARMING_TRADES: dict[str, str] = {
    "Firebloom": "herbalism",
}

# Which profession holds each shared cooldown. Mooncloth is tailoring, Arcanite
# is enchanting - the ticket's two examples.
COOLDOWN_PROFESSIONS: dict[str, str] = {
    "Mooncloth": "tailoring",
    "Arcanite": "enchanting",
}

# ---------------------------------------------------------------------------
# THE FACTS.


@dataclass(frozen=True)
class Member:
    """One guild member, as the world currently describes them.

    `online` is a measured fact with no default: an offline taker is the same
    as no taker, and presence cannot be inferred from having a name (the same
    rule guildshare.Member keeps).

    `skills` is {skill line id: current value} from `character_skills`.
    """

    name: str
    guild: str
    level: int = 0
    online: bool = False
    skills: Mapping[int, int] = None

    def rank_in(self, skill_id: int) -> int:
        """Current value in one skill line, 0 for a line they do not hold."""
        return int((self.skills or {}).get(int(skill_id), 0) or 0)

    def holds(self, profession: str) -> bool:
        """Whether this member holds this profession at any rank."""
        skill_id = goals.SKILL_IDS.get(profession)
        if skill_id is None:
            return False
        return self.rank_in(skill_id) > 0


@dataclass(frozen=True)
class WorkOrder:
    """One order the guild has placed, at whatever stage it has reached.

    `kind` is consumable, farming or cooldown. `status` moves requested ->
    assigned -> in_progress -> complete, or requested -> refused when nobody
    can take it. `assigned_to` names the taker once the plan assigns one, and
    is empty until then.
    """

    kind: str
    item: str
    quantity: int = 0
    zone: str = ""
    requested_by: str = ""
    status: str = REQUESTED
    assigned_to: str = ""

    def is_open(self) -> bool:
        """Whether this order still wants a taker or is still being worked."""
        return self.status in (REQUESTED, ASSIGNED, IN_PROGRESS)


@dataclass(frozen=True)
class Assignment:
    """One order placed with one taker, and why that taker was chosen."""

    order: WorkOrder
    taker: str
    why: str

    @property
    def said(self) -> str:
        """What the taker says out loud when the order lands with them."""
        if self.order.kind == CONSUMABLE:
            return "%s: the guild needs %d %s" % (
                self.taker,
                self.order.quantity,
                self.order.item,
            )
        if self.order.kind == FARMING:
            return "%s: the guild wants %s from %s" % (
                self.taker,
                self.order.item,
                self.order.zone,
            )
        if self.order.kind == COOLDOWN:
            return "%s: the %s cooldown is mine to spend" % (
                self.taker,
                self.order.item,
            )
        return "%s: %s" % (self.taker, self.why)


@dataclass(frozen=True)
class WorkOrderPlan:
    """What this pass decided, including everything it decided against.

    `assignments` is one Assignment per order the plan placed with a taker.
    `notes` is one line per order the plan could not place, saying why - an
    empty plan that goes quiet is indistinguishable from a broken one.
    `taken` is the names that received an assignment, one each, so a caller can
    budget one order per member per cycle.
    """

    assignments: tuple = ()
    notes: tuple = ()
    taken: tuple = ()


# ---------------------------------------------------------------------------
# WHO CAN TAKE WHAT.


def _profession_for(kind: str, order: WorkOrder) -> str:
    """The profession this order needs, or '' when nothing names it.

    UNKNOWN IS A REFUSAL, not an invitation to guess. An item this map does not
    name matches no craft, a zone this map does not cover matches no gathering
    trade, and a cooldown this map does not name matches no profession. Each
    is a real gap the page should say out loud.
    """
    if kind == CONSUMABLE:
        return CONSUMABLE_CRAFTS.get(order.item, "")
    if kind == FARMING:
        return FARMING_TRADES.get(order.item, "")
    if kind == COOLDOWN:
        return COOLDOWN_PROFESSIONS.get(order.item, "")
    return ""


def can_take(member: Member, order: WorkOrder) -> str:
    """Why this member could take this order, or '' if they could not.

    A sentence or nothing: the caller gets the taker's own reason, which goes
    into what they say out loud, never a bare True a log line would have to
    justify. Offline members match nothing, and so does a member who holds no
    rank in the profession the order names.
    """
    if not member.online:
        return ""
    profession = _profession_for(order.kind, order)
    if not profession:
        return ""
    if not member.holds(profession):
        return ""
    return "%s holds %s" % (member.name, profession)


# ---------------------------------------------------------------------------
# THE PASS.


def _best_taker(order: WorkOrder, members, taken: Mapping) -> tuple:
    """Which online guild member takes this order, and their reason.

    ONE ORDER PER MEMBER PER CYCLE, budgeted across the whole plan: a member
    measured able to take three orders would get three rows that each wait on
    the same bags, so one each is the version this module can defend without a
    read it does not have.

    LOWEST LEVEL FIRST AMONG THOSE WHO QUALIFY. The need is the guild's, the
    members are levelling, and Firebloom is worth more to the one still
    grinding Herbalism than to the one already at 300. Ties break on name so
    the plan is deterministic.
    """
    best = None
    for member in sorted(members, key=lambda m: (int(m.level), m.name)):
        if str(member.name) in taken:
            continue
        why = can_take(member, order)
        if why:
            best = (member, why)
            break
    return best or (None, "")


def _no_taker_note(order: WorkOrder) -> str:
    """Why this order has no taker, said rather than dropped."""
    profession = _profession_for(order.kind, order)
    if not profession:
        return "%s names no craft or trade this guild knows: %s" % (
            order.kind,
            order.item,
        )
    return "nobody online holds %s, so %s stays unassigned" % (
        profession,
        order.item,
    )


def _would_take(order: WorkOrder, members) -> bool:
    """Whether any online member holds what this order needs.

    Ignores the one-order-per-member budget: a member who could take the order
    but already has one is still a holder, and the note says so.
    """
    return any(can_take(member, order) for member in members or ())


def _taken_note(order: WorkOrder) -> str:
    """Why an order with a qualified holder is not placed this cycle."""
    return "the only member who can take %s is already taken this cycle" % (order.item,)


def plan(orders, members, recent=()) -> WorkOrderPlan:
    """Every open order that should have a taker, in one pass.

    `orders` are the work orders the bridge read, oldest first. `members` are
    the guild members the world says are in it, with their skills. `recent`
    holds recently judged rows and is reserved for a later pass that refuses a
    taker still on a profession cooldown; this release does not read it.

    THE ORDER OF THE GATES. What kind of order is this (is there a craft or
    trade that names it), is there somebody online who holds it, and has that
    somebody already taken an order this cycle. Each gate is cheaper than the
    next, and an order that fails any gate stays requested with a note saying
    why - the finding is never silent.

    COMPLETE AND REFUSED ORDERS ARE SKIPPED. A finished order needs no taker,
    and a refused one has already been judged impossible.
    """
    roster = list(members or ())
    taken: dict = {}
    assignments = []
    notes = []

    for order in orders or ():
        if not order.is_open():
            continue
        taker, why = _best_taker(order, roster, taken)
        if taker is None:
            if _would_take(order, roster):
                note = _taken_note(order)
            else:
                note = _no_taker_note(order)
            if note not in notes:
                notes.append(note)
            continue
        taken[str(taker.name)] = True
        assignments.append(Assignment(order=order, taker=taker.name, why=why))

    return WorkOrderPlan(
        assignments=tuple(assignments), notes=tuple(notes), taken=tuple(sorted(taken))
    )


# ---------------------------------------------------------------------------
# WHAT THE PAGE SAYS.


def lines(work_order_plan: WorkOrderPlan) -> list:
    """The guild saying it, "Name: words", one line per placed order."""
    return [assignment.said for assignment in work_order_plan.assignments]


def headline(work_order_plan: WorkOrderPlan) -> str:
    """One line over the plan, saying nothing rather than inventing a finding.

    THE THREE EMPTY CASES ARE DIFFERENT. No open orders, open orders with no
    taker, and orders already placed are three distinct states of a healthy
    guild, and collapsing them into "0 assignments" is how a reader concludes
    the pass is broken when it is working perfectly.
    """
    if not work_order_plan.assignments:
        if not work_order_plan.notes:
            return "no open work orders this cycle"
        return "%d open order%s and nobody online who can take them" % (
            len(work_order_plan.notes),
            "" if len(work_order_plan.notes) == 1 else "s",
        )
    return "%d work order%s going out to %d member%s: %s" % (
        len(work_order_plan.assignments),
        "" if len(work_order_plan.assignments) == 1 else "s",
        len(work_order_plan.taken),
        "" if len(work_order_plan.taken) == 1 else "s",
        ", ".join(work_order_plan.taken),
    )
