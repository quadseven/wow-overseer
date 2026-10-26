"""One executor for a class quest Move: the orders it sends, and nothing else.

classquest.py plans (rows in, a Move out); turning that Move into realm orders
is spread over guildjobs.py (which builds the rows) and bridge.py (which writes
and follows them). `run` is the one place that maps a Move kind to the orders
it sends, and it talks only to orders.send (quadseven/wow-overseer#739):

  take, turnin   a walk to the giver or ender, then `take|turnin quest:<id>`
  hunt           a walk to the pack, then the `hunt-spawn` row the caller built
  use            a walk to the target, then the use row
  cross          one `cross-to-map` row, no walk
  abandon        one `abandon quest:<id>` row, no walk
  blocked        nothing; the Move's reason is on the result

This is the shadow slice. The bridge calls `run` against an orders.MemoryStore
next to the writers it already has and logs whether the two agree; no writer
here replaces one there. Nothing here grants an item, gold or XP: every verb
is one a player could ask by walking and talking.
"""

from __future__ import annotations

import os

import classhunt
import classquest
import guildjobs
import guildroute
import orders

# CLASSQUEST_EXECUTOR: "shadow" (the default) runs `run` beside the writers and
# logs a comparison; "off" does not run it.
MODE_ENV = "CLASSQUEST_EXECUTOR"
SHADOW, OFF = "shadow", "off"


def mode() -> str:
    """The executor mode from the environment; an unknown word is an error."""
    value = os.environ.get(MODE_ENV, SHADOW).strip().lower() or SHADOW
    if value not in (SHADOW, OFF):
        raise ValueError("%s must be %s or %s" % (MODE_ENV, SHADOW, OFF))
    return value


class Sent(list):
    """The orders `run` sent, in order, and `reason` for a blocked Move."""

    reason: str = ""


def _order(member, kind, command, source) -> orders.Order:
    return orders.Order(
        target=member, command=command, source=source, kind=kind, target_arg=""
    )


def _walk(move, member, cap, source_action) -> orders.Order:
    spot = guildjobs.class_spot(move)
    return _order(
        member,
        "job",
        spot.command + guildroute.errand_cap_word(cap),
        guildjobs.source_for(source_action, member),
    )


def _row(move, member, hunt) -> orders.Order | None:
    """The order that does the Move's work once the member is there."""
    source = guildjobs.source_for(classquest.ACTION, member)
    if move.kind == classquest.HUNT:
        return _order(member, "job", hunt, source) if hunt else None
    if move.kind == classquest.USE:
        command = classquest.use_command(move.use, move.spot)
    elif move.kind == classquest.ABANDON:
        command = "abandon quest:%d" % int(move.quest)
    else:
        verb = "turnin" if move.kind == classquest.TURN_IN else "take"
        command = "%s quest:%d" % (verb, int(move.quest))
    return _order(member, "quest", command, source)


def _plan(move, member, cap, walk, hunt) -> list:
    """The orders a Move calls for, in the order they are sent."""
    if move.kind == classquest.CROSS:
        source = guildjobs.source_for(classquest.CROSS_ACTION, member)
        return [_order(member, "job", classquest.cross_command(move.to_map), source)]
    if move.kind == classquest.ABANDON:
        return [_row(move, member, hunt)]
    wanted = []
    if walk:
        # A hunt with no row to write is the walk alone, as the planner makes it.
        action = classquest.ACTION
        if move.kind != classquest.HUNT or hunt:
            action += "-walk"
        wanted.append(_walk(move, member, cap, action))
    row = _row(move, member, hunt)
    return wanted + ([row] if row is not None else [])


def run(move, orders_store, member, cap=0, walk=True, hunt="") -> Sent:
    """Send the orders one Move calls for to `orders_store`.

    `member` is the character the orders are for. `cap` is the walk cap the
    walk row asks for (guildroute.errand_cap_word). `walk` is False for a
    member already beside its target, who needs no walk row. `hunt` is the
    `hunt-spawn` command classhunt built for a HUNT Move; empty, a hunt is the
    walk alone. A blocked Move sends nothing and leaves its reason on the
    result.
    """
    sent = Sent()
    if move.kind == classquest.BLOCKED:
        sent.reason = move.why
        return sent
    for order in _plan(move, member, cap, walk, hunt):
        orders.send(orders_store, order)
        sent.append(order)
    return sent


def _rows_as_orders(step) -> list:
    """The orders the planner's own rows for `step` are, walk first."""
    rows = ([step.walk] if step.walk is not None else []) + list(step.rows)
    return [_order(step.holder, r.kind, r.command, r.source) for r in rows]


def compare(step, cap) -> tuple:
    """(match, new, old) for one class quest step: what `run` sends for the
    step's Move against the orders its rows are, both as lists of Orders.

    The hunt row is taken from the step, since classhunt builds it from the
    book and the hunt clock, which `run` does not read. A hunt step with no
    such row is the walk alone, which the planner writes as its only row.
    """
    old = _rows_as_orders(step)
    hunt = old[-1].command if old and classhunt.is_hunt_row(old[-1].command) else ""
    walk = step.walk is not None or (step.move.kind == classquest.HUNT and not hunt)
    new = run(step.move, orders.MemoryStore(), step.holder, cap, walk, hunt)
    return list(new) == old, list(new), old


def line(step, cap) -> str:
    """The shadow comparison log line for one class quest step."""
    match, new, old = compare(step, cap)
    return "classquest executor: %s %s match=%s new=%s old=%s" % (
        step.holder,
        step.move.kind,
        str(match).lower(),
        [(o.kind, o.command) for o in new],
        [(o.kind, o.command) for o in old],
    )
