"""Translate a class quest move into command queue orders."""

from __future__ import annotations

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
