"""Guild work orders: what the guild asks for, and which member takes it (#486).

THE PULL HALF OF PROFESSION COORDINATION. guildshare.py pushes surplus to a
guildmate who can use it, without anyone asking. Nothing let the guild ASK:
"we need 96 Greater Fire Protection Potion for raid night", "farm Firebloom in
Searing Gorge", "who spends the Mooncloth cooldown today". This module is the
decision for those asks.

Pure module, same seam as guildshare.py and craftpleas.py: work orders and
member facts go in, an assignment plan and its sentences come out. No SQL, no
Discord, no worldserver verb. The bridge reads the facts and keeps the
orders; this only decides.

THE LIFE OF AN ORDER. requested -> assigned -> complete. `plan` takes every
REQUESTED order and gives it to one qualified member, one order per member per
pass, and returns the order with status ASSIGNED and its assignee. `complete`
moves an ASSIGNED order to COMPLETE only when its own assignee reports it; any
other report leaves the order as it was. An order nobody can take stays
REQUESTED and the plan carries a note saying why, so a gap reads as a gap.

THREE KINDS OF ORDER.
  consumable  "need N of an item": goes to a member holding the craft.
  farming     "gather an item in a zone": goes to a member holding the trade.
  cooldown    "spend a profession cooldown": goes to a member holding the
              craft whose own cooldown for it is ready now. A holder still on
              cooldown is not a taker, and the note names the soonest one.

WHO QUALIFIES. Online, and holding the order's profession at a skill above
zero. Skills are keyed by the ids in goals.SKILL_IDS, the ids
acore_characters.character_skills uses. A skill value that is not a number is
a defect in the caller's data and raises; it is not read as "does not hold
the trade". Among qualified members the lowest level goes first (the capped
ones are needed elsewhere), then name, so a pass is deterministic.

WHERE IT RUNS. bridge.py's guild surplus pass already reads the guild roster
(name, level, online, character_skills) for guildshare; it hands the same
roster to `members_from_roster` and plans STANDING_ORDERS, and logs the
headline, each taker's line and each note. That is all it does with the plan:
it writes no row and sends no order, so nothing in the world changes. The
realm's cooldown times are not read yet, so every holder counts as ready
until that read exists.

WHAT IT DOES NOT DO. It does not check recipe knowledge or skill rank for a
specific recipe, it does not read cooldown times from the realm, and it does
not persist orders between passes: those are the caller's facts. The item
table below names the ticket's own examples; an item it does not name is
reported, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import goals

CONSUMABLE, FARMING, COOLDOWN = "consumable", "farming", "cooldown"
KINDS = (CONSUMABLE, FARMING, COOLDOWN)
REQUESTED, ASSIGNED, COMPLETE = "requested", "assigned", "complete"

# (kind, item lowercased) -> the profession, as named in goals.SKILL_IDS.
ORDER_TRADES = {
    (CONSUMABLE, "greater fire protection potion"): "alchemy",
    (FARMING, "firebloom"): "herbalism",
    (COOLDOWN, "mooncloth"): "tailoring",
    (COOLDOWN, "arcanite"): "alchemy",
}


@dataclass(frozen=True)
class WorkOrder:
    """One guild request, with its progress and its assignee once it has one."""

    kind: str
    item: str
    quantity: int = 0
    zone: str = ""
    requested_by: str = "the guild"
    status: str = REQUESTED
    assigned_to: str = ""


@dataclass(frozen=True)
class WorkMember:
    """One guild member as the caller read it.

    `skills` maps a goals.SKILL_IDS id to the member's skill value.
    `cooldowns` maps a cooldown item (lowercased) to the seconds left before
    the member can spend it again; an item not listed is ready.
    """

    name: str
    level: int = 1
    online: bool = False
    skills: dict = field(default_factory=dict)
    cooldowns: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WorkAssignment:
    order: WorkOrder
    taker: str


@dataclass(frozen=True)
class WorkOrderPlan:
    assignments: tuple = ()
    notes: tuple = ()


# The orders that stand every pass, with nobody having to ask: a profession
# cooldown is spent whenever someone is ready to spend it. Consumable and
# farming orders need someone to ask for them, and the intake for those is
# not built yet (see WHERE IT RUNS).
STANDING_ORDERS = (
    WorkOrder(COOLDOWN, "Mooncloth"),
    WorkOrder(COOLDOWN, "Arcanite"),
)


def members_from_roster(roster) -> list:
    """WorkMember for each guild roster entry (guildshare.Member's shape)."""
    return [
        WorkMember(
            name=str(m.name),
            level=int(m.level or 0),
            online=bool(m.online),
            skills=dict(m.skills or {}),
        )
        for m in roster or ()
    ]


def _item_key(order: WorkOrder) -> str:
    return str(order.item).strip().lower()


def trade_for(order: WorkOrder) -> str:
    """The profession an order needs, or "" when the table does not name it."""
    return ORDER_TRADES.get((str(order.kind).lower(), _item_key(order)), "")


def cooldown_left(member: WorkMember, order: WorkOrder) -> int:
    """Seconds before `member` can spend this cooldown; 0 for other kinds."""
    if order.kind != COOLDOWN:
        return 0
    return max(0, int(member.cooldowns.get(_item_key(order), 0)))


def holds_trade(member: WorkMember, order: WorkOrder) -> bool:
    """Whether the member is online and holds the order's profession."""
    trade = trade_for(order)
    if not trade or not member.online:
        return False
    return int(member.skills.get(goals.SKILL_IDS[trade], 0)) > 0


def can_take(member: WorkMember, order: WorkOrder) -> str:
    """Why `member` can take `order` now, or "" when it cannot."""
    if not holds_trade(member, order) or cooldown_left(member, order):
        return ""
    return "%s holds %s" % (member.name, trade_for(order))


def _hours(seconds: int) -> int:
    return max(1, -(-int(seconds) // 3600))


def plan(orders, members) -> WorkOrderPlan:
    """Assign each requested order to one qualified member, deterministically."""
    assignments, notes = [], []
    busy = set()
    ranked = sorted(members or (), key=lambda m: (int(m.level), str(m.name).casefold()))
    for order in orders or ():
        if order.status != REQUESTED:
            continue
        trade = trade_for(order)
        if not trade:
            notes.append("%s has no craft or trade this guild knows" % order.item)
            continue
        holders = [m for m in ranked if holds_trade(m, order)]
        if not holders:
            notes.append(
                "nobody online holds %s, so %s stays unassigned" % (trade, order.item)
            )
            continue
        ready = [m for m in holders if not cooldown_left(m, order)]
        if not ready:
            soonest = min(holders, key=lambda m: cooldown_left(m, order))
            notes.append(
                "every %s holder is on the %s cooldown; %s is ready in %dh"
                % (
                    trade,
                    order.item,
                    soonest.name,
                    _hours(cooldown_left(soonest, order)),
                )
            )
            continue
        free = [m for m in ready if m.name not in busy]
        if not free:
            notes.append(
                "every member who can take %s already has an order this pass"
                % order.item
            )
            continue
        taker = free[0].name
        busy.add(taker)
        assigned = replace(order, status=ASSIGNED, assigned_to=taker)
        assignments.append(WorkAssignment(assigned, taker))
    return WorkOrderPlan(tuple(assignments), tuple(notes))


def complete(order: WorkOrder, reporter: str) -> WorkOrder:
    """Mark an assigned order complete, only when its own assignee reports it."""
    if order.status != ASSIGNED or order.assigned_to != str(reporter):
        return order
    return replace(order, status=COMPLETE)


def lines(work_plan: WorkOrderPlan) -> list:
    """Each assignment as the short line its taker says to the guild."""
    output = []
    for assignment in work_plan.assignments:
        order = assignment.order
        if order.kind == CONSUMABLE:
            message = "the guild needs %d %s" % (order.quantity, order.item)
        elif order.kind == FARMING:
            message = "the guild wants %s from %s" % (order.item, order.zone)
        else:
            message = "the %s cooldown is mine to spend" % order.item
        output.append("%s: %s" % (assignment.taker, message))
    return output


def headline(work_plan: WorkOrderPlan) -> str:
    """One line over an assignment pass."""
    count = len(work_plan.assignments)
    if not count:
        if work_plan.notes:
            noun = "order" if len(work_plan.notes) == 1 else "orders"
            return "%d open %s and nobody who can take them now" % (
                len(work_plan.notes),
                noun,
            )
        return "no open work orders this pass"
    takers = sorted({a.taker for a in work_plan.assignments}, key=str.casefold)
    return "%d %s going out to %d %s: %s" % (
        count,
        "work order" if count == 1 else "work orders",
        len(takers),
        "member" if len(takers) == 1 else "members",
        ", ".join(takers),
    )
