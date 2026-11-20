"""Bring a routed piece's holder and wearer together (#2503).

`gearroutingexec` writes a hand-over only when the holder already stands beside
the wearer or at a mailbox. Most waiting routes are guild bot to guild bot, and
nothing moves either of them. This module is the PURE planner for that gap: it
turns the routes that wait into fetches and says why for every one it will not
fetch. It reads no database and no clock, and it writes nothing.

Two kinds of fetch:

- MAILBOX: the wearer is on the family roster and the holder is a walkable
  guild bot. The existing mailbox run planner (`guildroute.plan_mail_runs`)
  already walks the holder, so this plan carries no row; it only names the
  route so the caller does not plan a second walk for it.
- MEET: neither character is on the roster. Both get the module's
  `walk-to-spawn gameobject:<mailbox spawn>` row with a `stay:` hold, to one
  mailbox near the wearer. When both have arrived the caller runs the routing
  pass once so the trade is written while they stand together.

A roster leader or follower is never walked here: that spends the family's one
travel seat (the town slot owns it). Nothing is granted; only the executor's
trade and letter rows move an item.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import gearrouting
import gearroutingexec
import guildroute
import keep

MAILBOX = "mailbox"
MEET = "meet"

# The furthest a member walks to the meeting mailbox, in yards.
MEET_YARDS = guildroute.MAIL_RUN_YARDS
# Seconds the first to arrive is held at the mailbox for the other.
MEET_STAY_SECONDS = 600
# Fetches the pass may start, the realm in any day, and the ones under way.
PER_PASS = 2
PER_DAY = 12
AT_ONCE = 4


@dataclass(frozen=True)
class Member:
    """What the planner needs to know about one character."""

    name: str
    map_id: int
    x: float
    y: float
    in_combat: bool = False
    in_instance: bool = False
    roster: bool = False  # a family leader or follower
    family: str = ""  # the family it belongs to, "" for a guild bot off one


@dataclass(frozen=True)
class Mailbox:
    map_id: int
    spawn: int
    x: float
    y: float


@dataclass(frozen=True)
class Fetch:
    kind: str
    route: gearrouting.Route
    mailbox: int = 0
    walks: tuple = ()  # ((member name, walk command), ...)

    @property
    def said(self) -> str:
        r = self.route
        if self.kind == MAILBOX:
            return "%s (item %d) goes to %s by the mailbox run" % (
                r.holder,
                r.guid,
                r.wearer,
            )
        return "%s and %s meet at mailbox %d for %s (item %d)" % (
            r.holder,
            r.wearer,
            self.mailbox,
            r.item,
            r.guid,
        )


@dataclass(frozen=True)
class Plan:
    fetches: tuple = ()
    notes: tuple = ()


def walk_command(mailbox: Mailbox, yards: float = MEET_YARDS) -> str:
    return "walk-to-spawn gameobject:%d max:%d stay:%d" % (
        int(mailbox.spawn),
        int(yards),
        MEET_STAY_SECONDS,
    )


def _yards(member: Member, box: Mailbox) -> float:
    return math.hypot(member.x - box.x, member.y - box.y)


def _in_disc(box: Mailbox, discs) -> bool:
    for map_id, x, y, radius in discs or ():
        if int(map_id) == box.map_id and math.hypot(box.x - x, box.y - y) <= radius:
            return True
    return False


def _member_refusal(m, busy, held) -> str:
    if m is None:
        return "is not in the world"
    if m.roster:
        return "is a family member, whose travel seat is not spent on a fetch"
    if m.name in busy:
        return "is already on another walk"
    if m.in_combat:
        return "is in combat"
    if m.in_instance:
        return "is inside an instance"
    if m.family and m.family in held:
        return "belongs to a family under an operator hold"
    return ""


def _meeting(holder, wearer, mailboxes, discs):
    """The mailbox nearest the wearer that both can reach, or a reason."""
    if holder.map_id != wearer.map_id:
        return None, "%s and %s are on different maps" % (holder.name, wearer.name)
    boxes = [b for b in mailboxes or () if int(b.map_id) == int(wearer.map_id)]
    if not boxes:
        return None, "no mailbox is spawned on their map"
    boxes.sort(key=lambda b: (_yards(wearer, b), b.spawn))
    reached = [
        b
        for b in boxes
        if _yards(wearer, b) <= MEET_YARDS and _yards(holder, b) <= MEET_YARDS
    ]
    if not reached:
        return None, "no mailbox is within %d yards of both" % int(MEET_YARDS)
    safe = [b for b in reached if not _in_disc(b, discs)]
    if not safe:
        return None, "every mailbox in reach lies inside a death-cell avoid disc"
    return safe[0], ""


def plan(
    routes,
    members,
    mailboxes,
    *,
    busy=(),
    held_families=(),
    kept=keep.Reservations(),
    discs=(),
    running=0,
    spent=0,
    per_pass=PER_PASS,
    per_day=PER_DAY,
    at_once=AT_ONCE,
) -> Plan:
    """Which waiting routes start a fetch this pass, and why the rest do not.

    `routes` are the routes that could not be written this pass, best first.
    `members` maps name to Member. `busy` holds the names another pass has on
    a walk, `held_families` the families under an operator hold, `discs` the
    (map, x, y, radius) death-cell avoid discs. `running` is the fetches under
    way and `spent` the ones started today.
    """
    taken = set(busy)
    fetches, notes = [], []
    started = 0
    for route in routes or ():
        lead = "%s -> %s, %s (item %d)" % (
            route.holder,
            route.wearer,
            route.item,
            route.guid,
        )
        if route.holder == gearrouting.BANK_HOLDER:
            notes.append("%s: the guild bank is not walked" % lead)
            continue
        if gearroutingexec._kept(route, kept):
            notes.append("%s: kept (overseer_keep), not moved" % lead)
            continue
        holder, wearer = members.get(route.holder), members.get(route.wearer)
        if wearer is not None and wearer.roster and holder is not None:
            if holder.roster:
                notes.append("%s: a family holder is not walked here" % lead)
                continue
            why = _member_refusal(holder, taken, held_families)
            if why:
                notes.append("%s: %s %s" % (lead, holder.name, why))
                continue
            fetches.append(Fetch(MAILBOX, route))
            taken.add(holder.name)
            continue
        refusal = ""
        for who in (holder, wearer):
            why = _member_refusal(who, taken, held_families)
            if why:
                refusal = "%s %s" % (getattr(who, "name", "a member"), why)
                break
        if refusal:
            notes.append("%s: %s" % (lead, refusal))
            continue
        if started >= per_pass:
            notes.append("%s: past the %d fetches a pass may start" % (lead, per_pass))
            continue
        if spent + started >= per_day:
            notes.append("%s: the %d fetches a day are spent" % (lead, per_day))
            continue
        if running + started >= at_once:
            notes.append("%s: %d fetches are already under way" % (lead, at_once))
            continue
        box, why = _meeting(holder, wearer, mailboxes, discs)
        if box is None:
            notes.append("%s: %s" % (lead, why))
            continue
        command = walk_command(box)
        fetches.append(
            Fetch(
                MEET,
                route,
                box.spawn,
                ((holder.name, command), (wearer.name, command)),
            )
        )
        taken.update((holder.name, wearer.name))
        started += 1
    return Plan(tuple(fetches), tuple(notes))
