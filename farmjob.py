"""The farm job: a family gathers a named material on purpose (#2417).

`jobs.MODES` has always named `farm` ("gather deliberately for a named
material, not opportunistically") and nothing drove it. Gathering on the way
to quests and dungeon doors left the family's gathering trades the lowest
numbers it has, and one raid night eats hundreds of herbs a guild.

WHAT THE ORDER SAYS. The job column carries the material, the way a dungeon
job carries its portal:

- `farm:<item entry>` gathers that item, for example `farm:13463` (Dreamfoil).
- `farm:mining` / `farm:herbalism` raises the skill: any node the family's best
  gatherer of that trade can open that still gives skill.

A bare `farm` names nothing and is refused (`jobs.why_not`): "farm what" has no
answer this module could make up.

HOW IT GATHERS. The bots' own `gather` and `loot` strategies pick any node
they can open within reach of where they stand; they are on for every roster
character and the escort puts them back after every walk. What the bots cannot
do is choose WHERE to stand. So this module chooses a field (a zone holding
nodes that drop the material), walks the leader to the nearest such spawn, and
then hops it from one surveyed spawn to the next inside that zone. Every
coordinate it hands out is a row of `acore_world.gameobject` - never a point
it computed, because a guessed Z has no navmesh (gatheraim's header).

THE FAMILY TRAVELS AS ONE (jobs are family-wide, #2426 makes them per member
later). So a node counts when SOMEBODY in the family can open it, the walk
moves all five, and the danger ceiling is the weakest member's level. The per
member form needs only `decide` to be asked with one member's skills.

WHEN IT STOPS. The job ends on its own (the bridge writes the default job back)
when the count is met, the time box is up, too many members died since it
began, or there is nowhere left it may farm. When bags fill it yields the
travel column so the vendor and bank trips can run, and resumes when there is
room. Every pass is one decision and one log line.

PURE MODULE: no MySQL, no clock, no Discord. `bridge._farm_once` reads and
writes; this decides.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import gatheraim
import gatherband
import jobs

PREFIX = jobs.FARM_PREFIX
SKILLS = gatheraim.AIMABLE

# How many of the material end the job when no count was given. Twenty is the
# live acceptance number on #2417, and small enough that a first session ends
# by itself rather than by its time box.
TARGET_COUNT = 20

# How long one farm order may run before it ends on its own. A judgement, sized
# so a session is attended: the operator's rule is that nothing farms
# unwatched for hours.
TIME_BOX_SECONDS = 90 * 60

# Deaths since the order began that strike a zone off, and that end the job
# outright. The repo's own measure of a bad trip is the death table
# (`overseer_death`), and a ground aim is level-checked nowhere in the module,
# so these are the only brakes a farm walk has once it is under way.
ZONE_DEATHS = 2
TOTAL_DEATHS = 4

# A node this close to the leader is in the bots' own gathering reach, so no
# aim is written for it: hopping onto a node they would walk to anyway only
# takes the column from the town errands.
HOP_MIN_YARDS = 40.0

# How long a spawn the family was sent to is passed over. Herb and ore nodes
# respawn in minutes, not seconds, so a hop straight back to the node just
# picked finds nothing.
REVISIT_SECONDS = 15 * 60

# A node counts as a source when the material drops from it at least this
# often. Herbs and ores drop their own material at 100; a chest that sometimes
# holds a herb (lock 57, no gathering skill at all) is not a field. Applied in
# the bridge's survey (`bridge._FARM_ITEM_NODE_SQL`), where the loot table is.
MIN_DROP_CHANCE = 50.0

# A node gives skill until the gatherer is this far past its band (grey).
GREY_AFTER = 100

# The danger margin, the same three levels gatheraim and the dungeon planner use.
LEVEL_MARGIN = gatheraim.LEVEL_MARGIN

END = "end"
TOWN = "town"
WALK = "walk"
HOP = "hop"
WAIT = "wait"


def job_for(what) -> str | None:
    """The job string for an item entry or a skill name, or None."""
    text = str(what or "").strip().lower()
    if text in SKILLS:
        return PREFIX + text
    if text.isdigit() and not text.startswith("0") and len(text) <= 9:
        return PREFIX + text
    return None


def order_of(job) -> tuple:
    """(item entry, skill name) a farm job names; (0, "") when it names nothing.

    Exactly one of the two is set for a valid farm order.
    """
    text = str(job or "").strip().lower()
    if not text.startswith(PREFIX):
        return 0, ""
    what = text[len(PREFIX) :]
    if what in SKILLS:
        return 0, what
    if what.isdigit() and not what.startswith("0") and len(what) <= 9:
        return int(what), ""
    return 0, ""


def is_farm_job(job) -> bool:
    item, skill = order_of(job)
    return bool(item or skill)


def skill_of_lock(lock_id) -> tuple:
    """(skill name, band) a node's lock demands, or (None, None)."""
    for name in SKILLS:
        band = gatherband.band_for(lock_id, name)
        if band is not None:
            return name, band
    return None, None


def best_skills(skills) -> dict:
    """{skill name: best value in the family} for the aimable trades."""
    return dict(gatheraim.strongest_gatherers(skills))


def skill_locks(skill_name, value) -> list:
    """Locks of `skill_name` that `value` can open and that still give skill."""
    out = []
    for lock in gatherband.reachable_locks(skill_name, value):
        band = gatherband.band_for(lock, skill_name)
        if band is not None and int(value) < band + GREY_AFTER:
            out.append(lock)
    return out


def target_for(skills) -> str:
    """The farm job one member can still advance with its own skills (#2498).

    `skills` is that member's {trade name: value}. Of the aimable trades it
    holds with a node that still gives skill, the lowest is taken, the same
    "most starved" rule gatheraim uses. A member with none (skinning, tailoring
    and the other trades with no node to walk to) has no farm target: "".
    """
    best = None
    for name in SKILLS:
        try:
            have = int((skills or {}).get(name))
        except (TypeError, ValueError):
            continue
        if not skill_locks(name, have):
            continue
        if best is None or have < best[1]:
            best = (name, have)
    return job_for(best[0]) if best else ""


@dataclass(frozen=True)
class Order:
    """One farm order, as the bridge read it."""

    job: str
    item: int = 0
    skill: str = ""
    name: str = ""
    started: float = 0.0
    target: int = TARGET_COUNT
    time_box: float = TIME_BOX_SECONDS


@dataclass(frozen=True)
class Reads:
    """Everything one decision needs, read by the bridge this pass.

    `spawns` are the material's node spawns on EVERY map (for an item) or the
    leader's map (for a skill), each with its lock. `leader_at` is the leader's
    snapshot row (map_id, zone_id, pos_x, pos_y) or None. `deaths` is
    [(zone id, map id)] for the family since the order began. `walking` is the
    spawn this job's own aim still holds in the column, or None. `visited` is
    {(map, x, y): when it was aimed at}.
    """

    skills: dict
    levels: dict
    leader_at: object
    spawns: tuple
    zone_levels: dict
    deaths: tuple = ()
    free_slots: dict = dataclasses.field(default_factory=dict)
    gathered: int = 0
    walking: object = None
    visited: dict = dataclasses.field(default_factory=dict)
    now: float = 0.0
    # When the leader began standing within HOP_MIN_YARDS of a node spawn, or
    # 0.0 when it is not standing at one (or nobody has read it).
    stood_since: float = 0.0


@dataclass(frozen=True)
class Step:
    """What to do this pass, and the one line that says so."""

    action: str
    line: str
    spawn: object = None
    zone_id: int = 0
    # An END that a family in the profession loop should answer with a fresh
    # order rather than by leaving the farm: a spent time box or a met target.
    renew: bool = False


# How far from the leader a member may stand and still take part in the order.
# The rest follow on their own strategy; a member further out, on another map
# or inside an instance is not part of the order (it would only hold the
# family's bag, death and job reads hostage).
REACH_YARDS = 300.0


def in_reach(positions, leader) -> list:
    """The sorted names the order covers: the leader and every member on the
    leader's map, outside any instance, within REACH_YARDS of it.

    `positions` is name -> snapshot row (map_id, instance_id, pos_x, pos_y).
    With no reading of the leader nobody is cut, which is the old behaviour.
    """
    here = (positions or {}).get(leader)
    if not here or here.get("map_id") is None:
        return sorted(positions or {})
    out = []
    for name, row in positions.items():
        if name == leader:
            out.append(name)
            continue
        if row.get("map_id") is None or int(row["map_id"]) != int(here["map_id"]):
            continue
        if int(row.get("instance_id") or 0) != int(here.get("instance_id") or 0):
            continue
        if int(row.get("instance_id") or 0):
            continue
        dx = float(row.get("pos_x") or 0.0) - float(here.get("pos_x") or 0.0)
        dy = float(row.get("pos_y") or 0.0) - float(here.get("pos_y") or 0.0)
        if (dx * dx + dy * dy) ** 0.5 <= REACH_YARDS:
            out.append(name)
    return sorted(out)


def spawn_key(spawn) -> tuple:
    return (int(spawn.map_id), round(float(spawn.x), 1), round(float(spawn.y), 1))


def spawn_unsafe(top, levels) -> str:
    """Why one spawn's own neighbourhood is not safe to send the family to, or "".

    `top` is the highest creature level spawned near it (None when nothing
    was measured, which is refused like gatheraim refuses an unmeasured zone).
    """
    lowest = min((int(v) for v in (levels or {}).values()), default=0)
    if top is None:
        return "nothing near it was measured"
    if lowest and int(top) > lowest + LEVEL_MARGIN:
        return "level %d creatures stand near it and the weakest member is %d" % (
            int(top),
            lowest,
        )
    return ""


def _what(order) -> str:
    if order.skill:
        return "%s skill" % order.skill
    return order.name or "item %d" % order.item


def usable(order, spawns, skills) -> tuple:
    """(spawns somebody can open, the refusal when nobody can open any).

    For an item, the lowest band among its nodes is what the refusal names, so
    "Dreamfoil needs herbalism 270, the best herbalist has 200" is said rather
    than "no field".
    """
    best = best_skills(skills)
    if order.skill and order.skill not in best:
        return [], "nobody in the family has %s" % order.skill
    open_, bands = [], []
    for spawn in spawns or ():
        name, band = skill_of_lock(spawn.lock_id)
        if name is None:
            continue
        if order.skill and name != order.skill:
            continue
        bands.append((band, name))
        have = best.get(name)
        if have is None or int(have) < band:
            continue
        if order.skill and int(have) >= band + GREY_AFTER:
            continue
        open_.append(spawn)
    if open_:
        return open_, ""
    if not bands:
        return [], (
            "no herb or ore node in this world drops %s, so there is nowhere to "
            "farm it" % _what(order)
        )
    band, name = min(bands)
    return [], (
        "%s needs %s %d at its lowest node and the family's best is %s, so no "
        "node of it can be opened" % (_what(order), name, band, best.get(name, "none"))
    )


def fields(spawns, leader_at, visited=None, now=0.0) -> list:
    """[(yards to the nearest spawn, zone id, nodes, nearest spawn)] on the
    leader's map, nearest field first and the densest breaking a tie.

    The spawn named for a field is the nearest one not tried within
    REVISIT_SECONDS (`visited`), so a spawn the travel column refused is not
    asked for again every pass; when every spawn was tried, the nearest."""
    if not leader_at or leader_at.get("map_id") is None:
        return []
    here = int(leader_at["map_id"])
    origin = (
        float(leader_at.get("pos_x") or 0.0),
        float(leader_at.get("pos_y") or 0.0),
    )
    per_zone = {}
    for spawn in spawns:
        if int(spawn.map_id) != here or not int(spawn.zone_id or 0):
            continue
        per_zone.setdefault(int(spawn.zone_id), []).append(spawn)
    out = []
    for zone, rows in per_zone.items():
        fresh = [
            r
            for r in rows
            if now - (visited or {}).get(spawn_key(r), -REVISIT_SECONDS)
            >= REVISIT_SECONDS
        ]
        near = min(fresh or rows, key=lambda s: gatheraim.yards(s, origin))
        out.append((gatheraim.yards(near, origin), zone, len(rows), near))
    out.sort(key=lambda r: (r[0], -r[2], r[1]))
    return out


def struck_zones(deaths) -> dict:
    """{zone id: deaths} for every zone at or past ZONE_DEATHS."""
    count = {}
    for zone, _map in deaths or ():
        count[int(zone)] = count.get(int(zone), 0) + 1
    return {z: n for z, n in count.items() if n >= ZONE_DEATHS}


def _next_hop(rows, origin, visited, now):
    """The nearest spawn in the field not visited lately and not already in
    the bots' own reach; the longest-unvisited one when every spawn is."""
    fresh = []
    for spawn in rows:
        when = visited.get(spawn_key(spawn))
        if when is not None and now - when < REVISIT_SECONDS:
            continue
        if gatheraim.yards(spawn, origin) < HOP_MIN_YARDS:
            continue
        fresh.append(spawn)
    if fresh:
        return min(fresh, key=lambda s: gatheraim.yards(s, origin))
    far = [s for s in rows if gatheraim.yards(s, origin) >= HOP_MIN_YARDS]
    if not far:
        return None
    return min(
        far, key=lambda s: (visited.get(spawn_key(s), 0.0), gatheraim.yards(s, origin))
    )


def _ending(order, reads, what):
    """The END step for a met count, a spent time box or too many deaths."""
    elapsed = max(0.0, float(reads.now) - float(order.started))
    if elapsed >= float(order.time_box):
        return Step(
            END,
            "the %d-minute time box is up with %d %s gathered"
            % (int(order.time_box // 60), reads.gathered, what),
            renew=True,
        )
    if order.item and reads.gathered >= int(order.target):
        return Step(
            END,
            "the target is met: %d of %d %s gathered"
            % (reads.gathered, int(order.target), what),
            renew=True,
        )
    if len(reads.deaths or ()) >= TOTAL_DEATHS:
        return Step(
            END,
            "%d deaths since the farm began, at or past %d, so the "
            "family stops farming %s" % (len(reads.deaths), TOTAL_DEATHS, what),
        )
    return None


def _judge(zone, top, struck, ceiling):
    """Why a field may not be farmed, or ""."""
    if zone in struck:
        return "zone %d struck off after %d deaths" % (zone, struck[zone])
    if top is None:
        return "zone %d not measured" % zone
    if ceiling and int(top) > ceiling:
        return "zone %d tops out at %d" % (zone, int(top))
    return ""


def safe_fields(candidates, reads):
    """([(yards, zone, nodes, nearest spawn, top level)], [reasons refused])."""
    struck = struck_zones(reads.deaths)
    lowest = min((int(v) for v in (reads.levels or {}).values()), default=0)
    ceiling = lowest + LEVEL_MARGIN if lowest else 0
    safe, said = [], []
    for far, zone, nodes, near in candidates:
        top = (reads.zone_levels or {}).get(zone)
        why = _judge(zone, top, struck, ceiling)
        if why:
            said.append(why)
        else:
            safe.append((far, zone, nodes, near, int(top)))
    return safe, said


# How long the family stands at a node before hopping on. The bots gather what
# is within reach of where they stand, a node can be mid-respawn, and a hop the
# moment the leader arrives gave them no time at all.
DWELL_SECONDS = 120.0


def stand_update(prev, spawns, leader_at, now):
    """(spawn key the leader stands at, since when) after this pass.

    `prev` is the last answer. The start is kept while the leader stays at the
    same spawn and restarts at another; (None, 0.0) when it stands at none.
    """
    if not leader_at or leader_at.get("map_id") is None:
        return (None, 0.0)
    origin = (
        float(leader_at.get("pos_x") or 0.0),
        float(leader_at.get("pos_y") or 0.0),
    )
    best = None
    for spawn in spawns or ():
        if int(spawn.map_id) != int(leader_at["map_id"]):
            continue
        if int(spawn.zone_id or 0) != int(leader_at.get("zone_id") or 0):
            continue
        gap = gatheraim.yards(spawn, origin)
        if gap < HOP_MIN_YARDS and (best is None or gap < best[0]):
            best = (gap, spawn)
    if best is None:
        return (None, 0.0)
    key = spawn_key(best[1])
    if prev and prev[0] == key and prev[1]:
        return prev
    return (key, float(now))


def _hop(open_, reads, what, standing):
    """The HOP step inside the field, or a WAIT when every node is in reach."""
    here = int(reads.leader_at["map_id"])
    origin = (
        float(reads.leader_at.get("pos_x") or 0.0),
        float(reads.leader_at.get("pos_y") or 0.0),
    )
    rows = [s for s in open_ if int(s.map_id) == here and int(s.zone_id) == standing]
    since = float(reads.stood_since or 0.0)
    at_node = any(gatheraim.yards(s, origin) < HOP_MIN_YARDS for s in rows)
    if at_node and since and float(reads.now) - since < DWELL_SECONDS:
        return Step(
            WAIT,
            "dwelling at a %s spawn for %d of %d seconds so the bots gather it"
            % (what, int(float(reads.now) - since), int(DWELL_SECONDS)),
            zone_id=standing,
        )
    hop = _next_hop(rows, origin, reads.visited or {}, float(reads.now))
    if hop is None:
        return Step(
            WAIT,
            "every %s node in zone %d is within %d yards, so the "
            "bots' own gathering reaches it" % (what, standing, int(HOP_MIN_YARDS)),
            zone_id=standing,
        )
    return Step(
        HOP,
        "hopping %d yards to the next %s spawn in zone %d, %d gathered "
        "so far" % (int(gatheraim.yards(hop, origin)), what, standing, reads.gathered),
        spawn=hop,
        zone_id=standing,
    )


def _where(open_, reads, what):
    """WALK to the nearest safe field, WAIT on a walk in flight, or HOP."""
    here = int(reads.leader_at["map_id"])
    candidates = fields(open_, reads.leader_at, reads.visited or {}, float(reads.now))
    if not candidates:
        maps = sorted({int(s.map_id) for s in open_})
        return Step(
            END,
            "every %s node the family can open is on map %s and the "
            "family stands on map %d; a farm walk never leaves its map"
            % (what, ", ".join(str(m) for m in maps), here),
        )
    safe, said = safe_fields(candidates, reads)
    if not safe:
        lowest = min((int(v) for v in (reads.levels or {}).values()), default=0)
        return Step(
            END,
            "no field of %s on map %d is safe for a family whose "
            "weakest member is %d (%s)" % (what, here, lowest, "; ".join(said)),
        )
    zones = {row[1] for row in safe}
    walking = reads.walking
    if walking is not None and int(walking.zone_id) in zones:
        return Step(
            WAIT,
            "the leader is still walking to the %s spawn at "
            "%.1f,%.1f in zone %d" % (what, walking.x, walking.y, int(walking.zone_id)),
            zone_id=int(walking.zone_id),
        )
    standing = int(reads.leader_at.get("zone_id") or 0)
    if standing in zones:
        return _hop(open_, reads, what, standing)
    far, zone, nodes, near, top = safe[0]
    return Step(
        WALK,
        "walking the family %d yards to zone %d, which holds %d "
        "%s node(s) somebody can open and tops out at level %d"
        % (int(far), zone, nodes, what, top),
        spawn=near,
        zone_id=zone,
    )


def decide(order, reads) -> Step:
    """The one thing to do this pass for a family on `order`.

    In order: the job's own ends, full bags, nobody able to open the
    material, no snapshot to measure from, then where to stand.
    """
    what = _what(order)
    ended = _ending(order, reads, what)
    if ended is not None:
        return ended
    full = gatheraim.bags_block_gathering(reads.free_slots)
    if full:
        return Step(TOWN, full)
    open_, refused = usable(order, reads.spawns, reads.skills)
    if refused:
        return Step(END, refused)
    if not reads.leader_at or reads.leader_at.get("map_id") is None:
        return Step(
            WAIT,
            "the leader has no fresh snapshot row, so nobody "
            "can say where the family stands",
        )
    return _where(open_, reads, what)
