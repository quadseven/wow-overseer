"""Which bind-on-equip piece in the wrong bags should move to which member.

THE GAP THIS FILLS. The equip pass (`equipscore.plan`) puts a member's OWN
best carried piece on them, and `gear.route_plan` hands a guildmate's loot
onward - but it ranks by item level, the judge the equip pass retired for
exactly the failures equipscore.py's docstring measures. Nobody ran the
SPEC SCORE across the guild: a bind-on-equip upgrade sits in one member's
bags while another member wears an antique in that slot, and the two facts
never meet. This module is that meeting. It is a dry run: it decides and it
reports, and it moves nothing. The rows that move an item already exist
(`gear.route_plan`'s guildroute rows, the give/mail machinery of #189); an
executor reads this report's routes and writes them, and until one does,
this pass is the audit a person can read before anything changes hands.

THE JUDGE IS NOT REWRITTEN HERE. Every comparison is `equipscore.choose`
over the wearer's worn pieces and a carried pool widened to the guild: the
same spec (the played talent tree, `equipscore.wearer_from_row`), the same
refusals (level, class, race, proficiency, the off-hand guards), and the
same margin - a routed piece beats what is worn by MIN_GAIN of the deciding
score (`equipscore.beats`), the ten percent the equip pass and
mod-playerbots' own equip both ask, so a route never asks for a sidegrade
the bot would take straight back off.

WHOSE BAGS ARE A SOURCE, AND WHOSE ARE NOT.
  * Bind-on-equip copies only, read off the INSTANCE
    (`bag_pressure.item_binding`): a bind-on-pickup piece cannot move, and
    a bind-on-equip copy somebody already wore is soulbound whatever its
    template says. A piece whose binding cannot be read is refused - the
    reading that closes the most doors.
  * A piece its own holder's equip pass would put on them never leaves:
    every judged member's own `choose` runs first, and its picks are
    spoken for. Taking a member's pending upgrade to route it elsewhere
    would trade one antique for another.
  * A piece whose holder cannot be judged (no member row, or no spec the
    scorer can settle) is left where it is, for the same reason: this pass
    cannot prove it is spare. The holder is named in the report's unjudged
    list rather than silently skipped.
  * A holder's never-dispose mark (`bag_pressure.owner_keeps`) keeps a
    piece out of the pool, exactly as it keeps it out of the equip pass.
  * Nothing crosses a guild line. Bags route inside one guild; the guild
    bank (holder `guild bank`, the label the bridge's own bank reads use)
    routes inside its own.

ONE PIECE, ONE PROMISE. Members are considered in name order and a routed
guid leaves the pool, so the same physical piece is never promised to two
members. A routed piece also had to beat everything the wearer already
carries, not only what they wear: the wearer's own bags are in the pool
`choose` sees, so a route is only ever the best piece the wearer does not
hold.

THE GAIN A ROUTE NAMES is the relative gain on the axis `equipscore.beats`
decided by - the gear score, or the role score when the spec scores
neither piece - recomputed from `equipscore.value` over the slot the pick
displaces. For the weapon hands the pick is judged as a set by `choose`;
the gain here is the candidate's hand against the worn set with the other
hand unchanged, and the route's `reason` (equipscore's own words) carries
the set verdict. Where the slot was empty there is no gain to name: the
old score is zero and the route says so with a gain of None.

PURE: rows in, a Report out. The bridge and the site read the rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure
import disposition
import equipscore

# The holder label the bridge's guild-bank reads already use
# (_CRAFTER_GUILD_BANK_SQL: 'guild bank' AS holder).
BANK_HOLDER = "guild bank"

# equipscore._KEY's ranged entries: the weapon DPS key a ranged piece is
# scored under. A label, not a weight - the weights are gearscore's.
_RANGED_KEY = {15: "ranged", 25: "ranged", 26: "ranged", 28: "ranged"}
_SINGLE_GROUPS = frozenset(equipscore.SINGLE.values())
_PAIR_GROUPS = frozenset(equipscore.PAIRS.values())


@dataclass(frozen=True)
class Route:
    """One piece that should change hands, and the audit trail for it."""

    wearer: str  # who should receive and wear it
    holder: str  # who holds it now: a member name, or BANK_HOLDER
    guid: int
    entry: int
    item: str  # the candidate's name
    slot: str  # the equipscore slot group it is worn in
    worn: str  # the piece it replaces ("" when the slot was empty)
    worn_entry: int
    gain: float | None  # relative gain on the deciding axis (None: empty slot)
    reason: str  # equipscore's own words for the pick


@dataclass(frozen=True)
class Report:
    """The whole pass: the routes, and the coverage they were decided over."""

    routes: tuple = ()
    members: int = 0  # member rows read
    judged: int = 0  # members the scorer could judge
    unjudged: tuple = ()  # names it could not (no row facts, or no spec)
    candidates: int = 0  # bind-on-equip pieces the pools held
    notes: tuple = ()


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_worn(row: dict) -> bool:
    slot = row.get("equipment_slot")
    return slot is not None and 0 <= _int(slot, -1) < 19


def _guild_of(row: dict) -> str:
    return str(row.get("guild") or "")


def _same_guild(row: dict, guilds: dict, guild: str) -> bool:
    """Is this pool row in `guild`: a bank row by the guild it names, a
    member's row by its holder's guild (the member row outranks the gear
    row's own guild column, which the same read fills from the same join)."""
    holder = str(row.get("holder") or "")
    if holder == BANK_HOLDER:
        return _guild_of(row) == guild
    return guilds.get(holder, _guild_of(row)) == guild


# --- the gain a route names ----------------------------------------------------


def _key(row) -> str:
    return _RANGED_KEY.get(_int((row or {}).get("inventory_type")), "")


def _worn_in_group(worn, group: str) -> list:
    return [
        r
        for r in worn
        if equipscore.WORN_GROUP.get(_int(r.get("equipment_slot"))) == group
    ]


def _total(values) -> tuple:
    out = (0.0, 0.0)
    for gs, rs in values:
        out = (out[0] + gs, out[1] + rs)
    return out


def _gain(new: tuple, old: tuple) -> float | None:
    """The relative gain on the axis equipscore.beats decides by, or None
    when the old score is zero (an empty slot: any real score is a gain,
    and no ratio names it)."""
    axis = 0 if max(new[0], old[0]) >= equipscore.SCORE_FLOOR else 1
    if old[axis] <= equipscore.EPSILON:
        return None
    return new[axis] / old[axis] - 1.0


def _single_displacement(pick, candidate, wearer, worn, book) -> tuple:
    """Score a pick in a slot with only one worn item."""
    on = _worn_in_group(worn, pick.slot)
    old_row = on[0] if on else None
    new = equipscore.value(candidate, wearer, _key(candidate), book)
    old = equipscore.value(old_row, wearer, _key(old_row), book)
    return old_row, new, old


def _paired_displacement(pick, candidate, wearer, worn, book) -> tuple:
    """Score a pick against both worn slots in a paired gear group."""
    on = _worn_in_group(worn, pick.slot)
    values = [(equipscore.value(row, wearer, "", book), row) for row in on]
    cand = equipscore.value(candidate, wearer, "", book)
    ranked = sorted(
        values + [(cand, candidate)],
        key=lambda pair: (pair[0][0], pair[0][1]),
        reverse=True,
    )
    kept = {id(row) for _value, row in ranked[:2]}
    displaced = next((row for row in on if id(row) not in kept), None)
    old = _total(value for value, _row in values)
    new = _total(value for value, _row in ranked[:2])
    return displaced, new, old


def _main_hand_value(row, wearer, book):
    """Score a main-hand item with the key used by the equip judge."""
    key = (
        "two_hand"
        if _int(row.get("inventory_type")) == equipscore.TWO_HAND
        else "main_hand"
    )
    return equipscore.value(row, wearer, key, book)


def _off_hand_value(row, wearer, book):
    """Score an off-hand weapon or held item with the equip judge's key."""
    key = (
        "off_hand"
        if _int(row.get("item_class")) == equipscore.ITEM_CLASS_WEAPON
        else ""
    )
    return equipscore.value(row, wearer, key, book)


def _weapon_displacement(group, candidate, wearer, worn, book) -> tuple:
    """Score one weapon-hand pick against the current pair of hands."""
    main = next(
        (
            row
            for row in worn
            if _int(row.get("equipment_slot")) == equipscore.MAIN_HAND_SLOT
        ),
        None,
    )
    off = next(
        (
            row
            for row in worn
            if _int(row.get("equipment_slot")) == equipscore.OFF_HAND_SLOT
        ),
        None,
    )
    old_parts = [_main_hand_value(main, wearer, book)] if main is not None else []
    if off is not None:
        old_parts.append(_off_hand_value(off, wearer, book))
    old = _total(old_parts)
    if group == "two_hand":
        return main, _main_hand_value(candidate, wearer, book), old
    if group == "main_hand":
        parts = [_main_hand_value(candidate, wearer, book)]
        if off is not None:
            parts.append(_off_hand_value(off, wearer, book))
        return main, _total(parts), old
    parts = [_main_hand_value(main, wearer, book)] if main is not None else []
    parts.append(_off_hand_value(candidate, wearer, book))
    return off, _total(parts), old


def _displaced(pick, candidate, wearer, worn, book) -> tuple:
    """Return the displaced row and old/new scores for one equip pick."""
    if pick.slot in _SINGLE_GROUPS:
        return _single_displacement(pick, candidate, wearer, worn, book)
    if pick.slot in _PAIR_GROUPS:
        return _paired_displacement(pick, candidate, wearer, worn, book)
    # Weapon hands are judged as a set, with the untouched hand preserved.
    return _weapon_displacement(pick.slot, candidate, wearer, worn, book)


# --- the pass ------------------------------------------------------------------


def _wearers(rows, tanks):
    guilds: dict = {}
    wearers: dict = {}
    unjudged: list = []
    for row in rows:
        name = str(row.get("name") or "")
        if not name:
            continue
        guilds[name] = _guild_of(row)
        wearer = equipscore.wearer_from_row(row, tanks)
        if wearer is not None and wearer.spec:
            wearers[name] = wearer
        else:
            unjudged.append(name)
    return guilds, wearers, unjudged


def _gear_by_holder(gear_rows, bank_rows, keep_names, guilds, unjudged):
    worn: dict = {}
    carried: dict = {}
    for row in gear_rows + bank_rows:
        holder = str(row.get("holder") or "")
        if _is_worn(row):
            worn.setdefault(holder, []).append(row)
        elif not bag_pressure.owner_keeps(str(row.get("name") or ""), keep_names):
            carried.setdefault(holder, []).append(row)
    for holder in carried:
        if holder != BANK_HOLDER and holder not in guilds and holder not in unjudged:
            unjudged.append(holder)
    return worn, carried, unjudged


def _spoken_items(wearers, worn, carried, book):
    spoken: dict = {}
    for name, wearer in wearers.items():
        picks = equipscore.choose(
            wearer, worn.get(name, ()), carried.get(name, ()), book
        )
        spoken[name] = {_int(e.guid) for e in picks}
    return spoken


def _routing_pool(carried, wearers, spoken):
    pool: list = []
    for holder, rows in carried.items():
        if holder != BANK_HOLDER and holder not in wearers:
            continue
        for row in rows:
            if bag_pressure.item_binding(row) != disposition.BIND_ON_EQUIP:
                continue
            if _int(row.get("item_guid")) in spoken.get(holder, set()):
                continue
            pool.append(row)
    return pool


def _available_for(wearer_name, guild, guilds, pool, routed):
    return [
        row
        for row in pool
        if str(row.get("holder") or "") != wearer_name
        and _int(row.get("item_guid")) not in routed
        and _same_guild(row, guilds, guild)
    ]


def _route_pick(pick, row, wearer, worn, book):
    displaced, new, old = _displaced(pick, row, wearer, worn, book)
    return Route(
        wearer=wearer.name,
        holder=str(row.get("holder") or ""),
        guid=_int(pick.guid),
        entry=_int(row.get("entry")),
        item=str(row.get("name") or ""),
        slot=pick.slot,
        worn=str((displaced or {}).get("name") or ""),
        worn_entry=_int((displaced or {}).get("entry")),
        gain=_gain(new, old),
        reason=pick.reason,
    )


def _routes_for(wearers, guilds, worn, carried, pool, book):
    routes: list = []
    routed: set = set()
    for name in sorted(wearers):
        wearer = wearers[name]
        guild = guilds.get(name, "")
        available = _available_for(name, guild, guilds, pool, routed)
        if not available:
            continue
        by_guid = {_int(r.get("item_guid")): r for r in available}
        picks = equipscore.choose(
            wearer,
            worn.get(name, ()),
            list(carried.get(name, ())) + available,
            book,
        )
        for pick in picks:
            row = by_guid.get(_int(pick.guid))
            if row is None:
                continue
            routes.append(_route_pick(pick, row, wearer, worn.get(name, ()), book))
            routed.add(_int(pick.guid))
    return routes


def _notes(unjudged, has_bank_rows):
    notes: list = []
    if unjudged:
        notes.append(
            "%d member%s could not be scored (no spec the scorer can settle) "
            "and were left out of the routing: %s"
            % (
                len(unjudged),
                "" if len(unjudged) == 1 else "s",
                ", ".join(sorted(unjudged)),
            )
        )
    if not has_bank_rows:
        notes.append(
            "no guild-bank gear was read, so only bags were routed; the guild "
            "bank joins the pool when a read supplies its rows"
        )
    return tuple(notes)


def plan(wearer_rows, gear_rows, bank_rows=(), keep_names=(), tanks=(), book=None):
    """Every cross-member upgrade in the guilds the rows describe.

    `wearer_rows` are member rows for `equipscore.wearer_from_row` (one per
    member of each guild, carrying `guild`); `gear_rows` are worn
    (`equipment_slot` 0..18) and carried rows in the scored-gear shape plus
    `bonding` and `instance_flags`, each naming its `holder` and `guild`;
    `bank_rows` are the guild bank's rows in the same shape, holder
    BANK_HOLDER. A member the scorer cannot judge is counted and named,
    never routed to or from.
    """
    members = list(wearer_rows or ())
    gear = list(gear_rows or ())
    bank = list(bank_rows or ())
    guilds, wearers, unjudged = _wearers(members, tanks)
    worn, carried, unjudged = _gear_by_holder(gear, bank, keep_names, guilds, unjudged)
    spoken = _spoken_items(wearers, worn, carried, book)
    pool = _routing_pool(carried, wearers, spoken)
    routes = _routes_for(wearers, guilds, worn, carried, pool, book)
    return Report(
        routes=tuple(routes),
        members=len(guilds),
        judged=len(wearers),
        unjudged=tuple(sorted(unjudged)),
        candidates=len(pool),
        notes=_notes(unjudged, bool(bank)),
    )


# --- the report ----------------------------------------------------------------


def build(report: Report) -> dict:
    """The payload the site serves: the routes and the coverage, as data."""
    return {
        "min_gain": equipscore.MIN_GAIN,
        "members": report.members,
        "judged": report.judged,
        "unjudged": list(report.unjudged),
        "candidates": report.candidates,
        "notes": list(report.notes),
        "routes": [
            {
                "wearer": r.wearer,
                "holder": r.holder,
                "guid": r.guid,
                "entry": r.entry,
                "item": r.item,
                "slot": r.slot,
                "worn": r.worn,
                "worn_entry": r.worn_entry,
                "gain": None if r.gain is None else round(r.gain, 4),
                "reason": r.reason,
            }
            for r in report.routes
        ],
    }


def lines(report: Report) -> list:
    """One sentence per route, in the order the pass decided them."""
    out = []
    for r in report.routes:
        replaces = "replacing %s" % r.worn if r.worn else "filling an empty slot"
        gain = "" if r.gain is None else ", a %.0f%% gain" % (r.gain * 100)
        out.append(
            "%s's %s goes to %s for their %s (%s; %s%s)"
            % (r.holder, r.item, r.wearer, r.slot, r.reason, replaces, gain)
        )
    return out


def headline(report: Report) -> str:
    """One line over the report, saying nothing rather than inventing one.

    The empty cases are different and are said differently: nobody could
    be scored, nothing movable was found, and movable pieces existed but
    none cleared the margin are three different states of the guild."""
    if not report.judged:
        return "nobody in either guild could be scored, so nothing was routed"
    if not report.routes:
        if not report.candidates:
            return (
                "%d member%s scored, and no bind-on-equip gear is sitting in "
                "the wrong bags" % (report.judged, "" if report.judged == 1 else "s")
            )
        return (
            "%d bind-on-equip piece%s were looked at, and none beats what "
            "its would-be wearer already wears by the margin"
            % (report.candidates, "" if report.candidates == 1 else "s")
        )
    return (
        "%d upgrade%s routed to %d member%s, out of %d bind-on-equip piece%s looked at"
        % (
            len(report.routes),
            "" if len(report.routes) == 1 else "s",
            len({r.wearer for r in report.routes}),
            "" if len({r.wearer for r in report.routes}) == 1 else "s",
            report.candidates,
            "" if report.candidates == 1 else "s",
        )
    )
