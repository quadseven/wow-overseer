"""Write the gear routing pass's decisions as guild hand-over rows (#2136).

`gearrouting.plan` decides which bind-on-equip piece should move to which
member and moves nothing. This module is the executor that report was left
waiting for. It adds NO judge: the routes are taken unchanged, in the
report's order, and turned into the same `gear.Route` (via bag_pressure) the guild hand-over
machinery already writes (`gear.route_deliverable` picks trade or post;
`guildroute.source_for` keys the audit trail; the caller's `insert` is the
bridge's `_insert_route`, which refuses any kind but a trade or a letter).
Nothing is ever a `give`, and nothing is granted: the piece is one the guild
already owns.

WHAT THE EXECUTOR ASKS IS THE WORLD'S QUESTION, NOT THE JUDGE'S. The report
is a snapshot; a route is written only if its piece is still in its holder's
bags (`World.carried`), and the holder can reach the wearer the way every
other hand-over does. A piece that has moved, been worn or been disposed of
is STALE and skipped; a route the world cannot carry yet WAITS, with the
machinery's own words for why. Both are visible in `Result.steps`, never
forced.

A dry run walks the same decisions and calls nothing: one step per report
route, in report order, with status WOULD_WRITE where a live run writes.

TWO CALLERS. The bridge's gear routing pass (`bridge._gear_routing_once`)
runs it live once a cycle, with `_insert_route` as `insert`, a per-pass cap,
the holders at a mailbox, the writer's retry window (`queued`) and the
operator's keep reservations (`kept`: a kept piece is never moved). The
site's dry-run read (`world_from_rows`, `dry_run_view`) builds the World from
rows it already reads and returns what WOULD be written, one line per route;
it has no mailbox read, so a dry run names trades only.

PURE: no MySQL, no clock. The caller reads the world and supplies `insert`.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure
import gearrouting
import keep

WRITTEN = "written"
WOULD_WRITE = "would write"
STALE = "stale"
WAITING = "waiting"
DECLINED = "declined"
KEPT = "kept"

# The statuses that are a hand-off DECISION, one log line each; a wait or a
# stale route is counted, not listed (bridge._log_capped says why).
DECISIONS = (WRITTEN, KEPT, DECLINED)

_BANK_WAIT = (
    "the guild bank is not a character: it cannot trade or post, so a bank "
    "piece waits for a member to withdraw it"
)


@dataclass(frozen=True)
class World:
    """What the executor needs to know that the report cannot."""

    carried: frozenset | set = frozenset()  # (holder, item guid) still in bags
    positions: dict | None = None  # name -> snapshot row (map_id, pos_x, ...)
    at_mailbox: tuple = ()  # holders standing at a mailbox
    free_slots: dict | None = None  # name -> free bag slots
    family: frozenset | set = frozenset()  # receivers a letter may go to
    # The operator's keep reservations (overseer_keep, keep.Reservations).
    kept: keep.Reservations = keep.Reservations()
    # (holder, item guid) already written inside the writer's retry window.
    queued: frozenset | set = frozenset()
    # Receivers a letter may go to. None reads as `family`. Every guild member
    # is postable: the guild post pass walks a member off the roster to its
    # mailbox and takes its post out (guildpost.py, #625).
    postable: frozenset | set | None = None


@dataclass(frozen=True)
class Step:
    """One report route and what became of it."""

    route: gearrouting.Route
    status: str
    why: str = ""
    row: object = None  # the gear.Route handed to `insert`, when there was one

    @property
    def said(self) -> str:
        """Who gave, who received, what piece - the audit line."""
        if self.row is not None:
            return self.row.said
        r = self.route
        return "%s -> %s, %s (item %d): %s" % (
            r.holder,
            r.wearer,
            r.item,
            r.guid,
            self.why or self.status,
        )


@dataclass(frozen=True)
class Result:
    steps: tuple = ()
    dry_run: bool = False

    @property
    def written(self) -> int:
        return sum(1 for s in self.steps if s.status == WRITTEN)


def _percent(gain) -> int:
    """The hand-over row's gain column is a whole number; the report's gain is
    a ratio (None for an empty slot), so it is carried as whole percent."""
    return 0 if gain is None else max(0, round(gain * 100))


def _as_gear_route(route: gearrouting.Route, postable) -> object:
    return bag_pressure.guild_route(
        holder=route.holder,
        taker=route.wearer,
        guid=route.guid,
        entry=route.entry,
        name=route.item,
        gain=_percent(route.gain),
        family=route.wearer in postable,
        reason=route.reason,
    )


def _wait_reason(route, notes) -> str:
    lead = "%s stays with %s" % (route.item, route.holder)
    for note in notes:
        if note.startswith(lead):
            return note
    return "cannot reach %s this pass" % route.wearer


def _kept(route, reservations) -> bool:
    """Does an overseer_keep reservation cover this piece on its holder?

    A keep has no form that lets its piece leave: bankpolicy reads it as
    "stays with this character" (in their own bank below its level, worn
    after it), and mod-overseer refuses to trade or mail a kept item. So a
    kept piece is never handed to `insert`, by guid or by entry.
    """
    name = str(route.holder or "").strip().lower()
    return (name, int(route.guid)) in reservations.guids or (
        name,
        int(route.entry),
    ) in reservations.entries


def execute(
    report, world: World, insert, dry_run: bool = False, per_pass=None
) -> Result:
    """Decide, and unless `dry_run`, write, every route in `report`.

    `insert(gear.Route) -> int` writes one hand-over row and returns how many
    it wrote (0: declined, e.g. already in the retry window or reserved).
    `per_pass` caps how many routes are written (None: every one that can
    be); a route past the cap waits, with the machinery's own words.
    """
    postable = (
        set(world.family or ()) if world.postable is None else set(world.postable)
    )
    carried = set(world.carried or ())
    queued = set(world.queued or ())
    steps: dict = {}
    live: list = []
    for index, route in enumerate(report.routes):
        if route.holder == gearrouting.BANK_HOLDER:
            steps[index] = Step(route, WAITING, _BANK_WAIT)
        elif (route.holder, route.guid) not in carried:
            steps[index] = Step(
                route,
                STALE,
                "%s is no longer in %s's bags, so it is not moved"
                % (route.item, route.holder),
            )
        elif _kept(route, world.kept):
            steps[index] = Step(
                route,
                KEPT,
                "%s keeps %s (overseer_keep), so it is not moved"
                % (route.holder, route.item),
            )
        elif (route.holder, route.guid) in queued:
            steps[index] = Step(
                route,
                WAITING,
                "%s is already queued to leave %s; not asked again this pass"
                % (route.item, route.holder),
            )
        else:
            live.append((index, _as_gear_route(route, postable)))
    ready = bag_pressure.guild_route_deliverable(
        [g for _i, g in live],
        world.positions,
        world.at_mailbox,
        world.free_slots,
        per_pass=max(len(live), 1) if per_pass is None else max(int(per_pass), 0),
    )
    by_key = {(g.holder, g.guid): g for g in ready.grants}
    for index, planned in live:
        route = report.routes[index]
        chosen = by_key.get((planned.holder, planned.guid))
        if chosen is None:
            steps[index] = Step(route, WAITING, _wait_reason(route, ready.notes))
        elif dry_run:
            steps[index] = Step(route, WOULD_WRITE, row=chosen)
        elif insert(chosen):
            steps[index] = Step(route, WRITTEN, row=chosen)
        else:
            steps[index] = Step(
                route, DECLINED, "the hand-over writer declined the row", row=chosen
            )
    return Result(
        steps=tuple(steps[i] for i in range(len(report.routes))), dry_run=dry_run
    )


# --- walking a waiting holder to a mailbox (#2503) ------------------------------

# How gear.py ends the wait note of a route whose holder is beside none of its
# receivers and stands at no mailbox: the one wall a walk to a mailbox fixes.
# A full bag, an absent wearer and a spent pass cap are other walls.
APART_NO_MAILBOX = ", and at no mailbox"


@dataclass(frozen=True)
class Waiting:
    """A waiting route in the shape guildroute.plan_mail_runs reads."""

    holder: str
    taker: str
    name: str
    guid: int
    gain: int
    family: bool = True
    alternates: tuple = ()


def fetchable(result: Result, postable) -> list:
    """The routes that wait only for their holder to reach a mailbox, in
    report order. The guild bank cannot walk; a stale, kept, queued or
    otherwise walled route is not here."""
    out = []
    postable = set(postable or ())
    for step in result.steps:
        r = step.route
        if step.status != WAITING or r.holder == gearrouting.BANK_HOLDER:
            continue
        if r.wearer not in postable or not step.why.endswith(APART_NO_MAILBOX):
            continue
        out.append(Waiting(r.holder, r.wearer, r.item, int(r.guid), _percent(r.gain)))
    return out


def walkable(waiting, busy=(), held=()) -> tuple:
    """(routes, notes): at most one route per holder, none whose holder another
    pass has on a walk or whose family an operator hold stands down."""
    busy, held = set(busy or ()), set(held or ())
    kept, notes, seen = [], [], set()
    for w in waiting:
        if w.holder in held:
            notes.append("%s stays with %s: held by operator hold" % (w.name, w.holder))
        elif w.holder in busy:
            notes.append(
                "%s stays with %s: %s is on another walk" % (w.name, w.holder, w.holder)
            )
        elif w.holder not in seen:
            seen.add(w.holder)
            kept.append(w)
    return kept, notes


def decision_lines(result: Result) -> list:
    """One plain line per hand-off decision (written, kept, declined), in
    report order: the status, then who gave, who received, what piece."""
    return [
        "%s: %s" % (step.status, step.said)
        for step in result.steps
        if step.status in DECISIONS
    ]


def summary(result: Result) -> str:
    """How many routes ended in each status, as one line."""
    counts: dict = {}
    for step in result.steps:
        counts[step.status] = counts.get(step.status, 0) + 1
    order = (WRITTEN, WOULD_WRITE, KEPT, DECLINED, WAITING, STALE)
    said = ", ".join("%d %s" % (counts[s], s) for s in order if counts.get(s))
    return "%s of %d route(s)" % (said or "nothing", len(result.steps))


def queued(seen) -> frozenset:
    """(holder, item guid) from the writer's retry window, (holder, command)
    pairs: a trade names `guid:<n>`, a letter `item:<n>` (keep.items_named)."""
    return frozenset(
        (str(holder), guid)
        for holder, command in seen or ()
        for guid in keep.items_named(command)[0]
    )


def carried(gear_rows) -> frozenset:
    """(holder, item guid) for every gear row not worn: what is in bags."""
    return frozenset(
        (str(r.get("holder") or ""), int(r.get("item_guid") or 0))
        for r in gear_rows or ()
        if not gearrouting._is_worn(r)
    )


# --- the read-only dry run -------------------------------------------------------

# The fresh snapshot rows a trade is judged on (map, instance, position).
POSITIONS_SQL = (
    "SELECT name, map_id, instance_id, zone_id, pos_x, pos_y "
    "FROM overseer_snapshot "
    "WHERE name IN ({holes}) AND updated_at > NOW() - INTERVAL 60 SECOND"
)

# Free bag slots per member, in the shape `gear.general_bag_room` reads: the
# backpack, then each worn bag with its kind and the items in it.
ROOM_SQL = (
    "SELECT c.name AS name, 0 AS bag_slot, 16 AS size, 1 AS bag_class, "
    "0 AS bag_subclass, "
    "(SELECT COUNT(*) FROM character_inventory ci WHERE ci.guid = c.guid "
    "AND ci.bag = 0 AND ci.slot BETWEEN 23 AND 38) AS used "
    "FROM characters c WHERE c.name IN ({holes}) "
    "UNION ALL "
    "SELECT c.name AS name, b.slot AS bag_slot, "
    "COALESCE(it.ContainerSlots, 0) AS size, it.class AS bag_class, "
    "it.subclass AS bag_subclass, "
    "(SELECT COUNT(*) FROM character_inventory ci WHERE ci.guid = c.guid "
    "AND ci.bag = b.item) AS used "
    "FROM characters c "
    "JOIN character_inventory b ON b.guid = c.guid AND b.bag = 0 "
    "AND b.slot BETWEEN 19 AND 22 "
    "LEFT JOIN item_instance ii ON ii.guid = b.item "
    "LEFT JOIN acore_world.item_template it ON it.entry = ii.itemEntry "
    "WHERE c.name IN ({holes})"
)


def members_to_read(report, wearer_names) -> list:
    """Every name the world must know: the wearers AND the holders, whose
    bags the pieces sit in. The guild bank is a label, not a member."""
    names = {str(n) for n in wearer_names or () if n}
    names |= {r.holder for r in report.routes}
    names.discard(gearrouting.BANK_HOLDER)
    names.discard("")
    return sorted(names)


def world_from_rows(gear_rows, position_rows, room_rows, family=()) -> World:
    """The World from rows a read supplies. Pure.

    `gear_rows` are the routing read's scored-gear rows: a row with no worn
    slot is carried. `position_rows` are fresh snapshot rows; a member
    missing from them is not in the world. `room_rows` are ROOM_SQL's.
    """
    positions = {str(r["name"]): dict(r) for r in position_rows or () if r.get("name")}
    room = {
        name: free
        for name, (free, _total) in bag_pressure.general_bag_room(room_rows).items()
    }
    return World(
        carried=carried(gear_rows),
        positions=positions,
        at_mailbox=(),
        free_slots=room,
        family=frozenset(family or ()),
    )


def dry_run_view(report, world: World) -> dict:
    """What a live run would do with `report`, as data. Writes nothing."""
    result = execute(report, world, lambda _row: 0, dry_run=True)
    steps = []
    for step in result.steps:
        r = step.route
        steps.append(
            {
                "holder": r.holder,
                "wearer": r.wearer,
                "guid": r.guid,
                "item": r.item,
                "status": step.status,
                "verb": step.row.verb if step.row is not None else "",
                "why": step.why,
            }
        )
    return {
        "dry_run": True,
        "would_write": sum(1 for s in steps if s["status"] == WOULD_WRITE),
        "steps": steps,
        "lines": ["%s: %s" % (step.status, step.said) for step in result.steps],
        "notes": [
            "dry run: nothing was written",
            "letters were not considered (no mailbox read here), so only "
            "trades between members standing together are listed",
        ],
    }
