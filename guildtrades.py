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
    live = live or {}
    seats = []
    for s in raidteams.seats(key):
        name = next((n for n in (s.name, s.was) if n and n in live), s.name)
        seen = live.get(name)
        level = UNSEEN_LEVEL if seen is None else int(seen.level)
        held = frozenset(seen.held) if seen is not None else frozenset()
        seats.append((name, int(s.class_id), level, held))
    left = {p.name: p.seats for p in PAIRS}
    by_skills = {frozenset(p.skills): p for p in PAIRS}
    out: dict = {}

    def take(pair):
        left[pair.name] -= 1

    # 1. Seats that hold a whole pair, or two trades that are no pair.
    for name, _cls, _lvl, held in sorted(seats):
        if len(held) >= 2:
            pair = by_skills.get(frozenset(held))
            if pair is not None:
                out[name] = pair.skills
                take(pair)
            else:
                out[name] = tuple(sorted(held))
    # 2. Seats that hold one trade: the pair that contains it and suits the class.
    singles = sorted(
        (s for s in seats if len(s[3]) == 1 and s[0] not in out),
        key=lambda s: (s[2], s[0]),
    )
    for name, cls, _lvl, held in singles:
        (trade,) = tuple(held)
        options = [p for p in PAIRS if trade in p.skills]
        if not options:
            out[name] = (trade,)
            continue

        def score(p):
            tier = 1 if not p.prefer else (0 if _fit(p, cls) < len(p.prefer) else 2)
            return (tier, -left[p.name], PAIRS.index(p))

        pair = min(options, key=score)
        out[name] = pair.skills
        take(pair)
    # 3. Seats that hold nothing fill what is left, pair by pair.
    free = [s for s in seats if s[0] not in out]
    for pair in PAIRS:
        free.sort(key=lambda s: (_fit(pair, s[1]), s[2], s[0]))
        while left[pair.name] > 0 and free:
            name = free.pop(0)[0]
            out[name] = pair.skills
            take(pair)
    # Slots a kept trade used up elsewhere leave seats over: the plain pair.
    rest = by_skills[frozenset((HERBALISM, MINING))]
    for name, _cls, _lvl, _held in free:
        out[name] = rest.skills
    return out


def missing(held, assigned) -> tuple:
    """The assigned trades a seat does not hold yet, in the assigned order."""
    return tuple(s for s in assigned if s not in set(held))
