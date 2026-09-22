"""Where a family should stand to raise a gathering skill.

infra#3789, hole 2: "nothing decides WHERE". Not one status in
`NewRpgStatusUpdateAction` is a node picker, so a family told to gather roams
wherever the leader's quest log points, which is nobody's material by
construction. Measured 2026-09-19 the family stood in Un'Goro (zone 490) whose
every node needs 230-280 skill, carrying Mining 8 and Mining 1 - so their
combined holdings were one Rough Stone and one Silverleaf, and Ugga's herbalism
moved 132 to 133 over several days.

This module is the pure half of the answer: given what the family can open
(`gatherband`) and a survey of live spawns, which spawn should the leader be
aimed at. `bridge` owns the survey and the write; nothing here touches a
database or a clock.

THE COORDINATE IS ALWAYS A REAL SPAWN ROW, NEVER A COMPUTED POINT. A centroid
of scattered veins is a coordinate this process invented, and a guessed Z has no
navmesh - it lifted one character and killed another in the void at full health
(infra#3519). So a zone's centroid is used ONLY to rank and to pick which real
spawn is most central; the `x/y/z` that leaves this module is copied from a row
of `acore_world.gameobject`, surveyed with the rest of the map, exactly as
`bridge._nearest_forge` does it.

THE FAMILY TRAVELS AS ONE, SO THE BAND IS THE LOWEST SKILL PRESENT. Jobs are
family-wide and `DriveCatchUp` drags any follower past 500 yards back to the
leader, overwriting its errand on the way - so there is no such thing as sending
Grug to copper and Ugga to herbs. A destination has to be somewhere the WEAKEST
gatherer can work, or it is a long walk for somebody.

WHY DENSITY AND NOT DISTANCE. `_nearest_forge` wants the closest forge because
one smelt needs one forge. Gathering wants a field, not a node: walking twenty
minutes to a single Copper Vein and then standing in an empty zone raises
nothing. So zones are ranked by how many reachable nodes they hold, and only
then by how far away they are.

SKINNING IS NOT HERE AND CANNOT BE. Skinning comes off creature corpses, not
`gameobject` spawns, so `gatherband` has no lock for it and this module can
never aim at it. Bork's Skinning 12 is not addressed by any destination; saying
so is better than silently treating him as served.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import gatherband

# The professions this module can aim at, in the order a tie is broken. Mining
# first because its lowest band (Copper, lock 38, band 0) is the most abundant
# low-level node in the world by a wide margin - 1843 live spawns against
# Peacebloom's 835 - so when two skills are equally starved, mining is the trip
# more likely to pay for itself.
AIMABLE = ("mining", "herbalism")

# How far above the family's own level a destination's neighbourhood may be
# before it is refused. A ground `at:` aim early-returns with `outEntry = 0`
# (`mod_overseer.cpp:9839-9857`) and every level check in that file sits AFTER
# that return, so nothing in C++ judges the danger of a ground destination at
# all - Python is the only place left that can. Five characters at 43-48 were
# sent roaming and wiped twice on a level 61 elite, eight deaths in four
# minutes (infra#3789). Three is the same margin the dungeon planner uses.
LEVEL_MARGIN = 3


@dataclass(frozen=True)
class Spawn:
    """One surveyed node, straight out of `acore_world.gameobject`.

    `lock_id` is `gameobject_template.Data0`, which for a type-3 chest IS the
    Lock.dbc id - that is the join that makes the band exact. `zone_id` groups
    spawns into fields; it is only ever used for grouping and reporting, never
    to derive a position.
    """

    map_id: int
    zone_id: int
    x: float
    y: float
    z: float
    lock_id: int
    name: str = ""


@dataclass(frozen=True)
class NodeField:
    """A zone's worth of reachable nodes, and the one spawn to aim at."""

    zone_id: int
    map_id: int
    skill_name: str
    nodes: int
    spawn: Spawn
    top_level: int = 0


@dataclass(frozen=True)
class Choice:
    """Where to send the family, or why nowhere will do.

    `refused` is a sentence or it is empty, and a non-empty `refused` is a
    promise that `chosen` is None - the same convention `travel.ForgeAim` and
    `skillgoal.Plan` already use, so a caller reads all three the same way.
    """

    chosen: object = None
    refused: str = ""
    why: str = ""
    considered: tuple = dataclasses.field(default_factory=tuple)


def lowest_gatherer(skills):
    """(skill_name, value) of the weakest aimable gathering skill in the family.

    `skills` is {character: {skill_name: value}}. Returns (None, 0) when nobody
    holds an aimable gathering skill at all - which is a real state, not an
    error: a family of five tailors has nothing for this module to do.
    """
    worst = None
    for holdings in (skills or {}).values():
        for name, value in (holdings or {}).items():
            if name not in AIMABLE:
                continue
            try:
                have = int(value)
            except (TypeError, ValueError):
                continue
            if worst is None or have < worst[1]:
                worst = (name, have)
    return worst if worst is not None else (None, 0)


def fields_in_band(spawns, skill_name, value, standing_on):
    """Every zone on THIS map holding a node `value` can open, densest first.

    Same-map only, because `ResolveTravelTarget` refuses a spawn on another map
    and the family never learned its flight nodes - an off-map field is not a
    longer walk, it is not a candidate.
    """
    if skill_name is None or standing_on is None:
        return []
    per_zone = {}
    for spawn in spawns or ():
        if int(spawn.map_id) != int(standing_on):
            continue
        if not gatherband.in_band(spawn.lock_id, skill_name, value):
            continue
        per_zone.setdefault(int(spawn.zone_id), []).append(spawn)

    out = []
    for zone_id, rows in per_zone.items():
        cx = sum(float(r.x) for r in rows) / len(rows)
        cy = sum(float(r.y) for r in rows) / len(rows)
        # The centroid ranks and selects; it is never itself a destination.
        # `min` over real rows guarantees the coordinate that leaves here was
        # surveyed by the world, not computed by this process.
        central = min(
            rows, key=lambda r: (float(r.x) - cx) ** 2 + (float(r.y) - cy) ** 2
        )
        out.append(
            NodeField(
                zone_id=zone_id,
                map_id=int(standing_on),
                skill_name=skill_name,
                nodes=len(rows),
                spawn=central,
            )
        )
    out.sort(key=lambda f: (-f.nodes, f.zone_id))
    return out


def choose(*, skills, standing_on, spawns, family_level=0, zone_levels=None):
    """The destination, or the reason there is not one.

    `zone_levels` is {zone_id: highest creature level seen there} and is the
    level guard's only input. A zone absent from it is UNKNOWN, not safe: this
    refuses it rather than walking five characters into something nothing
    measured. That asymmetry is deliberate - the failure it exists to prevent
    already happened once, eight deaths in four minutes.
    """
    skill_name, value = lowest_gatherer(skills)
    if skill_name is None:
        return Choice(
            refused=(
                "nobody in the family holds mining or herbalism, so there is no "
                "gathering destination to choose - skinning comes off corpses "
                "rather than nodes and no walk addresses it"
            ),
            why="no aimable gathering skill in the roster.",
        )

    if standing_on is None:
        return Choice(
            refused=(
                "nobody can say which map the family is standing on - "
                "overseer_snapshot has no fresh row for the leader, so the family "
                "is either offline or the module has stopped writing the snapshot"
            ),
            why="no standing map for the leader.",
        )

    candidates = fields_in_band(spawns, skill_name, value, standing_on)
    if not candidates:
        return Choice(
            refused=(
                "no zone on map %s holds a single node %s %d can open; every node "
                "in reach needs more skill than the family's weakest gatherer has, "
                "and an off-map field is not a candidate because the family never "
                "learned its flight nodes" % (standing_on, skill_name, value)
            ),
            why="no in-band node on this map.",
        )

    levels = zone_levels or {}
    ceiling = int(family_level) + LEVEL_MARGIN if family_level else 0
    considered = []
    for cand in candidates:
        top = levels.get(cand.zone_id)
        considered.append((cand.zone_id, cand.nodes, top))
        if top is None:
            continue
        if ceiling and int(top) > ceiling:
            continue
        return Choice(
            chosen=NodeField(
                zone_id=cand.zone_id,
                map_id=cand.map_id,
                skill_name=cand.skill_name,
                nodes=cand.nodes,
                spawn=cand.spawn,
                top_level=int(top),
            ),
            why="zone %d holds %d node(s) %s %d can open and tops out "
            "at level %d, within the family's %d."
            % (cand.zone_id, cand.nodes, skill_name, value, int(top), ceiling),
            considered=tuple(considered),
        )

    return Choice(
        refused=(
            "every zone on map %s holding a node %s %d can open is either unmeasured "
            "for danger or tops out above level %d, and a ground aim is not "
            "level-checked anywhere in the module - so none of them may be walked "
            "to (infra#3789)" % (standing_on, skill_name, value, ceiling)
        ),
        why="all in-band fields failed the level guard.",
        considered=tuple(considered),
    )


def report(choice):
    """One sentence for Discord and the thought log."""
    if choice.refused:
        return choice.refused
    got = choice.chosen
    return (
        "aiming the family at zone %d on map %d, where %d %s node(s) sit "
        "within reach of the weakest gatherer; the destination is a "
        "surveyed spawn at %.1f,%.1f,%.1f and the zone tops out at level %d"
        % (
            got.zone_id,
            got.map_id,
            got.nodes,
            got.skill_name,
            got.spawn.x,
            got.spawn.y,
            got.spawn.z,
            got.top_level,
        )
    )
