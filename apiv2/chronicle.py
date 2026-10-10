"""GET /api/v2/chronicle[?guild=cave]: what a guild has done, newest first.

    {guilds, days, items: [{kind, at, guild, who, text, place?, run?}]}

The feed the Guilds view's Chronicle draws, and the count behind the Guilds
nav badge (items newer than a device's last visit). Without `guild` it covers
both managed guilds, which is what the badge reads.

FOUR KINDS, each read straight off a table the realm writes:

  level   overseer_level: the members who reached a new level, one item per
          guild per hour so a busy hour is one line, not forty.
  clear   a guild run that went in and cleared (guildrun.came_back).
  run     a guild run that went in and did not clear (wiped, abandoned,
          timed out). Runs that never went in are not history.
  death   overseer_death inside a dungeon the site knows (achievements.MAP_NAMES),
          one item per guild, dungeon and hour. Deaths in the open world run
          to thousands a day and are counted on the Progress tab instead.

Notable loot is not here: /api/loot already tells it, per guild, and the app
merges it in, so one item is never built twice.

Every `at` is a Unix time in seconds from the database's own clock.
"""

from __future__ import annotations

import guildrun
import council
from apiv2 import _scope

DAYS = 7
HOUR = 3600
LIMIT = 200
# Every read is bounded, newest first: far more rows than LIMIT items need.
MAX_ROWS = 20000
CONTINENTS = (0, 1, 530, 571)

_GUILDS_SQL = "SELECT guildid, name FROM guild WHERE name IN ({holes})"
_LEVELS_SQL = (
    "SELECT character_name AS name, new_level AS level, guild_id, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_level "
    "WHERE guild_id IN ({holes}) AND created_at >= NOW() - INTERVAL %s DAY "
    "ORDER BY created_at DESC LIMIT %s"
)
_DEATHS_SQL = (
    "SELECT d.character_name AS name, d.map, d.killer_name AS killer, "
    "gm.guildid AS guild_id, UNIX_TIMESTAMP(d.created_at) AS at "
    "FROM overseer_death d JOIN guild_member gm ON gm.guid = d.character_guid "
    "WHERE gm.guildid IN ({holes}) AND d.created_at >= NOW() - INTERVAL %s DAY "
    "AND d.map NOT IN ({continents}) ORDER BY d.id DESC LIMIT %s"
)


def names_line(names: list, most: int = 4) -> str:
    """ "A", "A and B", "A, B and C", "A, B, C and 2 more"."""
    names = list(dict.fromkeys(names))
    if len(names) <= 1:
        return "".join(names)
    if len(names) <= most:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[: most - 1]) + " and %d more" % (len(names) - most + 1)


def level_items(rows: list, guild_of: dict) -> list:
    groups: dict = {}
    for r in rows:
        key = (guild_of.get(int(r["guild_id"]), ""), int(r["at"]) // HOUR)
        groups.setdefault(key, []).append(r)
    items = []
    for (guild, _), rs in groups.items():
        rs.sort(key=lambda r: (-int(r["at"]), r["name"]))
        best: dict = {}
        for r in rs:
            best[r["name"]] = max(best.get(r["name"], 0), int(r["level"]))
        if len(best) == 1:
            ((who, lvl),) = best.items()
            text = "%s reached level %d." % (who, lvl)
        else:
            text = (
                "Reached a new level: "
                + names_line(["%s %d" % (n, lv) for n, lv in best.items()], 6)
                + "."
            )
        items.append(
            {
                "kind": "level",
                "at": int(rs[0]["at"]),
                "guild": guild,
                "who": list(best),
                "text": text,
            }
        )
    return items


def run_items(rows: list) -> list:
    items = []
    for r in rows:
        place = council.keyword_place(r["keyword"])
        # "Crag:tank:warrior:23,Ortimo:healer:paladin:19,..."
        who = [s.split(":")[0] for s in (r["members"] or "").split(",") if s]
        bosses = ""
        if r["bosses_total"]:
            bosses = ", %d of %d bosses" % (
                int(r["bosses_done"] or 0),
                int(r["bosses_total"]),
            )
        if r["outcome"] == guildrun.CLEARED:
            text = "%s cleared %s%s." % (r["guild"], place, bosses)
            kind = "clear"
        else:
            text = "%s came back from %s: %s%s." % (
                r["guild"],
                place,
                r["outcome"],
                bosses,
            )
            kind = "run"
        items.append(
            {
                "kind": kind,
                "at": int(r["at"]),
                "guild": r["guild"],
                "who": who,
                "text": text,
                "place": place,
                "run": int(r["id"]),
            }
        )
    return items


def death_items(rows: list, guild_of: dict, maps: dict) -> list:
    groups: dict = {}
    for r in rows:
        if int(r["map"]) not in maps:
            continue  # not a dungeon the site knows: a start zone, a battleground
        key = (
            guild_of.get(int(r["guild_id"]), ""),
            int(r["map"]),
            int(r["at"]) // HOUR,
        )
        groups.setdefault(key, []).append(r)
    items = []
    for (guild, map_id, _), rs in groups.items():
        rs.sort(key=lambda r: -int(r["at"]))
        where = maps[map_id]
        who = list(dict.fromkeys(r["name"] for r in rs))
        killers = [k for k in dict.fromkeys(r["killer"] for r in rs) if k]
        text = "%s died in %s" % (names_line(who), where)
        if len(rs) > len(who):
            text += " (%d deaths)" % len(rs)
        if killers:
            text += ": " + names_line(killers, 3)
        items.append(
            {
                "kind": "death",
                "at": int(rs[0]["at"]),
                "guild": guild,
                "who": who,
                "text": text + ".",
                "place": where,
            }
        )
    return items


def _all(cur, sql: str, args=()) -> list:
    cur.execute(sql, args)
    return list(cur.fetchall())


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


def build(cur, guilds: list, maps: dict) -> dict:
    found = _all(cur, _GUILDS_SQL.format(holes=_holes(len(guilds))), tuple(guilds))
    guild_of = {int(r["guildid"]): r["name"] for r in found}
    names = [r["name"] for r in found]
    items: list = []
    if guild_of:
        ids = list(guild_of)
        ih = _holes(len(ids))
        conts = ", ".join(str(c) for c in CONTINENTS)
        items += level_items(
            _all(cur, _LEVELS_SQL.format(holes=ih), (*ids, DAYS, MAX_ROWS)), guild_of
        )
        came_back = guildrun.came_back(cur, names, DAYS, MAX_ROWS)
        items += run_items([dict(r, at=r["ended_unix"]) for r in came_back])
        items += death_items(
            _all(
                cur,
                _DEATHS_SQL.format(holes=ih, continents=conts),
                (*ids, DAYS, MAX_ROWS),
            ),
            guild_of,
            maps,
        )
    items.sort(key=lambda i: (-i["at"], i["kind"], i["text"]))
    return {"guilds": sorted(names), "days": DAYS, "items": items[:LIMIT]}


def chronicle(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    # Only a family guild, refused before this read opens a connection.
    if asked and _scope.guild(ctx, asked) is None:
        return 404, _scope.no_such_guild(ctx)
    guilds = [_scope.guild(ctx, asked)] if asked else list(_scope.guilds(ctx).values())
    maps = ctx.server.achievements.MAP_NAMES
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            payload = build(cur, guilds, maps)
    finally:
        conn.close()
    if asked and not payload["guilds"]:
        return 404, {"error": "no such guild", "guild": asked}
    return 200, payload


ROUTES = {"/api/v2/chronicle": chronicle}
