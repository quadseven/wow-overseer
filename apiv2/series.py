"""GET /api/v2/series: level and XP per hour over time, for a member or a guild.

    /api/v2/series?name=Grug     -> {name, level, xp_per_hour,
                                     xp_per_hour_24h, xp_hours_measured, basis}
    /api/v2/series?guild=cave    -> {guild, members, measured, level,
                                     xp_per_hour, by_member, basis}

`level` is [[ts, level]] over the last 7 days and `xp_per_hour` is [[ts, n]],
one point per hour over the last 24. Every ts is a Unix time in seconds, read
from the database's own clock so the server's timezone never enters it.

WHAT IS MEASURED. Nothing on the realm records experience over time. What is
recorded is every level change of a family or managed-guild character
(`overseer_level`, one row per ding) and the experience a character holds now
(`characters.xp`). Together with the core's own table of experience per level
(`acore_world.player_xp_for_level`) that gives the character's total
experience at known instants: exactly the sum of the levels below at each
ding, and that sum plus `xp` now. Between two such instants the total is
interpolated in a straight line, so an hour's XP is the average rate between
the dings around it, not a count of kills in that hour.

WHAT IS NOT. An hour before the first known instant has no value: it is null,
never 0, and the app says "not measured". A member with no ding in the window
has no rate at all, because one instant is not a rate. When nothing in the
window is measured the list is empty.

A guild's XP per hour is the sum over its members of the hours that are
measured, and `measured` says how many members that sum covers. A guild's
level line is the median level of its members, every six hours.

ONE NUMBER PER MEMBER. `xp_per_hour_24h` is the mean of a member's measured
hours in the last 24 and `xp_hours_measured` how many hours that mean covers;
with no measured hour it is null, never 0. A guild read carries the same two
for every member under `by_member`, keyed by name, so the members table can
print a rate per row from one read per guild.
"""

from __future__ import annotations

import statistics

from apiv2 import _allow

DAY = 86400
HOUR = 3600
LEVEL_DAYS = 7
XP_HOURS = 24
GUILD_LEVEL_STEP = 6 * HOUR
# One extra day of dings is read before the windows, so the first hour of the
# 24 can be interpolated from the ding before it.
LOOKBACK = (LEVEL_DAYS + 1) * DAY

BASIS = (
    "Levels come from the realm's record of every level change. Experience is "
    "not recorded over time: an hour's XP is the straight-line average between "
    "the level changes around it and the experience held now, using the core's "
    "experience per level. An hour before the first level change on record is "
    "not measured."
)

_NOW_SQL = "SELECT UNIX_TIMESTAMP() AS now"
_XP_TABLE_SQL = (
    "SELECT Level AS level, Experience AS xp FROM acore_world.player_xp_for_level"
)
# Only a member of a managed guild (_allow): a name outside them reads as
# unknown, in the same query that reads it.
# S608: the only text joined in is a run of %s placeholders sized by the
# allowlist; every value is bound by the driver.
_MEMBER_SQL = (  # noqa: S608
    "SELECT c.guid, c.name, c.level, c.xp FROM characters c "
    "JOIN guild_member gm ON gm.guid = c.guid "
    "JOIN guild g ON g.guildid = gm.guildid "
    "WHERE c.name = %s AND g.name IN ({holes}) LIMIT 1"
).format(holes=_allow.guild_holes())
_GUILD_SQL = "SELECT guildid, name FROM guild WHERE name = %s LIMIT 1"
# A guild holds at most a thousand members; the bound is the game's.
MAX_MEMBERS = 1000
MAX_EVENTS = 50000
_GUILD_MEMBERS_SQL = (
    "SELECT c.guid, c.name, c.level, c.xp FROM characters c "
    "JOIN guild_member gm ON gm.guid = c.guid WHERE gm.guildid = %s LIMIT %s"
)
_EVENTS_SQL = (
    "SELECT character_guid AS guid, old_level, new_level, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_level "
    "WHERE character_guid IN ({holes}) AND created_at >= FROM_UNIXTIME(%s) "
    "ORDER BY created_at, id LIMIT %s"
)


# ---- pure arithmetic ---------------------------------------------------------


def total_xp(level: int, xp_into: int, table: dict) -> int | None:
    """Experience earned since level 1, or None when the table lacks a level."""
    total = 0
    for lvl in range(1, int(level)):
        step = table.get(lvl)
        if step is None:
            return None
        total += int(step)
    return total + max(0, int(xp_into or 0))


def anchors(events: list, level: int, xp_into: int, now: float, table: dict) -> list:
    """(ts, total experience) at every known instant, oldest first.

    A ding is an instant with no experience into the new level. An instant
    whose total is lower than the one before it (a level the table does not
    know, a deleted and rerolled name) is dropped rather than drawn as
    experience lost.
    """
    points = []
    for ev in events:
        total = total_xp(int(ev["new_level"]), 0, table)
        if total is not None:
            points.append((float(ev["at"]), total))
    current = total_xp(level, xp_into, table)
    if current is not None:
        points.append((float(now), current))
    points.sort(key=lambda p: p[0])
    out: list = []
    for ts, total in points:
        if out and total < out[-1][1]:
            continue
        out.append((ts, total))
    return out


def total_at(points: list, ts: float) -> float | None:
    """Total experience at `ts`, interpolated; None before the first instant."""
    if not points or ts < points[0][0]:
        return None
    # Consecutive pairs: the second list is one shorter by design.
    for (t0, v0), (t1, v1) in zip(points, points[1:], strict=False):
        if t0 <= ts <= t1:
            if t1 == t0:
                return float(v1)
            return v0 + (v1 - v0) * (ts - t0) / (t1 - t0)
    return float(points[-1][1])


def hourly(points: list, now: float, hours: int = XP_HOURS) -> list:
    """[[ts, n or None]] for each hour ending at `ts`, oldest first.

    Fewer than two instants is no rate at all, so every hour is None.
    """
    start = now - hours * HOUR
    out = []
    for k in range(hours):
        a, b = start + k * HOUR, start + (k + 1) * HOUR
        if len(points) < 2:
            out.append([int(b), None])
            continue
        va, vb = total_at(points, a), total_at(points, b)
        out.append([int(b), None if va is None or vb is None else round(vb - va)])
    return out


def level_at(events: list, level: int, ts: float) -> int:
    """The level held at `ts`: the last ding at or before it, else the level
    the first later ding started from, else the level held now."""
    held = None
    for ev in events:
        if float(ev["at"]) <= ts:
            held = int(ev["new_level"])
        elif held is None:
            return int(ev["old_level"])
        else:
            break
    return held if held is not None else int(level)


def level_line(events: list, level: int, now: float) -> list:
    """[[ts, level]] over the level window: where it began, every ding inside
    it, and now."""
    start = now - LEVEL_DAYS * DAY
    inside = [ev for ev in events if float(ev["at"]) >= start]
    out = [[int(start), level_at(events, level, start)]]
    out += [[int(ev["at"]), int(ev["new_level"])] for ev in inside]
    out.append([int(now), int(level)])
    return out


def measured_or_empty(series: list) -> list:
    """The series, or [] when no point in it is measured."""
    return series if any(v is not None for _, v in series) else []


def rate(hours: list) -> dict:
    """The mean of the measured hours and how many there are.

    {"xp_per_hour_24h": n or None, "xp_hours_measured": k}: None when no hour
    is measured, so "not measured" is never drawn as 0 XP an hour.
    """
    vals = [v for _, v in hours if v is not None]
    return {
        "xp_per_hour_24h": round(sum(vals) / len(vals)) if vals else None,
        "xp_hours_measured": len(vals),
    }


def member_series(char: dict, events: list, table: dict, now: float) -> dict:
    points = anchors(events, char["level"], char["xp"], now, table)
    hours = hourly(points, now)
    return {
        "name": char["name"],
        "level": level_line(events, char["level"], now),
        "xp_per_hour": measured_or_empty(hours),
        **rate(hours),
        "basis": BASIS,
    }


def _sum_hours(per_member: list) -> list:
    if not per_member:
        return []
    # Every member's series is the same 24 hours (hourly() builds them all
    # off one `now`), so the rows line up; strict says so out loud.
    out = []
    for hour in zip(*per_member, strict=True):
        vals = [v for _, v in hour if v is not None]
        out.append([hour[0][0], sum(vals) if vals else None])
    return out


def guild_series(name: str, chars: list, events: list, table: dict, now: float) -> dict:
    by_guid: dict = {}
    for ev in events:
        by_guid.setdefault(int(ev["guid"]), []).append(ev)
    hours = []
    by_member = {}
    for char in chars:
        mine = by_guid.get(int(char["guid"]), [])
        points = anchors(mine, char["level"], char["xp"], now, table)
        hours.append(hourly(points, now))
        by_member[char["name"]] = rate(hours[-1])
    measured = sum(1 for h in hours if any(v is not None for _, v in h))
    start = now - LEVEL_DAYS * DAY
    steps = int(LEVEL_DAYS * DAY // GUILD_LEVEL_STEP)
    level = []
    for k in range(steps + 1):
        ts = start + k * GUILD_LEVEL_STEP
        lv = [level_at(by_guid.get(int(c["guid"]), []), c["level"], ts) for c in chars]
        if lv:
            level.append([int(ts), statistics.median(lv)])
    return {
        "guild": name,
        "members": len(chars),
        "measured": measured,
        "level": level,
        "xp_per_hour": measured_or_empty(_sum_hours(hours)),
        "by_member": by_member,
        "basis": BASIS,
    }


# ---- reads -------------------------------------------------------------------


def _one(rd, sql: str, args=()):
    found = rd.must(sql, args)
    return found[0] if found else None


def _events(rd, guids: list, now: float) -> list:
    if not guids:
        return []
    holes = ", ".join(["%s"] * len(guids))
    return rd.must(
        _EVENTS_SQL.format(holes=holes), (*guids, int(now - LOOKBACK), MAX_EVENTS)
    )  # noqa: S608


def _arg(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def series(query: dict, ctx) -> tuple[int, dict]:
    name, guild = _arg(query, "name"), _arg(query, "guild")
    if not name and not guild:
        return 400, {"error": "say name= or guild="}
    # Refused before any query: only a managed guild, only a name's shape.
    if name and not _allow.name(name):
        return 400, {"error": "name= is a character name"}
    if not name and not _allow.guild(guild):
        return 404, {"error": "no such guild", "guilds": sorted(_allow.GUILDS)}
    rd = ctx.read
    now = float(_one(rd, _NOW_SQL)["now"])
    table = {int(r["level"]): int(r["xp"]) for r in rd.must(_XP_TABLE_SQL, ())}
    if name:
        char = _one(rd, _MEMBER_SQL, (name, *_allow.guild_args()))
        if not char:
            return 404, {"error": "no such character", "name": name}
        events = _events(rd, [int(char["guid"])], now)
        return 200, member_series(char, events, table, now)
    row = _one(rd, _GUILD_SQL, (_allow.guild(guild),))
    if not row:
        return 404, {"error": "no such guild", "guild": guild}
    chars = rd.must(_GUILD_MEMBERS_SQL, (row["guildid"], MAX_MEMBERS))
    events = _events(rd, [int(c["guid"]) for c in chars], now)
    return 200, guild_series(row["name"], chars, events, table, now)


ROUTES = {"/api/v2/series": series}
