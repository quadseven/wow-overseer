"""How one item changes hands between two characters, decided from where they stand (#189).

WHY THIS EXISTS. mod-overseer's `kind='give'` used to move an item between
two characters at any distance, in one database write. mod-overseer#566 made
it refuse unless the two stand on one map and within the core's trade
distance (TRADE_DISTANCE, 11.11 yards), with the sentence

    giver and receiver are too far apart to hand over; meet within trade range or mail it
    giver and receiver are on different maps; meet within trade range or mail it

Five passes wrote a give with no distance check of their own (bags, reagents,
guild surplus, gear, the town trip's conjured food). Against a module that
refuses, each of them would retry a row that can never land and then count
the pair as stuck. So each pass asks here first, and gets one of three
answers:

    give   the two stand together, inside trade range: hand it over.
    mail   the two are apart, the item may travel by post, and the giver
           stands at a mailbox now: post it. The receiver collects it on a
           later mailbox visit.
    ""     neither: the item waits, with one sentence saying what it waits on.
           A family walks together, so for two members this is the natural
           case and the hand-over happens on a later pass.

PURE MODULE: no MySQL, no clock. Positions are the snapshot rows the bridge
already reads for `gear.deliverable`, parsed by the same `gear.spots_from_rows`
and judged by the same `gear._within_trade_range` (through `bag_pressure`,
gear's one importer), so there is one opinion about "together" here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import bag_pressure

GIVE = bag_pressure.GIVE
MAIL = bag_pressure.MAIL

# The two refusals mod-overseer#566 added to DoGive, as the module words them
# (OverseerDecisions::GiveRangeRefusal). Matched on the stable head, so a
# change to the advice after the semicolon does not hide the wall.
TOO_FAR = "giver and receiver are too far apart to hand over"
OTHER_MAP = "giver and receiver are on different maps"
RANGE_REFUSALS = (TOO_FAR, OTHER_MAP)


def is_range_refusal(detail) -> bool:
    """Is this row's detail the module's distance wall on a give?

    A distance wall is a fact about where two characters stood for one
    second, not about the item or the pair, so it must never count toward
    `materials.stuck`.
    """
    text = str(detail or "").strip()
    return any(text.startswith(head) for head in RANGE_REFUSALS)


@dataclass(frozen=True)
class Verdict:
    """How the item moves now: `verb` is GIVE, MAIL or "" (it waits, `why`)."""

    verb: str
    why: str = ""


def spots(position_rows) -> dict:
    """name -> gear.Spot from fresh snapshot rows; a missing name is not in the world."""
    return bag_pressure.spots_from_rows(position_rows)


def _apart(giver, receiver, here, there) -> str:
    """The sentence for two characters who are not within trade range."""
    if int(here.map_id) != int(there.map_id):
        return "%s and %s are on different maps" % (giver, receiver)
    yards = math.hypot(here.x - there.x, here.y - there.y)
    return "%s and %s are %d yards apart, past the %s yards a hand-over needs" % (
        giver,
        receiver,
        int(round(yards)),
        bag_pressure.TRADE_YARDS,
    )


def verdict(giver, receiver, where, *, posting=(), mailable=False) -> Verdict:
    """How `giver` hands one item to `receiver` this pass.

    `where` is `spots(...)`. `posting` names the characters standing at a
    mailbox now. `mailable` says whether this item may go by post at all: a
    bag that is to be worn, or a conjured stack, may not, and a pass that
    wants the item handed over in person passes False.

    Never GIVE unless both are seen, on one map, inside trade range.
    """
    giver, receiver = str(giver), str(receiver)
    here = where.get(giver)
    if here is None:
        return Verdict("", "%s is not in the world" % giver)
    there = where.get(receiver)
    if there is not None and bag_pressure.within_trade_range(here, there):
        return Verdict(GIVE)
    if mailable and giver in set(posting or ()):
        return Verdict(MAIL)
    if there is None:
        why = "%s is not in the world" % receiver
    else:
        why = _apart(giver, receiver, here, there)
    if mailable:
        return Verdict(
            "", "%s; it goes by post when %s next stands at a mailbox" % (why, giver)
        )
    return Verdict("", "%s; it waits until they stand together" % why)


def waiting(item, giver, receiver, why) -> str:
    """The one log line for a hand-over that waits this pass."""
    return "%s from %s to %s waits: %s" % (item, giver, receiver, why)
