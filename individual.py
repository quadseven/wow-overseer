"""Individual mode outside dungeons (#2395): who a drive acts for, per member.

WHY THIS EXISTS. The operator's order of 2026-11-13: outside a dungeon, each
family member does its own crafting and gathering; the family need not move as
one. Before this, a job was family-wide by design (jobs.py, "THE FAMILY, NOT
THE CHARACTER"), and every drive that read it (`trainjob.family_mode`,
`craft_rhythm.standing_mode`) answered '' the moment two members disagreed,
then stood down with "nothing agreed".

THE RULE. A family is LINKED while any member's job is a dungeon job, a raid
job or `town run` (the campaign's waiting room, jobs.TOWN_RUN, which walks the
family into its next door). A linked family keeps the old rule exactly: a drive
acts only when every member agrees. A family that is not linked, with the
setting on, is INDIVIDUAL: each drive acts for each member whose own job is the
drive's mode, whatever the others are doing.

THE SETTING. `FAMILY_INDIVIDUAL`, off unless set to a true word. It stays off
until the module change that lets a follower walk its own errand is live:
without it, an aim written on a follower moves nobody (mod-overseer's
AimedMover answers RefuseInFormation), so sending several members to several
trainers would leave all but the leader waiting at aims they never walk.

PURE: a job map and the environment in, an answer out.
"""

from __future__ import annotations

import os

import jobs

ENV = "FAMILY_INDIVIDUAL"
TRUE_WORDS = frozenset({"1", "true", "yes", "on"})


def enabled(environ=None) -> bool:
    """Whether the operator has turned individual mode on."""
    env = os.environ if environ is None else environ
    return str(env.get(ENV, "") or "").strip().lower() in TRUE_WORDS


def links(job) -> bool:
    """Whether one member's job links its whole family."""
    value = str(job or "").strip().lower()
    return (
        jobs.is_dungeon_job(value) or jobs.is_raid_job(value) or value == jobs.TOWN_RUN
    )


def linked(job_by_name: dict) -> bool:
    """Whether any member's job links the family."""
    return any(links(job) for job in (job_by_name or {}).values())


def active(job_by_name: dict, environ=None) -> bool:
    """Whether this family acts per member right now."""
    return bool(job_by_name) and enabled(environ) and not linked(job_by_name)


def members_on(job_by_name: dict, modes, environ=None, exempt=()) -> tuple:
    """The members a drive for `modes` acts for, sorted by name.

    Individual: every member whose own job is one of `modes`. Otherwise the
    old rule: everybody when the members not `exempt` all hold one mode and it
    is one of `modes`, else nobody, because rows that disagree in a linked
    family are a half-landed order.
    """
    wanted = {str(m).strip() for m in modes}
    skip = set(exempt or ())
    rows = {
        name: str(job or "").strip()
        for name, job in (job_by_name or {}).items()
        if name not in skip
    }
    if active(job_by_name, environ):
        return tuple(sorted(name for name, job in rows.items() if job in wanted))
    held = set(rows.values())
    if len(held) == 1 and held <= wanted:
        return tuple(sorted(rows))
    return ()
