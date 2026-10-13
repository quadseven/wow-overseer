"""GET /api/v2/goal?guild=<cave|bonkers>: one answer per guild for the goal page.

The two-hourly report the operator's goal contract asks for, read from the
same tables the other v2 reads use. It is cached per guild and bounded, and a
missing module table answers zeros with a note instead of raising.

  seats          the 40 lineup raiders, each with level, online, life and
                 xp_per_hour_24h
  level          median, lowest and a 10-level histogram for the 40 seats
  gaining_xp     seats that earned XP in the last 24 hours
  runs           formed, cleared, wiped and clears per attempt in the last 24h
  class_quests   class quest asks done and blocked
  deaths_24h     total deaths and the top 5 repeated deaths by member, spot
                 and killer
  ghosts         seats that are a corpse or a released spirit
  stuck          seats blocked by a live class quest ask
  offline        seats not in the world now
  projected_60   the date the 30th seat reaches 60 at its 24h XP rate
  checkpoints    seats at 20 (A), 40 (B) and 60 (C)
"""

from __future__ import annotations

import datetime

import guildrun
import raidteams
import readcache
import realmread
import situation

from . import members as roster
from . import presence
from . import series
from . import _scope

CACHE_SECONDS = 60.0
_MAX_RUNS = 1000
_MAX_DEATH_GROUPS = 5

NOW_SQL = "SELECT UNIX_TIMESTAMP() AS now"
CHARS_SQL = (
    "SELECT c.guid, c.name, c.level, c.xp FROM characters c WHERE c.name IN ({holes})"
)
DEATHS_SQL = (
    "SELECT character_name AS name, map, zone, killer_name AS killer, "
    "COUNT(*) AS n FROM overseer_death "
    "WHERE character_name IN ({holes}) AND created_at >= NOW() - INTERVAL 1 DAY "
    "GROUP BY character_name, map, zone, killer_name "
    "ORDER BY n DESC LIMIT %s"
)
QUEST_ASKS_SQL = (
    "SELECT asker, state FROM overseer_guild_ask "
    "WHERE kind = 'quest' AND asker IN ({holes}) "
    "AND created_at >= NOW() - INTERVAL 1 DAY"
)

_CACHE = readcache.ReadCache(CACHE_SECONDS)


def _safe_rows(rd, sql, params, what, missing):
    """Rows from `sql`, or [] when the realm does not have the table/column.

    The table name is recorded in `missing` so the caller can say which reads
    were absent.
    """
    try:
        return rd.must(sql, params)
    except realmread.Gap:
        missing.add(what)
        return []


def _seat_char(seats, chars_rows):
    """Map each seat's approved name to the character row that fills it."""
    by_name = {r["name"]: r for r in chars_rows}
    out = {}
    for seat in seats:
        row = by_name.get(seat.name) or (by_name.get(seat.was) if seat.was else None)
        out[seat.name] = row
    return out


def _empty_histogram() -> dict:
    return {"%d-%d" % (b, b + 9): 0 for b in range(1, 61, 10)}


def _level_stats(levels: list) -> dict:
    if not levels:
        return {
            "median": None,
            "lowest": None,
            "histogram": _empty_histogram(),
        }
    ordered = sorted(levels)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) // 2
    hist = _empty_histogram()
    for lvl in levels:
        band = ((lvl - 1) // 10) * 10 + 1
        if band > 51:
            band = 51
        hist["%d-%d" % (band, band + 9)] += 1
    return {"median": median, "lowest": ordered[0], "histogram": hist}


def _checkpoints(levels: list) -> dict:
    return {
        "A": sum(1 for lvl in levels if lvl >= 20),
        "B": sum(1 for lvl in levels if lvl >= 40),
        "C": sum(1 for lvl in levels if lvl >= 60),
    }


def _projected_60(seat_chars, rates_by_seat, table, now):
    """The date the 30th seat reaches 60, or None when it cannot be measured."""
    hours_to = []
    for name, char in seat_chars.items():
        if not char:
            continue
        rate = rates_by_seat.get(name, {}).get("xp_per_hour_24h")
        if not rate:
            continue
        level = int(char.get("level") or 0)
        if level >= 60:
            hours_to.append(0.0)
            continue
        remaining = series.xp_to_level_60(level, char.get("xp"), table)
        if remaining is None:
            continue
        hours_to.append(remaining / rate)
    if len(hours_to) < 30:
        return None
    hours_to.sort()
    when = datetime.datetime.fromtimestamp(
        now + hours_to[29] * 3600, datetime.timezone.utc
    )
    return when.date().isoformat()


def _deaths(rows):
    total = sum(int(r["n"] or 0) for r in rows)
    repeated = [
        {
            "member": r["name"],
            "spot": situation.zone_name(r.get("zone"), r.get("map")),
            "killer": r["killer"] or "",
            "n": int(r["n"] or 0),
        }
        for r in rows
    ]
    return {"total": total, "repeated": repeated}


def _runs(rows):
    formed = len(rows)
    cleared = sum(1 for r in rows if r.get("outcome") == "cleared")
    wiped = sum(1 for r in rows if r.get("outcome") == "wiped")
    return {
        "formed": formed,
        "cleared": cleared,
        "wiped": wiped,
        "clears_per_attempt": round(cleared / formed, 2) if formed else None,
    }


def _class_quests(rows):
    return {
        "done": sum(1 for r in rows if r.get("state") == "ran"),
        "blocked": sum(1 for r in rows if r.get("state") == "open"),
    }


def _stuck(seat_names, asks, now_at):
    streaks = roster.ask_streaks(asks)
    return sum(
        1
        for name in seat_names
        if roster.ask_blocker(streaks.get(name, []), now_at) is not None
    )


def _build_seats(seats, seat_chars, readings, rates_by_seat):
    out = []
    for seat in seats:
        char = seat_chars.get(seat.name)
        reading = readings.get(seat.name) or {}
        rate = rates_by_seat.get(seat.name, {})
        out.append(
            {
                "name": seat.name,
                "level": int(char["level"])
                if char and char.get("level") is not None
                else None,
                "online": bool(reading.get("online")),
                "life": reading.get("life"),
                "xp_per_hour_24h": rate.get("xp_per_hour_24h"),
                "xp_hours_measured": rate.get("xp_hours_measured", 0),
            }
        )
    return out


def fetch(rd, guild: str, now_at: float, missing: set):
    """All rows for one guild's goal read, with missing tables recorded."""
    seats = raidteams.seats(guild)
    names = list(dict.fromkeys(n for seat in seats for n in (seat.name, seat.was) if n))
    chars = _safe_rows(
        rd,
        CHARS_SQL.format(holes=_scope.holes(len(names))),
        tuple(names),
        "characters",
        missing,
    )
    seat_chars = _seat_char(seats, chars)
    seat_names = [seat.name for seat in seats]
    readings = presence.of(rd, seat_names)

    xp_rows = _safe_rows(rd, series._XP_TABLE_SQL, (), "player_xp_for_level", missing)
    table = {int(r["level"]): int(r["xp"]) for r in xp_rows}

    guids = [int(c["guid"]) for c in chars if c.get("guid")]
    events = []
    if guids:
        events = _safe_rows(
            rd,
            series._EVENTS_SQL.format(holes=_scope.holes(len(guids))),
            (*guids, int(now_at - series.LOOKBACK), series.MAX_EVENTS),
            "overseer_level",
            missing,
        )

    asks = _safe_rows(
        rd,
        roster.ASKS_SQL.format(holes=_scope.holes(len(seat_names))),
        (*seat_names, roster.ASK_DAYS),
        "overseer_guild_ask",
        missing,
    )
    runs = guildrun.formed_since(rd, [guild], days=1, n=_MAX_RUNS)
    deaths = _safe_rows(
        rd,
        DEATHS_SQL.format(holes=_scope.holes(len(seat_names))),
        (*seat_names, _MAX_DEATH_GROUPS),
        "overseer_death",
        missing,
    )
    quest_rows = _safe_rows(
        rd,
        QUEST_ASKS_SQL.format(holes=_scope.holes(len(seat_names))),
        tuple(seat_names),
        "overseer_guild_ask",
        missing,
    )
    return seats, seat_chars, readings, table, events, asks, runs, deaths, quest_rows


def build(rd, guild: str) -> dict:
    """The full /api/v2/goal payload for one guild."""
    missing: set = set()
    now_rows = _safe_rows(rd, NOW_SQL, (), "clock", missing)
    now_at = float(now_rows[0]["now"]) if now_rows else 0.0

    seats, seat_chars, readings, table, events, asks, runs, deaths, quest_rows = fetch(
        rd, guild, now_at, missing
    )

    events_by_guid: dict = {}
    for ev in events:
        events_by_guid.setdefault(int(ev["guid"]), []).append(ev)

    rates_by_seat: dict = {}
    for seat in seats:
        char = seat_chars.get(seat.name)
        if char and table:
            mine = events_by_guid.get(int(char["guid"]), [])
            points = series.anchors(mine, char["level"], char["xp"], now_at, table)
            hours = series.hourly(points, now_at)
            rates_by_seat[seat.name] = series.rate(hours)
        else:
            rates_by_seat[seat.name] = {
                "xp_per_hour_24h": None,
                "xp_hours_measured": 0,
            }

    seat_rows = _build_seats(seats, seat_chars, readings, rates_by_seat)
    levels = [s["level"] for s in seat_rows if s["level"] is not None]
    gaining = sorted(s["name"] for s in seat_rows if s["xp_per_hour_24h"] is not None)

    return {
        "guild": guild,
        "seats": seat_rows,
        "level": _level_stats(levels),
        "gaining_xp": gaining,
        "runs": _runs(runs),
        "class_quests": _class_quests(quest_rows),
        "deaths_24h": _deaths(deaths),
        "ghosts": sum(1 for s in seat_rows if s["life"] in ("dead", "ghost")),
        "stuck": _stuck([seat.name for seat in seats], asks, int(now_at)),
        "offline": sum(1 for s in seat_rows if not s["online"]),
        "projected_60": _projected_60(seat_chars, rates_by_seat, table, now_at),
        "checkpoints": _checkpoints(levels),
        "checked_at": int(now_at) or None,
        "missing": sorted(missing),
    }


def goal(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    if not asked:
        return 400, {"error": "say guild="}
    guild_name = _scope.guild(ctx, asked)
    if guild_name is None:
        return 404, _scope.no_such_guild(ctx)
    key = "goal:%s" % guild_name
    return 200, _CACHE.get(key, lambda: build(ctx.read, guild_name))


ROUTES = {"/api/v2/goal": goal}
