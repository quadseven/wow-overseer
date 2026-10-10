"""A family's tank and healer take guild-run seats while their family is idle (#784).

WHY THIS EXISTS. A guild run needs a real tank and a real healer at the
bosses' level (#721), and outside the families each guild has about 7 tanks
and 7 to 10 healers, so 31 to 36 members of each guild never get a dungeon
seat. The families hold tanks and healers too, and most of the day they are
not in a dungeon: on wow-dev on the afternoon of 2026-10-10 Grug's family
quested for hours with its campaign withheld for bag room. The operator decided on
2026-10-10: yes, a family's tank and healer may take guild-run seats while
their own family has no campaign run going.

THE RULE, one family member at a time (`lendable`):

  idle family   no member of its family is on a campaign's job (a dungeon or
                raid job, armed or running, or the town run a campaign waits
                in town on; jobs.py) and none stands inside an instance (a
                run going). The module asks the same of a party helper
                (InAFamilyCampaign) and asks it again when the finder row
                names a family member, so a campaign armed in between refuses
                the run rather than losing its member.
  not the head  the family's head leads the party its family follows, so it
                stays with them (the module refuses it too).
  its seats     the tank or healer seat only, the one its spent talents play,
                dressed for it and at the bosses' level (guildsocial.can_take,
                #721). It never asks for a dungeon itself and never takes a
                damage seat: the guild's damage dealers are not short.
  never pulled  once in a guild run it is busy as any guildmate is
                (guildrun.why_not) until the run ends. Its family's queue
                waits for it before a campaign starts (`waiting_for`): it
                finishes the run, or leaves with it, and goes back between
                runs.

Natural play only: the family member answers in guild chat as a guildmate
does, and goes in through the dungeon finder with the group. Nothing is
granted.

Off (GUILD_FAMILY_SEATS off): no family member is lent and the queue holds
nobody.

PURE: rows in, names out. The bridge reads the roster, seats the lent members
through the social layer, and holds the queue.
"""

from __future__ import annotations

import os

import guildrun
import jobs

ENV_SWITCH = "GUILD_FAMILY_SEATS"

# The roster as this reads it: who belongs to which family, and its job.
ROSTER_SQL = "SELECT name, family, job FROM overseer_roster WHERE enabled = 1"


def enabled(environ=None) -> bool:
    """On unless GUILD_FAMILY_SEATS says off."""
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_SWITCH, "") or "").strip().lower()
    return raw not in ("off", "0", "false", "no")


def campaign_job(job) -> bool:
    """Whether this roster job belongs to a campaign: a dungeon or raid job, or
    the town run a campaign's family waits in town on."""
    text = str(job or "").strip().lower()
    return jobs.is_dungeon_job(text) or jobs.is_raid_job(text) or text == jobs.TOWN_RUN


def _families(roster: list) -> dict:
    """family -> [(name, job)] for the enabled roster rows."""
    out: dict = {}
    for row in roster or ():
        name = str(row.get("name") or "")
        if not name:
            continue
        family = str(row.get("family") or "")
        out.setdefault(family, []).append((name, str(row.get("job") or "")))
    return out


def inside(member_rows: list) -> set:
    """The names read standing inside an instance (not on an open-world map)."""
    out = set()
    for row in member_rows or ():
        member = guildrun.member_from_row(row)
        if member is not None and member.map_id not in guildrun.OPEN_WORLD_MAPS:
            out.add(member.name)
    return out


def idle_families(roster: list, inside_names, in_runs=()) -> set:
    """The families with no campaign run going: no member on a campaign's job
    and none inside an instance, a member inside with a guild run (`in_runs`)
    aside."""
    within = set(inside_names or ()) - set(in_runs or ())
    return {
        family
        for family, members in _families(roster).items()
        if not any(campaign_job(job) or name in within for name, job in members)
    }


def lendable(roster: list, inside_names, in_runs=()) -> set:
    """The family members who may take a guild run's tank or healer seat now:
    every member of an idle family but its head (the family key is the head's
    name; a roster with no family names no head, so lends nobody). Which seat,
    if any, is the social layer's to say (guildsocial.can_take); one already
    in a guild run is busy there."""
    idle = idle_families(roster, inside_names, in_runs)
    return {
        name
        for family, members in _families(roster).items()
        if family and family in idle
        for name, _job in members
        if name != family
    }


def waiting_for(names, in_runs) -> list:
    """The family's members out in a guild run, sorted: its queue waits for
    them before a campaign starts."""
    return sorted(set(names or ()) & set(in_runs or ()))


def hold_line(names: list) -> str:
    """The queue's line for a family waiting on its lent members."""
    return "waits for %s to come back from a guild run before its campaign starts" % (
        ", ".join(names)
    )


def release(
    held: dict, mates: list, lent_names, busy, resting, benched=frozenset()
) -> tuple:
    """(held, lent) for the guild's dungeon asks: each lendable family member
    held only for being one is weighed again as a guildmate (guildrun.why_not
    without the family). Already in a party is not a reason: a family member
    stands in its family's group, which the module leaves for the run. Free,
    it is lent; held for anything else, it keeps that reason."""
    out = dict(held)
    lent = set()
    lendable_now = set(lent_names or ())
    for mate in mates or ():
        name = mate.name
        if name not in lendable_now or out.get(name) != guildrun.FAMILY_MEMBER:
            continue
        why = guildrun.why_not(
            mate.member, set(busy), set(resting), set(), set(benched)
        )
        if why in ("", guildrun.GROUPED):
            del out[name]
            lent.add(name)
        else:
            out[name] = why
    return out, lent
