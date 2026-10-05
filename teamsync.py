"""Bring each approved guild to its approved teams (raidteams, 2026-10-05):
the leavers leave, a fitting recruit fills each open seat, and everyone the
operator renamed takes the new name.

WHY. raidteams holds what the operator approved; this decides, each pass, the
few rows that move a guild toward it. It never judges who should raid: that is
raidteams. It only says what is still to do, in order, a few rows at a time.

THE ORDER. Leavers first, so the guild has room; then invites, one recruit per
open seat that no member already fits; then renames. A recruit is matched to
its seat by class and race, because the seat's name is a joke about its race
(Coom is an orc shaman, Dairymoo a tauren one), and a member the teams do not
name who matches an open seat is that seat's recruit and takes its name.

PACE. A few rows per pass, and never a second row for something already in
flight (`pending`), so a slow worldserver is not flooded and a refused row is
simply asked again on a later pass.

PURE: plain values in, actions out.
"""

from __future__ import annotations

from dataclasses import dataclass

import raidteams

GUILD_SIZE = 71
REMOVES_PER_PASS = 2
INVITES_PER_PASS = 2
RENAMES_PER_PASS = 6
RECRUIT_MAX_LEVEL = 10

# race word (raidteams) -> characters.race id (3.3.5a).
RACE_IDS = {
    "Human": 1,
    "Orc": 2,
    "Dwarf": 3,
    "Night Elf": 4,
    "Undead": 5,
    "Tauren": 6,
    "Gnome": 7,
    "Troll": 8,
    "Blood Elf": 10,
    "Draenei": 11,
}


@dataclass(frozen=True)
class Action:
    kind: str  # "remove", "invite" or "rename"
    target: str  # the character the row is about
    new_name: str = ""  # for "rename"
    why: str = ""


def open_seats(guild: str, member_names) -> list:
    """The approved seats no member of the guild fills yet, by approved or
    current name: the recruits still to come."""
    names = set(member_names)
    return [
        s
        for s in raidteams.seats(guild)
        if s.name not in names and (not s.was or s.was not in names)
    ]


def _fits(member: dict, seat) -> bool:
    return int(member.get("class_id") or 0) == seat.class_id and int(
        member.get("race") or 0
    ) == RACE_IDS.get(seat.race, -1)


def recruits_in_guild(guild: str, members: list) -> dict:
    """seat name -> member: guild members the teams do not name, each matched
    to an open seat of its class and race (first come, first seated)."""
    known = raidteams.names_of(guild)
    seats = open_seats(guild, [m["name"] for m in members])
    out = {}
    for member in sorted(members, key=lambda m: m["name"]):
        if member["name"] in known:
            continue
        for seat in seats:
            if seat.name not in out and _fits(member, seat):
                out[seat.name] = member
                break
    return out


def _removals(guild: str, names: set, pending: set) -> list:
    leaving = [
        n for n in raidteams.LEAVING.get(guild, ()) if n in names and n not in pending
    ]
    return [
        Action("remove", name, why="leaves for a recruit (approved teams)")
        for name in leaving[:REMOVES_PER_PASS]
    ]


def _best_candidate(seat, candidates: list, taken: set):
    fit = sorted(
        (
            c
            for c in candidates
            if _fits(c, seat)
            and int(c.get("level") or 0) <= RECRUIT_MAX_LEVEL
            and c["name"] not in taken
        ),
        key=lambda c: (int(c.get("level") or 0), c["name"]),
    )
    return fit[0] if fit else None


def _invites(
    guild: str, members: list, seated: dict, candidates: list, pending: set
) -> list:
    """One invite per open seat no member fits, while the guild has room.
    Room is counted from who is in the guild now: a leaver asked to go this
    pass still holds its place until the row has run."""
    names = {m["name"] for m in members}
    limit = min(INVITES_PER_PASS, max(0, GUILD_SIZE - len(members)))
    actions, taken = [], set(pending)
    for seat in open_seats(guild, names):
        if len(actions) >= limit:
            break
        if seat.name in seated:
            continue
        pick = _best_candidate(seat, candidates, taken)
        if pick is None:
            continue
        actions.append(
            Action("invite", pick["name"], why="recruit for %s's seat" % seat.name)
        )
        taken.add(pick["name"])
    return actions


def _renames(guild: str, names: set, seated: dict, pending: set) -> list:
    wanted = [(old, new) for old, new in raidteams.renames(guild) if old in names]
    wanted += [(m["name"], seat) for seat, m in seated.items() if m["name"] != seat]
    wanted = [
        (old, new) for old, new in wanted if old not in pending and new not in names
    ]
    return [
        Action("rename", old, new_name=new, why="approved name")
        for old, new in wanted[:RENAMES_PER_PASS]
    ]


def plan(
    guild: str, members: list, candidates: list, pending: set, renames_on: bool
) -> list:
    """The actions for one pass over one approved guild: removals, then
    invites, then (when the module's rename verb is live) renames.

    members     the guild's members: name, class_id, race, level
    candidates  characters in no guild: name, class_id, race, level
    pending     names a row is already in flight for (any of these actions)
    renames_on  whether the module's rename verb is live
    """
    names = {m["name"] for m in members}
    seated = recruits_in_guild(guild, members)
    actions = _removals(guild, names, pending)
    # NO INVITE IN A PASS THAT REMOVES: the worldserver runs both rows in the
    # same moment, and an invite checks the roster's size after it adds, so a
    # removal beside it reads as a mismatch and the invite is refused
    # (2026-10-05: 3 of the first 4 invites). Invites follow once the guild's
    # leavers have gone.
    if not actions:
        actions += _invites(guild, members, seated, candidates, pending)
    if renames_on:
        actions += _renames(guild, names, seated, pending)
    return actions
