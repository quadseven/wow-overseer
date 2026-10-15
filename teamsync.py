"""Bring each approved guild to its approved teams (raidteams, 2026-10-05):
the leavers leave, a fitting recruit fills each open seat, and everyone the
operator renamed takes the new name.

WHY. raidteams holds what the operator approved; this decides, each pass, the
few rows that move a guild toward it. It never judges who should raid: that is
raidteams. It only says what is still to do, in order, a few rows at a time.

THE ORDER. Leavers first, so the guild has room; then invites, one recruit per
open seat that no member already fits; then renames; then the questers'
resets. A recruit is matched to its seat by class and race, because the seat's
name is a joke about its race (Coom is an orc shaman, Dairymoo a tauren one),
and a member the teams do not name who matches an open seat is that seat's
recruit and takes its name.

QUESTERS (raidteams.QUESTERS, #927). A quester's seat is recruited, matched
and renamed like a raid seat, after the raid seats. Once a quester holds its
name and its guild, a `naturalize reset-level-1` row starts it over at level 1
with nothing at its race's start (natural.py), once: a name the ledger already
holds `reset` for is never asked again. The reset waits for the name because
the name is what says the character is a quester and not a raid recruit.

PACE. A few rows per pass, and never a second row for something already in
flight (`pending`), so a slow worldserver is not flooded and a refused row is
simply asked again on a later pass.

WHO MAY BE RECRUITED. Only a character the realm logs in by itself: one on a
random-bot account the playerbot manager rotates (see ROTATING_ACCOUNT_TYPE).
A seat is for a member who plays, and the guild's always-online setting keeps
only those accounts' members in the world.

PURE: plain values in, actions out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import raidteams

# 40 raiders, 21 summoners, 10 maintenance and 5 questers. The module's own
# gate, Overseer.Recruit.TargetSize, refuses an invite past its number, so it
# must say the same.
GUILD_SIZE = 76
REMOVES_PER_PASS = 2
INVITES_PER_PASS = 2
RENAMES_PER_PASS = 6
RESETS_PER_PASS = 2
# THE LEVEL A RECRUIT MAY HAVE, by seat (#1015). A raid seat keeps what it
# earns, so it takes only a level-1 character, the band the realm's natural
# reset set. A quester is reset to level 1 with nothing once it holds its name,
# so the level it joins at does not matter and its seat takes a rotating bot at
# any level up to the realm's MaxPlayerLevel (60): on 2026-10-15 the lowest
# rotating bot of a quester's class and race was level 5 to 22, so a ceiling
# of 10 left 8 of the 10 seats with no candidate. RECRUIT_MAX_LEVEL is the
# higher of the two, what the bridge reads candidates up to, and the realm's
# Overseer.Recruit.LevelMax.
RAID_RECRUIT_MAX_LEVEL = 1
QUESTER_RECRUIT_MAX_LEVEL = 60
RECRUIT_MAX_LEVEL = max(RAID_RECRUIT_MAX_LEVEL, QUESTER_RECRUIT_MAX_LEVEL)
RESET_COMMAND = "reset-level-1"

# HOW LONG A REFUSED CANDIDATE IS LEFT ALONE. The module answers a refused
# invite with status `unchanged` and its reason in `result` (wow-overseer#1015:
# 1,442 refusals in a day, every candidate re-asked every ten minutes, because
# the pass read only `error` rows). A reason a later pass cannot change (the
# candidate joined another guild, is of the other faction, or is flagged for
# deletion) holds for six hours. Any other reason (the level band, the roster
# size) is the realm's configuration, which can change, so it holds an hour.
LASTING_REFUSALS = ("already in a guild", "the other faction", "flagged for deletion")
REFUSAL_HOLD_MINUTES = 60
LASTING_HOLD_MINUTES = 360

# playerbots_account_type.account_type of the accounts the playerbot manager
# logs in and out on its own (RNDbot). The other bot type, 2, is the AddClass
# pool kept for the `addclass` chat command, and a player's account has no
# row at all. The manager never logs a character of either in, and the
# always-online guild pass admits RNDbot accounts only, so a recruit from them
# holds a seat and never enters the world. Lowest level first made that the
# rule rather than the exception: the AddClass pool is hundreds of never-played
# level-1 characters, the RNDbot ones at this level have all been played to
# level 2 or more, and all sixteen seats filled on 2026-10-05 went to the pool.
ROTATING_ACCOUNT_TYPE = 1

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
    kind: str  # "remove", "invite", "rename" or "reset"
    target: str  # the character the row is about
    new_name: str = ""  # for "rename"
    why: str = ""


def open_seats(guild: str, member_names) -> list:
    """The approved seats no member of the guild fills yet, by approved or
    current name: the recruits still to come. The raid seats first, then the
    questers'."""
    names = set(member_names)
    raid = [
        s
        for s in raidteams.seats(guild)
        if s.name not in names and (not s.was or s.was not in names)
    ]
    return raid + [q for q in raidteams.QUESTERS.get(guild, ()) if q.name not in names]


def refusal_reason(status: str, detail, result) -> str:
    """The module's reason for refusing a row, or "" when it did not refuse.
    An `error` row says it in `detail`; a refused guild verb comes back
    `unchanged` with `{"outcome": "refused", "reason": ...}` in `result`."""
    if detail:
        return str(detail)
    if isinstance(result, (str, bytes)):
        try:
            result = json.loads(result)
        except ValueError:
            result = None
    if isinstance(result, dict) and result.get("outcome") == "refused":
        return str(result.get("reason") or "refused, no reason given")
    return "no detail" if status == "error" else ""


def refused_candidates(rows: list) -> dict:
    """candidate -> reason for the invites the module refused recently enough
    to hold. `rows` are invite rows: target_arg, status, detail, result and
    age (minutes since written). The newest refusal per candidate decides:
    the rows are walked oldest first (largest age first), so a newer row for
    the same candidate always writes or clears its entry last."""
    out = {}
    for row in sorted(rows, key=lambda r: int(r.get("age") or 0), reverse=True):
        reason = refusal_reason(
            row.get("status") or "", row.get("detail"), row.get("result")
        )
        name = str(row.get("target_arg") or "")
        if not reason or not name:
            continue
        lasting = any(word in reason for word in LASTING_REFUSALS)
        hold = LASTING_HOLD_MINUTES if lasting else REFUSAL_HOLD_MINUTES
        if int(row.get("age") or 0) < hold:
            out[name] = reason
        else:
            out.pop(name, None)
    return out


def refusal_counts(rows: list, minutes: int = 30) -> dict:
    """reason -> count of the rows refused in the last `minutes`."""
    out = {}
    for row in rows:
        if int(row.get("age") or 0) >= minutes:
            continue
        reason = refusal_reason(
            row.get("status") or "", row.get("detail"), row.get("result")
        )
        if reason:
            out[reason] = out.get(reason, 0) + 1
    return out


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


def logs_in_by_itself(candidate: dict) -> bool:
    """Whether the realm puts this character in the world without anyone
    asking: it sits on an account the playerbot manager rotates. A missing or
    unknown account type is a no."""
    return int(candidate.get("account_type") or 0) == ROTATING_ACCOUNT_TYPE


def max_level(seat) -> int:
    """The highest level a recruit for `seat` may have (see the constants)."""
    if isinstance(seat, raidteams.Quester):
        return QUESTER_RECRUIT_MAX_LEVEL
    return RAID_RECRUIT_MAX_LEVEL


def _best_candidate(seat, candidates: list, taken: set):
    fit = sorted(
        (
            c
            for c in candidates
            if _fits(c, seat)
            and int(c.get("level") or 0) <= max_level(seat)
            and logs_in_by_itself(c)
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


def _resets(guild: str, names: set, pending: set, reset_done) -> list:
    """A reset for each quester in the guild under its name that the ledger
    has not reset. Nothing while the ledger is unread (`reset_done` None):
    the reset cannot be undone, so not knowing is a no."""
    if reset_done is None:
        return []
    wanted = [
        q.name
        for q in raidteams.QUESTERS.get(guild, ())
        if q.name in names and q.name not in reset_done and q.name not in pending
    ]
    return [
        Action("reset", name, why="a quester starts at level 1 with nothing")
        for name in wanted[:RESETS_PER_PASS]
    ]


def plan(
    guild: str,
    members: list,
    candidates: list,
    pending: set,
    renames_on: bool,
    reset_done=None,
    refused=None,
) -> list:
    """The actions for one pass over one approved guild: removals, then
    invites, then (when the module's rename verb is live) renames, then the
    questers' resets.

    members     the guild's members: name, class_id, race, level
    candidates  characters in no guild: name, class_id, race, level,
                account_type (its account's playerbots_account_type, or None)
    pending     names a row is already in flight for (any of these actions)
    renames_on  whether the module's rename verb is live
    reset_done  names the naturalize ledger holds `reset` for, or None when
                the ledger cannot be read
    refused     candidate -> reason for invites the module refused within
                their hold (refused_candidates); those are not asked again
    """
    candidates = [c for c in candidates if c["name"] not in (refused or {})]
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
    actions += _resets(guild, names, pending, reset_done)
    return actions


def _waiting_line(seated: dict, pending: set, refusals: dict | None) -> str:
    waiting = ", ".join(
        "%s as %s" % (m["name"], seat) for seat, m in sorted(seated.items())
    )
    line = (
        "%d seats are filled by recruits already in the guild, waiting for "
        "the approved name (%s)" % (len(seated), waiting)
    )
    if pending & {m["name"] for m in seated.values()}:
        line += "; their rows are in flight or were asked in the last ten minutes"
    if refusals:
        line += "; recent refusals: " + ", ".join(
            "%s x%d" % (detail, n) for detail, n in sorted(refusals.items())
        )
    return line


def _unfilled_lines(
    unfilled: list, members: list, candidates: list, pending: set, actor_online: bool
) -> list:
    taken, missing = set(pending), []
    for seat in unfilled:
        pick = _best_candidate(seat, candidates, taken)
        if pick is None:
            missing.append("%s (level %d or under)" % (seat.name, max_level(seat)))
        else:
            taken.add(pick["name"])
    out = []
    if missing:
        out.append(
            "no candidate on a rotating random-bot account fits %s" % ", ".join(missing)
        )
    if len(missing) == len(unfilled):
        return out
    if len(members) >= GUILD_SIZE:
        out.append(
            "the guild is full (%d) and the approved teams name no leaver"
            % len(members)
        )
    elif not actor_online:
        out.append("the family head is not in the world")
    else:
        out.append("invites wait on rows in flight")
    return out


def stall_reason(
    guild: str,
    members: list,
    candidates: list,
    pending: set,
    actor_online: bool = True,
    refusals: dict | None = None,
    refused: dict | None = None,
) -> str:
    """Why a pass with open seats moved nothing, or "" when no seat is open.

    A seat counts as open by name, so a recruit already in the guild that fits
    it (not yet renamed) still leaves the seat open. That case is the usual
    stall: the invites are done and the rename is what waits. `refusals` is
    reason -> count for the recently refused rows; `refused` the candidates
    held after a refusal (refused_candidates).
    """
    candidates = [c for c in candidates if c["name"] not in (refused or {})]
    opens = open_seats(guild, {m["name"] for m in members})
    if not opens:
        return ""
    seated = recruits_in_guild(guild, members)
    parts = [_waiting_line(seated, pending, refusals)] if seated else []
    unfilled = [s for s in opens if s.name not in seated]
    if unfilled:
        parts += _unfilled_lines(unfilled, members, candidates, pending, actor_online)
        if refusals and not seated:
            parts.append(
                "the module refused: "
                + ", ".join("%s x%d" % (r, n) for r, n in sorted(refusals.items()))
            )
    return "%s has %d open seats: %s" % (guild, len(opens), "; ".join(parts))
