"""Individual mode outside dungeons (#2395): who a drive acts for, per member.

WHY THIS EXISTS. The operator asked that, outside a dungeon, each family
member does its own crafting and gathering and the family need not move as
one. Before this, a job was family-wide by design (jobs.py, "THE FAMILY, NOT
THE CHARACTER"), and every drive that read it (`trainjob.family_mode`,
`craft_rhythm.standing_mode`) answered '' the moment two members disagreed,
then stood down with "nothing agreed".

THE RULE. A family is LINKED while any member's job is a dungeon job
(`dungeon`, `dungeon:<keyword>`) or a raid job (`raid:<keyword>`). `town run`
and `raid prep` do not link: the operator's order links a family only for a
dungeon or a raid. A linked family keeps the old rule exactly: a drive acts
only when every member agrees. A family that is not linked, and is named in
the setting, is INDIVIDUAL: each drive acts for each member whose own job is
the drive's mode, whatever the others are doing. Being inside a run, a
campaign queue that owns the job and a summon also re-link a family; those
are facts the bridge reads elsewhere (`_mid_run`, `_queue_owns_job`) and each
caller asks them before it writes.

THE SETTING. `FAMILY_INDIVIDUAL` is a comma-separated list of family keys (the
`overseer_roster.family` value, which is the head's name), matched without
regard to case. Unset or empty, no family is individual. It stays empty until
the module change that lets a follower walk its own errand is live and its own
switch is on: without it, an aim written on a follower moves nobody
(mod-overseer's AimedMover answers RefuseInFormation), so sending several
members to several trainers would leave all but the leader waiting at aims
they never walk.

PURE: a job map, a family key and the environment in, an answer out.
"""

from __future__ import annotations

import os

import jobs

ENV = "FAMILY_INDIVIDUAL"


def families(environ=None) -> frozenset:
    """The family keys the operator has made individual, lower-cased."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV, "") or "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def enabled(family, environ=None) -> bool:
    """Whether the operator has named `family` in the setting."""
    key = str(family or "").strip().lower()
    return bool(key) and key in families(environ)


def links(job) -> bool:
    """Whether one member's job links its whole family: a dungeon or a raid."""
    value = str(job or "").strip().lower()
    return jobs.is_dungeon_job(value) or jobs.is_raid_job(value)


def linked(job_by_name: dict) -> bool:
    """Whether any member's job links the family."""
    return any(links(job) for job in (job_by_name or {}).values())


def active(job_by_name: dict, family, environ=None) -> bool:
    """Whether this family acts per member right now, by its jobs alone.

    A caller that is about to write still asks the run and the campaign queue,
    which this pure module cannot see.
    """
    return bool(job_by_name) and enabled(family, environ) and not linked(job_by_name)


def members_on(job_by_name: dict, modes, family, environ=None, exempt=()) -> tuple:
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
    if active(job_by_name, family, environ):
        return tuple(sorted(name for name, job in rows.items() if job in wanted))
    held = set(rows.values())
    if len(held) == 1 and held <= wanted:
        return tuple(sorted(rows))
    return ()


def farm_cohort(job_by_name: dict, leader, family, environ=None) -> dict:
    """The rows the farm pass judges as one order (#2498).

    Linked or unnamed families, and rows holding no farm job, are returned
    unchanged: the old split rule applies to them. An individual family keeps
    only the members on the leader's own farm job, or when the leader is not
    farming, the members of the first farm job by name, so members holding
    different farm jobs are not a half-landed order and the rest are left alone.
    """
    rows = dict(job_by_name or {})
    if not active(rows, family, environ):
        return rows
    farming = {n: j for n, j in rows.items() if jobs.is_farm_job(j)}
    if not farming:
        return rows
    pick = farming.get(leader) or farming[min(farming)]
    return {n: j for n, j in farming.items() if j == pick}
