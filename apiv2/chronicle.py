"""GET /api/v2/chronicle[?guild=cave]: what a guild has done, newest first.

    {guilds, days, items: [{kind, at, guild, who, text, place?, run?}]}

The feed the Guilds view's Chronicle draws, and the count behind the Guilds
nav badge (items newer than a device's last visit). Without `guild` it covers
every family guild, which is what the badge reads.

FIVE KINDS, each read straight off a table the realm writes:

  first_kill  a family's first kill of a boss, from overseer_event boss_kill
          rows by the clip ledger's own picker (clipledger.first_kills), so
          the item and the ledger row agree on who got it. It carries the
          clip link of the ledger row under clipledger.boss_key.

  level   overseer_level: the members who reached a new level, one item per
          guild per hour so a busy hour is one line, not forty.
  clear   a guild run that went in and came out `cleared` (guildrun.came_back):
          the module's word for its last boss down. The line says cleared only
          when the count holds every boss the run expects, and finished when
          side bosses were left. That total is the map's encounters less those
          only an event brings out (the module's EventGatedEncounterMask:
          Tuten'kash, Grubbis, Mutanus, Gahz'rilla), by wing where a map has
          independent wings, so Razorfen Downs is 3 and not 4.
  run     a guild run that went in and did not clear (wiped, abandoned,
          timed out, stalled). Runs that never went in are not history.
  death   overseer_death inside a dungeon the site knows (achievements.MAP_NAMES),
          one item per guild, dungeon and hour. Deaths in the open world run
          to thousands a day and are counted on the Progress tab instead.

Notable loot is not here: /api/loot already tells it, per guild, and the app
merges it in, so one item is never built twice.

Every `at` is a Unix time in seconds from the database's own clock.
"""

from __future__ import annotations

import clipledger
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


# Boss kills of the family's characters over the whole record, oldest first:
# a first is a fact about the whole history, and the feed window is applied to
# the first afterwards. `now` is the database clock, in the same unit as `at`.
_KILLS_SQL = (
    "SELECT character_name, kind, subject_id, subject_name, "  # noqa: S608
    "UNIX_TIMESTAMP(first_seen) AS first_seen, UNIX_TIMESTAMP() AS now "
    "FROM overseer_event WHERE kind = 'boss_kill' "
    "AND character_name IN ({names}) ORDER BY first_seen ASC LIMIT %s"
)
# The clip ledger's rows for these event keys: only the states a feed item
# says something about. A realm without the table answers with no rows.
_CLIPS_SQL = (
    "SELECT event_key, kind, `character`, state, file_name, detail "  # noqa: S608
    "FROM overseer_clip WHERE event_key IN ({keys}) "
    "AND state IN ('ready', 'no_view', 'failed')"
)


def names_line(names: list, most: int = 4) -> str:
    """ "A", "A and B", "A, B and C", "A, B, C and 2 more"."""
    names = list(dict.fromkeys(names))
    if len(names) <= 1:
        return "".join(names)
    if len(names) <= most:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[: most - 1]) + " and %d more" % (len(names) - most + 1)


def _clip_of(clips: dict | None, key: str) -> dict:
    """The link for the ledger row under `key`. The key names the family and
    the boss, or the character, so it is the identity: the row links whichever
    member the ledger credited."""
    row = (clips or {}).get(key)
    return clipledger.link(row) if row else {}


def first_kill_items(kills: list, kin: list, clips: dict, now: int) -> list:
    """One item per family per boss: that family's first kill, picked by
    clipledger.first_kills, inside the feed window.

    `kin` is [(guild, family, member names)], one entry per family shown.
    `now` is the database clock in Unix seconds.
    """
    items = []
    for guild, family, names in kin:
        for row in clipledger.first_kills(kills, names, lambda _n: ""):
            at = int(row["first_seen"])
            if at < now - DAYS * 24 * HOUR:
                continue
            who = row["character_name"]
            boss = row.get("subject_name") or "a boss"
            items.append(
                {
                    "kind": "first_kill",
                    "at": at,
                    "guild": guild,
                    "who": [who],
                    "text": "%s landed the family's first kill of %s." % (who, boss),
                    **_clip_of(clips, clipledger.boss_key(row["subject_id"], family)),
                }
            )
    return items


def level_items(rows: list, guild_of: dict, clips: dict | None = None) -> list:
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
        item = {
            "kind": "level",
            "at": int(rs[0]["at"]),
            "guild": guild,
            "who": list(best),
            "text": text,
        }
        sixty = [
            {"who": who, **_clip_of(clips, clipledger.level_key(who))}
            for who, lvl in best.items()
            if lvl == 60
        ]
        sixty = [c for c in sixty if len(c) > 1]
        if sixty:
            item["clips"] = sixty
        items.append(item)
    return items


# A run that went in and did not clear, as the words after the guild's name.
_FAILED = {
    "wiped": "wiped in %s",
    "abandoned": "abandoned %s",
    "timed out": "ran out of time in %s",
    "stalled": "stalled in %s",
}


def run_text(guild: str, place: str, outcome: str, done: int, total: int) -> str:
    """One run as a sentence. A count of nothing on a finished run is a count
    that failed, since its last boss is down, so it is not told as bosses."""
    if outcome == guildrun.CLEARED:
        if guildrun.every_boss_fell(done, total):
            return "%s cleared %s, %d of %d bosses down." % (guild, place, done, total)
        line = "%s finished %s with its last boss down" % (guild, place)
        if not total:
            return line + "."
        if not done:
            return line + "; the boss count was not recorded."
        return line + ", %d of %d bosses." % (done, total)
    said = _FAILED.get(outcome, "came back from %s") % place
    counted = ", %d of %d bosses down" % (done, total) if total else ""
    return "%s %s%s." % (guild, said, counted)


def run_items(rows: list) -> list:
    items = []
    for r in rows:
        place = council.keyword_place(r["keyword"])
        # "Crag:tank:warrior:23,Ortimo:healer:paladin:19,..."
        who = [s.split(":")[0] for s in (r["members"] or "").split(",") if s]
        items.append(
            {
                "kind": "clear" if r["outcome"] == guildrun.CLEARED else "run",
                "at": int(r["at"]),
                "guild": r["guild"],
                "who": who,
                "text": run_text(
                    r["guild"],
                    place,
                    r["outcome"],
                    int(r["bosses_done"] or 0),
                    int(r["bosses_total"] or 0),
                ),
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


def _kin(ctx, guilds: list) -> list:
    """[(guild, family, member names)] for the families behind `guilds`, one
    entry per family, the guild chosen by name so the answer does not move."""
    members = ctx.families.families()
    shown = set(guilds)
    out, seen = [], set()
    for g in sorted(ctx.families.guilds(), key=lambda g: g["name"]):
        if g["name"] in shown and g["family"] in members and g["family"] not in seen:
            seen.add(g["family"])
            out.append((g["name"], g["family"], members[g["family"]]))
    return out


def _clip_rows(rd, keys: list) -> dict:
    """The ledger rows under `keys`, by key. A realm without the ledger table
    gives none, so the items it would link render without a link."""
    if not keys:
        return {}
    rows = rd.rows(
        _CLIPS_SQL.format(keys=_holes(len(keys))),  # noqa: S608 - placeholders from a COUNT, values bound
        tuple(keys),
        what="the Chronicle clips",
    )
    return {r["event_key"]: r for r in rows}


def build(rd, guilds: list, maps: dict, kin: list | None = None) -> dict:
    found = rd.must(_GUILDS_SQL.format(holes=_holes(len(guilds))), tuple(guilds))
    guild_of = {int(r["guildid"]): r["name"] for r in found}
    names = [r["name"] for r in found]
    items: list = []
    if guild_of:
        ids = list(guild_of)
        ih = _holes(len(ids))
        conts = ", ".join(str(c) for c in CONTINENTS)
        level_rows = rd.must(_LEVELS_SQL.format(holes=ih), (*ids, DAYS, MAX_ROWS))
        who = sorted({n for _g, _f, members in kin or [] for n in members})
        kills = (
            rd.rows(
                _KILLS_SQL.format(names=_holes(len(who))),  # noqa: S608 - placeholders from a COUNT, values bound
                (*who, MAX_ROWS),
                what="the Chronicle boss kills",
            )
            if who
            else []
        )
        keys = sorted(
            {
                clipledger.boss_key(k["subject_id"], family)
                for _g, family, members in kin or []
                for k in kills
                if k["character_name"] in members
            }
            | {
                clipledger.level_key(r["name"])
                for r in level_rows
                if int(r["level"]) == 60
            }
        )
        clips = _clip_rows(rd, keys)
        if kills:
            items += first_kill_items(kills, kin, clips, int(kills[0]["now"]))
        items += level_items(level_rows, guild_of, clips)
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
    payload = build(ctx.read, guilds, maps, _kin(ctx, guilds))
    if asked and not payload["guilds"]:
        return 404, {"error": "no such guild", "guild": asked}
    return 200, payload


ROUTES = {"/api/v2/chronicle": chronicle}
