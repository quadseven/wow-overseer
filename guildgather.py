"""Raid seats pick up the nodes they pass while they level (slice 1 of the
raid-seat profession plan).

WHY IT EXISTS. The bridge's life loop hands `nc +gather` and `nc +loot` to the
ten roster family characters and to nobody else: on the dev realm 9,820 of
9,871 such command rows were written for five names. A raid seat outside the
two families that holds Herbalism or Mining therefore has no one telling its AI
to pick a node up as it quests or travels. `gather` puts a node in the loot
stack and `loot` walks to it (goals.GATHER_STRATEGIES), so both are needed, and
both are rebuilt from defaults on every login, so the grant is re-asserted.

WHAT IT DECIDES. Of the 70 approved raid seats that are not family members, who
is sent the pair now: a bot-driven seat under level 60 that holds a gathering
trade it can still raise, standing in the open world, out of combat, alive and
in no group. A grouped seat keeps its formation (a pull to a node would scatter
a party), an instance is a run, and a level 60 seat is left to its own jobs.
Nothing here walks anybody: the grant rides the questing and travelling the
seat already does, so it costs no levelling time. It never stands a strategy
down; a seat that qualifies again is simply told again.

NORTH STAR. Nothing here grants, teaches, gives or teleports. The only rows are
`nc +gather` and `nc +loot`, the strategies a player turns on. Skinning has no
node, so it does not qualify a seat.

PURE: rows in, rows out. The bridge reads the seats, writes the rows and keeps
the clock. ON unless `GUILD_GATHER` is `off`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

import goals
import levelroute
import raidteams

SOURCE = "overseer:guildgather"
ENV_SWITCH = "GUILD_GATHER"
HERBALISM, MINING = 182, 186
NODE_SKILLS = (HERBALISM, MINING)
LEVEL_CAP = 60
# The top rank of a trade: nothing left to gain from a node.
SKILL_CAP = 300
# A grant lasts until a login, which is not seen here, so it is told again on
# this cadence; the game ignores a strategy already present.
REASSERT_SECONDS = 30 * 60
PER_PASS = 40

# THE OTHER SIDE'S HOME GROUND (ticket 2624). `loot` walks a seat to a node it
# sees, and a seat standing in a city or camp of the other side is killed by
# that side's guards on the way (the dev realm's Alliance Draenei died to the
# Barrens, Thunder Bluff and Mulgore guards while idle with this pair on). Only
# zones that are one side's alone are listed; a contested zone (Ashenvale,
# Stonetalon, Feralas) is in neither set. Side -> the zone ids that are the
# OTHER side's: a seat of that side is not sent the pair while it stands there.
_HORDE_HOME = frozenset({14, 17, 215, 1637, 1638, 85, 130, 1497})
_ALLIANCE_HOME = frozenset(
    {12, 1, 40, 38, 141, 148, 1519, 1537, 1657, 3524, 3525, 3557}
)
HOSTILE_ZONES = {
    levelroute.ALLIANCE: _HORDE_HOME,
    levelroute.HORDE: _ALLIANCE_HOME,
}


def side_of(race: int) -> str:
    """The side of a character.race id, "" when it is neither."""
    if race in levelroute.ALLIANCE_RACES:
        return levelroute.ALLIANCE
    if race in levelroute.HORDE_RACES:
        return levelroute.HORDE
    return ""


@dataclass(frozen=True)
class Seat:
    name: str
    level: int
    skills: Mapping[int, int]
    online: bool
    alive: bool
    grouped: bool
    in_instance: bool
    in_combat: bool
    race: int = 0
    zone_id: int = 0


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(ENV_SWITCH, "")).strip().lower() not in (
        "off",
        "0",
        "no",
        "false",
    )


def seat_names(include_old: bool = False) -> frozenset:
    """The approved raid seats outside group 1 (the families, who have their
    own loop). `include_old` adds the names a seat had before its rename."""
    out = set()
    for groups in raidteams.GROUPS.values():
        for group in groups[1:]:
            for s in group:
                out.add(s.name)
                if include_old and s.was:
                    out.add(s.was)
    return frozenset(out)


def refusal(seat: Seat) -> str:
    """Why this seat is not sent the pair now, or "" when it is."""
    if not seat.online:
        return "it is not in the world"
    if not seat.alive:
        return "it is dead"
    if int(seat.level) >= LEVEL_CAP:
        return "it is level %d and keeps its own jobs" % LEVEL_CAP
    if seat.grouped:
        return "it is in a group and keeps its formation"
    if seat.in_instance:
        return "it is inside an instance"
    if seat.in_combat:
        return "it is in combat"
    if int(seat.zone_id or 0) in HOSTILE_ZONES.get(side_of(int(seat.race or 0)), ()):
        return "it stands on the other side's ground, where its guards kill it"
    held = [int(seat.skills.get(s, 0) or 0) for s in NODE_SKILLS]
    if not any(0 < v for v in held):
        return "it holds no gathering trade with a node"
    if all(v == 0 or v >= SKILL_CAP for v in held):
        return "its gathering trades are at their top rank"
    return ""


def plan(seats, seen: dict, now: float) -> list:
    """(name, command, source) rows for the seats owed the pair, and `seen`
    updated in place with the time each was told. A seat told within
    REASSERT_SECONDS is skipped; a pass tells at most PER_PASS seats."""
    rows = []
    told = 0
    for seat in sorted(seats, key=lambda s: s.name):
        if told >= PER_PASS:
            break
        if refusal(seat):
            continue
        last = seen.get(seat.name)
        if last is not None and now - last < REASSERT_SECONDS:
            continue
        seen[seat.name] = now
        told += 1
        rows.extend((seat.name, cmd, SOURCE) for cmd in goals.GATHER_STRATEGIES)
    return rows
