"""A GUILD MEMBER LED OFF BY A STRANGER'S BOT LEAVES THAT GROUP.

Random bots of the realm invite guild members they pass, and a member that
accepts follows that leader. Read on the dev realm in November 2026: 13 guild
members were followers in four groups led by random bots in no guild, some on
another continent from their leader, and the bridge holds every walk of a
grouped follower (followhold.py), so two of them wrote no row for days.

A member (not on the roster) whose leader is in none of the guilds and not on
the roster, and who has stood apart from that leader (another map, the leader
offline, or more than RANGE_YARDS away) for STRAY_MINUTES running, is sent
mod-overseer's `leave-group` (kind='guild'): the member alone leaves, as a
player's /leave does. Nothing is done to the leader or its group. A member
grouped with a guildmate or with the family is never asked.

STRAY_MINUTES is 30: a group that is really playing together is on one map and
within sight, and a dungeon run or a quest party never spends half an hour
with its members on different continents. Pure: the bridge reads the rows,
keeps the clock and writes the rows.

THE MODULE'S OWN ANSWER DECIDES THE BACKOFF. A leave row the module refused
(the group is a battleground or dungeon finder group, which this verb may
not break up) can never take for that group, however often it is asked, so
the bridge reads the newest row's status and detail back (`refusals`:
name -> the module's named reason) and the pass neither asks that member
again nor guesses at the cause: the one log line names the refusal the
module actually gave.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

STRAY_MINUTES = 30
RANGE_YARDS = 1000.0
COOLDOWN_MINUTES = 60
# A member asked this many times in a day and still grouped is not asked again
# that day: the leave does not take for it (a battleground or finder group, or
# a leader the module refuses), and another row would only be refused again.
MAX_TRIES = 3
LEAVES_PER_PASS = 3

VERB = "leave-group"
SOURCE = "strayfollow"


@dataclass(frozen=True)
class Follower:
    """A guild member grouped as a follower, and its leader as read."""

    name: str
    guild: str
    map_id: int | None
    x: float | None
    y: float | None
    in_combat: bool
    leader: str
    leader_guild: str
    leader_roster: bool
    leader_online: bool
    leader_map: int | None
    leader_x: float | None
    leader_y: float | None


@dataclass(frozen=True)
class Row:
    name: str
    command: str
    source: str


def source_for(name) -> str:
    return "%s:%s" % (SOURCE, name)


def stranger(f: Follower, guilds) -> bool:
    """Whether the leader is in none of `guilds` and not on the roster."""
    return not f.leader_roster and (f.leader_guild or "") not in set(guilds)


def apart(f: Follower) -> str:
    """Why the member stands apart from its leader, "" when it does not."""
    if not f.leader_online or f.leader_map is None:
        return "the leader is offline"
    if f.map_id is None or int(f.map_id) != int(f.leader_map):
        return "the leader is on another map"
    if None in (f.x, f.y, f.leader_x, f.leader_y):
        return ""
    yards = math.hypot(float(f.x) - float(f.leader_x), float(f.y) - float(f.leader_y))
    if yards > RANGE_YARDS:
        return "the leader is %d yards away" % int(yards)
    return ""


def track(since: dict, followers, now: float) -> dict:
    """name -> when (seconds) the member was first read apart from its leader,
    for the members apart now; a member together again, or no longer grouped,
    is dropped."""
    out = {}
    for f in followers or ():
        if apart(f):
            out[f.name] = since.get(f.name, now)
    return out


def plan(
    followers,
    since: dict,
    now: float,
    recent: dict,
    guilds,
    tries: dict | None = None,
    refusals: dict | None = None,
) -> tuple:
    """(rows, lines): a `leave-group` row and one log line for each stray
    member apart for STRAY_MINUTES, out of a fight and off its cooldown
    (`recent`: name -> minutes since its last leave row) and under MAX_TRIES
    rows in the last day (`tries`: name -> that count), at most
    LEAVES_PER_PASS, longest apart first. A member in `refusals` (name -> the
    module's named reason for refusing its newest leave row) is not asked
    again: the module has said that leave cannot take for this group."""
    tries = tries or {}
    refusals = refusals or {}
    due = []
    for f in followers or ():
        why = apart(f)
        if not why or not stranger(f, guilds) or f.in_combat:
            continue
        if f.name in refusals:
            continue
        first = since.get(f.name)
        if first is None or now - first < STRAY_MINUTES * 60.0:
            continue
        last = recent.get(f.name)
        if last is not None and int(last) < COOLDOWN_MINUTES:
            continue
        if int(tries.get(f.name, 0)) >= MAX_TRIES:
            continue
        due.append((first, f, why))
    due.sort(key=lambda d: (d[0], d[1].name))
    rows, lines = [], []
    for first, f, why in due[:LEAVES_PER_PASS]:
        rows.append(Row(f.name, VERB, source_for(f.name)))
        lines.append(
            "%s leaves the group of %s, a bot in no guild of ours: %s for %d minutes"
            % (f.name, f.leader, why, int((now - first) // 60))
        )
    return tuple(rows), tuple(lines)


def gave_up(
    followers,
    since: dict,
    now: float,
    tries: dict,
    guilds,
    refusals: dict | None = None,
) -> tuple:
    """One log line for each member plan() has stopped asking: a stray apart
    for STRAY_MINUTES with MAX_TRIES or more leave rows in the last day, so the
    cause is read from the log and not guessed from a stream of rows. A member
    the module refused is named at once, under the limit or over it, and the
    line carries the module's own reason, not a guess."""
    refusals = refusals or {}
    lines = []
    for f in followers or ():
        why = apart(f)
        first = since.get(f.name)
        count = int(tries.get(f.name, 0))
        if not why or not stranger(f, guilds) or first is None:
            continue
        if now - first < STRAY_MINUTES * 60.0:
            continue
        reason = refusals.get(f.name)
        if reason:
            lines.append(
                "%s is still in the group of %s and is not asked again: the module "
                "refused the leave (%s)" % (f.name, f.leader, reason)
            )
            continue
        if count < MAX_TRIES:
            continue
        lines.append(
            "%s is still in the group of %s after %d leave-group rows today and is "
            "not asked again until the count falls: the leave did not take (%s)"
            % (f.name, f.leader, count, why)
        )
    return tuple(lines)


def refusals_from_rows(rows) -> dict:
    """name -> the module's named reason, from each member's newest leave row
    (the bridge reads them newest first, so the first row a name has is its
    newest). A row counts as a refusal when its status is `refused` or
    `error`, or its detail says refused; an answered leave is no entry."""
    out = {}
    for r in rows or ():
        name = str(r.get("target_name") or "")
        if not name or name in out:
            continue
        status = str(r.get("status") or "").strip().lower()
        detail = str(r.get("detail") or "").strip()
        if status not in ("refused", "error") and "refus" not in detail.lower():
            continue
        reason = detail
        for prefix in ("refused:", "refused -", "refused"):
            if reason.lower().startswith(prefix):
                reason = reason[len(prefix) :].strip(" :-")
                break
        out[name] = reason or status
    return out


def _int(value):
    return None if value is None else int(value)


def _float(value):
    return None if value is None else float(value)


def followers_from_rows(rows) -> tuple:
    out = []
    for r in rows or ():
        out.append(
            Follower(
                name=str(r.get("name") or ""),
                guild=str(r.get("guild") or ""),
                map_id=_int(r.get("map_id")),
                x=_float(r.get("pos_x")),
                y=_float(r.get("pos_y")),
                in_combat=bool(int(r.get("in_combat") or 0)),
                leader=str(r.get("leader") or ""),
                leader_guild=str(r.get("leader_guild") or ""),
                leader_roster=bool(int(r.get("leader_roster") or 0)),
                leader_online=bool(int(r.get("leader_online") or 0)),
                leader_map=_int(r.get("leader_map")),
                leader_x=_float(r.get("leader_x")),
                leader_y=_float(r.get("leader_y")),
            )
        )
    return tuple(out)
