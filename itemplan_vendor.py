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

REFUSABLE ROWS. Every SELL_VENDOR decision is `refusable`: the executor
may skip it and the next pass asks again. `carry_out` therefore treats
an insert that writes nothing (a falsy row id, the shape `_insert_sell`
returns for a kept or unavailable row) as a refusal: that sale is
counted as skipped and the rest still go out. A real failure raises, as
it does in the pass today; this module does not swallow it.

GOLD. `carry_out` reports the gold realized per member: the copper of
the sales actually written, summed by holder, with one log line per
member in `vendorsale.money` words.

PURE. Decisions and rows in, sales and a report out. No MySQL, no clock.
The bridge supplies the plan (through `itemplan_shadow.shadow`), the
rows, the released keys and the insert.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import bag_pressure
import itemplan
import vendorsale

ENV_SWITCH = "ITEMPLAN_SELL_VENDOR"
PREFIX = "itemplan vendor:"


def enabled(environ=None) -> bool:
    """On only when ITEMPLAN_SELL_VENDOR says so."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


@dataclass(frozen=True)
class Sale:
    """One released SELL_VENDOR decision, ready for the sell insert."""

    holder: str
    name: str
    count: int
    copper: int  # the plan's value for the stack: sell price times count
    key: tuple
    candidate: bag_pressure.SellCandidate


@dataclass(frozen=True)
class Report:
    carried: tuple = ()  # the Sale rows the insert wrote
    skipped: tuple = ()  # the Sale rows the executor refused
    gold: dict = field(default_factory=dict)  # holder -> copper written
    lines: tuple = ()  # one line per member, naming its gold


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sales_for(plan_, stack_rows, keep_names=(), released=frozenset()) -> tuple:
    """The route's sales from a plan, in plan order.

    `stack_rows` is (stack, carried row) pairs in the shape
    `itemplan_shadow.build_stacks` produces from the economy pass's rows:
    the stack supplies the decision key, the row supplies the guid the
    sell insert names and the current protection's reading.
    """
    rows_by_key = {stack.key: row for stack, row in stack_rows}
    out = []
    for decision in plan_.decisions:
        if decision.route != itemplan.SELL_VENDOR:
            continue
        if decision.from_loc not in itemplan.CARRIED or decision.stuck:
            continue
        if decision.reason.startswith(itemplan.NO_ROOM):
            continue
        if decision.confirm and decision.key not in released:
            continue
        row = rows_by_key.get(decision.key)
        if row is None:
            continue
        # Only where the current protection would keep the stack.
        if not bag_pressure.vendor_refusal(row, keep_names):
            continue
        guid = _int(row.get("item_guid"))
        count = max(1, _int(row.get("count"), 1))
        if guid <= 0:
            continue
        candidate = bag_pressure.SellCandidate(
            holder=str(row["holder"]),
            item_guid=guid,
            count=count,
            item=bag_pressure.ItemForSale(
                quality=_int(row.get("quality")),
                sell_price=max(0, _int(row.get("sell_price"))),
            ),
        )
        out.append(
            Sale(
                holder=decision.holder,
                name=decision.name,
                count=count,
                copper=max(0, _int(decision.value)),
                key=decision.key,
                candidate=candidate,
            )
        )
    return tuple(out)


def carry_out(sales, insert) -> Report:
    """Write each sale through `insert`; a refusal skips only that row.

    `insert(candidate)` returns the written row id, or a falsy value when
    the executor refuses the row. Gold is counted only for written rows.
    """
    carried, skipped = [], []
    gold: dict = {}
    for sale in sales:
        if insert(sale.candidate):
            carried.append(sale)
            gold[sale.holder] = gold.get(sale.holder, 0) + sale.copper
        else:
            skipped.append(sale)
    lines = tuple(
        "%s %s: %d sale(s) carried out, gold %s"
        % (
            PREFIX,
            holder,
            sum(1 for s in carried if s.holder == holder),
            vendorsale.money(copper),
        )
        for holder, copper in sorted(gold.items())
    )
    return Report(tuple(carried), tuple(skipped), gold, lines)
