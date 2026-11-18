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


# A module row older than this is a leader that no longer leads.
ROW_FRESH_SECONDS = 600


def fresh_leader_row(leader: str, row: dict, leads) -> bool:
    """Is this intent row a live leader's? The table keeps rows of members that
    led once; they list the real leader as a straggler and must never act."""
    if leader not in (leads or ()):
        return False
    age = row.get("module_age")
    return age is not None and int(age) <= ROW_FRESH_SECONDS


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
    reason = (
        hearthcast._stone_reason(member)
        or hearthcast._cooldown_reason(member)
        or hearthcast._alive_reason(member)
    )
    if reason:
        return reason
    away = math.hypot(
        float(bind.x) - float(leader_at["pos_x"]),
        float(bind.y) - float(leader_at["pos_y"]),
    )
    if away > yards + SLACK_YARDS:
        return NO_NEARER
    return ""


# A MEMBER LEFT ALONE INSIDE AN INSTANCE. The walk-back rule above sees only a
# member that is walking back with a distance; one on another map has neither
# (the family intent row reads `following|another map`), so a member stranded
# inside a dungeon after the family hearthed out was never seen. Here it is read
# by where it is: on a dungeon map while the leader is on a different, ordinary
# map, for as long as a stranded follower is given.
INSIDE_SECONDS = 600.0


def observe_inside(
    watch: dict,
    leader: str,
    states: dict,
    maps: dict,
    leader_map,
    dungeon_maps,
    now: float,
    lent=(),
) -> list:
    """The members that have stood inside a dungeon, apart from their leader,
    for INSIDE_SECONDS.

    `maps` is name -> the map each was last read on; a name not in it is not a
    reading. A leader that is itself on a dungeon map means a run is on, or
    about to be, and nobody is stranded. `lent` names members out in a guild
    run, which are inside a dungeon on purpose. `watch` maps
    ("inside", leader, name) -> since.
    """
    stranded = []
    leader_inside = leader_map is None or leader_map in dungeon_maps
    for name in sorted(states):
        key = ("inside", leader, name)
        mapped = maps.get(name)
        if (
            leader_inside
            or name in lent
            or mapped is None
            or mapped not in dungeon_maps
        ):
            watch.pop(key, None)
            continue
        since = watch.setdefault(key, now)
        if now - since >= INSIDE_SECONDS:
            stranded.append(name)
    for key in [
        k for k in watch if k[0] == "inside" and k[1] == leader and k[2] not in states
    ]:
        watch.pop(key, None)
    return stranded


def why_not_inside(member: hearthcast.Member, leader_at: dict) -> str:
    """Why this member's stone is no way out of the instance, or "".

    The stone must land on the leader's own map, so the member comes out where
    the family is. There is no distance rule: the member stands on another map,
    so there is no distance to compare, and a stone is the way out of an
    instance whatever it lands near.
    """
    bind = member.bind
    if bind is None or bind.map != (leader_at or {}).get("map_id"):
        return hearthcast.BOUND_ELSEWHERE
    if member.alive is False:
        return hearthcast.DEAD
    return (
        hearthcast._stone_reason(member)
        or hearthcast._cooldown_reason(member)
        or hearthcast._alive_reason(member)
        or ""
    )


# HOW OFTEN THE PASS RUNS, on its own loop. It used to sit at the end of the
# economy loop, behind a vendor, bag hand-over and purchase pass for every family.
CYCLE_SECONDS = 60.0


def summary_line(families: int, watching: int, sent: list, skipped: list) -> str:
    """One line for one cycle: what the pass read, watched, did and skipped.

    A pass with nothing to say and a pass that never ran read the same from
    outside, so every cycle says this.
    """
    done = "hearthed %d" % len(sent)
    if sent:
        done += " (%s)" % ", ".join(sent)
    line = "strand hearth: read %d famil%s, watching %d, %s" % (
        families,
        "y" if families == 1 else "ies",
        watching,
        done,
    )
    if skipped:
        line += "; skipped " + ", ".join("%s (%s)" % (n, why) for n, why in skipped)
    return line
