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

# How far from the leader a field may be before it is not a candidate (#170).
# Measured on wow-dev 2026-09-22: the family stood in Winterspring at level 60
# and the density ranking sent it to copper in The Barrens, 8208 yards away,
# holding the travel column the whole walk. A zone is one to three thousand
# yards across, so three thousand keeps the neighbouring zones and refuses a
# walk across the continent. Nothing in range is a refusal that says so.
MAX_YARDS = 3000.0

# How far below the family's level a field's neighbourhood may top out before
# it is passed over for one nearer the family's own level (#170). A judgement:
# a level 60 family farming a level 20 zone raises a skill but spends an hour
# walking somewhere nothing can hurt it and nothing it needs drops. Used only as
# a preference, so a family whose only fields are low still gets one.
LEVEL_FLOOR_BELOW = 20

# How many free bag slots any one member must have before a gathering walk may
# take the travel column (#170). The same number as the vendor trip's trigger
# (bag_pressure.TOWN_RUN_FREE_SLOTS), repeated rather than imported because this
# module stays dependency-free; tests/test_gatheraim.py pins that they agree.
# At or below it a member cannot reliably loot, a node picked into full bags
# is lost, and the vendor or bank trip that would fix it must go first.
GATHER_MIN_FREE_SLOTS = 3


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
    # `gameobject.guid`, the spawn id a walk-to-spawn row names; 0 where the
    # survey did not read it.
    guid: int = 0


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


def bags_block_gathering(free_slots, minimum_free=GATHER_MIN_FREE_SLOTS) -> str:
    """Why a gathering walk must not take the travel column now, or "" (#170).

    `free_slots` is {character: free bag slots}. Anybody at or below
    `minimum_free` cannot loot what the walk is for, and the town trip that
    would empty their bags needs the same column. An empty or unreadable
    reading refuses too: not knowing whether they can loot is not a reason to
    march them away from the vendor.
    """
    readings = {}
    for name, free in (free_slots or {}).items():
        try:
            readings[str(name)] = int(free)
        except (TypeError, ValueError):
            continue
    if not readings:
        return (
            "nobody's free bag slots could be read, so no gathering walk "
            "may take the travel column"
        )
    full = sorted(
        (free, name) for name, free in readings.items() if free <= int(minimum_free)
    )
    if not full:
        return ""
    return (
        "%s at %d free bag slot(s), at or below %d, so a gathering walk "
        "yields the travel column to the vendor and bank trips"
        % (", ".join(name for _free, name in full), full[0][0], int(minimum_free))
    )


def strongest_gatherers(skills):
    """[(skill_name, value)] - each aimable skill at its best in the family.

    A node counts for the family when SOMEBODY can open it (#170). The walk
    still moves all five, so this is used only with a distance cap: it widens
    what counts near the leader, never how far anybody is sent.
    """
    best = {}
    for holdings in (skills or {}).values():
        for name, value in (holdings or {}).items():
            if name not in AIMABLE:
                continue
            try:
                have = int(value)
            except (TypeError, ValueError):
                continue
            best[name] = max(have, best.get(name, have))
    return [(name, best[name]) for name in AIMABLE if name in best]


def yards(spawn, origin) -> float:
    """Straight-line yards on the map from `origin` (x, y) to a spawn."""
    return (
        (float(spawn.x) - float(origin[0])) ** 2
        + (float(spawn.y) - float(origin[1])) ** 2
    ) ** 0.5


def near_fields(spawns, skills, standing_on, origin, max_yards=MAX_YARDS):
    """Fields some gatherer can open within `max_yards` of `origin`, nearest
    first in thousand-yard steps and densest within a step (#170).

    Returns (in_range, nearest_out_of_range_yards). The second value is None
    when there was nothing out of range either, and is what the refusal names.
    """
    fields = []
    for skill_name, value in strongest_gatherers(skills):
        fields.extend(fields_in_band(spawns, skill_name, value, standing_on))
    inside, beyond = [], None
    for field in fields:
        far = yards(field.spawn, origin)
        if far > float(max_yards):
            beyond = far if beyond is None else min(beyond, far)
            continue
        inside.append(
            (int(far // 1000), -field.nodes, field.zone_id, field.skill_name, field)
        )
    inside.sort(key=lambda row: row[:4])
    return [row[4] for row in inside], beyond


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


def _below_floor(top, family_level) -> bool:
    """Is this neighbourhood far below the family's level (#170)?"""
    return bool(family_level) and int(top) < int(family_level) - LEVEL_FLOOR_BELOW


def _safe_fields(candidates, levels, ceiling):
    """([(field, top level)] measured and under `ceiling`, considered rows).

    A field missing from `levels` is unmeasured and never safe.
    """
    considered, safe = [], []
    for cand in candidates:
        top = levels.get(cand.zone_id)
        considered.append((cand.zone_id, cand.nodes, top))
        if top is None or (ceiling and int(top) > ceiling):
            continue
        safe.append((cand, top))
    return safe, considered


def _near_or_refused(spawns, skills, standing_on, origin, max_yards):
    """(fields near the leader, None), or ([], the Choice refusing) (#170)."""
    candidates, beyond = near_fields(spawns, skills, standing_on, origin, max_yards)
    if candidates:
        return candidates, None
    return [], Choice(
        refused=(
            "no field on map %s that anybody in the family can gather "
            "lies within %d yards of the leader%s, and a walk further "
            "than that is not worth the travel column"
            % (
                standing_on,
                int(max_yards),
                ""
                if beyond is None
                else " - the nearest is %d yards away" % int(beyond),
            )
        ),
        why="no in-band field within range of the leader.",
    )


def choose(
    *,
    skills,
    standing_on,
    spawns,
    family_level=0,
    zone_levels=None,
    origin=None,
    max_yards=MAX_YARDS,
):
    """The destination, or the reason there is not one.

    `origin` is the leader's (x, y). With it, the candidates are the fields
    SOME gatherer can open within `max_yards`, nearest first (`near_fields`),
    and nothing further away is ever chosen (#170). Without it the old
    weakest-gatherer density ranking is kept for callers that cannot say where
    the leader stands.

    Either way a field whose neighbourhood tops out more than
    LEVEL_FLOOR_BELOW under the family is taken only when no measured, safe
    field nearer their level exists.

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

    if origin is not None:
        candidates, refusal = _near_or_refused(
            spawns, skills, standing_on, origin, max_yards
        )
        if refusal is not None:
            return refusal
    else:
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
    safe, considered = _safe_fields(candidates, levels, ceiling)
    # A field near the family's own level before one far below it (#170).
    preferred = [pair for pair in safe if not _below_floor(pair[1], family_level)]
    for cand, top in (preferred or safe)[:1]:
        return Choice(
            chosen=NodeField(
                zone_id=cand.zone_id,
                map_id=cand.map_id,
                skill_name=cand.skill_name,
                nodes=cand.nodes,
                spawn=cand.spawn,
                top_level=int(top),
            ),
            why="zone %d holds %d %s node(s) the family can open and tops "
            "out at level %d, within the family's %d."
            % (cand.zone_id, cand.nodes, cand.skill_name, int(top), ceiling),
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
