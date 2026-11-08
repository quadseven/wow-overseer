"""Run the item plan beside the economy pass and log it; change nothing (#1972).

`itemplan.plan` is pure. This adapter turns the rows the economy pass already
holds (the carried-item query, the surplus gear query, the free slot counts,
the worn rows) into its Stack and Member inputs, runs it, and logs:

  itemplan: plan <member> ...      one line per member: free slots now and after
  itemplan: disagree <member> ...  one line per stack where a pass and the plan
                                   differ
  itemplan: tick ...               one summary line, naming what the plan lacked

Every line starts with `itemplan:` so a log search finds all of them.

QUIET LOG. A member's plan line and disagreement lines are written in full when
that member's plan changed since the last tick, or when 30 minutes have passed
since they were last written. Every other tick writes the one tick line, which
counts the members it left out.

THE SWITCH is ITEMPLAN_SHADOW, off unless it reads on/1/true/yes, read the way
guildrun reads GUILD_RUNS. Off, `run` returns None before touching a row. On,
it still acts on nothing: it returns a report and writes log lines, and a
failure inside it is logged and swallowed so the economy pass carries on.

WHAT THE ROWS LACK. The carried query holds no binding, item level, subclass
or required level; the surplus gear query holds them for uncommon or better
gear and they are joined by item guid. `Extras.templates` (item_template rows
by entry) gives every other row its binding, item level and required level;
without it those rows read as unbound with level 1, which only makes the plan
more willing to move them, and the log says so. The bank, the guild bank,
worn gear, auction prices and the guild roster come in through `Extras`, read
by `itemplan_reads` (#1973). A read that failed or was never made leaves its
field None, and the tick line names it under `ran without`.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Mapping

import bag_pressure
import itemplan
import itemplan_data

log = logging.getLogger("wow-overseer.itemplan")

ENV_SWITCH = "ITEMPLAN_SHADOW"
GIVE_ENV_SWITCH = "ITEMPLAN_GIVE"
PREFIX = "itemplan:"
# Seconds between full detail for a member whose plan has not changed.
REFRESH_SECONDS = 30 * 60

# The inputs the plan can run without, by the name `ran without` uses.
QUEST_LOG = "quest log"
WORN_GEAR = "equipped gear verdicts"
AUCTION_PRICES = "auction prices"
GUILD_ROSTER = "guild roster"
GUILD_ROOM = "guild bank room"
BANK_CONTENTS = "bank contents"
BINDING = "binding of non-gear rows"
FIRE_RESISTANCE = "per-item fire resistance"
BAG_SLOTS = "bag slot capacity"
RECIPE_RANK = "recipe skill rank"
ITEM_STATS = "item template stats"
INSTANCE_SOULBOUND = "item-instance soulbound flags"
INPUTS = (
    QUEST_LOG,
    WORN_GEAR,
    AUCTION_PRICES,
    GUILD_ROSTER,
    GUILD_ROOM,
    BANK_CONTENTS,
    BINDING,
    FIRE_RESISTANCE,
    BAG_SLOTS,
    RECIPE_RANK,
    ITEM_STATS,
    INSTANCE_SOULBOUND,
)

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


def give_enabled(environ=None) -> bool:
    """On only when ITEMPLAN_GIVE says so; independent of shadow logging."""
    env = os.environ if environ is None else environ
    raw = str(env.get(GIVE_ENV_SWITCH, "") or "").strip().lower()
    return raw in ("on", "1", "true", "yes")


@dataclass(frozen=True)
class Extras:
    """Facts the plan can use that the economy pass's rows do not hold (#1973).

    A field left None was not read, or its read failed, and the plan fails
    closed without it; `unread` says why, keyed by the input's `ran without`
    name. An empty mapping is a real read that found nothing.

    `open_quest_items` is holder -> frozenset of entries an open quest names;
    left None, the adapter derives it from the carried query's own quest flag.
    `worn` is `itemplan_data.equipped`'s answer; with `templates` it yields the
    gear verdicts unless `gear_verdict` is given. `templates` is
    `itemplan_data.item_templates`' answer. `bank_free` is holder -> free
    slots in the personal bank and its bags. `guild_free` is (family, tab) ->
    free slots. `guild_roster` is ((name, trade, skill, online), ...), and
    `guild_crafters` contains only online members from that roster.
    """

    open_quest_items: Mapping[str, frozenset] | None = None
    gear_verdict: Mapping[tuple, str] | None = None
    worn: Mapping[str, dict] | None = None
    market: Mapping[int, tuple] | None = None
    guild_free: Mapping[tuple, int] | None = None
    guild_crafters: tuple | None = None
    guild_roster: tuple | None = None
    templates: Mapping[int, dict] | None = None
    bank_free: Mapping[str, int] | None = None
    instance_soulbound: Mapping[int, bool] | None = None
    fire_gear: frozenset | None = None
    unread: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Report:
    plan: itemplan.Plan
    lines: tuple  # every plan line
    disagreements: tuple  # every disagree line
    missing: tuple  # what the plan ran without
    detail: tuple = ()  # ((member, plan line, disagree lines, signature), ...)
    no_room: int = 0  # stacks no destination had room for


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


def build_stacks(rows, gear_rows=(), templates=None, instance_soulbound=None) -> list:
    """One itemplan.Stack per carried row, in row order within the holder.

    The surplus gear row (by item guid) wins; `templates` (by entry) fills in
    what it lacks, so a bind-on-pickup recipe reads as bound.
    """
    gear = {_int(r.get("item_guid")): r for r in gear_rows or ()}
    templates = templates or {}
    seen: dict = {}
    out = []
    for row in rows:
        holder = str(row["holder"])
        guid = _int(row.get("item_guid"))
        t = templates.get(_int(row.get("entry")), {})
        g = gear.get(guid) or {
            "item_subclass": t.get("subclass"),
            "bonding": t.get("bonding"),
            "required_level": t.get("req_level"),
            "item_level": t.get("item_level"),
        }
        soulbound = None if instance_soulbound is None else instance_soulbound.get(guid)
        raw_bonding = g.get("bonding")
        if raw_bonding is None:
            raw_bonding = t.get("bonding")
        binding_default = itemplan.BIND_NONE if raw_bonding is not None else None
        raw_required_level = g.get("required_level")
        if raw_required_level is None:
            raw_required_level = t.get("req_level")
        raw_item_level = g.get("item_level")
        if raw_item_level is None:
            raw_item_level = t.get("item_level")
        index = seen.get(holder, 0)
        seen[holder] = index + 1
        out.append(
            itemplan.Stack(
                holder=holder,
                loc=itemplan.CARRIED_BAG,
                entry=_int(row.get("entry")),
                name=str(row.get("name") or ""),
                item_class=_int(
                    row.get("item_class", g.get("item_class", t.get("item_class")))
                ),
                subclass=_int(g.get("item_subclass")),
                quality=_int(row.get("quality")),
                count=max(1, _int(row.get("count"), 1)),
                sell=max(0, _int(row.get("sell_price"))),
                bind=_int(raw_bonding, binding_default),
                req_level=_int(raw_required_level),
                item_level=_int(raw_item_level, 1),
                index=index,
                required_skill_rank=t.get("required_skill_rank"),
                container_slots=t.get("container_slots"),
                fire_res=t.get("fire_res"),
                soulbound=soulbound,
            )
        )
    return out


def build_members(
    names, family, stacks, free_slots, characters, bank_free=None
) -> list:
    """One itemplan.Member per name. Carried slots are free plus carried.

    `bank_free` (holder -> free personal bank slots, bank bags included) caps
    the bank route at the room that is really there. The plan keeps
    `BANK_RESERVE` slots free (the bank pass's own `BANK_FREE_RESERVE`), so a
    bank with 2 free takes nothing. The stacks the plan sees are the carried
    ones, so `bank_slots` is the free room itself. A holder missing from a
    mapping that was read has no room. None keeps the 28-slot default.
    """
    out = []
    for name in sorted(str(n) for n in names):
        carried = sum(1 for s in stacks if s.holder == name)
        free = _int((free_slots or {}).get(name), 0)
        class_id, level = (characters or {}).get(name, (0, 1))
        bank = {}
        if bank_free is not None:
            room = max(0, _int(bank_free.get(name), 0))
            bank = {"bank_slots": room}
        out.append(
            itemplan.Member(
                name=name,
                family=family,
                level=level,
                class_id=class_id,
                carried_slots=max(1, carried + max(0, free)),
                **bank,
            )
        )
    return out


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


_ABSENT_NOTE = {
    QUEST_LOG: "quest log",
    WORN_GEAR: "equipped gear verdicts",
    AUCTION_PRICES: "auction prices",
    GUILD_ROSTER: "guild roster",
    GUILD_ROOM: "guild bank room",
    BANK_CONTENTS: "bank contents",
    BINDING: "binding of non-gear rows",
    FIRE_RESISTANCE: "per-item fire resistance",
    BAG_SLOTS: "bag slot capacity",
    RECIPE_RANK: "recipe skill rank",
    ITEM_STATS: "item template stats",
    INSTANCE_SOULBOUND: "item-instance soulbound flags",
}


def _verdicts(extras: Extras, stacks, characters):
    """The gear verdicts: given, or worked out from worn gear and templates.

    None when they cannot be known: worn gear or templates were not read.
    """
    if extras.gear_verdict is not None:
        return extras.gear_verdict
    if extras.worn is None or extras.templates is None:
        return None
    bag = itemplan_data.verdict_rows(stacks, extras.templates, characters)
    return itemplan_data.upgrade_verdicts(extras.worn, bag)


def _missing(extras: Extras, verdicts=None) -> tuple:
    """What the plan ran without, in words, with the reason a read failed."""
    absent = {
        QUEST_LOG: extras.open_quest_items is None,
        WORN_GEAR: verdicts is None,
        AUCTION_PRICES: not extras.market,
        GUILD_ROSTER: extras.guild_crafters is None,
        GUILD_ROOM: extras.guild_free is None,
        BANK_CONTENTS: extras.bank_free is None,
        BINDING: extras.templates is None or BINDING in extras.unread,
        FIRE_RESISTANCE: extras.templates is None or FIRE_RESISTANCE in extras.unread,
        BAG_SLOTS: extras.templates is None or BAG_SLOTS in extras.unread,
        RECIPE_RANK: extras.templates is None or RECIPE_RANK in extras.unread,
        ITEM_STATS: extras.templates is None
        or extras.worn is None
        or ITEM_STATS in extras.unread,
        INSTANCE_SOULBOUND: extras.instance_soulbound is None
        or INSTANCE_SOULBOUND in extras.unread,
    }
    out = []
    for name in INPUTS:
        if not absent[name]:
            continue
        why = (extras.unread or {}).get(name)
        text = _ABSENT_NOTE[name]
        out.append("%s [%s]" % (text, why) if why else text)
    return tuple(out)


def _no_room(decision) -> bool:
    """True for a stack the plan could not place anywhere (NO_ROOM)."""
    return decision.reason.startswith(itemplan.NO_ROOM)


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
            "free after %d (%d with no vendor), no room %d, routes %s"
            % (
                PREFIX,
                m.name,
                len(mine),
                m.carried_slots,
                itemplan.free_now(m, mine),
                itemplan.free_after(plan_, m, mine),
                itemplan.free_after(plan_, m, mine, sales=False),
                sum(1 for d in plan_.by_holder(m.name) if _no_room(d)),
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
    """(holder, line) per stack and pass where the pass and the plan differ."""
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
                    (
                        d.holder,
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
                        ),
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
    stacks = build_stacks(
        rows,
        gear_rows,
        extras.templates,
        extras.instance_soulbound,
    )
    characters = characters_from_worn(worn_rows)
    members = build_members(
        names, family, stacks, free_slots, characters, extras.bank_free
    )
    verdicts = _verdicts(extras, stacks, characters)
    quest = extras.open_quest_items
    ctx = itemplan.Context(
        open_quest_items=quest,
        gear_verdict=verdicts or {},
        market=extras.market or {},
        guild_free=extras.guild_free or {},
        guild_crafters=extras.guild_crafters or (),
        fire_gear=extras.fire_gear,
    )
    plan_ = itemplan.plan(stacks, members, ctx)
    rows_by_key = {s.key: r for s, r in zip(stacks, rows, strict=True)}
    opinions = _opinions(rows, sales, keep_names, bank_keeps, clear)
    lines = _plan_lines(plan_, members, stacks)
    pairs = _disagreements(plan_, rows_by_key, opinions, keep_names)
    detail = []
    for m, line in zip(members, lines, strict=True):
        mine = tuple(text for holder, text in pairs if holder == m.name)
        shape = tuple(
            (d.key, d.route, d.target, d.tab, d.reason) for d in plan_.by_holder(m.name)
        )
        detail.append((m.name, line, mine, (line, mine, shape)))
    return Report(
        plan_,
        tuple(lines),
        tuple(text for _holder, text in pairs),
        _missing(extras, verdicts),
        tuple(detail),
        sum(1 for d in plan_.decisions if _no_room(d)),
    )


# member -> (signature, clock when its detail was last written), per family.
_LAST: dict = {}


def reset() -> None:
    """Forget what was logged, so the next tick writes every member in full."""
    _LAST.clear()


def _unread_all(why: str) -> Extras:
    return Extras(unread={name: why for name in INPUTS})


def _log_detail(report, out, family, state, now) -> int:
    """Write each member's plan and disagreement lines when they are news.

    News is a changed plan, or detail not written for REFRESH_SECONDS. Returns
    how many members were written.
    """
    written = 0
    for name, line, disagree, signature in report.detail:
        key = (family, name)
        last = state.get(key)
        if (
            last is not None
            and last[0] == signature
            and now - last[1] < REFRESH_SECONDS
        ):
            continue
        state[key] = (signature, now)
        written += 1
        for text in (line,) + disagree:
            out.info("%s", text)
    return written


def run(
    names,
    family,
    rows,
    free_slots,
    *,
    environ=None,
    logger=None,
    reader=None,
    state=None,
    clock=time.monotonic,
    **facts,
):
    """The economy pass's one call. Off: None. A failure is logged, not raised.

    `reader` (names, family, rows, gear_rows, worn_rows -> Extras) is called
    unless the caller passed `extras`; a reader that raises is logged and the
    plan runs without every input it would have read.
    """
    if not enabled(environ):
        return None
    out = logger or log
    try:
        if "extras" not in facts and reader is not None:
            try:
                facts["extras"] = reader(
                    names,
                    family,
                    rows,
                    facts.get("gear_rows", ()),
                    facts.get("worn_rows", ()),
                )
            except Exception as exc:
                out.exception(
                    "%s input reads failed; the plan runs without them", PREFIX
                )
                facts["extras"] = _unread_all("read failed: %s" % type(exc).__name__)
        report = shadow(names, family, rows, free_slots, **facts)
        written = _log_detail(
            report, out, family, _LAST if state is None else state, clock()
        )
        out.info(
            "%s tick: members %d, stacks %d, disagreements %d, no room %d, "
            "detail written for %d member(s), unchanged %d, ran without: %s",
            PREFIX,
            len(report.plan.members),
            len(report.plan.decisions),
            len(report.disagreements),
            report.no_room,
            written,
            len(report.detail) - written,
            "; ".join(report.missing) or "nothing",
        )
        return report
    except Exception:
        out.exception(
            "%s shadow failed; the economy pass is unaffected and carries on", PREFIX
        )
        return None
