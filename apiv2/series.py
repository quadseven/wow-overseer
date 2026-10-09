"""GET /api/v2/series: level and XP per hour over time, for a member or a guild.

    /api/v2/series?name=Grug     -> {name, level, xp_per_hour, basis}
    /api/v2/series?guild=cave    -> {guild, members, measured, level,
                                     xp_per_hour, basis}

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
"""

from __future__ import annotations

import statistics

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
_MEMBER_SQL = "SELECT guid, name, level, xp FROM characters WHERE name = %s LIMIT 1"
_GUILD_SQL = "SELECT guildid, name FROM guild WHERE name = %s LIMIT 1"
_GUILD_MEMBERS_SQL = (
    "SELECT c.guid, c.name, c.level, c.xp FROM characters c "
    "JOIN guild_member gm ON gm.guid = c.guid WHERE gm.guildid = %s"
)
_EVENTS_SQL = (
    "SELECT character_guid AS guid, old_level, new_level, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_level "
    "WHERE character_guid IN ({holes}) AND created_at >= FROM_UNIXTIME(%s) "
    "ORDER BY created_at, id"
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
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
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


def member_series(char: dict, events: list, table: dict, now: float) -> dict:
    points = anchors(events, char["level"], char["xp"], now, table)
    return {
        "name": char["name"],
        "level": level_line(events, char["level"], now),
        "xp_per_hour": measured_or_empty(hourly(points, now)),
        "basis": BASIS,
    }


def _sum_hours(per_member: list) -> list:
    if not per_member:
        return []
    out = []
    for i, (ts, _) in enumerate(per_member[0]):
        vals = [s[i][1] for s in per_member if s[i][1] is not None]
        out.append([ts, sum(vals) if vals else None])
    return out


def guild_series(name: str, chars: list, events: list, table: dict, now: float) -> dict:
    by_guid: dict = {}
    for ev in events:
        by_guid.setdefault(int(ev["guid"]), []).append(ev)
    hours = []
    for char in chars:
        mine = by_guid.get(int(char["guid"]), [])
        points = anchors(mine, char["level"], char["xp"], now, table)
        hours.append(hourly(points, now))
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
        "basis": BASIS,
    }


# ---- reads -------------------------------------------------------------------


def _one(cur, sql: str, args=()):
    cur.execute(sql, args)
    return cur.fetchone()


def _all(cur, sql: str, args=()) -> list:
    cur.execute(sql, args)
    return list(cur.fetchall())


def _events(cur, guids: list, now: float) -> list:
    if not guids:
        return []
    holes = ", ".join(["%s"] * len(guids))
    return _all(cur, _EVENTS_SQL.format(holes=holes), (*guids, int(now - LOOKBACK)))  # noqa: S608


def _arg(query: dict, key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def series(query: dict, ctx) -> tuple[int, dict]:
    name, guild = _arg(query, "name"), _arg(query, "guild")
    if not name and not guild:
        return 400, {"error": "say name= or guild="}
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            now = float(_one(cur, _NOW_SQL)["now"])
            table = {int(r["level"]): int(r["xp"]) for r in _all(cur, _XP_TABLE_SQL)}
            if name:
                char = _one(cur, _MEMBER_SQL, (name,))
                if not char:
                    return 404, {"error": "no such character", "name": name}
                events = _events(cur, [int(char["guid"])], now)
                return 200, member_series(char, events, table, now)
            row = _one(cur, _GUILD_SQL, (guild,))
            if not row:
                return 404, {"error": "no such guild", "guild": guild}
            chars = _all(cur, _GUILD_MEMBERS_SQL, (row["guildid"],))
            events = _events(cur, [int(c["guid"]) for c in chars], now)
            return 200, guild_series(row["name"], chars, events, table, now)
    finally:
        conn.close()


ROUTES = {"/api/v2/series": series}
