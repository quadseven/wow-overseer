"""Which two professions each approved raid seat takes (slice 2 of the plan).

WHY IT EXISTS. Of the 80 approved raid seats, 33 held no primary profession and
nothing chose which two a seat should take. The guild job pass split only the
three gathering trades, by "fewest holders", so the raid's real needs (flask
and fire protection alchemists, enchanters, tailors, leatherworkers, smiths,
engineers) were never planned for. This module is that plan, as data.

THE TABLE. Per guild of 40 seats: Herbalism and Alchemy 8, Herbalism and Mining
8, Mining and Engineering 6, Mining and Blacksmithing 6, Skinning and
Leatherworking 6, Tailoring and Enchanting 6.

THE RULE. A seat keeps any trade it already holds (a trade is never unlearned):
a seat holding a table pair takes that pair's slot, a seat holding one trade
takes the slot of the pair that contains it and that suits its class best, and
a seat holding two trades that are no pair keeps exactly those. The remaining
seats fill the remaining slots, pair by pair in FILL_ORDER, by class
preference (the pair's classes first, then any), then by lowest level first
(the most levelling time to raise the skill), then by name. Output is a mapping
seat name to its trades; the same inputs always give the same answer.

A seat that is not in the world yet counts as level UNSEEN_LEVEL, so a seat the
guild can see is never pushed out of a pair by one it cannot.

NORTH STAR. This decides who should learn what. Nothing here teaches, grants or
walks: a seat learns a trade by walking to a trainer and paying the fee.

PURE: data and lookups only. No MySQL, no clock.
"""

from __future__ import annotations

from typing import Mapping, NamedTuple

import guildcorps
import raidteams

HERBALISM, MINING, SKINNING = (
    guildcorps.HERBALISM,
    guildcorps.MINING,
    guildcorps.SKINNING,
)
TAILORING = guildcorps.TAILORING
BLACKSMITHING, LEATHERWORKING, ALCHEMY, ENGINEERING, ENCHANTING = (
    164,
    165,
    171,
    202,
    333,
)

# The nine primary trades the table hands out.
PRIMARIES = frozenset(
    {
        HERBALISM,
        MINING,
        SKINNING,
        TAILORING,
        BLACKSMITHING,
        LEATHERWORKING,
        ALCHEMY,
        ENGINEERING,
        ENCHANTING,
    }
)

# WotLK class ids, as the realm's characters.class column stores them.
WARRIOR, PALADIN, HUNTER, ROGUE, PRIEST = 1, 2, 3, 4, 5
DEATH_KNIGHT, SHAMAN, MAGE, WARLOCK, DRUID = 6, 7, 8, 9, 11

HEALER_CLASSES = frozenset({PRIEST, PALADIN, DRUID, SHAMAN})
CASTER_CLASSES = frozenset({MAGE, WARLOCK})
PLATE_CLASSES = frozenset({WARRIOR, PALADIN, DEATH_KNIGHT})
LEATHER_MAIL_CLASSES = frozenset({ROGUE, DRUID, HUNTER, SHAMAN})
CLOTH_CLASSES = frozenset({PRIEST, MAGE, WARLOCK})

# What a seat counts as when it is not in the world to be read.
UNSEEN_LEVEL = 99


class Pair(NamedTuple):
    name: str
    skills: tuple
    seats: int
    # Class groups, best first. Empty: any class fits equally.
    prefer: tuple


PAIRS = (
    Pair(
        "Herbalism and Alchemy",
        (HERBALISM, ALCHEMY),
        8,
        (HEALER_CLASSES, CASTER_CLASSES),
    ),
    Pair("Mining and Blacksmithing", (MINING, BLACKSMITHING), 6, (PLATE_CLASSES,)),
    Pair(
        "Skinning and Leatherworking",
        (SKINNING, LEATHERWORKING),
        6,
        (LEATHER_MAIL_CLASSES,),
    ),
    Pair("Tailoring and Enchanting", (TAILORING, ENCHANTING), 6, (CLOTH_CLASSES,)),
    Pair("Mining and Engineering", (MINING, ENGINEERING), 6, ()),
    Pair("Herbalism and Mining", (HERBALISM, MINING), 8, ()),
)


class Seen(NamedTuple):
    """What the world says of one seat: its level and the primaries it holds."""

    level: int
    held: frozenset


def _fit(pair, class_id) -> int:
    """0 for the pair's best class group, up to len(prefer) for a class it does
    not name; always 0 for a pair that takes any class."""
    for rank, group in enumerate(pair.prefer):
        if class_id in group:
            return rank
    return len(pair.prefer)


def _guild_key(guild):
    wanted = str(guild or "").lower()
    for name in raidteams.GROUPS:
        if name.lower() == wanted:
            return name
    return ""


def _seats_of(key, live) -> list:
    """(name, class id, level, held) for each approved seat of the guild."""
    seats = []
    for s in raidteams.seats(key):
        name = next((n for n in (s.name, s.was) if n and n in live), s.name)
        seen = live.get(name)
        level = UNSEEN_LEVEL if seen is None else int(seen.level)
        held = frozenset() if seen is None else frozenset(seen.held)
        seats.append((name, int(s.class_id), level, held))
    return seats


def _single_pair(trade, class_id, left):
    """The pair a seat holding only `trade` takes a slot of: the pair whose
    classes fit it, else a pair that takes any class, else a pair that names
    other classes; then the pair with the most slots left. The options all
    contain `trade`, so a class never leaves the trade it already holds."""
    options = [p for p in PAIRS if trade in p.skills]
    if not options:
        return None

    def tier(p):
        if not p.prefer:
            return 1
        return 0 if _fit(p, class_id) < len(p.prefer) else 2

    return min(options, key=lambda p: (tier(p), -left[p.name], PAIRS.index(p)))


def assign(guild, live: Mapping | None = None) -> dict:
    """name -> the trades each approved seat of `guild` should hold.

    `live` maps a seat's current name (its approved name, or the name it has
    until its rename) to a Seen; a seat missing from it is unseen. Every one of
    the guild's approved seats is in the answer, keyed by the name `live` knows
    it by, else by its approved name. {} for a guild with no approved seats.
    """
    key = _guild_key(guild)
    if not key:
        return {}
    seats = _seats_of(key, live or {})
    left = {p.name: p.seats for p in PAIRS}
    by_skills = {frozenset(p.skills): p for p in PAIRS}
    out: dict = {}

    # 1. Seats that hold a whole pair, or two trades that are no pair.
    for name, _cls, _lvl, held in sorted(seats):
        if len(held) >= 2:
            pair = by_skills.get(frozenset(held))
            out[name] = pair.skills if pair else tuple(sorted(held))
            if pair:
                left[pair.name] -= 1
    # 2. Seats that hold one trade take a slot of a pair that contains it.
    singles = [s for s in seats if len(s[3]) == 1 and s[0] not in out]
    for name, cls, _lvl, held in sorted(singles, key=lambda s: (s[2], s[0])):
        (trade,) = tuple(held)
        pair = _single_pair(trade, cls, left)
        out[name] = pair.skills if pair else (trade,)
        if pair:
            left[pair.name] -= 1
    # 3. Seats that hold nothing fill what is left, pair by pair; slots a kept
    # trade used up elsewhere leave seats over, who take the plain pair.
    free = [s for s in seats if s[0] not in out]
    for pair in PAIRS:
        free.sort(key=lambda s: (_fit(pair, s[1]), s[2], s[0]))
        take, free = free[: left[pair.name]], free[left[pair.name] :]
        out.update({s[0]: pair.skills for s in take})
    rest = by_skills[frozenset((HERBALISM, MINING))]
    out.update({s[0]: rest.skills for s in free})
    return out


def missing(held, assigned) -> tuple:
    """The assigned trades a seat does not hold yet, in the assigned order."""
    return tuple(s for s in assigned if s not in set(held))
