"""Ground the family died on twice is not a walk (#2457).

WHY THIS EXISTS. The town errand already passes over a vendor whose walk lies
along the family's recent deaths (townerrand.lethal_stop). Nothing did the
same for a ground aim or for the quest drive, so ground that had killed more
than once could be walked again.

WHAT IT DOES. It reads no database. Given `overseer_death` rows it finds
places where two or more deaths of kind lava, slime or fall (killer type
`self`, not drowning) cluster, as discs {map, centre, radius}, and answers
whether a straight line from one point to another crosses a disc. Nothing is
typed by hand: a disc exists because deaths exist, and ages out with them.

WHAT IT DOES NOT DO. It knows lines, not routes: the worldserver still picks
the path between the two ends, so a refusal here means "do not ask for this
walk", and the module's own avoidance (a separate change that needs a
worldserver roll) is what would route around a disc. The one step past a
refusal it can take is `detour`: given surveyed points (spawns the world
itself placed, read by the caller), it names the one whose two straight legs
both clear every disc, so the bridge can write the walk as two aims instead
of stranding it. The legs are still lines, with the same disagreement in
both directions. Drowning is left out on purpose: water deaths sit in every
lake and would void whole coasts.

PURE. Every function takes rows and points and returns plain values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import places
import travel

# Deaths within this many yards of a member of a cluster join it.
CLUSTER_YARDS = 150.0
# Deaths that make a place.
MIN_DEATHS = 2
# A disc is the cluster's reach plus this, never below or above these.
MARGIN_YARDS = 60.0
MIN_RADIUS = 100.0
MAX_RADIUS = 400.0
# A descent at least this long ending in a self death is a fall.
MIN_FALL_YARDS = 20.0
# How far back the rows are read, in days.
DEATH_DAYS = 7

SQL = (
    "SELECT map AS map_id, pos_x AS x, pos_y AS y, pos_z AS z, killer_type, "
    "liquid_type, yards_fallen FROM overseer_death "
    "WHERE created_at > NOW() - INTERVAL %s DAY AND killer_type = 'self'"
)

ENDS_SQL = (
    "SELECT e.quest AS quest, c.map AS map_id, c.position_x AS x, "
    "c.position_y AS y FROM acore_world.creature_questender e "
    "JOIN acore_world.creature c ON c.id = e.id WHERE e.quest IN ({quests})"
)


# The worldserver's own npcflag bit for each role keyword a travel aim may
# name (travel.ROLES mirrors the module's table of the same keys). A keyword
# aim names no ground: the worldserver walks to the nearest holder of the
# flag, so the bridge looks that holder up and judges the walk to it.
KEYWORD_FLAGS = {
    "trainer": 16,
    "class trainer": 32,
    "profession trainer": 64,
    "vendor": 128,
    "flight master": 8192,
    "repair": 4096,
    "innkeeper": 65536,
    "banker": 131072,
    "petitioner": 262144,
    "tabard designer": 524288,
    "guild petitioner": 262144 | 524288,
    "stable master": 4194304,
    "auctioneer": 2097152,
}


def keyword_mask(aim) -> int:
    """The npcflag mask a role-keyword aim walks to, or 0 for anything else
    (a ground aim, a flight node, a creature entry, nonsense)."""
    return KEYWORD_FLAGS.get(travel.resolve(aim) or "", 0)


@dataclass(frozen=True)
class Disc:
    map_id: int
    x: float
    y: float
    radius: float
    kind: str
    deaths: int

    def said(self) -> str:
        return "%d %s death%s within %d yards of (%d, %d) on map %d" % (
            self.deaths,
            self.kind,
            "" if self.deaths == 1 else "s",
            round(self.radius),
            round(self.x),
            round(self.y),
            self.map_id,
        )


def _num(row, key):
    try:
        value = float(row.get(key))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def kind_of(row) -> str:
    """ "lava", "slime", "fall" or "" for one death row."""
    if not isinstance(row, dict):
        return ""
    if _num(row, "map_id") is None or _num(row, "x") is None or _num(row, "y") is None:
        return ""
    liquid = str(row.get("liquid_type") or "")
    if liquid == "magma":
        return "lava"
    if liquid == "slime":
        return "slime"
    if liquid == "water" or str(row.get("killer_type") or "") != "self":
        return ""
    fell = _num(row, "yards_fallen")
    return "fall" if fell is not None and fell >= MIN_FALL_YARDS else ""


def discs(rows) -> list:
    """The avoid discs the death rows make."""
    spots = []
    for r in rows or ():
        kind = kind_of(r)
        if kind:
            spots.append((int(_num(r, "map_id")), _num(r, "x"), _num(r, "y"), kind))
    parent = list(range(len(spots)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(spots):
        for j in range(i + 1, len(spots)):
            b = spots[j]
            if a[0] == b[0] and math.hypot(a[1] - b[1], a[2] - b[2]) <= CLUSTER_YARDS:
                parent[find(i)] = find(j)
    groups: dict = {}
    for i, s in enumerate(spots):
        groups.setdefault(find(i), []).append(s)
    out = []
    for members in groups.values():
        if len(members) < MIN_DEATHS:
            continue
        cx = sum(m[1] for m in members) / len(members)
        cy = sum(m[2] for m in members) / len(members)
        reach = max(math.hypot(m[1] - cx, m[2] - cy) for m in members)
        kinds = sorted({m[3] for m in members})
        out.append(
            Disc(
                map_id=members[0][0],
                x=cx,
                y=cy,
                radius=min(MAX_RADIUS, max(MIN_RADIUS, reach + MARGIN_YARDS)),
                kind="/".join(kinds),
                deaths=len(members),
            )
        )
    return sorted(out, key=lambda d: (d.map_id, d.x, d.y))


def _point(p):
    if not isinstance(p, dict):
        return None
    m, x, y = _num(p, "map_id"), _num(p, "x"), _num(p, "y")
    if m is None or x is None or y is None:
        return None
    return int(m), x, y


def _to_segment(disc, a, b) -> float:
    dx, dy = b[1] - a[1], b[2] - a[2]
    span = dx * dx + dy * dy
    t = (
        0.0
        if span == 0
        else max(0.0, min(1.0, ((disc.x - a[1]) * dx + (disc.y - a[2]) * dy) / span))
    )
    return math.hypot(disc.x - a[1] - t * dx, disc.y - a[2] - t * dy)


def crossings(all_discs, start, goal) -> list:
    """Every disc the line start -> goal passes through, in disc order.

    The judgement `crossing` makes, kept whole: a disc the walker already
    stands in is ignored (it must be able to leave), a goal inside a disc is
    caught, and a point that cannot be read crosses nothing.
    """
    a, b = _point(start), _point(goal)
    if a is None or b is None or a[0] != b[0]:
        return []
    out = []
    for disc in all_discs or ():
        if disc.map_id != a[0]:
            continue
        if math.hypot(disc.x - a[1], disc.y - a[2]) <= disc.radius:
            continue
        if _to_segment(disc, a, b) <= disc.radius:
            out.append(disc)
    return out


def crossing(all_discs, start, goal):
    """The first disc the line start -> goal passes through, or None.

    A disc the walker already stands in is ignored (it must be able to leave),
    a goal inside a disc is caught, and a point that cannot be read refuses
    nothing: the check is advisory.
    """
    hits = crossings(all_discs, start, goal)
    return hits[0] if hits else None


def detour(all_discs, start, goal, candidates):
    """The surveyed point to walk by way of, so the walk crosses no disc.

    `candidates` are points the world itself surveyed ({map_id, x, y, ...}:
    spawns the caller read out of the world database); nothing here invents
    a coordinate. A candidate serves when it stands outside every disc and
    both straight legs, start -> candidate and candidate -> goal, clear
    every disc; of those, the shortest total walk wins. The outside-every-
    disc test is its own on purpose: `crossing` never judges ground the
    walker already stands in, so a walker standing in a disc could otherwise
    be routed by way of a point inside that same disc. None when the
    straight line already clears (nothing to route around), when no
    candidate serves, or when an end cannot be read. The candidate is
    returned as given, so the caller keeps the surveyed height it carried.
    """
    a, b = _point(start), _point(goal)
    if a is None or b is None or a[0] != b[0]:
        return None
    if crossing(all_discs, start, goal) is None:
        return None
    best, best_key = None, None
    for cand in candidates or ():
        c = _point(cand)
        if c is None or c[0] != a[0]:
            continue
        if any(
            d.map_id == c[0] and math.hypot(d.x - c[1], d.y - c[2]) <= d.radius
            for d in all_discs or ()
        ):
            continue
        if crossing(all_discs, start, cand) is not None:
            continue
        if crossing(all_discs, cand, goal) is not None:
            continue
        key = (
            math.hypot(c[1] - a[1], c[2] - a[2]) + math.hypot(b[1] - c[1], b[2] - c[2]),
            c[1],
            c[2],
        )
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best


def aim_refusal(all_discs, here, aim, spawn=None) -> str:
    """Why an aim must not be written, or "" when it may be.

    A ground aim is judged by its own ground. A role keyword is judged by
    `spawn`, the nearest holder of the role as the bridge looked it up
    ({map_id, x, y}); with no spawn it names no ground and is not refused.
    """
    if not all_discs:
        return ""
    ground = places.parse_ground_aim(aim)
    if ground:
        goal = {"map_id": ground[0], "x": ground[1], "y": ground[2]}
        what = aim
    elif spawn and keyword_mask(aim):
        goal = spawn
        what = "the nearest %s" % travel.resolve(aim)
    else:
        return ""
    hit = crossing(all_discs, here, goal)
    if hit is None:
        return ""
    return "the walk to %s crosses ground the family died on: %s" % (what, hit.said())


def member_aim_refusals(all_discs, positions, names, aim, spawns=None) -> dict:
    """{member: why} for each of `names` whose own walk to `aim` crosses a disc.

    Individual mode (wow-overseer#2395): a member walks from where IT stands,
    so each is judged from its own position in `positions` ({name: {map_id, x,
    y}}). A member with no known position is not refused here: the check is
    advisory and the module's errand death breaker still counts its deaths.
    A keyword aim is judged by `spawns` ({member: {map_id, x, y}}, the
    nearest holder of the role from each member's own place); a member with
    no spawn is not refused.
    """
    out = {}
    for name in names or ():
        here = (positions or {}).get(name)
        if not here:
            continue
        why = aim_refusal(all_discs, here, aim, spawn=(spawns or {}).get(name))
        if why:
            out[name] = why
    return out


# A STANDING AIM IS RE-JUDGED AFTER A DEATH (#2539). Two deaths of the family
# this close to the line of a walk, or to where it ends, in this many minutes,
# close the aim whoever killed them: a hostile that sits on the road is as
# final as lava, and the discs above only ever hear of lava and falls.
REPEAT_DEATHS = 2
REPEAT_MINUTES = 30
WALK_MARGIN_YARDS = 250.0
GOAL_MARGIN_YARDS = 400.0

RECENT_SQL = (
    "SELECT character_name AS name, map AS map_id, pos_x AS x, pos_y AS y, "
    "killer_type, killer_name FROM overseer_death "
    "WHERE created_at > NOW() - INTERVAL %s MINUTE "
    "AND character_name IN ({marks})"
)


def deaths_on_walk(deaths, here, goal) -> list:
    """The death rows on the line `here` -> `goal`, or within GOAL_MARGIN_YARDS
    of `goal`, on the walk's own map."""
    a, b = _point(here), _point(goal)
    if a is None or b is None or a[0] != b[0]:
        return []
    out = []
    for d in deaths or ():
        p = _point(d)
        if p is None or p[0] != a[0]:
            continue
        spot = Disc(p[0], p[1], p[2], 0.0, "", 1)
        if (
            math.hypot(p[1] - b[1], p[2] - b[2]) <= GOAL_MARGIN_YARDS
            or _to_segment(spot, a, b) <= WALK_MARGIN_YARDS
        ):
            out.append(d)
    return out


def standing_aim_refusal(all_discs, deaths, here, aim, spawn=None) -> str:
    """Why an aim already standing must be released, or "".

    The discs judge it as they would a new aim, and so do the recent deaths of
    the family: REPEAT_DEATHS of them on the walk close it. `deaths` None is an
    unreadable table and releases nothing.
    """
    why = aim_refusal(all_discs, here, aim, spawn=spawn)
    if why:
        return why
    if deaths is None:
        return ""
    ground = places.parse_ground_aim(aim)
    if ground:
        goal = {"map_id": ground[0], "x": ground[1], "y": ground[2]}
        what = aim
    elif spawn and keyword_mask(aim):
        goal = spawn
        what = "the nearest %s" % travel.resolve(aim)
    else:
        return ""
    hits = deaths_on_walk(deaths, here, goal)
    if len(hits) < REPEAT_DEATHS:
        return ""
    killers = sorted(
        {str(d.get("killer_name") or d.get("killer_type") or "?") for d in hits}
    )
    return "%d deaths of the family on the walk to %s in the last %d minutes (%s)" % (
        len(hits),
        what,
        REPEAT_MINUTES,
        ", ".join(killers),
    )


def pick_quest(all_discs, here, order, ends) -> tuple:
    """(quest id or 0, one note per quest passed over).

    `order` is the quests in the order they would be aimed; `ends` is
    {quest: [{map_id, x, y}]} of the spawns that end each. The end judged is
    the nearest on the walker's map. A quest with no known end is kept: not
    knowing where it goes is not a reason to refuse it.
    """
    notes = []
    for quest in order or ():
        spots = [s for s in (ends or {}).get(quest, ()) if _point(s)]
        a = _point(here)
        if not all_discs or not spots or a is None:
            return quest, notes
        same = [s for s in spots if _point(s)[0] == a[0]]
        if not same:
            return quest, notes
        goal = min(
            same, key=lambda s: math.hypot(_point(s)[1] - a[1], _point(s)[2] - a[2])
        )
        hit = crossing(all_discs, here, goal)
        if hit is None:
            return quest, notes
        notes.append(
            "quest %d passed over: its nearest end lies past ground "
            "the family died on (%s)" % (quest, hit.said())
        )
    return 0, notes
