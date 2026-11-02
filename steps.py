"""Translate a class quest move into command queue orders."""

from __future__ import annotations

import os

import classhunt
import classquest
import guildjobs
import orders


def _checked(move: classquest.Move) -> tuple[str, int]:
    """The member a move names and its quest id; a move missing either, or a
    hunt with no spot, raises rather than send an order to no one."""
    if not move.said:
        raise ValueError("class quest %s move names no member" % move.kind)
    if move.quest is None:
        raise ValueError("class quest %s move has no quest" % move.kind)
    if move.kind == classquest.HUNT and move.spot is None:
        raise ValueError("class quest hunt move has no spot")
    return move.said.split(" ", 1)[0], int(move.quest)


def _order(move: classquest.Move) -> orders.Order | None:
    """Build the action order for one executable move."""
    if move.kind == classquest.BLOCKED:
        return None
    target, quest = _checked(move)
    source = guildjobs.source_for(classquest.ACTION, target)
    if move.kind == classquest.TAKE:
        return orders.Order(target, "take quest:%d" % quest, source, "quest")
    if move.kind == classquest.HUNT:
        command = "%s creature:%d max:%d" % (
            classhunt.VERB,
            int(move.spot.entry),
            classhunt.MAX_SECONDS,
        )
        return orders.Order(target, command, source, "job")
    if move.kind == classquest.TURN_IN:
        return orders.Order(target, "turnin quest:%d" % quest, source, "quest")
    if move.kind == classquest.USE:
        command = classquest.use_command(move.use, move.spot)
        return orders.Order(target, command, source, "quest")
    if move.kind == classquest.CROSS:
        command = classquest.cross_command(move.to_map)
        return orders.Order(target, command, source, "job")
    if move.kind == classquest.ABANDON:
        return orders.Order(target, "abandon quest:%d" % quest, source, "quest")
    raise ValueError("unknown class quest move kind: %s" % move.kind)


def run(move: classquest.Move, orders_store) -> list[orders.Order] | str:
    """Send a move's action order and return it, or its reason when blocked."""
    order = _order(move)
    if order is None:
        return move.why
    orders.send(orders_store, order)
    return [order]


# SHADOW MODE (quadseven/wow-overseer#739). The bridge still writes the class
# quest rows itself. With CLASSQUEST_EXECUTOR=shadow (the default) it also asks
# `run` what it would send, against a memory queue that never touches the realm,
# and logs one line per move so the two can be compared before any writer goes.
MODE_ENV = "CLASSQUEST_EXECUTOR"
SHADOW = "shadow"
OFF = "off"


def mode(environ=None) -> str:
    """SHADOW when the variable is unset or says shadow; OFF for any other word."""
    value = (os.environ if environ is None else environ).get(MODE_ENV, SHADOW)
    return SHADOW if value.strip().lower() in ("", SHADOW) else OFF


def _shown(rows) -> str:
    return " | ".join("%s/%s" % (kind, command) for kind, command in rows) or "-"


def shadow_line(move: classquest.Move, old_rows) -> str:
    """The comparison line for one move: what `run` sends to a MemoryStore
    against `old_rows`, the rows (anything with .kind and .command) the bridge
    writes for the same move. Reads and writes nothing else."""
    store = orders.MemoryStore()
    result = run(move, store)
    new = [(o.kind, o.command) for o in result] if isinstance(result, list) else []
    old = [(r.kind, r.command) for r in old_rows]
    return "classquest executor: %s %s match=%s new=%s old=%s" % (
        move.said.split(" ", 1)[0] if move.said else "?",
        move.kind,
        "true" if new == old else "false",
        _shown(new),
        _shown(old),
    )
