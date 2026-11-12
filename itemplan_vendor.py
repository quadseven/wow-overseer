"""Carry out the item plan's vendor sales in the town-run pass (#1977).

`itemplan_shadow` (#1972) runs the plan beside the economy pass and logs
it; it acts on nothing. This is the first route that acts, on one route
only, matching the rollout in `docs/ITEM_PLAN.md`: act on one route at a
time, each route with its own switch, acting only where the current
protection would keep the stack.

THE SWITCH is ITEMPLAN_SELL_VENDOR, off unless it reads on/1/true/yes,
read the way `itemplan_shadow` reads its own. Off, the town-run pass
never calls `sales_for`.

WHAT COUNTS AS A ROUTE SALE. A decision of the plan is carried out only
when every one of these holds:

  * its route is SELL_VENDOR and the stack is carried (a banked stack is
    not this pass's: the town-run vendor candidates are carried stacks);
  * it is not a stuck stack (no destination had room for it);
  * the current protection would keep the stack: `bag_pressure`'s own
    reading (`vendor_refusal`) refuses the row, so a stack the existing
    sale pass already sells is left to that pass and never sold twice;
  * a `confirm` sale (quality 3 or better, or worth 1 gold or more) has
    been released: its decision key is in the caller's `released` set.
    An unreleased confirm sale is shown by the shadow and waits.

NOT A BAG, NOT A TOOL. The plan can route a bag (rule R2, its worn-bag test
is vacuous in the shadow) or a fishing pole (rule R8, not in
`disposition.TOOL_TRADES`) to SELL_VENDOR. The route holds both back by
item class, not by name.

NOT A FALLBACK. `Decision.options` lists the routes the plan weighed, best
first. When SELL_VENDOR was chosen only because a better route had no
room (a full guild bank tab), the plan wanted the stack kept and a sale
cannot be undone, so it is held back: `sales_for` appends it to the
`held` list its caller passes, and `held_lines` words it for the log.

REFUSABLE ROWS. Every SELL_VENDOR decision is `refusable`: the executor
may skip it and the next pass asks again. `carry_out` therefore treats
an insert that writes nothing (a falsy row id, the shape `_insert_sell`
returns for a kept or unavailable row) as a refusal: that sale is
counted as skipped and the rest still go out. A real failure raises, as
it does in the pass today; this module does not swallow it.

WORTH. `carry_out` only queues rows: the vendor has sold nothing yet. It
reports what the queued rows are worth per member: the copper of the
sales actually written, summed by holder, with one log line per member
in `vendorsale.money` words.

THE PRESSURE RELEASE (ITEMPLAN_SELL_RELEASE). The two holds above are each
right alone and wrong together: a member whose personal bank and guild bank
tab are both full has nowhere to put what the plan wanted kept, so its
fallback sales are held, and its confirm sales wait for a release nothing
supplies. Its bags then stay full for good. When the caller passes a
`pressure` (slots a member still has to free), the held sales of THAT member
are released, cheapest stack first, one slot per stack, only as many as the
pressure asks for, and never past `RELEASE_CEILING_COPPER` for one stack,
never epic quality, never a bag and never a profession tool. A member with
room has no pressure and releases nothing, and without a pressure the
function answers exactly as before. Each released sale carries which hold it
lifted, so the log can say what was sold and why.

PURE. Decisions and rows in, sales and a report out. No MySQL, no clock.
The bridge supplies the plan (through `itemplan_shadow.shadow`), the
rows, the released keys and the insert.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import bag_pressure
import disposition
import itemplan
import vendorsale

ENV_SWITCH = "ITEMPLAN_SELL_VENDOR"
ENV_RELEASE = "ITEMPLAN_SELL_RELEASE"

# Which hold a released sale lifted.
RELEASED_CONFIRM = "confirm"
RELEASED_FALLBACK = "fallback"

# The most one stack may be worth and still be released by pressure alone
# (5 gold, in copper). Above it a sale is a person's call, as it always was.
RELEASE_CEILING_COPPER = 50000
# An epic or better stack is never sold by the route, released or not.
RELEASE_MAX_QUALITY = 3
# A member is under pressure below the plan's trigger and is relieved up to
# this many free slots, the plan's own hysteresis band.
RELEASE_TARGET_FREE = itemplan.TRIGGER_FREE + 2

# Why a SELL_VENDOR decision is held back instead of carried out.
HELD_FALLBACK = "a fallback sale: the first choice had no room"
HELD_BAG = "a bag is never sold by the route"
HELD_TOOL = "a profession tool is never sold by the route"

# item_template class 2 (weapon) subclasses that are tools, not weapons.
_TOOL_SUBCLASSES = (14, 20)  # miscellaneous (pick, knife), fishing pole
PREFIX = "itemplan vendor:"


def enabled(environ=None) -> bool:
    """On only when ITEMPLAN_SELL_VENDOR says so."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


def release_enabled(environ=None) -> bool:
    """On only when the route is on and ITEMPLAN_SELL_RELEASE says so."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_RELEASE, "") or "").strip().lower()
    return enabled(env) and raw in ("on", "1", "true", "yes")


def pressure_for(names, free_slots, sellable_counts) -> dict:
    """holder -> slots still to free, for members under the plan's trigger.

    A member that is not under the trigger, or whose free slots were not
    read, has no entry. The ordinary sale pass's own count comes off first,
    because those stacks go out anyway and must not be made up for twice.
    """
    out = {}
    for name in names:
        free = (free_slots or {}).get(name)
        if free is None or free >= itemplan.TRIGGER_FREE:
            continue
        sellable = max(0, _int((sellable_counts or {}).get(name)))
        need = RELEASE_TARGET_FREE - max(0, _int(free)) - sellable
        if need > 0:
            out[name] = need
    return out


@dataclass(frozen=True)
class Sale:
    """One released SELL_VENDOR decision, ready for the sell insert."""

    holder: str
    name: str
    count: int
    copper: int  # the plan's value for the stack: sell price times count
    key: tuple
    candidate: bag_pressure.SellCandidate
    released: str = ""  # which hold pressure lifted, or "" for an ordinary sale


@dataclass(frozen=True)
class Report:
    carried: tuple = ()  # the Sale rows the insert wrote
    skipped: tuple = ()  # the Sale rows the executor refused
    worth: dict = field(default_factory=dict)  # holder -> copper queued
    lines: tuple = ()  # one line per member, naming what it queued


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _held_reason(decision, stack, row) -> str:
    """Why this SELL_VENDOR decision must not be carried out; '' when it may.

    From item class data (the stack's class and subclass, the row's class
    when the stack lacks one, `disposition.TOOL_TRADES`), never from names.
    """
    item_class = getattr(stack, "item_class", None)
    if item_class is None:
        item_class = row.get("item_class")
    subclass = getattr(stack, "subclass", None)
    if _int(item_class, -1) == itemplan.C_CONTAINER:
        return HELD_BAG
    if decision.entry in disposition.TOOL_TRADES or (
        _int(item_class, -1) == itemplan.C_WEAPON
        and _int(subclass, -1) in _TOOL_SUBCLASSES
    ):
        return HELD_TOOL
    if decision.options and decision.options[0] != itemplan.SELL_VENDOR:
        return HELD_FALLBACK
    return ""


def _sale_of(decision, row, released=""):
    """The Sale for a decision and its carried row, or None when the row
    names no item to sell."""
    guid = _int(row.get("item_guid"))
    count = max(1, _int(row.get("count"), 1))
    if guid <= 0:
        return None
    candidate = bag_pressure.SellCandidate(
        holder=str(row["holder"]),
        item_guid=guid,
        count=count,
        item=bag_pressure.ItemForSale(
            quality=_int(row.get("quality")),
            sell_price=max(0, _int(row.get("sell_price"))),
        ),
    )
    return Sale(
        holder=decision.holder,
        name=decision.name,
        count=count,
        copper=max(0, _int(decision.value)),
        key=decision.key,
        candidate=candidate,
        released=released,
    )


def _may_release(decision, row) -> bool:
    """May pressure alone lift the hold on this stack?"""
    if _int(row.get("quality")) > RELEASE_MAX_QUALITY:
        return False
    return max(0, _int(decision.value)) <= RELEASE_CEILING_COPPER


def _classify(decision, row, stack, released, keep_names):
    """What the route does with one carried SELL_VENDOR decision.

    Returns None to leave it alone, else (kind, why, release_kind):
    kind is "sell" for an ordinary sale, "held" for a hold that stays, and
    "pool" for a hold pressure may lift, in which case release_kind says
    which hold it is. `why` is the held reason, or ''.
    """
    # Only where the current protection would keep the stack.
    if not bag_pressure.vendor_refusal(row, keep_names):
        return None
    why = _held_reason(decision, stack, row)
    if decision.confirm and decision.key not in released:
        # Waits for a release, as it always did; a bag or a tool is never
        # released and says nothing.
        if not why or why == HELD_FALLBACK:
            return ("pool", why, RELEASED_CONFIRM)
        return None
    if why == HELD_FALLBACK:
        return ("pool", why, RELEASED_FALLBACK)
    return ("held", why, "") if why else ("sell", "", "")


def _eligible(decision):
    """The decisions the route looks at: carried, placed, sold to a vendor."""
    return (
        decision.route == itemplan.SELL_VENDOR
        and decision.from_loc in itemplan.CARRIED
        and not decision.stuck
        and not decision.reason.startswith(itemplan.NO_ROOM)
    )


def _release(pool, ordinary, pressure) -> tuple:
    """(sales released, fallback holds still held), both with plan index.

    Cheapest stack first, one slot per stack, after the holder's ordinary
    sales are counted against its pressure.
    """
    remaining = {
        holder: _int(need) - sum(1 for _i, sale in ordinary if sale.holder == holder)
        for holder, need in (pressure or {}).items()
    }
    lifted, still_held = [], []
    for _value, index, decision, row, kind, held_entry in sorted(
        pool, key=lambda entry: (entry[0], entry[1])
    ):
        sale = None
        if remaining.get(decision.holder, 0) > 0 and _may_release(decision, row):
            sale = _sale_of(decision, row, released=kind)
        if sale is not None:
            lifted.append((index, sale))
            remaining[decision.holder] -= 1
        elif held_entry is not None:
            still_held.append((index, held_entry))
    return lifted, still_held


def sales_for(
    plan_,
    stack_rows,
    keep_names=(),
    released=frozenset(),
    held=None,
    pressure=None,
) -> tuple:
    """The route's sales from a plan, in plan order.

    `stack_rows` is (stack, carried row) pairs in the shape
    `itemplan_shadow.build_stacks` produces from the economy pass's rows:
    the stack supplies the decision key, the row supplies the guid the
    sell insert names and the current protection's reading. A fallback
    sale is not returned; when `held` is a list it is appended there.

    `pressure` maps a holder to the slots it still has to free (see
    `pressure_for`). For such a holder the held sales, confirm and fallback,
    are released cheapest first up to the pressure, after the ordinary
    sales have been counted against it. No pressure, or none for a holder,
    changes nothing.
    """
    rows_by_key = {stack.key: row for stack, row in stack_rows}
    stack_of = {stack.key: stack for stack, _row in stack_rows}
    ordinary = []  # (plan index, Sale)
    pool = []  # (value, plan index, decision, row, release kind, held entry)
    for index, decision in enumerate(plan_.decisions):
        row = rows_by_key.get(decision.key)
        if row is None or not _eligible(decision):
            continue
        verdict = _classify(
            decision, row, stack_of.get(decision.key), released, keep_names
        )
        if verdict is None:
            continue
        kind, why, release_kind = verdict
        if kind == "sell":
            sale = _sale_of(decision, row)
            if sale is not None:
                ordinary.append((index, sale))
        elif kind == "held":
            if held is not None:
                held.append((decision, why))
        else:
            entry = (decision, why) if release_kind == RELEASED_FALLBACK else None
            pool.append(
                (
                    max(0, _int(decision.value)),
                    index,
                    decision,
                    row,
                    release_kind,
                    entry,
                )
            )
    lifted, still_held = _release(pool, ordinary, pressure)
    if held is not None:
        # Plan order, as the held lines have always read.
        held.extend(entry for _i, entry in sorted(still_held, key=lambda e: e[0]))
    chosen = ordinary + lifted
    return tuple(sale for _i, sale in sorted(chosen, key=lambda e: e[0]))


def release_lines(sales) -> tuple:
    """One log line per holder for the held sales pressure released."""
    by_holder: dict = {}
    for sale in sales:
        if sale.released:
            by_holder.setdefault(sale.holder, []).append(sale)
    return tuple(
        "%s %s releases %d held sale(s) under bag pressure, worth %s: %s"
        % (
            PREFIX,
            holder,
            len(found),
            vendorsale.money(sum(s.copper for s in found)),
            ", ".join(s.name for s in found),
        )
        for holder, found in sorted(by_holder.items())
    )


def held_lines(held) -> tuple:
    """One log line per holder for the sales held back, each with its reason."""
    names: dict = {}
    for decision, why in held:
        names.setdefault(decision.holder, []).append("%s (%s)" % (decision.name, why))
    return tuple(
        "%s %s holds back %d sale(s): %s"
        % (PREFIX, holder, len(found), ", ".join(found))
        for holder, found in sorted(names.items())
    )


def carry_out(sales, insert) -> Report:
    """Write each sale through `insert`; a refusal skips only that row.

    `insert(candidate)` returns the written row id, or a falsy value when
    the executor refuses the row. Worth is counted only for written rows.
    """
    carried, skipped = [], []
    worth: dict = {}
    for sale in sales:
        if insert(sale.candidate):
            carried.append(sale)
            worth[sale.holder] = worth.get(sale.holder, 0) + sale.copper
        else:
            skipped.append(sale)
    lines = tuple(
        "%s %s: %d sale(s) queued, worth %s"
        % (
            PREFIX,
            holder,
            sum(1 for s in carried if s.holder == holder),
            vendorsale.money(copper),
        )
        for holder, copper in sorted(worth.items())
    )
    return Report(tuple(carried), tuple(skipped), worth, lines)
