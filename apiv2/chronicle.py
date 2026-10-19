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
# The guilds' members by name, so the death read below runs down the death
# table's (character_name, created_at) key (#795). Joined to guild_member by
# guid, it had no key to use: the plan walked the primary key backward from
# the newest death and, with fewer dungeon deaths in the week than MAX_ROWS,
# read every row the table holds.
_MEMBERS_SQL = (
    "SELECT c.name, gm.guildid AS guild_id FROM guild_member gm "
    "JOIN characters c ON c.guid = gm.guid WHERE gm.guildid IN ({holes})"
)
_DEATHS_SQL = (
    "SELECT character_name AS name, map, killer_name AS killer, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_death "
    "WHERE character_name IN ({names}) AND created_at >= NOW() - INTERVAL %s DAY "
    "AND map NOT IN ({continents}) ORDER BY id DESC LIMIT %s"
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


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


def _deaths(rd, ids: list, ih: str, conts: str) -> list:
    """The guilds' deaths off the continents this week, each with its guild."""
    members = rd.must(_MEMBERS_SQL.format(holes=ih), tuple(ids))
    guild_by_name = {str(m["name"]).lower(): int(m["guild_id"]) for m in members}
    if not guild_by_name:
        return []
    names = sorted({str(m["name"]) for m in members})
    rows = rd.must(
        _DEATHS_SQL.format(names=_holes(len(names)), continents=conts),
        (*names, DAYS, MAX_ROWS),
    )
    out = []
    for r in rows:
        guild_id = guild_by_name.get(str(r["name"]).lower())
        if guild_id is not None:
            out.append(dict(r, guild_id=guild_id))
    return out


def build(rd, guilds: list, maps: dict) -> dict:
    found = rd.must(_GUILDS_SQL.format(holes=_holes(len(guilds))), tuple(guilds))
    guild_of = {int(r["guildid"]): r["name"] for r in found}
    names = [r["name"] for r in found]
    items: list = []
    if guild_of:
        ids = list(guild_of)
        ih = _holes(len(ids))
        conts = ", ".join(str(c) for c in CONTINENTS)
        items += level_items(
            rd.must(_LEVELS_SQL.format(holes=ih), (*ids, DAYS, MAX_ROWS)), guild_of
        )
        came_back = guildrun.came_back(rd, names, DAYS, MAX_ROWS)
        items += run_items([dict(r, at=r["ended_unix"]) for r in came_back])
        items += death_items(_deaths(rd, ids, ih, conts), guild_of, maps)
    items.sort(key=lambda i: (-i["at"], i["kind"], i["text"]))
    return {"guilds": sorted(names), "days": DAYS, "items": items[:LIMIT]}


def chronicle(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    # Only a family guild, refused before this read opens a connection.
    if asked and _scope.guild(ctx, asked) is None:
        return 404, _scope.no_such_guild(ctx)
    guilds = [_scope.guild(ctx, asked)] if asked else list(_scope.guilds(ctx).values())
    maps = ctx.server.achievements.MAP_NAMES
    payload = build(ctx.read, guilds, maps)
    if asked and not payload["guilds"]:
        return 404, {"error": "no such guild", "guild": asked}
    return 200, payload


ROUTES = {"/api/v2/chronicle": chronicle}
