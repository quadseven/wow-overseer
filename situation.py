"""What a family's movement looks like right now, as a few facts Jev can read.

WHY THIS EXISTS. Every Jev question so far is asked about bags, levels and
queues, and none of them can see where the family is or whether it is getting
anywhere. A family can be 1,388 yards apart with one member 190 yards below the
rest, dying to the same elite three times in ten minutes, or standing still
while the travel column says it is walking to a vendor, and the activity
choice reads exactly the same state as it does on a quiet afternoon. The facts
to see all of that already exist in the realm's tables; this module turns them
into one compact block any kind can carry.

WHAT IT COVERS, ONE FUNCTION EACH, EVERY ONE PURE:

  where      position and zone of each member (overseer_snapshot, which the
             module refreshes every few seconds; `characters` is up to 15
             minutes stale and is never read for this).
  goal       the leader's aim, as a point where one can be named: an `at:`
             aim in the travel column, or the door of a `dungeon:<keyword>`
             job. Distance and height to it.
  progress   what the last few minutes of samples say: moving, still, stuck
             (still with somewhere to be), circling, flying or teleported.
             The samples come from `Tracker`, which the bridge fills on its
             own clock, because no table keeps a position history.
  route      the travel survey (acore_playerbots.playerbots_travelnode): the
             nearest survey node to the leader and to the goal, and whether
             the leader can reach one. mod-overseer refuses a node it cannot
             walk to ("442 yards across, 193 up or down"), and so does this.
  danger     hostile spawn points near the leader from the world tables:
             how many, how many elite, and how far above the weakest member.
             Spawn points, not live creatures: a place's potential, not a
             count of what is alive.
  deaths     the family's deaths in the last half hour and what killed them
             (overseer_death).
  cohesion   the spread around the leader and who is far, in yards and in
             height.
  travel     who holds the family's one travel column (townslot.Slot) and
             what each member's column says.

WHAT IT REFUSES TO DO. It never decides anything and never writes anything.
It holds no connection: the bridge reads, this module shapes. A fact that
could not be read is "unknown", never a default that reads as a finding: a
member with no snapshot is not standing at 0,0,0, and no deaths read is not
"no deaths".

SIZE ON PURPOSE. TypeSafe's own guidance is that accuracy falls as the state
grows with content unrelated to the decision, so `Situation.state()` is a few
short fields per family and lists are capped.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

# How far back progress looks, and how much trail is kept per character.
PROGRESS_SECONDS = 300.0
TRAIL_SECONDS = 900.0
TRAIL_MAX = 64
# Fewer seconds of trail than this say nothing about progress.
MIN_SPAN_SECONDS = 60.0

# Base run speed is 7 yards a second and a 100% mount 14; a taxi flies at
# about 32. Anything faster than a mount on one leg is a flight, and faster
# than any flight, or a map change, is a teleport or a zone-in.
FLYING_YPS = 20.0
TELEPORT_YPS = 80.0
# Less than this over the whole window is standing still.
STILL_YARDS = 8.0
# A walk that went this far and ended up this little of it away from where it
# started is circling.
CIRCLING_MIN_YARDS = 40.0
CIRCLING_RATIO = 0.35
# Within this of the goal is arrived (townslot.ARRIVED_YARDS says the same).
ARRIVED_YARDS = 15.0

# mod-overseer's own follow limit: a member past this is "far", and the leader
# holds for it ("until that member is back within 100 yards").
FAR_YARDS = 100.0

# Danger is read in this radius around the leader.
DANGER_YARDS = 60.0
# How far the survey node search looks, and what counts as reachable: the
# node must be near and not a cliff away.
NODE_SEARCH_YARDS = 600.0
NODE_REACH_YARDS = 150.0
NODE_REACH_HEIGHT = 40.0

DEATH_WINDOW_SECONDS = 1800

# The lists a state carries are capped (see SIZE ON PURPOSE).
MAX_LISTED = 3

MOVING = "moving"
STILL = "still"
STUCK = "stuck"
CIRCLING = "circling"
FLYING = "flying"
TELEPORTED = "teleported"
UNKNOWN = "unknown"

# creature_template.rank.
RANK_WORDS = {1: "elite", 2: "rare elite", 3: "boss", 4: "rare"}
ELITE_RANKS = frozenset({1, 2, 3})

# FactionGroup masks in FactionTemplate: every player, Alliance, Horde.
PLAYER_MASK = 1
ALLIANCE_MASK = 2
HORDE_MASK = 4


def enabled(environ=None) -> bool:
    """SITUATION_MODE=off leaves every question as it was; anything else on."""
    env = os.environ if environ is None else environ
    return str(env.get("SITUATION_MODE", "") or "").strip().lower() != "off"


@dataclass(frozen=True)
class Point:
    """A place on one map. `z` is None when the source gives none (a door in
    entrances.json has no height)."""

    map: int
    x: float
    y: float
    z: float | None = None


def yards(a: Point | None, b: Point | None) -> float | None:
    """Straight-line yards between two points on one map, or None.

    Different maps are None rather than a number: a straight line from
    Kalimdor to the Eastern Kingdoms is not a distance anybody can walk.
    Height counts only when both points have one.
    """
    if a is None or b is None or a.map != b.map:
        return None
    dz = (a.z - b.z) if (a.z is not None and b.z is not None) else 0.0
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + dz**2)


def height(a: Point | None, b: Point | None) -> float | None:
    """How far `b` is above `a` (negative is below), or None."""
    if a is None or b is None or a.map != b.map or a.z is None or b.z is None:
        return None
    return b.z - a.z


@dataclass(frozen=True)
class Body:
    """One member as the snapshot has them. `age` is seconds since the row
    was refreshed; None when the member has no snapshot row at all."""

    name: str
    at: Point | None
    zone: int = 0
    health: int = 0
    max_health: int = 0
    in_combat: bool = False
    age: int | None = None

    @property
    def health_pct(self) -> int | None:
        if self.max_health <= 0:
            return None
        return int(round(100.0 * self.health / self.max_health))

    @property
    def dead(self) -> bool:
        return self.at is not None and self.max_health > 0 and self.health <= 0


def bodies_from_rows(names, rows) -> tuple:
    """Bodies in `names` order from overseer_snapshot rows. Pure.

    A member with no row is kept with `at` None, so the question can say it
    is not seen rather than drop it.
    """
    by_name = {str(r.get("name")): r for r in rows or ()}
    out = []
    for name in names:
        r = by_name.get(name)
        if r is None:
            out.append(Body(name=name, at=None))
            continue
        out.append(
            Body(
                name=name,
                at=Point(
                    int(r.get("map_id") or 0),
                    float(r.get("pos_x") or 0.0),
                    float(r.get("pos_y") or 0.0),
                    float(r.get("pos_z") or 0.0),
                ),
                zone=int(r.get("zone_id") or 0),
                health=int(r.get("health") or 0),
                max_health=int(r.get("max_health") or 0),
                in_combat=bool(r.get("in_combat")),
                age=None if r.get("age") is None else int(r.get("age")),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# THE TRAIL


@dataclass(frozen=True)
class Sample:
    t: float
    at: Point


class Tracker:
    """Recent positions per character, in memory, bounded.

    Nothing in the realm keeps a position history (overseer_snapshot holds one
    row per character and overwrites it), so progress over minutes needs this.
    `t` is whatever monotonic clock the caller uses. A restart starts empty,
    and progress reads unknown until the trail is long enough again.
    """

    def __init__(self, keep: float = TRAIL_SECONDS, cap: int = TRAIL_MAX):
        self.keep = float(keep)
        self.cap = int(cap)
        self._trails: dict = {}

    def record(self, name: str, at: Point | None, t: float) -> None:
        if at is None:
            return
        trail = self._trails.setdefault(name, deque(maxlen=self.cap))
        trail.append(Sample(float(t), at))
        while trail and trail[0].t < t - self.keep:
            trail.popleft()

    def record_bodies(self, bodies, t: float) -> None:
        for body in bodies:
            self.record(body.name, body.at, t)

    def trail(self, name: str, now: float, window: float = PROGRESS_SECONDS) -> list:
        return [s for s in self._trails.get(name, ()) if s.t >= now - window]


@dataclass(frozen=True)
class Progress:
    verdict: str
    moved_yards: int = 0
    net_yards: int = 0
    minutes: float = 0.0
    closing_yards: int | None = None


def _legs(samples) -> tuple:
    """(yards walked, fastest leg in yards a second, whether the map changed)."""
    moved = 0.0
    fastest = 0.0
    zoned = False
    for a, b in zip(samples, samples[1:], strict=False):
        leg = yards(a.at, b.at)
        if leg is None:
            zoned = True
            continue
        moved += leg
        fastest = max(fastest, leg / max(b.t - a.t, 1e-6))
    return moved, fastest, zoned


def _closing(first: Point, last: Point, goal: Point | None) -> int | None:
    """How many yards nearer the goal the trail ended, or None."""
    if goal is None:
        return None
    before, after = yards(first, goal), yards(last, goal)
    if before is None or after is None:
        return None
    return int(round(before - after))


def _verdict(moved, fastest, zoned, net, has_goal: bool, arrived: bool) -> str:
    if zoned or fastest >= TELEPORT_YPS:
        return TELEPORTED
    if fastest >= FLYING_YPS:
        return FLYING
    if moved < STILL_YARDS:
        return STUCK if (has_goal and not arrived) else STILL
    circling = (
        moved >= CIRCLING_MIN_YARDS and net is not None and net < CIRCLING_RATIO * moved
    )
    return CIRCLING if (circling and not arrived) else MOVING


def progress(trail, goal: Point | None = None) -> Progress:
    """What a trail says about getting anywhere. Pure.

    STILL AND STUCK ARE DIFFERENT FINDINGS. A family standing at a vendor is
    still and fine; one that has a goal it has not reached and has not moved
    is stuck. Only the second is a problem, so only it gets the word.
    """
    samples = list(trail or ())
    if len(samples) < 2 or samples[-1].t - samples[0].t < MIN_SPAN_SECONDS:
        return Progress(UNKNOWN)
    moved, fastest, zoned = _legs(samples)
    first, last = samples[0].at, samples[-1].at
    net = yards(first, last)
    left = yards(last, goal) if goal is not None else None
    arrived = left is not None and left <= ARRIVED_YARDS
    return Progress(
        _verdict(moved, fastest, zoned, net, goal is not None, arrived),
        moved_yards=int(round(moved)),
        net_yards=int(round(net or 0.0)),
        minutes=round((samples[-1].t - samples[0].t) / 60.0, 1),
        closing_yards=_closing(first, last, goal),
    )


# ---------------------------------------------------------------------------
# THE GOAL

_AT = re.compile(r"^at:(\d+):(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)$")


def _entrances() -> dict:
    """entrances.json, or {} when it cannot be read: every door is then
    unknown, which the goal and the dungeon distances already say."""
    try:
        with open(Path(__file__).resolve().parent / "entrances.json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_DOORS: dict | None = None


def door(keyword: str) -> Point | None:
    """The door of a portal keyword's dungeon (entrances.json), or None."""
    global _DOORS
    import dungeonpath

    map_id = dungeonpath.PORTAL_MAPS.get(str(keyword or "").strip().lower())
    if map_id is None:
        return None
    if _DOORS is None:
        _DOORS = _entrances()
    rec = _DOORS.get(str(map_id))
    if not rec:
        return None
    return Point(int(rec["map"]), float(rec["x"]), float(rec["y"]), None)


@dataclass(frozen=True)
class Goal:
    """What the leader is heading for. `at` is None when the aim names a role
    (a vendor, a banker) that only mod-overseer resolves to a spawn."""

    aim: str
    at: Point | None = None


def goal_of(travel_npc: str, job: str) -> Goal | None:
    """The leader's goal from its travel column, else its dungeon job. Pure.

    The column wins: a family on `dungeon:ragefire` walking to a vendor first
    is heading for the vendor.
    """
    aim = str(travel_npc or "").strip()
    if aim:
        m = _AT.match(aim)
        if m:
            return Goal(
                aim,
                Point(
                    int(m.group(1)),
                    float(m.group(2)),
                    float(m.group(3)),
                    float(m.group(4)),
                ),
            )
        return Goal(aim)
    job = str(job or "").strip().lower()
    if job.startswith("dungeon:"):
        keyword = job.split(":", 1)[1]
        return Goal(job, door(keyword))
    return None


# ---------------------------------------------------------------------------
# DANGER, DEATHS, ROUTE, COHESION, TRAVEL


def side_mask(races) -> int:
    """The FactionGroup bit for a family's side, or 0 when mixed or unread."""
    from core import _ALLIANCE_RACES, _HORDE_RACES

    got = {int(r) for r in races or () if r}
    if got and got <= set(_ALLIANCE_RACES):
        return ALLIANCE_MASK
    if got and got <= set(_HORDE_RACES):
        return HORDE_MASK
    return 0


def hostile(enemy_group, side: int) -> bool | None:
    """Whether a spawn's FactionTemplate EnemyGroup attacks this family.
    None when the template is not in the table (the dbc table is partial)."""
    if enemy_group is None:
        return None
    group = int(enemy_group)
    return bool(group & PLAYER_MASK) or bool(side and group & side)


def _rank(row) -> int:
    return int(row.get("rank") or 0)


def _label(row) -> str:
    """ "Gorishi Hive Guard (elite, 52-53)": name, rank word and levels."""
    word = RANK_WORDS.get(_rank(row))
    return "%s (%s%d-%d)" % (
        str(row.get("name") or "?"),
        (word + ", ") if word else "",
        int(row.get("minlevel") or 0),
        int(row.get("maxlevel") or 0),
    )


def _hostiles_near(spawns, around: Point, side: int) -> list:
    """(yards, row) for each hostile spawn within DANGER_YARDS of `around`."""
    near = []
    for r in spawns or ():
        d = yards(
            around, Point(around.map, float(r["x"]), float(r["y"]), float(r["z"]))
        )
        if d is not None and d <= DANGER_YARDS and hostile(r.get("enemy_group"), side):
            near.append((d, r))
    return near


def _worst(near) -> list:
    """The distinct labels of the worst spawns: elites first, then level, then
    the nearest, at most MAX_LISTED."""
    ranked = sorted(
        near,
        key=lambda dr: (
            -(_rank(dr[1]) in ELITE_RANKS),
            -int(dr[1].get("maxlevel") or 0),
            dr[0],
        ),
    )
    named: list = []
    for _, r in ranked:
        label = _label(r)
        if label not in named:
            named.append(label)
    return named[:MAX_LISTED]


def danger(spawns, around: Point | None, weakest_level: int, side: int) -> dict | None:
    """Hostile spawn points within DANGER_YARDS of `around`. Pure.

    `spawns` are rows with name, minlevel, maxlevel, rank, enemy_group and
    x/y/z on the same map (the bridge boxes the read). None when there is no
    position to read around.
    """
    if around is None:
        return None
    near = _hostiles_near(spawns, around, side)
    if not near:
        return {"hostile_spawns": 0}
    top = max(int(r.get("maxlevel") or 0) for _, r in near)
    return {
        "hostile_spawns": len(near),
        "elites": sum(1 for _, r in near if _rank(r) in ELITE_RANKS),
        "highest_level": top,
        "levels_above_weakest_member": max(0, top - int(weakest_level or 0)),
        "worst": _worst(near),
    }


def deaths(rows) -> dict | None:
    """The family's recent deaths and their killers. None when unread. Pure."""
    if rows is None:
        return None
    rows = list(rows)
    killers: dict = {}
    for r in rows:
        who = str(r.get("killer_name") or r.get("killer_type") or "unknown")
        killers[who] = killers.get(who, 0) + 1
    ranked = sorted(killers.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_LISTED]
    out = {"count": len(rows)}
    if rows:
        out["killers"] = ["%s x%d" % (k, n) if n > 1 else k for k, n in ranked]
        ages = [int(r["age"]) for r in rows if r.get("age") is not None]
        if ages:
            out["minutes_since_last"] = min(ages) // 60
        victims = sorted({str(r.get("character_name") or "") for r in rows} - {""})
        out["who"] = victims[: MAX_LISTED + 2]
    return out


def nearest_node(nodes, at: Point | None) -> dict | None:
    """The nearest survey node to `at` and whether it can be walked to. Pure."""
    if at is None or not nodes:
        return None
    best = None
    for n in nodes:
        p = Point(at.map, float(n["x"]), float(n["y"]), float(n["z"]))
        flat = math.hypot(p.x - at.x, p.y - at.y)
        if best is None or flat < best[0]:
            best = (flat, p, n)
    flat, p, n = best
    up = height(at, p) or 0.0
    return {
        "node": str(n.get("name") or n.get("id")),
        "yards": int(round(flat)),
        "height": int(round(up)),
        "reachable": flat <= NODE_REACH_YARDS and abs(up) <= NODE_REACH_HEIGHT,
    }


def route(
    leader_nodes,
    goal_nodes,
    leader: Point | None,
    goal: Goal | None,
    leader_progress: Progress | None,
) -> dict:
    """The way the leader is taking, as far as the survey and the trail say."""
    out = {}
    here = nearest_node(leader_nodes, leader)
    out["nearest_survey_node"] = here or "none within reach of the search"
    if goal is not None and goal.at is not None:
        there = nearest_node(goal_nodes, goal.at)
        if there:
            out["survey_node_at_goal"] = there["node"]
    if leader_progress is not None and leader_progress.verdict == FLYING:
        out["on_a_flight"] = True
    return out


def cohesion(bodies, leader: str) -> dict:
    """How far each member is from the leader, and who is far. Pure."""
    lead = next((b for b in bodies if b.name == leader), None)
    if lead is None or lead.at is None:
        return {"spread_yards": UNKNOWN}
    spread = 0.0
    far = []
    unseen = []
    for b in bodies:
        if b.name == leader:
            continue
        if b.at is None:
            unseen.append(b.name)
            continue
        d = yards(lead.at, b.at)
        if d is None:
            far.append((1e9, "%s on another map" % b.name))
            continue
        spread = max(spread, d)
        if d > FAR_YARDS:
            up = height(lead.at, b.at) or 0.0
            where = (
                ", %d below" % int(round(-up))
                if up < -10
                else (", %d above" % int(round(up)) if up > 10 else "")
            )
            far.append((d, "%s %d yd%s" % (b.name, int(round(d)), where)))
    out = {"spread_yards": int(round(spread))}
    if far:
        out["far_from_leader"] = [text for _, text in sorted(far, reverse=True)][
            : MAX_LISTED + 2
        ]
    if unseen:
        out["not_seen"] = unseen
    return out


def travel(holder, campaign: str, columns: dict) -> dict:
    """Who holds the travel column and what each member's says. Pure.

    `holder` is a townslot.Holder or None; `columns` is name -> travel_npc.
    """
    out = {}
    if holder is not None:
        out["held_by"] = holder.claimant or "an aim this process did not write"
        out["aim"] = holder.aim
    else:
        out["held_by"] = "nobody"
    if campaign:
        out["campaign_owns_it"] = campaign
    aimed = {n: a for n, a in (columns or {}).items() if a}
    if aimed:
        out["columns"] = aimed
    return out


# ---------------------------------------------------------------------------
# THE WHOLE PICTURE


@dataclass(frozen=True)
class Situation:
    """One family's movement picture. `state()` is what Jev reads."""

    leader: str
    bodies: tuple
    goal: Goal | None = None
    progress: dict = field(default_factory=dict)
    route: dict = field(default_factory=dict)
    danger: dict | None = None
    deaths: dict | None = None
    cohesion: dict = field(default_factory=dict)
    travel: dict = field(default_factory=dict)
    zone_name: str = ""
    vision: dict | None = None
    # The leader's trail in numbers, not only its verdict: how far he walked,
    # how far that got him, and how much nearer his goal (mod-overseer#722).
    # Jev read "moving" or "stuck" and nothing else, and a walk that bends away
    # from its goal reads "moving" whether it is closing or not.
    lead_progress: Progress | None = None
    # mod-overseer's intent book for the leader (overseer_family_intent): what
    # holds him, for how long, what else is asking, his distance to what his
    # errand resolved to, and what the module is doing with each member. None
    # on a realm without the table.
    intent: dict | None = None

    @property
    def lead_body(self) -> Body | None:
        return next((b for b in self.bodies if b.name == self.leader), None)

    def goal_state(self) -> dict | str:
        if self.goal is None:
            return "none"
        lead = self.lead_body
        out = {"aim": self.goal.aim}
        if self.goal.at is None:
            # The module resolves a role to a spawn and says how far it is.
            known = (self.intent or {}).get("goal_yards")
            out["yards"] = (
                int(known)
                if known is not None
                else "unknown: the aim names a role, not a place"
            )
            return out
        if lead is None or lead.at is None:
            out["yards"] = UNKNOWN
            return out
        if lead.at.map == _dungeon_map(self.goal.aim):
            out["inside_the_dungeon"] = True
            return out
        d = yards(lead.at, self.goal.at)
        if d is None:
            out["yards"] = "on another map"
            return out
        out["yards"] = int(round(d))
        up = height(lead.at, self.goal.at)
        out["height"] = UNKNOWN if up is None else int(round(up))
        out["arrived"] = d <= ARRIVED_YARDS
        return out

    def yards_to_door(self, keyword: str) -> int | str:
        """Yards from the leader to a dungeon's door, or why there is none."""
        lead = self.lead_body
        target = door(keyword)
        if lead is None or lead.at is None or target is None:
            return UNKNOWN
        d = yards(lead.at, target)
        return "another continent" if d is None else int(round(d))

    def state(self) -> dict:
        lead = self.lead_body
        members = []
        for b in self.bodies:
            if b.at is None:
                members.append({"name": b.name, "seen": False})
                continue
            m = {"name": b.name, "movement": self.progress.get(b.name, UNKNOWN)}
            if b.dead:
                m["dead"] = True
            elif b.health_pct is not None and b.health_pct < 100:
                m["health_pct"] = b.health_pct
            if b.in_combat:
                m["in_combat"] = True
            members.append(m)
        out = {
            "zone": self.zone_name or UNKNOWN,
            "leader": self.leader,
            "goal": self.goal_state(),
            "members": members,
            "cohesion": self.cohesion,
            "route": self.route,
            "danger_near_leader": UNKNOWN if self.danger is None else self.danger,
            "deaths_last_30_min": UNKNOWN if self.deaths is None else self.deaths,
            "travel_column": self.travel,
        }
        if lead is not None and lead.at is None:
            out["leader_seen"] = False
        out.update(self._leader_extras())
        return out

    def _leader_extras(self) -> dict:
        """The leader's trail in numbers, the module's intent book and his
        screen, each only when there is one."""
        out = {}
        trail = trail_state(self.lead_progress)
        if trail is not None:
            out["leader_trail"] = trail
        if self.intent is not None:
            out["leader_intent"] = intent_state(self.intent)
        if self.vision is not None:
            out["leader_screen"] = self.vision
        return out

    def line(self, limit: int = 300) -> str:
        """The situation in one short line, for the record's facts column."""
        parts = ["zone %s" % (self.zone_name or "?")]
        g = self.goal_state()
        if isinstance(g, dict):
            far = g.get("yards")
            if g.get("inside_the_dungeon"):
                parts.append("goal %s, inside" % g.get("aim"))
            else:
                parts.append(
                    "goal %s %s"
                    % (g.get("aim"), "%d yd" % far if isinstance(far, int) else "?")
                )
        lead_move = self.progress.get(self.leader)
        if lead_move:
            parts.append("leader %s" % lead_move)
        spread = self.cohesion.get("spread_yards")
        parts.append("spread %s" % spread)
        far = self.cohesion.get("far_from_leader")
        if far:
            parts.append("far " + ", ".join(far))
        if self.danger and self.danger.get("hostile_spawns"):
            parts.append(
                "hostiles %d (elite %d, top %d)"
                % (
                    self.danger["hostile_spawns"],
                    self.danger.get("elites", 0),
                    self.danger.get("highest_level", 0),
                )
            )
        if self.deaths and self.deaths.get("count"):
            parts.append("deaths %d" % self.deaths["count"])
        if self.vision and self.vision.get("screen"):
            parts.append("screen %s" % self.vision["screen"])
        return "; ".join(parts)[:limit]


def trail_state(lp: Progress | None) -> dict | None:
    """A trail's numbers, or None when it says nothing yet. Pure."""
    if lp is None or lp.verdict == UNKNOWN:
        return None
    trail = {
        "walked_yards": lp.moved_yards,
        "net_yards": lp.net_yards,
        "over_minutes": lp.minutes,
    }
    if lp.closing_yards is not None:
        trail["nearer_goal_by_yards"] = lp.closing_yards
    return trail


def intent_state(row: dict) -> dict:
    """The module's intent book for the leader, as Jev reads it. Pure.

    `row` is one overseer_family_intent row as the bridge selects it
    (current_for and module_age already in seconds).
    """
    out = _intent_doing(row)
    asking = _intent_asking(row)
    if asking:
        out["also_asking"] = asking[: MAX_LISTED + 2]
    members = _intent_members(row)
    if members:
        out["members"] = members
    return out


def _intent_doing(row: dict) -> dict:
    out = {"doing": str(row.get("current_kind") or "none")}
    if out["doing"] == "none":
        return out
    out["asked_by"] = str(row.get("current_owner") or "")
    if row.get("current_target"):
        out["target"] = str(row["current_target"])
    if row.get("current_for") is not None:
        out["for_seconds"] = int(row["current_for"])
    return out


def _intent_asking(row: dict) -> list:
    """`kind|owner|target` lines as "kind target (by owner)"."""
    out = []
    for line in str(row.get("on_the_table") or "").splitlines():
        kind, _, rest = line.partition("|")
        owner, _, target = rest.partition("|")
        if kind:
            out.append(("%s %s" % (kind, target)).strip() + " (by %s)" % owner)
    return out


def _intent_members(row: dict) -> dict:
    """Every member not simply following: its state and yards from him."""
    out = {}
    for line in str(row.get("members_state") or "").splitlines():
        name, _, rest = line.partition("|")
        state, _, far = rest.partition("|")
        if not name or not state or state == "following":
            continue
        out[name] = _member_words(state, far)
    return out


def _member_words(state: str, far: str) -> str:
    if far.isdigit():
        return "%s, %s yd" % (state, far)
    return "%s, %s" % (state, far) if far else state


def zone_names() -> dict:
    """area id -> zone name, from the committed zones.json."""
    with open(Path(__file__).resolve().parent / "zones.json") as f:
        doc = json.load(f)
    out = {}
    for cont in (doc.get("continents") or {}).values():
        for z in cont.get("zones") or ():
            if z.get("area_id") is not None:
                out[int(z["area_id"])] = str(z.get("name") or "")
    return out


_ZONES: dict | None = None


def zone_name(zone_id: int, map_id: int | None = None) -> str:
    """The zone's name, or inside a dungeon the dungeon's (zones.json holds
    no zones inside an instance)."""
    global _ZONES
    if _ZONES is None:
        try:
            _ZONES = zone_names()
        except (OSError, ValueError):
            _ZONES = {}
    name = _ZONES.get(int(zone_id or 0), "")
    if name or map_id is None:
        return name
    return instance_name(map_id)


def instance_name(map_id: int) -> str:
    """A dungeon's name from its map id, via its first portal keyword."""
    import council
    import dungeonpath

    for keyword, m in dungeonpath.PORTAL_MAPS.items():
        if m == int(map_id):
            return council.keyword_place(keyword)
    return ""


def _dungeon_map(aim: str) -> int | None:
    import dungeonpath

    if not aim.startswith("dungeon:"):
        return None
    return dungeonpath.PORTAL_MAPS.get(aim.split(":", 1)[1])


def build(
    names,
    leader: str,
    snapshot_rows,
    tracker: Tracker | None,
    now: float,
    *,
    leader_travel: str = "",
    leader_job: str = "",
    spawn_rows=None,
    death_rows=None,
    leader_nodes=None,
    goal_nodes=None,
    races=(),
    weakest_level: int = 0,
    holder=None,
    campaign: str = "",
    columns: dict | None = None,
    vision: dict | None = None,
    intent: dict | None = None,
) -> Situation:
    """The whole picture from the bridge's reads. Pure, given the tracker.

    The tracker is read, not written: the caller records samples on its own
    clock, so asking twice in a minute does not shorten the trail's legs.
    """
    bodies = bodies_from_rows(list(names), snapshot_rows)
    goal = goal_of(leader_travel, leader_job)
    moves = {}
    lead_progress = None
    for b in bodies:
        trail = tracker.trail(b.name, now) if tracker is not None else []
        p = progress(trail, goal.at if (goal and b.name == leader) else None)
        moves[b.name] = p.verdict
        if b.name == leader:
            lead_progress = p
    lead = next((b for b in bodies if b.name == leader), None)
    lead_at = lead.at if lead else None
    return Situation(
        leader=leader,
        bodies=bodies,
        goal=goal,
        progress=moves,
        route=route(leader_nodes, goal_nodes, lead_at, goal, lead_progress),
        danger=(
            None
            if spawn_rows is None
            else danger(spawn_rows, lead_at, weakest_level, side_mask(races))
        ),
        deaths=deaths(death_rows),
        cohesion=cohesion(bodies, leader),
        travel=travel(holder, campaign, columns or {}),
        zone_name=zone_name(lead.zone, lead.at.map if lead.at else None)
        if lead
        else "",
        vision=vision,
        lead_progress=lead_progress,
        intent=intent,
    )


INSTRUCTION = (
    " `situation` is what the family's movement looks like right now, read "
    "from the world: where they are, whether each member is getting anywhere "
    "(stuck means standing still with a goal not reached), who is far from "
    "the leader, hostile spawns near the leader and how far above the weakest "
    "member they are, recent deaths and their killers, and what holds the "
    "family's one travel column. `leader_trail` is how far the leader walked "
    "in the last few minutes and how much nearer his goal that got him, and "
    "`leader_intent` is what the module is having him do, what else is asking "
    "for him, and what is being done with each member who is not simply "
    "following. A family that is stuck, scattered or dying "
    "to the same thing is not in shape for anything demanding until that is "
    "fixed."
)
