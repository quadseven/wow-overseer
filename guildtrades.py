"""Which two professions each approved raid seat and guild maintenance
character takes (the guild-wide profession plan).

WHY IT EXISTS. Of the 80 approved raid seats, 33 held no primary profession and
nothing chose which two a seat should take. The raid's real needs (flask, fire
protection and mana potions, enchants, the fire resistance pieces) were never
planned for. This module is that plan, as data.

WHO IS IN THE PLAN. The guild's approved raid seats (raidteams.GROUPS, 40) and
its guild maintenance characters (raidteams.MAINTENANCE, 10): fifty characters
a guild. The summon warlocks (raidteams.SUMMONERS) and the questers
(raidteams.QUESTERS) are never in it, whatever `live` says of them. The five
family characters of a guild (the first group) are in it, counted against the
mix, and are never moved: whatever they hold is what they keep.

THE MIX. One table for both guilds, so that each guild is self-sufficient and
neither depends on the other: every crafter is paired with the gathering trade
that feeds it (Herbalism with Alchemy, Mining with Blacksmithing, Mining with
Engineering, Skinning with Leatherworking) or is a Tailoring with Enchanting
pair (cloth drops, and disenchanting feeds the enchanter), and a few pure
gatherers (Herbalism with Mining) top up the supply. The counts are read off
the raid's real consumption (raidsupply.SUPPLIES, raidsupply.FIRE_GEAR,
data/bis/situational.json), per guild of fifty:

    Herbalism and Alchemy       18   11 of the 15 supplies a raid night eats
                                     are Alchemy, about 370 potions, flasks and
                                     elixirs a night for forty raiders
    Skinning and Leatherworking  8   9 of the 15 craftable fire resistance
                                     pieces by slot are Leatherworking
    Mining and Blacksmithing     7   5 of them are Blacksmithing (Dark Iron
                                     plate and the plate fire pieces)
    Tailoring and Enchanting     7   Tailoring makes 2 (Wizardweave, Flarecore);
                                     Enchanting is the cloak and the weapons
                                     and chests of 40 raiders
    Mining and Engineering       3   nothing in the night's list needs it, so
                                     last, and a few for the Mining feed
    Herbalism and Mining         7   the pure gatherers that top the herbs and
                                     ore up (Alchemy eats herbs fastest)

THE RULE, in the order it decides.
  1. A family character keeps exactly what it holds.
  2. A character that already holds a table pair, or two crafts, and fits the
     mix (the pair's slots are not all taken) is complete and keeps it. So is
     a character holding two trades one of which is a gathering trade above
     DROP_GUARD: it keeps both, and counts as a pure gatherer, so the mix still
     adds up around it.
  3. Every other character is placed by the cheapest assignment (a minimum
     cost matching, deterministic) onto the remaining slots. The cost is the
     skill points the character would drop to fit the pair; a crafting trade is
     never dropped (forbidden); a character is given a slot of a pair
     containing the trades it already holds before any other, and the class a
     pair prefers breaks a tie. A maintenance character is steered off the pure
     gatherers, since it stays near banks.
  4. Nothing is granted: this decides who should learn, and what a character
     must give up to fit. The learning is a walk to a trainer; the giving up
     is `drops`, and no verb in this repo performs it for a guild character.

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
GATHERING = frozenset({HERBALISM, MINING, SKINNING})
# A character is never made to drop one of these.
CRAFTS = PRIMARIES - GATHERING

# A trade above this skill is not dropped without a decision: `drops` lists it.
DROP_GUARD = 75

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

# What a trade is worth when the world gave no skill value for it.
UNKNOWN_VALUE = 1

# Cost weights, small beside a skill point so a point is never traded for taste.
_LEARN_COST = 1
_CLASS_STEP = 2
_PURE_GATHERER_COST = 6
# Keeping a trade the character holds is worth this much, so a held trade
# outweighs a class preference.
_KEEP_BONUS = 20
# A gatherer that keeps its trade and takes the craft it feeds.
_FEED_BONUS = 30
_MAINTENANCE_GATHERER_COST = 40
# A slot past a pair's count, taken only when nothing else keeps a craft.
_OVERFLOW_COST = 300
_FORBIDDEN = 10**9
_GUARDED = 10**6


class Pair(NamedTuple):
    name: str
    skills: tuple
    seats: int
    # Class groups, best first. Empty: any class fits equally.
    prefer: tuple


# Fifty characters a guild, the same for both. Alchemy first, as it is filled
# first and takes the most.
PAIRS = (
    Pair(
        "Herbalism and Alchemy",
        (HERBALISM, ALCHEMY),
        18,
        (HEALER_CLASSES, CASTER_CLASSES),
    ),
    Pair("Mining and Blacksmithing", (MINING, BLACKSMITHING), 7, (PLATE_CLASSES,)),
    Pair(
        "Skinning and Leatherworking",
        (SKINNING, LEATHERWORKING),
        8,
        (LEATHER_MAIL_CLASSES,),
    ),
    Pair("Tailoring and Enchanting", (TAILORING, ENCHANTING), 7, (CLOTH_CLASSES,)),
    Pair("Mining and Engineering", (MINING, ENGINEERING), 3, ()),
    Pair("Herbalism and Mining", (HERBALISM, MINING), 7, ()),
)
PURE_GATHERERS = frozenset((HERBALISM, MINING))


class Seen(NamedTuple):
    """What the world says of one character: its level, the primaries it holds
    and, when read, the skill value of each (skill id -> value)."""

    level: int
    held: frozenset
    values: Mapping = {}


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


class _Member(NamedTuple):
    name: str
    class_id: int
    level: int
    held: frozenset
    values: Mapping
    maintenance: bool
    frozen: bool


def _read(name, live, class_id, maintenance, frozen) -> _Member:
    seen = live.get(name)
    if seen is None:
        return _Member(
            name, class_id, UNSEEN_LEVEL, frozenset(), {}, maintenance, frozen
        )
    return _Member(
        name,
        class_id,
        int(seen.level),
        frozenset(seen.held),
        dict(seen.values or {}),
        maintenance,
        frozen,
    )


def members_of(guild, live) -> list:
    """The planned characters of the guild, in name order: its approved seats,
    then its maintenance characters, each under the name `live` knows it by.
    Summoners and questers are never among them."""
    key = _guild_key(guild)
    if not key:
        return []
    live = live or {}
    family = {s.name for s in raidteams.GROUPS[key][0]} | {
        s.was for s in raidteams.GROUPS[key][0] if s.was
    }
    out = []
    for s in raidteams.seats(key):
        name = next((n for n in (s.name, s.was) if n and n in live), s.name)
        out.append(
            _read(
                name, live, int(s.class_id), False, s.name in family or name in family
            )
        )
    seen_names = {m.name for m in out}
    for old, new in raidteams.MAINTENANCE.get(key, ()):
        name = next((n for n in (new, old) if n and n in live), new)
        if name not in seen_names:
            out.append(_read(name, live, 0, True, False))
            seen_names.add(name)
    return sorted(out, key=lambda m: m.name)


def _value(m, skill) -> int:
    return int(m.values.get(skill, UNKNOWN_VALUE) or UNKNOWN_VALUE)


def _cost(m, pair) -> int:
    """What it costs this character to end as `pair`: the skill points it drops,
    a small price for each trade it must learn, a class-fit step and, for a
    maintenance character, a push off the pure gatherers."""
    cost = 0
    for skill in m.held:
        if skill in pair.skills:
            continue
        if skill in CRAFTS:
            return _FORBIDDEN
        cost += _value(m, skill)
        if _value(m, skill) > DROP_GUARD:
            cost += _GUARDED
    cost += _LEARN_COST * sum(1 for s in pair.skills if s not in m.held)
    cost -= _KEEP_BONUS * sum(1 for s in pair.skills if s in m.held)
    if (m.held & GATHERING & set(pair.skills)) and set(pair.skills) & CRAFTS:
        cost -= _FEED_BONUS
    if not (m.held & set(pair.skills)):
        # Class fit places a character with no trade of the pair; it never
        # outweighs a trade the character already holds.
        cost += _CLASS_STEP * _fit(pair, m.class_id)
    if set(pair.skills) == PURE_GATHERERS:
        cost += _PURE_GATHERER_COST
        if m.maintenance:
            cost += _MAINTENANCE_GATHERER_COST
    return cost


def _relax(cost, j0, tree) -> int:
    """One step of the alternating tree grown from column `j0`: tighten the
    slack of every unused column and return the next column to enter it."""
    u, v, p, way, minv, used = tree
    inf = float("inf")
    used[j0] = True
    i0, delta, j1 = p[j0], inf, 0
    for j in range(1, len(v)):
        if used[j]:
            continue
        cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
        if cur < minv[j]:
            minv[j], way[j] = cur, j0
        if minv[j] < delta:
            delta, j1 = minv[j], j
    for j in range(len(v)):
        if used[j]:
            u[p[j]] += delta
            v[j] -= delta
        else:
            minv[j] -= delta
    return j1


def _hungarian(cost) -> list:
    """The column each row takes at least total cost (rows <= columns)."""
    n, m = len(cost), len(cost[0]) if cost else 0
    inf = float("inf")
    u, v = [0] * (n + 1), [0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        tree = (u, v, p, way, [inf] * (m + 1), [False] * (m + 1))
        while True:
            j0 = _relax(cost, j0, tree)
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def _ordered(m, pair) -> tuple:
    """The pair with the trades the character holds first."""
    kept = tuple(s for s in pair.skills if s in m.held)
    return kept + tuple(s for s in pair.skills if s not in m.held)


def assign(guild, live: Mapping | None = None) -> dict:
    """name -> the trades each planned character of `guild` should hold.

    `live` maps a character's current name (its approved name, or the name it
    has until its rename) to a Seen; a character missing from it is unseen and
    holds nothing. Every approved seat and maintenance character of the guild is
    in the answer, keyed by the name `live` knows it by, else by its approved
    name; nobody else ever is. {} for a guild with no approved seats.
    """
    people = members_of(guild, live)
    if not people:
        return {}
    left = {p.name: p.seats for p in PAIRS}
    by_skills = {frozenset(p.skills): p for p in PAIRS}
    out: dict = {}

    # 1. A family character keeps exactly what it holds.
    for m in people:
        if m.frozen:
            out[m.name] = tuple(sorted(m.held))
            pair = by_skills.get(frozenset(m.held))
            if pair:
                left[pair.name] -= 1
    # 2. A character that holds a whole table pair with a slot left, or two
    # crafts, or two trades one of which is a gathering trade above DROP_GUARD,
    # is complete as it is. The last kind keeps both trades and stands in for
    # a pure gatherer when every one of its trades is gathering, so the mix
    # still adds up around it.
    plain = by_skills[frozenset(PURE_GATHERERS)]
    for m in people:
        if m.name in out or len(m.held) < 2:
            continue
        pair = by_skills.get(frozenset(m.held))
        if pair and left[pair.name] > 0:
            out[m.name] = _ordered(m, pair)
            left[pair.name] -= 1
        elif not (m.held & GATHERING):
            out[m.name] = tuple(sorted(m.held))
        elif any(_value(m, sk) > DROP_GUARD for sk in m.held & GATHERING):
            out[m.name] = tuple(sorted(m.held))
            stand = (
                plain if m.held <= GATHERING else max(PAIRS, key=lambda p: left[p.name])
            )
            left[stand.name] = max(left[stand.name] - 1, 0)
    # 3. Everyone else takes the cheapest slot that is left.
    rest = [m for m in people if m.name not in out]
    slots = [(p, 0) for p in PAIRS for _ in range(max(left[p.name], 0))]
    # A slot past a pair's count costs extra, so it is taken only when a craft
    # a character holds has no slot left that keeps it (a craft is never
    # dropped), or when a kept trade used up slots elsewhere.
    slots += [(p, _OVERFLOW_COST) for p in PAIRS for _ in rest]
    if rest:
        cost = [[_cost(m, p) + extra for p, extra in slots] for m in rest]
        for m, col in zip(rest, _hungarian(cost), strict=True):
            out[m.name] = _ordered(m, slots[col][0])
    return out


def drops(guild, live: Mapping | None, assigned: Mapping | None = None) -> dict:
    """name -> ((skill, value), ...): what each character would have to give up
    to end as its assigned trades. Only characters that must give something up
    are in it. A family character never is."""
    assigned = assign(guild, live) if assigned is None else assigned
    out = {}
    for m in members_of(guild, live):
        want = assigned.get(m.name)
        if not want or m.frozen:
            continue
        gone = tuple((s, _value(m, s)) for s in sorted(m.held) if s not in want)
        if gone:
            out[m.name] = gone
    return out


def missing(held, assigned) -> tuple:
    """The assigned trades a seat does not hold yet, in the assigned order."""
    return tuple(s for s in assigned if s not in set(held))
