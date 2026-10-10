"""How long each guild member has stood on one spot.

WHY THIS EXISTS. Measured on the dev realm on 2026-10-10: Highlights, a level 7
Blood Elf of Bonkers, stood at one point in Eversong Woods for 10.8 hours
played at her level. Her own AI chose a grind spot or an innkeeper every few
minutes and gave each up, "stuck when moving far", 119 times in 3.2 hours, from
that same point. The guild jobs pass wrote her nothing: she had no job left, no
outgrown zone and no class quest, and the pass keeps no position history, so a
member that cannot move looked exactly like one that does not need to. Diggo,
Dug and Totta of Cave stood the same way for hours to days.

WHAT IS KEPT. Per member, the spot it was first read at (map, x, y), its level
there, and when. Each pass a member read within STILL_YARDS of that spot, on the
same map and at the same level, keeps it; any other reading starts it again.
Nothing in the realm keeps a position history (overseer_snapshot holds one row
per character), so this lives in the bridge's memory like situation.Tracker,
and a restart starts every clock again: a stand is then counted from the first
pass after it, which only delays the hearth.

WHAT IT IS FOR. guildjobs.stood_still_step: a member that has stood
STILL_MINUTES with nothing asked of it hearths home, the way a player gets a
stuck character moving.

PURE: members and a clock in, anchors and minutes out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import situation

# Less than this from where it was first read is the same spot: a bot shuffling
# where it stands, never a walk (situation.STILL_YARDS).
STILL_YARDS = situation.STILL_YARDS

# Standing this long with nothing asked of it is stuck, not resting. A rest, a
# revive hold, a cast or a wait for a boat lasts minutes; the guild jobs pass
# reads every member about every fifteen, so an hour is four readings or more.
STILL_MINUTES = 60

# A member no pass has read for this long is dropped: two guilds' passes share
# the anchors, and each reads only its own members.
FORGET_SECONDS = 3 * 3600.0


@dataclass(frozen=True)
class Anchor:
    """Where a member was first read standing, at what level, since when, and
    when a pass last read it there (seconds on the caller's clock)."""

    map_id: int
    x: float
    y: float
    level: int
    since: float
    seen: float


def _standing(m) -> bool:
    return bool(
        m.online
        and getattr(m, "alive", True)
        and m.map_id is not None
        and m.x is not None
        and m.y is not None
    )


def track(anchors, members, now) -> dict:
    """name -> Anchor after one pass's reading of `members` at `now`.

    A member read on its anchor's map, at its level and within STILL_YARDS of
    it keeps the anchor; one read anywhere else gets a new one from now. A
    member offline, dead or unread has none. Members not in this reading keep
    theirs until FORGET_SECONDS after they were last read."""
    now = float(now)
    out = {
        name: a
        for name, a in (anchors or {}).items()
        if now - float(a.seen) <= FORGET_SECONDS
    }
    for m in members or ():
        name = str(m.name)
        if not _standing(m):
            out.pop(name, None)
            continue
        here = (int(m.map_id), float(m.x), float(m.y), int(m.level))
        old = out.get(name)
        if old is not None and _same_spot(old, here):
            out[name] = Anchor(old.map_id, old.x, old.y, old.level, old.since, now)
        else:
            out[name] = Anchor(*here, since=now, seen=now)
    return out


def _same_spot(anchor: Anchor, here) -> bool:
    map_id, x, y, level = here
    return (
        anchor.map_id == map_id
        and anchor.level == level
        and math.hypot(anchor.x - x, anchor.y - y) < STILL_YARDS
    )


def minutes(anchors, name, now) -> int:
    """Whole minutes `name` has stood on its anchor, 0 when it has none."""
    anchor = (anchors or {}).get(str(name))
    if anchor is None:
        return 0
    return max(0, int((float(now) - float(anchor.since)) // 60))


def all_minutes(anchors, now) -> dict:
    """name -> minutes stood, for every anchored member."""
    return {name: minutes(anchors, name, now) for name in anchors or {}}
