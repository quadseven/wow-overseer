"""GET /api/v2/guild?guild=cave: one guild's progress, as the Guilds view draws it.

    {guild, faction, family, count, online, members, gaining, deaths,
     class_quests, dungeons, now}

Everything here is read from the realm's own tables, at the moment of the
read, and nothing is written:

  members       characters joined to guild_member: level, class, online, and
                ghost. Online and ghost are presence.of's reading, the one the
                roster and the gear table serve too: online is a snapshot
                written in the last minute, and ghost is a corpse or a
                released spirit. The saved online column is not read: it
                lagged the world, and this page once counted members online
                that the roster did not.
  gaining       members with a level change in the last 24 hours
                (overseer_level). Experience itself is not recorded, so
                "gaining" means a level, not a kill.
  deaths        overseer_death over the last 24 hours: the count, the killers
                that took the most, and for each ghost the death that made it.
  class_quests  class quests (classquest.py's definition: a single-class
                AllowableClasses or a class QuestSortID) rewarded, in the log,
                and blocked: a member whose latest class quest step from the
                guild job runner (guildjobs) in the last BLOCKED_HOURS failed,
                with the reason the module gave.
  dungeons      the doors this guild's faction runs (guildrun.GUILD_DOORS), in
                level order, with what overseer_guild_run says about each:
                runs that went in, clears, wipes, the best clear, the last run,
                and the commonest way a run that went in did not clear.

A value the tables do not hold is null, never 0, and the app says "not
measured".
"""

from __future__ import annotations

import collections
import json
import re
import statistics

import classquest
import council
import guildrun
from apiv2 import _allow, presence

BLOCKED_HOURS = 2
TOP_KILLERS = 5
CONTINENTS = (0, 1, 530, 571)
# Every read is bounded. A guild holds at most a thousand members (the game's
# own limit); the rest are generous ceilings over a day or two of rows.
MAX_MEMBERS = 1000
MAX_ROWS = 5000

_GUILD_SQL = "SELECT guildid, name FROM guild WHERE name = %s LIMIT 1"
_NOW_SQL = "SELECT UNIX_TIMESTAMP() AS now"
_MEMBERS_SQL = (
    "SELECT c.guid, c.name, c.level, c.class, c.race, c.zone FROM characters c "
    "JOIN guild_member gm ON gm.guid = c.guid WHERE gm.guildid = %s LIMIT %s"
)
_ROSTER_SQL = (
    "SELECT name, family FROM overseer_roster "
    "WHERE family IS NOT NULL AND family <> '' LIMIT %s"
)
_DINGS_SQL = (
    "SELECT character_name AS name, MAX(new_level) AS level, "
    "MAX(UNIX_TIMESTAMP(created_at)) AS at FROM overseer_level "
    "WHERE guild_id = %s AND created_at >= NOW() - INTERVAL 1 DAY "
    "GROUP BY character_name"
)
_DEATH_TOTAL_SQL = (
    "SELECT COUNT(*) AS n, COUNT(DISTINCT character_name) AS who "
    "FROM overseer_death WHERE character_name IN ({holes}) "
    "AND created_at >= NOW() - INTERVAL 1 DAY"
)
_KILLERS_SQL = (
    "SELECT killer_name AS killer, COUNT(*) AS n, "
    "COUNT(DISTINCT character_name) AS who FROM overseer_death "
    "WHERE character_name IN ({holes}) AND created_at >= NOW() - INTERVAL 1 DAY "
    "GROUP BY killer_name ORDER BY n DESC LIMIT %s"
)
_LAST_DEATH_SQL = (
    "SELECT character_name AS name, killer_name AS killer, map, zone, "
    "UNIX_TIMESTAMP(created_at) AS at FROM overseer_death WHERE id IN ("
    "SELECT MAX(id) FROM overseer_death WHERE character_name IN ({holes}) "
    "GROUP BY character_name)"
)
_CLASS_QUEST = "(a.AllowableClasses IN ({masks}) OR q.QuestSortID IN ({sorts}))".format(
    masks=", ".join(str(m) for m in classquest.SINGLE_CLASS_MASKS),
    sorts=", ".join(str(s) for s in sorted(classquest.CLASS_OF_SORT)),
)
_CQ_OPEN_SQL = (
    "SELECT c.name, s.quest AS id, s.status, q.LogTitle AS title "
    "FROM character_queststatus s JOIN characters c ON c.guid = s.guid "
    "JOIN guild_member gm ON gm.guid = c.guid "
    "JOIN acore_world.quest_template q ON q.ID = s.quest "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE gm.guildid = %s AND s.status IN (1, 3) AND " + _CLASS_QUEST + " LIMIT %s"
)
_CQ_DONE_SQL = (
    "SELECT COUNT(*) AS n, COUNT(DISTINCT r.guid) AS who "
    "FROM character_queststatus_rewarded r "
    "JOIN guild_member gm ON gm.guid = r.guid "
    "JOIN acore_world.quest_template q ON q.ID = r.quest "
    "LEFT JOIN acore_world.quest_template_addon a ON a.ID = q.ID "
    "WHERE gm.guildid = %s AND " + _CLASS_QUEST
)
_CQ_STEPS_SQL = (
    "SELECT target_name AS name, command, status, detail, "
    "LEFT(result, 600) AS result, UNIX_TIMESTAMP(created_at) AS at "
    "FROM overseer_command WHERE source LIKE 'guildjobs:classquest%%' "
    "AND created_at >= NOW() - INTERVAL %s HOUR AND target_name IN ({holes}) "
    "ORDER BY id DESC LIMIT %s"
)
_QUEST_TITLES_SQL = (
    "SELECT ID AS id, LogTitle AS title FROM acore_world.quest_template "
    "WHERE ID IN ({holes})"
)
_RUNS_SQL = (
    "SELECT keyword, state, outcome, why, deaths, seconds_inside, "
    "UNIX_TIMESTAMP(created_at) AS created, UNIX_TIMESTAMP(ended_at) AS ended "
    "FROM overseer_guild_run WHERE guild = %s ORDER BY id DESC LIMIT %s"
)

_QUEST_IN_COMMAND = re.compile(r"\bquest:(\d+)")


# ---- pure shaping --------------------------------------------------------------


def class_name(class_id) -> str:
    return classquest.CLASS_NAMES.get(int(class_id or 0), "").title()


def faction_of(races) -> str:
    races = {int(r) for r in races if r}
    if races and races <= guildrun.ALLIANCE_RACES:
        return "Alliance"
    if races and races <= guildrun.HORDE_RACES:
        return "Horde"
    return ""


def family_of(names: set, roster_rows: list) -> str:
    """The family with the most members in this guild, or ""."""
    counts = collections.Counter(
        r["family"] for r in roster_rows if r.get("name") in names
    )
    return counts.most_common(1)[0][0] if counts else ""


def member_rows(rows: list, readings: dict) -> list:
    """Each member, online and ghost as presence.of read them. Ghost is a
    corpse or a released spirit: either is out of play."""
    out = []
    for r in sorted(rows, key=lambda r: r["name"]):
        reading = readings.get(r["name"]) or {}
        out.append(
            {
                "name": r["name"],
                "level": int(r["level"] or 0),
                "class": class_name(r["class"]),
                "online": bool(reading.get("online")),
                "ghost": reading.get("life") in ("dead", "ghost"),
            }
        )
    return out


def place(map_id, zone, zones: dict, maps: dict) -> str:
    map_id = int(map_id or 0)
    if map_id not in CONTINENTS and maps.get(map_id):
        return maps[map_id]
    return zones.get(int(zone or 0), "")


def _reason(step: dict) -> str:
    try:
        said = json.loads(step.get("result") or "")
    except (TypeError, ValueError):
        said = None
    if isinstance(said, dict) and said.get("reason"):
        return str(said["reason"])
    return step.get("detail") or step.get("status") or ""


def blocked_steps(steps: list) -> dict:
    """name -> the latest class quest step, when that step failed."""
    latest: dict = {}
    for step in steps:
        latest[step["name"]] = step
    return {n: s for n, s in latest.items() if s.get("status") == "error"}


def class_quest_rows(
    open_rows: list, blocked: dict, titles: dict, classes: dict
) -> list:
    """Blocked first, then in progress; one blocked row per member."""
    rows = []
    for name, step in sorted(blocked.items()):
        found = _QUEST_IN_COMMAND.search(step.get("command") or "")
        mine = [r for r in open_rows if r["name"] == name]
        qid = int(found.group(1)) if found else (mine[0]["id"] if mine else None)
        title = titles.get(qid) or next(
            (r["title"] for r in mine if r["id"] == qid), None
        )
        rows.append(
            {
                "member": name,
                "class": classes.get(name, ""),
                "quest_id": qid,
                "quest": title,
                "state": "blocked",
                "note": _reason(step),
                "at": int(step["at"]),
            }
        )
    taken = {(r["member"], r["quest_id"]) for r in rows}
    for r in sorted(open_rows, key=lambda r: (r["name"], r["id"])):
        if (r["name"], r["id"]) in taken:
            continue
        rows.append(
            {
                "member": r["name"],
                "class": classes.get(r["name"], ""),
                "quest_id": int(r["id"]),
                "quest": r["title"],
                "state": "ready to hand in" if int(r["status"]) == 1 else "in progress",
                "note": "",
                "at": None,
            }
        )
    return rows


def _lesson(failed: list) -> dict | None:
    """The commonest way a run that went in did not clear, with the latest
    reason given for it."""
    if not failed:
        return None
    outcome, n = collections.Counter(r["outcome"] for r in failed).most_common(1)[0]
    why = next((r["why"] for r in reversed(failed) if r["outcome"] == outcome), "")
    return {"outcome": outcome, "n": n, "why": why}


def _tally(runs: list) -> dict:
    went = [r for r in runs if r["outcome"] in guildrun.WENT_IN]
    cleared = [r for r in went if r["outcome"] == guildrun.CLEARED]
    best = [int(r["seconds_inside"]) for r in cleared if r["seconds_inside"]]
    deaths = [int(r["deaths"] or 0) for r in went]
    times = [r["ended"] or r["created"] for r in runs if r["ended"] or r["created"]]
    return {
        "runs": len(went),
        "started": len(runs),
        "cleared": len(cleared),
        "wiped": sum(1 for r in went if r["outcome"] == "wiped"),
        "best_seconds": min(best) if best else None,
        "deaths_per_run": round(statistics.mean(deaths), 1) if deaths else None,
        "last_at": int(max(times)) if times else None,
        "inside": any(r["state"] == "inside" for r in runs),
        "lesson": _lesson([r for r in went if r["outcome"] != guildrun.CLEARED]),
    }


def dungeon_rows(doors: list, faction: str, runs: list) -> list:
    """The faction's doors in level order, each with its tally."""
    allowed = guildrun.GUILD_DOORS.get(faction)
    by_kw: dict = {}
    for r in runs:
        by_kw.setdefault(r["keyword"], []).append(r)
    rows = []
    seen = set()
    for door in sorted(doors, key=lambda d: (d.floor, d.place)):
        if (
            allowed is not None
            and door.keyword not in allowed
            and door.keyword not in by_kw
        ):
            continue
        seen.add(door.keyword)
        row = {
            "keyword": door.keyword,
            "place": door.place,
            "map_id": door.map_id,
            "floor": door.floor,
            "ceiling": door.ceiling,
        }
        row.update(_tally(by_kw.get(door.keyword, [])))
        rows.append(row)
    for kw in sorted(set(by_kw) - seen):
        row = {
            "keyword": kw,
            "place": council.keyword_place(kw),
            "map_id": None,
            "floor": None,
            "ceiling": None,
        }
        row.update(_tally(by_kw[kw]))
        rows.append(row)
    return rows


# ---- reads ---------------------------------------------------------------------


def _all(cur, sql: str, args=()) -> list:
    cur.execute(sql, args)
    return list(cur.fetchall())


def _holes(n: int) -> str:
    return ", ".join(["%s"] * n)


def _deaths(cur, names: list, ghosts: list, zones: dict, maps: dict) -> dict:
    if not names:
        return {"total": 0, "members": 0, "killers": [], "ghosts": []}
    holes = _holes(len(names))
    total = _all(cur, _DEATH_TOTAL_SQL.format(holes=holes), tuple(names))[0]
    killers = _all(cur, _KILLERS_SQL.format(holes=holes), (*names, TOP_KILLERS))
    last = {}
    if ghosts:
        found = _all(
            cur, _LAST_DEATH_SQL.format(holes=_holes(len(ghosts))), tuple(ghosts)
        )
        last = {r["name"]: r for r in found}
    return {
        "total": int(total["n"] or 0),
        "members": int(total["who"] or 0),
        "killers": [
            {"killer": k["killer"] or "", "n": int(k["n"]), "members": int(k["who"])}
            for k in killers
        ],
        "ghosts": [_ghost(name, last.get(name), zones, maps) for name in ghosts],
    }


def _ghost(name: str, death, zones: dict, maps: dict) -> dict:
    if not death:
        return {"name": name, "killer": None, "where": None, "at": None}
    return {
        "name": name,
        "killer": death["killer"] or None,
        "where": place(death["map"], death["zone"], zones, maps) or None,
        "at": int(death["at"]),
    }


def _class_quests(cur, guild_id: int, names: list, classes: dict) -> dict:
    done = _all(cur, _CQ_DONE_SQL, (guild_id,))[0]
    open_rows = _all(cur, _CQ_OPEN_SQL, (guild_id, MAX_ROWS))
    steps = []
    if names:
        steps = _all(
            cur,
            _CQ_STEPS_SQL.format(holes=_holes(len(names))),
            (BLOCKED_HOURS, *names, MAX_ROWS),
        )[::-1]  # newest first under the bound, then back to oldest first
    blocked = blocked_steps(steps)
    wanted = sorted(
        {
            int(m.group(1))
            for s in blocked.values()
            for m in [_QUEST_IN_COMMAND.search(s.get("command") or "")]
            if m
        }
    )
    titles = {}
    if wanted:
        found = _all(
            cur, _QUEST_TITLES_SQL.format(holes=_holes(len(wanted))), tuple(wanted)
        )
        titles = {int(r["id"]): r["title"] for r in found}
    rows = class_quest_rows(open_rows, blocked, titles, classes)
    return {
        "done": int(done["n"] or 0),
        "done_members": int(done["who"] or 0),
        "blocked": sum(1 for r in rows if r["state"] == "blocked"),
        "open": sum(1 for r in rows if r["state"] != "blocked"),
        "rows": rows,
    }


def build(cur, row: dict, zones: dict, maps: dict) -> dict:
    gid = int(row["guildid"])
    now = int(_all(cur, _NOW_SQL)[0]["now"])
    raw = _all(cur, _MEMBERS_SQL, (gid, MAX_MEMBERS))
    members = member_rows(raw, presence.of(cur, [r["name"] for r in raw]))
    names = [m["name"] for m in members]
    classes = {m["name"]: m["class"] for m in members}
    faction = faction_of(r["race"] for r in raw)
    ghosts = [m["name"] for m in members if m["ghost"]]
    return {
        "guild": row["name"],
        "faction": faction,
        "family": family_of(set(names), _all(cur, _ROSTER_SQL, (MAX_ROWS,))),
        "count": len(members),
        "online": sum(1 for m in members if m["online"]),
        "members": members,
        "gaining": [
            {"name": d["name"], "level": int(d["level"]), "at": int(d["at"])}
            for d in _all(cur, _DINGS_SQL, (gid,))
        ],
        "deaths": _deaths(cur, names, ghosts, zones, maps),
        "class_quests": _class_quests(cur, gid, names, classes),
        "dungeons": dungeon_rows(
            guildrun.doors(),
            faction,
            _all(cur, _RUNS_SQL, (row["name"], MAX_ROWS))[::-1],
        ),
        "now": now,
    }


def guild(query: dict, ctx) -> tuple[int, dict]:
    asked = (query.get("guild") or [""])[0].strip()
    if not asked:
        return 400, {"error": "say guild="}
    # Only a managed guild, refused before any query (_allow).
    name = _allow.guild(asked)
    if name is None:
        return 404, {"error": "no such guild", "guilds": sorted(_allow.GUILDS)}
    server = ctx.server
    zones = server.recap.zone_names(server.GEO.continents)
    maps = server.achievements.MAP_NAMES
    conn = ctx.connect()
    try:
        with conn.cursor() as cur:
            found = _all(cur, _GUILD_SQL, (name,))
            if not found:
                return 404, {"error": "no such guild", "guild": name}
            return 200, build(cur, found[0], zones, maps)
    finally:
        conn.close()


ROUTES = {"/api/v2/guild": guild}
