"""A hunter that has learned Tame Beast tames its first pet, as a player does.

WHY THIS EXISTS. Measured on the dev realm on 2026-10-10: 0 of the two guilds'
14 hunters had a pet, and the hunters died 1,551 times in a day, 110.8 each,
three times a mage's 36.7; 1,192 of those deaths were to creatures at or below
the hunter's level. A hunter without a pet fights every mob alone.

WHAT A PLAYER DOES. Finishes the level 10 Taming the Beast chain at its own
trainer (classquest.py walks it there), which teaches Tame Beast (spell 1515,
taught by the chain's Tame Beast spell 1579). The rods of the chain only charm a
beast for 15 minutes; the hunter's own pet comes from casting Tame Beast at a
beast of its level or below, standing still for the 20 second channel. Then it
calls the pet, mends it, revives it after a death and keeps it fed: the bot's
own hunter strategy (mod-playerbots `call pet`, `mend pet`, `revive pet`).

WHAT THIS DOES. For a hunter that knows Tame Beast and has no pet (no
character_pet row), the nearest tameable beast (creature_template type 1, the
tameable type flag, a pet family, rank 0, not an exotic family) whose top level
is at or below the hunter's and at most LEVEL_BELOW under it: a walk to that
spawn, then `use-spell-on creature:<entry> spell:1515` (quadseven/mod-overseer,
the cast a client sends at its target). The core tames it or does not. A beast
this hunter was walked to lately is left for another (AVOID_MINUTES), so a beast
that died, wandered or could not be reached is not asked for again at once.

NOTHING IS GRANTED. No pet is created here: the core's TAME_CREATURE effect
makes it when the channel ends with the beast alive.

PURE MODULE: rows in, a choice out. No MySQL, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

HUNTER = 3
TAME_BEAST = 1515

# The step's action word, in the command log's source (guildjobs.source_for).
ACTION = "hunterpet"
# A tame row waits this long before the next is asked: the walk, the 20 second
# channel and a save of the new pet row fit well inside it.
COOLDOWN_MINUTES = 20
# A beast walked to lately is left for another this long.
AVOID_MINUTES = 90
# At most this many tame steps per guild per pass.
STEPS_PER_GUILD = 4
# How far a hunter is sent for a beast. The level walk keeps a hunter where
# beasts of its level live, so one is rarely far.
BEAST_YARDS = 800.0
# A beast at most this many levels under the hunter: a pet levels with its
# master from where it is tamed, and a much lower one dies in the next fight.
LEVEL_BELOW = 4
# creature_template.type 1 is a beast; type_flags 1 is CREATURE_TYPE_FLAG_TAMEABLE.
BEAST_TYPE = 1
TAMEABLE_FLAG = 1
# The exotic families (Beast Mastery's 51-point talent): chimaera, devilsaur,
# silithid, worm, rhino, core hound, spirit beast. Tame Beast refuses them.
EXOTIC_FAMILIES = frozenset({38, 39, 41, 42, 43, 45, 46})

# The tameable beasts around one hunter, nearest first (BEAST_TYPE and
# TAMEABLE_FLAG written out, so the query is one literal). The %s are, in order:
# x, y, map, the hunter's level (top), the lowest level, x, the box, y, the box,
# and the radius.
BEASTS_SQL = (
    "SELECT c.guid AS guid, c.id AS entry, c.map AS map_id, c.position_x AS x, "
    "c.position_y AS y, ct.name AS name, ct.maxlevel AS level, ct.family AS family, "
    "SQRT(POW(c.position_x - %s, 2) + POW(c.position_y - %s, 2)) AS yards "
    "FROM acore_world.creature c "
    "JOIN acore_world.creature_template ct ON ct.entry = c.id "
    "WHERE c.map = %s AND ct.type = 1 "
    "AND (ct.type_flags & 1) <> 0 AND ct.family > 0 "
    "AND ct.`rank` = 0 AND ct.maxlevel <= %s AND ct.maxlevel >= %s "
    "AND ABS(c.position_x - %s) <= %s AND ABS(c.position_y - %s) <= %s "
    "HAVING yards <= %s ORDER BY yards, guid LIMIT 60"
)

# The hunters (class HUNTER) that know Tame Beast (TAME_BEAST) and have no pet,
# by name. The %s is the names' placeholders, one per name, bound by the driver.
UNPETTED_SQL = (
    "SELECT c.name AS name FROM characters c "
    "JOIN character_spell s ON s.guid = c.guid AND s.spell = 1515 "
    "WHERE c.class = 3 AND c.name IN (%s) "
    "AND NOT EXISTS (SELECT 1 FROM character_pet p WHERE p.owner = c.guid)"
)


@dataclass(frozen=True)
class Beast:
    """A tameable beast spawn: the spawn id, the creature entry, where it is."""

    guid: int
    entry: int
    map_id: int
    x: float
    y: float
    name: str = ""
    level: int = 0
    family: int = 0


def wants_pet(m, unpetted) -> bool:
    """True for a hunter that knows Tame Beast and has no pet (`unpetted`, the
    names UNPETTED_SQL read), online, alive, out of combat and placed."""
    return (
        int(getattr(m, "class_id", 0) or 0) == HUNTER
        and m.name in (unpetted or ())
        and bool(m.online)
        and bool(getattr(m, "alive", True))
        and not m.in_combat
        and m.map_id is not None
        and m.x is not None
        and m.y is not None
    )


def lowest_level(level) -> int:
    """The lowest beast level a hunter of `level` tames."""
    return max(1, int(level) - LEVEL_BELOW)


def beasts_from_rows(rows) -> tuple:
    """Beast spawns from BEASTS_SQL rows, without the exotic families."""
    out = []
    for r in rows or ():
        family = int(r.get("family") or 0)
        if family <= 0 or family in EXOTIC_FAMILIES:
            continue
        out.append(
            Beast(
                guid=int(r["guid"]),
                entry=int(r["entry"]),
                map_id=int(r["map_id"]),
                x=float(r["x"]),
                y=float(r["y"]),
                name=str(r.get("name") or ""),
                level=int(r.get("level") or 0),
                family=family,
            )
        )
    return tuple(out)


def avoided(name, recent) -> frozenset:
    """The beast spawns this hunter was walked to inside AVOID_MINUTES."""
    return frozenset(
        int(r.spawn)
        for r in recent or ()
        if r.name == name and r.action == ACTION and r.walk and r.spawn
        and int(r.age_minutes) < AVOID_MINUTES
    )  # fmt: skip


def choose(m, beasts, avoid=frozenset()):
    """The beast the hunter tames: on its map, at or below its level and at
    most LEVEL_BELOW under it, not avoided, the nearest; the higher level first
    between two equally near. None when there is none."""
    if m.map_id is None or m.x is None or m.y is None:
        return None
    top, low = int(m.level), lowest_level(m.level)
    fits = [
        b
        for b in beasts or ()
        if b.map_id == int(m.map_id) and low <= b.level <= top and b.guid not in avoid
    ]
    if not fits:
        return None
    return min(
        fits,
        key=lambda b: (
            round(math.hypot(b.x - float(m.x), b.y - float(m.y))),
            -b.level,
            b.guid,
        ),
    )


def command(beast) -> str:
    """The quest row that casts Tame Beast at the beast."""
    return "use-spell-on creature:%d spell:%d" % (int(beast.entry), TAME_BEAST)
