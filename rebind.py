"""A member bound at another inn is asked to bind where its leader's inn is.

Pure. The hearthstone is the family's way home, and a member bound in another
town is skipped by every exit hearth and finder stage (`bound at another inn`),
so each run's end can leave it thousands of yards from the family. The `bind`
verb sets a character's home where it stands, and only beside an innkeeper, so
this moves nobody: it asks only while a member already stands at the leader's
inn (for instance on a family town errand there). The verb itself answers the
faction and innkeeper questions, and a refusal is retried only after a back-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SOURCE = "rebind"
# Standing this close to the leader's bind point is standing at its inn: the
# bind point is where the innkeeper's door is.
NEAR_INN_YARDS = 40.0
# Two binds this close are the same inn.
SAME_INN_YARDS = 150.0
# A member is asked at most this often (the verb refuses with a reason when no
# innkeeper is in reach or the character cannot bind now).
BACKOFF_SECONDS = 1200

SAME_INN = "bound at the leader's inn already"
NOT_AT_INN = "not standing at the leader's inn"
UNREAD = "a bind was not read"
DEAD = "dead"
BACKING_OFF = "asked lately"


@dataclass(frozen=True)
class Member:
    bind: object = None  # situation.Point: map, x, y
    at: dict | None = None  # fresh snapshot row: map_id, pos_x, pos_y
    alive: bool | None = None


def _yards(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(float(ax) - float(bx), float(ay) - float(by))


def why_not(leader_bind, member: Member) -> str:
    """Why this member is not asked to bind now, or ""."""
    if leader_bind is None or member.bind is None:
        return UNREAD
    if member.alive is False:
        return DEAD
    if int(member.bind.map) == int(leader_bind.map) and (
        _yards(member.bind.x, member.bind.y, leader_bind.x, leader_bind.y)
        <= SAME_INN_YARDS
    ):
        return SAME_INN
    at = member.at
    if (
        not at
        or at.get("map_id") is None
        or int(at["map_id"]) != int(leader_bind.map)
        or _yards(at["pos_x"], at["pos_y"], leader_bind.x, leader_bind.y)
        > NEAR_INN_YARDS
    ):
        return NOT_AT_INN
    return ""


def select(leader_bind, members: dict, recent=frozenset()) -> tuple:
    """(names to ask, [(name, why not)] for the others), by name order."""
    asked, skipped = [], []
    for name in sorted(members):
        why = why_not(leader_bind, members[name])
        if why:
            skipped.append((name, why))
        elif name in recent:
            skipped.append((name, BACKING_OFF))
        else:
            asked.append(name)
    return asked, skipped
