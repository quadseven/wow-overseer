"""Paladins who change to the Holy tree at a class trainer, with their own gold.

WHY THIS EXISTS. The Molten Core first-kill quorum asks for eight healers at
level 50 or more, and Cave had two, while all six of its level 60 paladins
were seated Retribution. The owner decided that three of them respec to Holy
by the natural path only: they walk to a paladin trainer, pay the talent reset
from their own purse and spend their points in Holy. Nothing is granted. The
lineup rule "nobody respecs" (raidteams.py) holds for every other seat; this
is the one named exception, and raidteams.RESPEC_HEALERS is where it is
written.

THE MODULE ALREADY DOES THE ERRAND. mod-overseer's `walk-to-trainer
talents:<tree>` row (mod-overseer#692, RespecAtTheTrainer) walks the member to
a trainer of its own class, buys the reset through the core's own handler (the
core takes the price), spends the points with the playerbots premade build for
the tree and then calls PlayerbotAI::ResetStrategies, which rebuilds the
strategies from the new talents: a Holy paladin gets the healing strategy
("holy") with no order from here. What was missing is the row. This module
decides who is sent and says why anyone waits.

PURE: rows in, walks and sentences out. No MySQL and no clock.
"""

from __future__ import annotations

from typing import NamedTuple

import classtrain
import guildroute
import raidroles
import raidteams

LOG_PREFIX = "healer respec:"
SOURCE = "healerrespec"
KIND = "cast"
COOLDOWN_MINUTES = 180
# At most this many walks per guild per pass: a trainer queue, not a stampede.
PER_PASS = 2

GOLD = 10000

# The read of the named members: current rows by name, with the spent talents.
# Built from constant strings; the names are bound by the driver.
MEMBERS_SQL = (
    "SELECT c.name, c.level, c.class AS class_id, c.money, c.online, "  # noqa: S608
    "c.resettalents_cost, "
    + raidroles.TALENTS_COLUMN
    + " FROM characters c WHERE c.name IN ({holes})"
)


def reset_price(last_cost) -> int:
    """What the core asks for the next talent reset, in copper, given the
    cost the character last paid (`characters.resettalents_cost`).

    Player::resetTalentsCost: 1 gold the first time, then 5, then 10, then
    rising by 5 gold to a cap of 50. The core also lowers the cost 5 gold a
    month, which this ignores, so the figure here is never below the price.
    """
    last = int(last_cost or 0)
    if last < 1 * GOLD:
        return 1 * GOLD
    if last < 5 * GOLD:
        return 5 * GOLD
    if last < 10 * GOLD:
        return 10 * GOLD
    return min(last + 5 * GOLD, 50 * GOLD)


def names(guild: str) -> tuple:
    """The approved names the owner's decision sends to Holy in `guild`."""
    return tuple(raidteams.RESPEC_HEALERS.get(guild, ()))


class Candidate(NamedTuple):
    name: str
    guild: str
    level: int
    money: int
    price: int
    played: str
    target: str
    tab: int


class Walk(NamedTuple):
    name: str
    guild: str
    command: str
    kind: str
    source: str
    said: str


def candidates(guild: str, rows, roster) -> tuple:
    """(candidates, notes): the named members whose spent talents are not the
    seat's tree and whose own purse covers the reset.

    `rows` carry name, class_id, level, money, resettalents_cost and
    talent_spells. A roster character is left to the roster's own talent
    drive. A member that has spent no point yet is not a respec: its free
    points go to the seat's tree already (overseer_raid_spec).
    """
    wanted = set(names(guild))
    seats = {}
    for seat in raidteams.seats(guild):
        if seat.name in wanted:
            seats[seat.name] = seats[seat.was] = seat
    found, notes = [], []
    for row in rows or ():
        name = str(row.get("name") or "")
        seat = seats.get(name)
        if seat is None or name in (roster or ()):
            continue
        try:
            class_id = int(row.get("class_id"))
        except (TypeError, ValueError):
            continue
        if class_id != seat.class_id:
            continue
        played = raidroles.tree_of(class_id, row.get("talent_spells"))
        if not played or played == seat.tree:
            continue
        price = reset_price(row.get("resettalents_cost"))
        money = int(row.get("money") or 0)
        if money < price:
            notes.append(
                "%s saves for its talent reset: it carries %dc and the trainer "
                "asks %dc" % (name, money, price)
            )
            continue
        found.append(
            Candidate(
                name,
                guild,
                int(row.get("level") or 0),
                money,
                price,
                played,
                seat.tree,
                raidroles.tree_tab(class_id, seat.tree),
            )
        )
    return found, notes


def command_for(tab: int, cap=guildroute.FAR_WALK_YARDS) -> str:
    return "walk-to-trainer talents:%d%s" % (tab, guildroute.errand_cap_word(cap))


def plan(cands, walkers, recent, busy, per_pass=PER_PASS) -> tuple:
    """(walks, notes): who walks to a class trainer for the reset now.

    The walk's own refusals are the class trainer walk's (classtrain.
    walk_refusal), so a member in combat, inside an instance or out of the
    world waits for the same reasons.
    """
    walks, notes, started = [], [], {}
    for c in sorted(cands or (), key=lambda c: (-c.money, c.name)):
        if c.name in recent:
            continue
        if c.name in busy:
            notes.append("%s waits: it is on another guild walk" % c.name)
            continue
        why = classtrain.walk_refusal((walkers or {}).get(c.name), c.name)
        if why:
            notes.append("%s waits: %s" % (c.name, why))
            continue
        if started.get(c.guild, 0) >= per_pass:
            notes.append(
                "%s waits: %d talent reset walks per guild per pass"
                % (c.name, per_pass)
            )
            continue
        started[c.guild] = started.get(c.guild, 0) + 1
        walks.append(
            Walk(
                c.name,
                c.guild,
                command_for(c.tab),
                KIND,
                "%s:%s" % (SOURCE, c.name),
                "%s %s (%s, level %d, %s now) walks to its class trainer to "
                "reset into %s with %dc against a price of %dc"
                % (
                    LOG_PREFIX,
                    c.name,
                    c.guild,
                    c.level,
                    c.played,
                    c.target,
                    c.money,
                    c.price,
                ),
            )
        )
    return walks, notes


def recent_walkers(rows, minutes=COOLDOWN_MINUTES) -> set:
    """Members walked inside the cooldown, from the command log's rows."""
    out = set()
    for row in rows or ():
        source = str(row.get("source") or "")
        if not source.startswith(SOURCE + ":"):
            continue
        try:
            age = int(row.get("age"))
        except (TypeError, ValueError):
            age = minutes + 1
        if age <= minutes:
            out.add(str(row.get("target_name") or source.split(":", 1)[1]))
    return out


def pass_line(cands, started) -> str:
    return "%s %d paladin(s) can pay for the Holy reset; started %d walk(s)" % (
        LOG_PREFIX,
        len(cands),
        started,
    )
