"""Run the item plan beside the economy pass and log it; change nothing (#1972).

`itemplan.plan` is pure. This adapter turns the rows the economy pass already
holds (the carried-item query, the surplus gear query, the free slot counts,
the worn rows) into its Stack and Member inputs, runs it, and logs:

  itemplan: plan <member> ...      one line per member: free slots now and after
  itemplan: disagree <member> ...  one line per stack where a pass and the plan
                                   differ
  itemplan: tick ...               one summary line, naming what the plan lacked

Every line starts with `itemplan:` so a log search finds all of them.

THE SWITCH is ITEMPLAN_SHADOW, off unless it reads on/1/true/yes, read the way
guildrun reads GUILD_RUNS. Off, `run` returns None before touching a row. On,
it still acts on nothing: it returns a report and writes log lines, and a
failure inside it is logged and swallowed so the economy pass carries on.

WHAT THE ROWS LACK. The carried query holds no binding, item level, subclass
or required level; the surplus gear query holds them for uncommon or better
gear and they are joined by item guid. Other rows read as unbound with level 1,
which only makes the plan more willing to move them, and the log says so. The
bank, the guild bank, equipped gear, auction prices and the guild roster are
not read here (#1973 reads them): they go in through `Extras`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Mapping

import bag_pressure
import itemplan

log = logging.getLogger("wow-overseer.itemplan")

ENV_SWITCH = "ITEMPLAN_SHADOW"
PREFIX = "itemplan:"

# Pass names in the disagreement lines.
SALE, BANK_PASS, CLEARANCE_PASS = "sale pass", "bank pass", "clearance pass"

_CLEARANCE_ROUTE = {
    "keep": itemplan.KEEP_CARRY,
    "bank": itemplan.BANK_PERSONAL,
    "family": itemplan.GIVE,
    "guild": itemplan.GUILD_BANK,
    "auction": itemplan.AUCTION,
    "vendor": itemplan.SELL_VENDOR,
}


def enabled(environ=None) -> bool:
    """On only when ITEMPLAN_SHADOW says so."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


@dataclass(frozen=True)
class Extras:
    """Facts the plan can use that this adapter does not read (#1973).

    Every field is absent by default and the plan fails closed without it.
    `open_quest_items` is holder -> frozenset of entries an open quest names;
    left None, the adapter derives it from the carried query's own quest flag.
    """

    open_quest_items: Mapping[str, frozenset] | None = None
    gear_verdict: Mapping[tuple, str] = field(default_factory=dict)
    market: Mapping[int, tuple] = field(default_factory=dict)
    guild_free: Mapping[tuple, int] = field(default_factory=dict)
    guild_crafters: tuple = ()


@dataclass(frozen=True)
class Report:
    plan: itemplan.Plan
    lines: tuple  # every plan line
    disagreements: tuple  # every disagree line
    missing: tuple  # what the plan ran without


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def characters_from_worn(worn_rows) -> dict:
    """name -> (class id, level) from the worn rows the gear pass reads."""
    out: dict = {}
    for row in worn_rows or ():
        name = str(row.get("name") or "")
        if name and "class_id" in row and "level" in row:
            out[name] = (_int(row["class_id"]), _int(row["level"]))
    return out


def build_stacks(rows, gear_rows=()) -> list:
    """One itemplan.Stack per carried row, in row order within the holder."""
    gear = {_int(r.get("item_guid")): r for r in gear_rows or ()}
    seen: dict = {}
    out = []
    for row in rows:
        holder = str(row["holder"])
        guid = _int(row.get("item_guid"))
        g = gear.get(guid, {})
        index = seen.get(holder, 0)
        seen[holder] = index + 1
        out.append(
            itemplan.Stack(
                holder=holder,
                loc=itemplan.CARRIED_BAG,
                entry=_int(row.get("entry")),
                name=str(row.get("name") or ""),
                item_class=_int(row.get("item_class", g.get("item_class"))),
                subclass=_int(g.get("item_subclass")),
                quality=_int(row.get("quality")),
                count=max(1, _int(row.get("count"), 1)),
                sell=max(0, _int(row.get("sell_price"))),
                bind=_int(g.get("bonding"), itemplan.BIND_NONE),
                req_level=_int(g.get("required_level")),
                item_level=_int(g.get("item_level"), 1),
                index=index,
            )
        )
    return out


def build_members(names, family, stacks, free_slots, characters) -> list:
    """One itemplan.Member per name. Carried slots are free plus carried."""
    out = []
    for name in sorted(str(n) for n in names):
        carried = sum(1 for s in stacks if s.holder == name)
        free = _int((free_slots or {}).get(name), 0)
        class_id, level = (characters or {}).get(name, (0, 1))
        out.append(
            itemplan.Member(
                name=name,
                family=family,
                level=level,
                class_id=class_id,
                carried_slots=max(1, carried + max(0, free)),
            )
        )
    return out


def _quest_items(rows) -> dict:
    out: dict = {}
    for row in rows:
        if _int(row.get("item_class")) == itemplan.C_QUEST and row.get("quest_item"):
            out.setdefault(str(row["holder"]), set()).add(_int(row.get("entry")))
    return {h: frozenset(v) for h, v in out.items()}


def _opinions(rows, sales, keep_names, bank_keeps, clear) -> dict:
    """pass name -> {(holder, guid): route in the plan's words}."""
    sold = {}
    for c in tuple(bag_pressure.vendor_candidates(rows, keep_names=keep_names)) + tuple(
        sales or ()
    ):
        sold[(str(c.holder), _int(c.item_guid))] = itemplan.SELL_VENDOR
    out = {SALE: sold}
    banks = {}
    for guid, placement in (bank_keeps or {}).items():
        to_guild = str(getattr(placement, "to", "")).lower() == "guild"
        banks[(str(placement.holder), _int(guid))] = (
            itemplan.GUILD_BANK if to_guild else itemplan.BANK_PERSONAL
        )
    out[BANK_PASS] = banks
    clears = {}
    for r in clear or ():
        route = _CLEARANCE_ROUTE.get(str(r.route))
        if route:
            clears[(str(r.stack.holder), _int(r.stack.guid))] = route
    out[CLEARANCE_PASS] = clears
    return out


def _missing(extras: Extras) -> tuple:
    """What the plan ran without, in words."""
    gaps = (
        (
            extras.open_quest_items is None,
            "quest log (using the sale query's quest flag)",
        ),
        (not extras.gear_verdict, "equipped gear verdicts"),
        (not extras.market, "auction prices"),
        (not extras.guild_crafters, "guild roster"),
        (not extras.guild_free, "guild bank room"),
        (True, "bank contents"),
        (True, "binding of non-gear rows"),
    )
    return tuple(text for absent, text in gaps if absent)


def _plan_lines(plan_, members, stacks) -> list:
    """One line per member: free slots now and after the plan."""
    lines = []
    for m in members:
        mine = [s for s in stacks if s.holder == m.name]
        by_route: dict = {}
        for d in plan_.by_holder(m.name):
            by_route[d.route] = by_route.get(d.route, 0) + 1
        routes = ", ".join("%s %d" % kv for kv in sorted(by_route.items()))
        lines.append(
            "%s plan %s: carried stacks %d, carried slots %d, free now %d, "
            "free after %d (%d with no vendor), routes %s"
            % (
                PREFIX,
                m.name,
                len(mine),
                m.carried_slots,
                itemplan.free_now(m, mine),
                itemplan.free_after(plan_, m, mine),
                itemplan.free_after(plan_, m, mine, sales=False),
                routes or "none",
            )
        )
    return lines


def _said(pass_name, theirs, decision, row, keep_names):
    """What a pass says about a stack when it differs from the plan, else None."""
    if pass_name == SALE:
        sells = theirs == itemplan.SELL_VENDOR
        if sells == (decision.route == itemplan.SELL_VENDOR):
            return None
        if sells:
            return "sells"
        why = bag_pressure.vendor_refusal(row, keep_names) or "not offered"
        return "keeps (%s)" % why
    if theirs is None or theirs == decision.route:
        return None
    return "routes it to %s" % theirs


def _disagreements(plan_, rows_by_key, opinions, keep_names) -> list:
    """One line per stack and pass where the pass and the plan differ."""
    out = []
    for d in plan_.decisions:
        row = rows_by_key.get(d.key)
        if row is None:
            continue
        guid = _int(row.get("item_guid"))
        for pass_name, opinion in opinions.items():
            said = _said(pass_name, opinion.get((d.holder, guid)), d, row, keep_names)
            if said:
                out.append(
                    "%s disagree %s: %s x%d (guid %s) %s %s, plan %s (%s, %s)"
                    % (
                        PREFIX,
                        d.holder,
                        d.name,
                        d.count,
                        guid,
                        pass_name,
                        said,
                        d.route,
                        d.reason,
                        d.rule,
                    )
                )
    return out


def shadow(
    names,
    family,
    rows,
    free_slots,
    *,
    gear_rows=(),
    worn_rows=(),
    sales=(),
    keep_names=(),
    bank_keeps=None,
    clear=(),
    extras: Extras | None = None,
) -> Report:
    """Plan and compare. Pure: no log, no read, no write."""
    extras = extras or Extras()
    rows = list(rows)
    stacks = build_stacks(rows, gear_rows)
    members = build_members(
        names, family, stacks, free_slots, characters_from_worn(worn_rows)
    )
    quest = extras.open_quest_items
    ctx = itemplan.Context(
        open_quest_items=_quest_items(rows) if quest is None else quest,
        gear_verdict=extras.gear_verdict,
        market=extras.market,
        guild_free=extras.guild_free,
        guild_crafters=extras.guild_crafters,
    )
    plan_ = itemplan.plan(stacks, members, ctx)
    rows_by_key = {s.key: r for s, r in zip(stacks, rows, strict=True)}
    opinions = _opinions(rows, sales, keep_names, bank_keeps, clear)
    return Report(
        plan_,
        tuple(_plan_lines(plan_, members, stacks)),
        tuple(_disagreements(plan_, rows_by_key, opinions, keep_names)),
        _missing(extras),
    )


def run(names, family, rows, free_slots, *, environ=None, logger=None, **facts):
    """The economy pass's one call. Off: None. A failure is logged, not raised."""
    if not enabled(environ):
        return None
    out = logger or log
    try:
        report = shadow(names, family, rows, free_slots, **facts)
        for line in report.lines + report.disagreements:
            out.info("%s", line)
        out.info(
            "%s tick: members %d, stacks %d, disagreements %d, ran without: %s",
            PREFIX,
            len(report.plan.members),
            len(report.plan.decisions),
            len(report.disagreements),
            "; ".join(report.missing),
        )
        return report
    except Exception:
        out.exception(
            "%s shadow failed; the economy pass is unaffected and carries on", PREFIX
        )
        return None
