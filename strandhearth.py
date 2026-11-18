"""A follower that cannot close on its held leader goes home by its own stone (#1261).

The module holds a leader still while a member walks back to it, for up to
1200s, and that hold outranks the leader's errand. A member stuck in a lava
pocket, or refused every bearing thousands of yards away, never arrives, so the
errand never starts. The same rule as the travel column's: an errand that
cannot finish must not hold the family for ever.

Pure. The bridge reads the family intent row, the positions and the stone
facts, and writes the kind='hearth' row this names. The stone is the member's
own item; nothing here grants or moves anything.
"""

from __future__ import annotations

import math

import hearthcast

SOURCE = "strand-hearth"
WALKING_BACK = "walking back to the leader"
# No 5-yard improvement for this long is "not closing".
STRAND_SECONDS = 600.0
IMPROVE_YARDS = 5.0
# Closer than this the module's own follow hands it back.
MIN_YARDS = 300.0
# A member that has not closed in STRAND_SECONDS is stuck where it stands (a
# pocket it cannot leave), so a stone is an exit even when it lands about as
# far from the leader; it must not land the member much FARTHER than it is.
SLACK_YARDS = 300.0
NO_NEARER = "bind_farther"


def parse_members_state(text) -> dict:
    """`Name|state|yards` lines -> {name: (state, yards or None)}."""
    out = {}
    for line in str(text or "").splitlines():
        parts = line.split("|")
        if len(parts) != 3 or not parts[0].strip():
            continue
        try:
            yards = float(parts[2])
        except ValueError:
            yards = None
        out[parts[0].strip()] = (parts[1].strip(), yards)
    return out


def observe(watch: dict, leader: str, states: dict, now: float) -> list:
    """Update `watch` and return the members not closing for STRAND_SECONDS.

    `watch` maps (leader, name) -> (best yards, since). A member improving by
    IMPROVE_YARDS restarts its clock; one no longer walking back is forgotten.
    """
    stranded = []
    for name, (state, yards) in sorted(states.items()):
        key = (leader, name)
        if state != WALKING_BACK or yards is None or yards < MIN_YARDS:
            watch.pop(key, None)
            continue
        best, since = watch.get(key, (None, now))
        if best is None or yards <= best - IMPROVE_YARDS:
            best, since = yards, now
        watch[key] = (best, since)
        if now - since >= STRAND_SECONDS:
            stranded.append(name)
    for key in [k for k in watch if k[0] == leader and k[1] not in states]:
        watch.pop(key, None)
    return stranded


def why_not(member: hearthcast.Member, leader_at: dict, yards: float) -> str:
    """Why this member's stone is no way back to the leader, or ""."""
    bind = member.bind
    if bind is None or bind.map != (leader_at or {}).get("map_id"):
        return hearthcast.BOUND_ELSEWHERE
    if member.alive is False:
        return hearthcast.DEAD
    reason = (hearthcast._stone_reason(member)
              or hearthcast._cooldown_reason(member)
              or hearthcast._alive_reason(member))
    if reason:
        return reason
    away = math.hypot(float(bind.x) - float(leader_at["pos_x"]),
                      float(bind.y) - float(leader_at["pos_y"]))
    if away > yards + SLACK_YARDS:
        return NO_NEARER
    return ""
