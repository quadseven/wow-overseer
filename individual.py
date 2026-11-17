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
from dataclasses import dataclass

import farmjob
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


def resolve_member(job_by_name: dict, member) -> str:
    """The roster name `member` matches without regard to case, or ''."""
    wanted = str(member or "").strip().casefold()
    for name in job_by_name or {}:
        if str(name).casefold() == wanted and wanted:
            return str(name)
    return ""


def member_order_refusal(job_by_name: dict, member, mode) -> str:
    """Why a job order naming one member cannot be written, or '' (#2407).

    Accepted only for a member on the roster, while the family is not linked,
    and for a mode that is not a dungeon or raid job: those belong to the
    whole family. Pure: the jobs read and the order in, a sentence out.
    """
    name = resolve_member(job_by_name, member)
    if not name:
        return "%s is not on the roster, so there is no job to give." % (
            str(member or "").strip() or "Nobody"
        )
    if links(mode):
        return (
            "%s is a job for the whole family, so it cannot be given to %s alone."
            % (mode, name)
        )
    if linked(job_by_name):
        return (
            "The family is linked (a member is on a dungeon or raid job), so "
            "%s cannot be given a job of its own now." % name
        )
    return ""


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


@dataclass(frozen=True)
class Solo:
    """One member of an individual family, run as a family of one (#2498).

    The farm pass is written for a family: a leader, its names, a town slot.
    Handed a Solo it runs for the one member, with the member as its own
    leader, its own state (`key`), and its own farm count. `slot_key` names
    the town slot that arbitrates its travel column: the family's own slot for
    the leader, who is the family's one traveller everywhere else, and a slot
    of its own for any other member. `solo` is what the pass tests for.
    """

    key: str
    leader: str
    names: tuple
    family: str
    slot_key: object = None
    solo: bool = True


def solo_of(name, family, leader, slot_key=None) -> Solo:
    """The family-of-one `name` is farmed as. The leader shares the family's
    town slot (`slot_key`, None for this bridge's own family); the rest each
    hold a slot named for themselves."""
    who = str(name)
    return Solo(
        key="solo:" + who,
        leader=who,
        names=(who,),
        family=str(family or ""),
        slot_key=slot_key if who == leader else "solo:" + who,
    )


def farm_members(job_by_name: dict, family, environ=None, exempt=()) -> tuple:
    """The members the farm pass drives on their own, sorted by name.

    Only in an individual, unlinked family, and only members holding a farm
    job. Anything else, including a linked or unnamed family, drives nobody
    here: the family-wide farm pass keeps those.
    """
    if not active(job_by_name, family, environ):
        return ()
    skip = set(exempt or ())
    return tuple(
        sorted(
            n
            for n, job in job_by_name.items()
            if n not in skip and jobs.is_farm_job(job)
        )
    )


def farm_retargets(
    job_by_name: dict, skills_by_name: dict, family, environ=None, exempt=()
) -> dict:
    """{member: farm job} each member on a farm SKILL order should hold.

    A member told `farm:mining` whose own best node trade is herbalism is
    moved to `farm:herbalism`. A member whose target is already its job, or
    who has no node trade at all, is left as it is (the latter ends its own
    order, saying why). An order for one ITEM (`farm:<entry>`) is the
    operator's choice of material and is never rewritten.
    """
    out = {}
    for name in farm_members(job_by_name, family, environ, exempt):
        job = str(job_by_name[name]).strip().lower()
        if not farmjob.order_of(job)[1]:
            continue
        mine = (skills_by_name or {}).get(name)
        # A member whose own order still advances it keeps it: the lower
        # trade changes with every node and would flip the order each time.
        if farmjob.advances(job, mine):
            continue
        want = farmjob.target_for(mine)
        if want and want != job:
            out[name] = want
    return out


def gather_targets(
    job_by_name: dict,
    skills_by_name: dict,
    family,
    loop_job,
    environ=None,
    exempt=(),
    member_orders=None,
) -> dict:
    """{member: job} the profession loop's GATHER phase writes (#2498).

    The loop owns the phase order and names one gather job for the family.
    Family-wide that job goes to everybody. In an individual, unlinked family,
    a farm SKILL order (`farm:mining`, `farm:herbalism`) is replaced, member by
    member, by the order that member's own skills advance
    (`farmjob.target_for`); a member with no node trade keeps the loop's job,
    and an ITEM order (`farm:<entry>`) or `quest` is the family's and goes to
    all. Members in `exempt` are left out.

    `member_orders` (#2502) is name -> the kill-drop order that member's own
    reagent plan needs (`profloop.member_kill_drops`). In an individual,
    unlinked family that member gets it alone, and the others keep their own
    skill target instead of following an item they do not eat. Elsewhere it is
    ignored: a linked or unnamed family moves as one.
    """
    skip = set(exempt or ())
    names = sorted(n for n in (job_by_name or {}) if n not in skip)
    job = str(loop_job or "").strip().lower()
    own = {
        n: str(j).strip().lower()
        for n, j in (member_orders or {}).items()
        if jobs.can_set(str(j).strip().lower())
    }
    if not active(job_by_name, family, environ):
        return {n: loop_job for n in names}
    if not (farmjob.order_of(job)[1] or own):
        return {n: loop_job for n in names}
    return {
        n: own.get(n) or farmjob.target_for((skills_by_name or {}).get(n)) or loop_job
        for n in names
    }


# --- what a page may say of a family (#2408) ---------------------------------

LINKED = "linked"
INDIVIDUAL = "individual"
UNREAD = "unread"


def standing(job_by_name: dict, family, environ=None) -> dict:
    """Whether a family reads as linked or individual by its jobs, and why.

    For a surface that only reports. `state` is LINKED, INDIVIDUAL, UNREAD or
    '' (nobody on the roster), and `reason` names the fact that decided it:

      'job'      a member's dungeon or raid job links the family; `by` names
                 every such member, sorted.
      'unnamed'  no job links it, and the setting does not name the family.
      'named'    no job links it, and the setting names the family.
      'setting'  no job links it, and this process was never handed the
                 setting, so it cannot tell 'unnamed' from 'named'.

    UNSET IS NOT EMPTY HERE. The bridge treats an unset `FAMILY_INDIVIDUAL` as
    "no family is individual", which is right for the process that acts on it.
    A page served by another process is not handed the bridge's environment
    unless the deployment passes it, and a page that read "unset" as "linked"
    would call a family linked while the bridge walks its members apart. So a
    missing key answers UNREAD, and an empty value answers 'unnamed'.

    The run, the campaign queue and a summon re-link a family too; this module
    cannot see them, and a caller that reports this answer says so.
    """
    rows = dict(job_by_name or {})
    if not rows:
        return {"state": "", "reason": "", "by": ()}
    by = tuple(sorted(str(name) for name, job in rows.items() if links(job)))
    if by:
        return {"state": LINKED, "reason": "job", "by": by}
    env = os.environ if environ is None else environ
    if ENV not in env:
        return {"state": UNREAD, "reason": "setting", "by": ()}
    if enabled(family, env):
        return {"state": INDIVIDUAL, "reason": "named", "by": ()}
    return {"state": LINKED, "reason": "unnamed", "by": ()}
