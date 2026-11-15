"""The family's bag loop for the approved raid seats (#2609).

WHY IT EXISTS. Read on the dev realm on 2026-11-15 over the approved seats
outside the two families' first groups: a median of 2 free carried slots, 45
seats at 2 or fewer, no stack in any bank. The cause was three gaps at once.

  * THE READ. The guild job read (`_JOB_ITEMS_SQL`) holds only the stacks a
    vendor can buy. About 1,200 of the roughly 3,000 stacks the seats carry
    are quest-class items with no vendor price, so the pass that decides what
    leaves the bags never saw them.
  * THE PLAN. The item plan (itemplan.py) decides, per stack, whether it is
    kept, banked, sold or broken down. It ran for the two families only; the
    guild job sold by `vendorsale`'s own, narrower rule.
  * THE RUNG. The sale step fired when a quarter of the slots were free or
    fewer, once every two hours, and no step banked anything for a seat.

WHAT THIS DOES. For a seat under the plan's trigger (`itemplan.TRIGGER_FREE`
free carried slots) it runs the same plan the family runs, over the seat's
whole bags, and hands the guild job two lists: the stacks the plan sells and
the stacks it banks. `guildjobs.seat_loop_first` turns them into a vendor step
and a banker step on a town stop. Nothing is granted or created: the loop only
moves what the seat already carries, through a vendor and its own bank.

THE SAME GATES. The plan's own gates stand (a quality 3 or better stack waits
for a release, never a bag or a tool, never an item a quest in the log names,
never an epic), `itemplan_vendor` still holds fallback sales until pressure
releases them, and the sell row is written through the bridge's keep and epic
gates like every other sell row. A seat has no guild-bank or gift route here:
the plan is run without guild bank room and without guild crafters, so its
answer for a seat is keep, bank, sell, disenchant or destroy, and only the
sale and the deposit are carried out by this module's caller.

PURE: rows and facts in, a plan and members out. No MySQL, no clock but the
`now` it is given. The bridge supplies the reads.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace

import guildjobs
import itemplan
import itemplan_shadow
import itemplan_vendor
import raidteams

ENV_BANK = "GUILD_SEAT_BANK"
PREFIX = "seat bags:"
# Seconds a seat's plan is kept before it is read and planned again.
REFRESH_SECONDS = 10 * 60
TRIGGER_FREE = itemplan.TRIGGER_FREE


def bank_enabled(environ=None) -> bool:
    """On unless GUILD_SEAT_BANK says off: a deposit that finds no banker in
    reach is refused by the module and asked again later, so it is safe on."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_BANK, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


def seat_names(guild: str) -> frozenset:
    """The approved seats of a guild outside its family's first group: both the
    approved name and the name held until the rename."""
    out = set()
    for group in raidteams.GROUPS.get(guild, ())[1:]:
        for s in group:
            out.add(s.name)
            if s.was:
                out.add(s.was)
    return frozenset(out)


def is_seat(member) -> bool:
    """An approved raid seat of a guild, a family head excluded (the economy
    pass runs the family's own loop)."""
    return member.role == guildjobs.RAIDER and member.name in seat_names(member.guild)


def needs_plan(member) -> bool:
    """A seat in the world with fewer free slots than the plan's trigger."""
    return bool(
        is_seat(member)
        and member.online
        and member.alive
        and member.free_slots is not None
        and int(member.free_slots) < TRIGGER_FREE
    )


@dataclass(frozen=True)
class SeatPlan:
    sales: dict = field(default_factory=dict)  # name -> Carried to sell
    banks: dict = field(default_factory=dict)  # name -> Carried to bank
    lines: tuple = ()  # one log line per seat that got a plan


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def carried_of(row) -> guildjobs.Carried:
    """The guild job's Carried for an economy-pass carried row."""
    return guildjobs.Carried(
        guid=_int(row.get("item_guid")),
        entry=_int(row.get("entry")),
        count=max(1, _int(row.get("count"), 1)),
        item_class=_int(row.get("item_class")),
        quality=_int(row.get("quality"), 1),
        sell_price=max(0, _int(row.get("sell_price"))),
        name=str(row.get("name") or ""),
    )


def plan_for(
    names,
    family,
    rows,
    free_slots,
    extras,
    gear_rows=(),
    worn_rows=(),
    keep_names=(),
) -> SeatPlan:
    """What the item plan sells and banks for these seats.

    `rows` and `extras` are what the economy pass reads for the family
    (`_fetch_vendor_items`, `itemplan_reads.read`), read for the seats. The
    guild bank and the guild's crafters are left out of the plan's world: a
    seat has no gift or guild deposit here, so those routes must not be
    chosen and then left undone.
    """
    names = sorted({str(n) for n in names})
    mine = [r for r in rows if str(r.get("holder")) in names]
    if not names or not mine:
        return SeatPlan()
    extras = replace(extras, guild_free={}, guild_crafters=())
    report = itemplan_shadow.shadow(
        names,
        family,
        mine,
        free_slots,
        gear_rows=gear_rows,
        worn_rows=worn_rows,
        keep_names=keep_names,
        extras=extras,
    )
    stacks = itemplan_shadow.build_stacks(
        mine, gear_rows, extras.templates, extras.instance_soulbound
    )
    pairs = list(zip(stacks, mine, strict=True))
    row_of = {stack.key: row for stack, row in pairs}
    sales = itemplan_vendor.sales_for(
        report.plan,
        pairs,
        keep_names=keep_names,
        held=[],
        pressure=itemplan_vendor.pressure_for(names, free_slots, None),
        only_kept=False,
    )
    sold: dict = {}
    for sale in sales:
        row = row_of.get(sale.key)
        if row is not None:
            sold.setdefault(sale.holder, []).append(carried_of(row))
    banked: dict = {}
    for d in report.plan.decisions:
        if d.route != itemplan.BANK_PERSONAL or d.from_loc not in itemplan.CARRIED:
            continue
        if d.stuck or d.reason.startswith(itemplan.NO_ROOM):
            continue
        row = row_of.get(d.key)
        if row is not None:
            banked.setdefault(d.holder, []).append(carried_of(row))
    lines = tuple(
        "%s %s: %d free slot(s), the plan sells %d stack(s) and banks %d"
        % (
            PREFIX,
            name,
            _int((free_slots or {}).get(name)),
            len(sold.get(name, ())),
            len(banked.get(name, ())),
        )
        for name in names
        if sold.get(name) or banked.get(name)
    )
    return SeatPlan(
        {k: tuple(v) for k, v in sold.items()},
        {k: tuple(v) for k, v in banked.items()},
        lines,
    )


def nearest_banker(member, spots, cap):
    """The banker spawn on the member's map nearest it, within `cap` yards."""
    if member.map_id is None or member.x is None or member.y is None:
        return None
    best, best_yards = None, None
    for spot in spots or ():
        if int(spot.map_id) != int(member.map_id):
            continue
        yards = math.hypot(float(member.x) - spot.x, float(member.y) - spot.y)
        if yards <= float(cap) and (best_yards is None or yards < best_yards):
            best, best_yards = spot, yards
    return best


def attach(members, seat_plan, bankers, cap, bank=True) -> list:
    """The members, each seat carrying its plan and its nearest banker."""
    out = []
    for m in members:
        sales = seat_plan.sales.get(m.name, ())
        banks = seat_plan.banks.get(m.name, ()) if bank else ()
        if not sales and not banks:
            out.append(m)
            continue
        out.append(
            replace(
                m,
                plan_sales=tuple(sales),
                plan_bank=tuple(banks),
                banker=nearest_banker(m, bankers, cap) if banks else None,
            )
        )
    return out


class Memo:
    """Each seat's last plan, so the whole bags are read and planned at most
    once in REFRESH_SECONDS per seat, not on every guild job pass."""

    def __init__(self):
        self._at: dict = {}
        self._plan: dict = {}

    def fresh(self, name, now) -> bool:
        return name in self._at and now - self._at[name] < REFRESH_SECONDS

    def keep(self, names, seat_plan, now) -> None:
        for name in names:
            self._at[name] = now
            self._plan[name] = (
                seat_plan.sales.get(name, ()),
                seat_plan.banks.get(name, ()),
            )

    def merged(self, names, seat_plan) -> SeatPlan:
        sales = dict(seat_plan.sales)
        banks = dict(seat_plan.banks)
        for name in names:
            if name in sales or name in banks:
                continue
            old = self._plan.get(name)
            if old is None:
                continue
            if old[0]:
                sales[name] = old[0]
            if old[1]:
                banks[name] = old[1]
        return SeatPlan(sales, banks, seat_plan.lines)


def relieve(members, read, bankers_for, cap, now, memo, environ=None):
    """(members with the seats' plans attached, log lines).

    `read(names)` returns (family, rows, free_slots, extras, gear_rows,
    worn_rows, keep_names) for those seats, or None when the reads failed;
    `bankers_for(map_ids)` returns the banker Spots on those maps. A seat
    planned inside REFRESH_SECONDS keeps its last plan and is not read again.
    The seats' plan is carried out only while the vendor route is on
    (`itemplan_vendor.enabled`), the same switch the family's sale rides.
    """
    if not itemplan_vendor.enabled(environ):
        return list(members), ()
    seats = [m for m in members if needs_plan(m)]
    due = [m for m in seats if not memo.fresh(m.name, now)]
    fresh_plan = SeatPlan()
    if due:
        got = read([m.name for m in due])
        if got is not None:
            family, rows, free_slots, extras, gear_rows, worn_rows, keep = got
            fresh_plan = plan_for(
                [m.name for m in due],
                family,
                rows,
                free_slots,
                extras,
                gear_rows,
                worn_rows,
                keep,
            )
            memo.keep([m.name for m in due], fresh_plan, now)
    plan = memo.merged(
        [m.name for m in seats if m.name not in {d.name for d in due}], fresh_plan
    )
    bank = bank_enabled(environ)
    spots = ()
    if bank and plan.banks:
        maps = sorted(
            {
                int(m.map_id)
                for m in seats
                if m.name in plan.banks and m.map_id is not None
            }
        )
        spots = bankers_for(maps) if maps else ()
    return attach(members, plan, spots, cap, bank), fresh_plan.lines
