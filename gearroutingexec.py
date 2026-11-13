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

PURE: no MySQL, no clock. The caller reads the world and supplies `insert`.
"""

from __future__ import annotations

from dataclasses import dataclass

import bag_pressure
import gearrouting

WRITTEN = "written"
WOULD_WRITE = "would write"
STALE = "stale"
WAITING = "waiting"
DECLINED = "declined"

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


def _as_gear_route(route: gearrouting.Route, family) -> object:
    return bag_pressure.guild_route(
        holder=route.holder,
        taker=route.wearer,
        guid=route.guid,
        entry=route.entry,
        name=route.item,
        gain=_percent(route.gain),
        family=route.wearer in family,
        reason=route.reason,
    )


def _wait_reason(route, notes) -> str:
    lead = "%s stays with %s" % (route.item, route.holder)
    for note in notes:
        if note.startswith(lead):
            return note
    return "cannot reach %s this pass" % route.wearer


def execute(report, world: World, insert, dry_run: bool = False) -> Result:
    """Decide, and unless `dry_run`, write, every route in `report`.

    `insert(gear.Route) -> int` writes one hand-over row and returns how many
    it wrote (0: declined, e.g. already in the retry window or reserved).
    """
    family = set(world.family or ())
    carried = set(world.carried or ())
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
        else:
            live.append((index, _as_gear_route(route, family)))
    ready = bag_pressure.guild_route_deliverable(
        [g for _i, g in live],
        world.positions,
        world.at_mailbox,
        world.free_slots,
        per_pass=max(len(live), 1),
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
