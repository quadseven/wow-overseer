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
worldserver roll) is what would route around a disc. Drowning is left out on
purpose: water deaths sit in every lake and would void whole coasts.

PURE. Every function takes rows and points and returns plain values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import places

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


def crossing(all_discs, start, goal):
    """The first disc the line start -> goal passes through, or None.

    A disc the walker already stands in is ignored (it must be able to leave),
    a goal inside a disc is caught, and a point that cannot be read refuses
    nothing: the check is advisory.
    """
    a, b = _point(start), _point(goal)
    if a is None or b is None or a[0] != b[0]:
        return None
    for disc in all_discs or ():
        if disc.map_id != a[0]:
            continue
        if math.hypot(disc.x - a[1], disc.y - a[2]) <= disc.radius:
            continue
        if _to_segment(disc, a, b) <= disc.radius:
            return disc
    return None


def aim_refusal(all_discs, here, aim) -> str:
    """Why a ground aim must not be written, or "" when it may be."""
    ground = places.parse_ground_aim(aim)
    if not ground or not all_discs:
        return ""
    goal = {"map_id": ground[0], "x": ground[1], "y": ground[2]}
    hit = crossing(all_discs, here, goal)
    if hit is None:
        return ""
    return "the walk to %s crosses ground the family died on: %s" % (aim, hit.said())


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
