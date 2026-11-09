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


def _displaced(pick, candidate, wearer, worn, book) -> tuple:
    """(displaced worn row or None, new total, old total) for one pick,
    over the slot group the pick is worn in - the arithmetic of
    equipscore's own per-group comparisons, over equipscore.value."""
    group = pick.slot
    if group in _SINGLE_GROUPS:
        on = _worn_in_group(worn, group)
        old_row = on[0] if on else None
        new = equipscore.value(candidate, wearer, _key(candidate), book)
        old = equipscore.value(old_row, wearer, _key(old_row), book)
        return old_row, new, old
    if group in _PAIR_GROUPS:
        on = _worn_in_group(worn, group)
        values = [(equipscore.value(r, wearer, "", book), r) for r in on]
        cand = equipscore.value(candidate, wearer, "", book)
        ranked = sorted(
            values + [(cand, candidate)], key=lambda t: (t[0][0], t[0][1]), reverse=True
        )
        kept = {id(r) for _v, r in ranked[:2]}
        displaced = next((r for r in on if id(r) not in kept), None)
        old = _total(v for v, _r in values)
        new = _total(v for v, _r in ranked[:2])
        return displaced, new, old
    # The weapon hands: the candidate's hand against the worn set, the
    # other hand unchanged (the module docstring owns the caveat). The
    # values are equipscore.value under the keys its hand judge uses:
    # a two-hander under "two_hand", any other main hand under
    # "main_hand", an off-hand weapon under "off_hand", a held piece
    # or shield under no key.
    main = next(
        (r for r in worn if _int(r.get("equipment_slot")) == equipscore.MAIN_HAND_SLOT),
        None,
    )
    off = next(
        (r for r in worn if _int(r.get("equipment_slot")) == equipscore.OFF_HAND_SLOT),
        None,
    )

    def main_value(row):
        key = (
            "two_hand"
            if _int(row.get("inventory_type")) == equipscore.TWO_HAND
            else "main_hand"
        )
        return equipscore.value(row, wearer, key, book)

    def off_value(row):
        key = (
            "off_hand"
            if _int(row.get("item_class")) == equipscore.ITEM_CLASS_WEAPON
            else ""
        )
        return equipscore.value(row, wearer, key, book)

    old = _total(
        [main_value(r) for r in (main,) if r is not None]
        + [off_value(r) for r in (off,) if r is not None]
    )
    if group == "two_hand":
        return main, main_value(candidate), old
    if group == "main_hand":
        parts = [main_value(candidate)]
        if off is not None:
            parts.append(off_value(off))
        return main, _total(parts), old
    parts = []
    if main is not None:
        parts.append(main_value(main))
    parts.append(off_value(candidate))
    return off, _total(parts), old


# --- the pass ------------------------------------------------------------------


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
    guilds: dict = {}
    wearers: dict = {}
    unjudged: list = []
    for row in wearer_rows or ():
        name = str(row.get("name") or "")
        if not name:
            continue
        guilds[name] = _guild_of(row)
        wearer = equipscore.wearer_from_row(row, tanks)
        if wearer is not None and wearer.spec:
            wearers[name] = wearer
        else:
            unjudged.append(name)

    worn: dict = {}
    carried: dict = {}
    for row in list(gear_rows or ()) + list(bank_rows or ()):
        holder = str(row.get("holder") or "")
        if _is_worn(row):
            worn.setdefault(holder, []).append(row)
        elif not bag_pressure.owner_keeps(str(row.get("name") or ""), keep_names):
            carried.setdefault(holder, []).append(row)
    for holder in carried:
        if holder != BANK_HOLDER and holder not in guilds and holder not in unjudged:
            unjudged.append(holder)

    # What each judged member's own equip pass would put on them is spoken
    # for: it never leaves its holder to become somebody else's route.
    spoken: dict = {}
    for name, wearer in wearers.items():
        picks = equipscore.choose(
            wearer, worn.get(name, ()), carried.get(name, ()), book
        )
        spoken[name] = {_int(e.guid) for e in picks}

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

    routes: list = []
    routed: set = set()
    for name in sorted(wearers):
        wearer = wearers[name]
        guild = guilds.get(name, "")
        available = [
            row
            for row in pool
            if str(row.get("holder") or "") != name
            and _int(row.get("item_guid")) not in routed
            and _same_guild(row, guilds, guild)
        ]
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
            routed.add(_int(pick.guid))
            displaced, new, old = _displaced(
                pick, row, wearer, worn.get(name, ()), book
            )
            routes.append(
                Route(
                    wearer=name,
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
            )

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
    if not bank_rows:
        notes.append(
            "no guild-bank gear was read, so only bags were routed; the guild "
            "bank joins the pool when a read supplies its rows"
        )
    return Report(
        routes=tuple(routes),
        members=len(guilds),
        judged=len(wearers),
        unjudged=tuple(sorted(unjudged)),
        candidates=len(pool),
        notes=tuple(notes),
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
