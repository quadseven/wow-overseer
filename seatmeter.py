"""Guild dungeon seats filled in the last hour, and the members waiting for one (#784).

WHY THIS EXISTS. Tanks and healers cap how many guild runs go in at once, so
the measure of a fix that brings more of them (pick-up groups from the realm,
the families' tanks and healers) is seats: how many members went into a
dungeon with their guild in the last hour, and how many free members whose
level fits one of their guild's doors are still waiting. Measured on wow-dev
over the 24 hours to 2026-10-10 14:40 New York time: Bonkers formed 83 runs
(23 turned away by the finder) and Cave 21, about 17 seats an hour between
them, 28 runs with a pug.

A seat is counted when its run went to the finder and was not turned away
(guildrun.TURNED_AWAY): a refused run filled nothing. Each seat filled by a
pug (the run's `pugs`) or by a lent family member (the roster's names) is
counted apart, so the log says where the new seats came from.

PURE: rows in, counts and a line out. The bridge reads and logs.
"""

from __future__ import annotations

from dataclasses import dataclass

import guildrun

# The runs formed in the last hour.
RUNS_SQL = (
    "SELECT guild, members, pugs, outcome FROM overseer_guild_run "
    "WHERE created_at > NOW() - INTERVAL 1 HOUR"
)
# How often the bridge says the line.
EVERY_SECONDS = 600


@dataclass(frozen=True)
class Meter:
    guild: str
    seats: int = 0
    runs: int = 0
    pug_seats: int = 0
    family_seats: int = 0
    waiting: int = 0


def _names(text) -> set:
    return {n.strip() for n in str(text or "").split(",") if n.strip()}


def seats(run_rows: list, family_names) -> dict:
    """guild -> (seats, runs, pug seats, family seats) over the runs read."""
    family = set(family_names or ())
    out: dict = {}
    for row in run_rows or ():
        if str(row.get("outcome") or "") in guildrun.TURNED_AWAY:
            continue
        members = [m["name"] for m in guildrun._member_list(row.get("members"))]
        pugs = _names(row.get("pugs"))
        guild = str(row.get("guild") or "")
        n, runs, p, f = out.get(guild, (0, 0, 0, 0))
        out[guild] = (
            n + len(members),
            runs + 1,
            p + sum(1 for m in members if m in pugs),
            f + sum(1 for m in members if m in family),
        )
    return out


def waiting(mates: list, held: dict, doors: list, factions: dict) -> dict:
    """guild -> free members whose level fits one of their guild's doors."""
    out: dict = {}
    for mate in mates or ():
        if mate.name in held:
            continue
        member = mate.member
        if guildrun.fitting_doors(
            [member.level], doors, factions.get(member.guild, "")
        ):
            out[member.guild] = out.get(member.guild, 0) + 1
    return out


def meters(
    guilds,
    run_rows: list,
    family_names,
    mates: list,
    held: dict,
    doors: list,
    factions: dict,
) -> list:
    """One Meter per guild, in the order given."""
    filled = seats(run_rows, family_names)
    wait = waiting(mates, held, doors, factions)
    out = []
    for guild in guilds:
        n, runs, p, f = filled.get(guild, (0, 0, 0, 0))
        out.append(Meter(guild, n, runs, p, f, wait.get(guild, 0)))
    return out


def line(found: list) -> str:
    """'Cave 10 seat(s) in 2 run(s) (1 pug, 1 family), 41 waiting | ...'."""
    return " | ".join(
        "%s %d seat(s) in %d run(s) (%d pug, %d family), %d waiting"
        % (m.guild, m.seats, m.runs, m.pug_seats, m.family_seats, m.waiting)
        for m in found
    )
