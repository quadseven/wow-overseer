"""GET /api/v2/run?id=N: one guild run, whenever it ran.

/api/guildruns answers the groups out now and the thirty that came back last,
which is all the Runs tab draws. The chronicle and a run's own links name older
runs too, and a run page that only looked in that window said "Not found" for
every one of them. This reads the one run by id (guildrun.by_id), shaped
exactly as /api/guildruns shapes a run, with its story for an ended run.

`id` must be a positive integer of at most 10 digits, else 400 before any
query. An id the table does not hold is 404. Read-only, one bounded row.
"""

from __future__ import annotations

import datetime

import achievements
import dungeonpath
import guildrun

_EVENT_GEAR_SQL = (
    "SELECT character_name AS member, subject_id AS entry, subject_name AS name, "
    "subject_quality AS quality, kind, last_seen AS at FROM overseer_event "
    "WHERE character_name IN ({names}) AND map = %s AND kind IN "
    "('item_loot', 'item_equip') AND last_seen >= %s "
    "AND last_seen <= COALESCE(%s, NOW()) "
    "ORDER BY last_seen DESC LIMIT 500"
)
_COUNCIL_GEAR_SQL = (
    "SELECT recipient AS member, item_entry AS entry, item_name AS name, "
    "item_quality AS quality, outcome, given_at AS at FROM overseer_loot_council "
    "WHERE recipient IN ({names}) AND source = %s AND given_at >= %s "
    "AND given_at <= COALESCE(%s, NOW()) "
    "AND outcome IS NOT NULL ORDER BY given_at DESC LIMIT 200"
)


def _gear_item(row: dict, source: str) -> dict:
    return {
        "member": row["member"],
        "entry": int(row.get("entry") or 0),
        "name": row.get("name") or "",
        "quality": int(row.get("quality") or 0),
        "source": source,
        "at": str(row.get("at") or ""),
    }


def _event_gear(reader, members: list, holes: str, view: dict, map_id: int) -> list:
    rows = reader.rows(
        _EVENT_GEAR_SQL.format(names=holes),
        tuple(members) + (map_id, view["created_at"], view["ended_at"] or None),
        what="overseer_event",
    )
    # `.get`: a row without `kind` reads as a plain loot rather than raising
    # a KeyError into the handler.
    return [
        _gear_item(row, "equipped" if row.get("kind") == "item_equip" else "looted")
        for row in rows
    ]


def _council_gear(reader, members: list, holes: str, view: dict, keyword: str) -> list:
    rows = reader.rows(
        _COUNCIL_GEAR_SQL.format(names=holes),
        tuple(members) + (keyword, view["created_at"], view["ended_at"] or None),
        what="overseer_loot_council",
    )
    return [_gear_item(row, "won by loot council") for row in rows]


def _gear(reader, view: dict) -> list:
    """Merge the two source-specific gear reads for this run's seated members."""
    members = [member["name"] for member in view["members"]]
    if not members:
        return []
    # run_view always sets `keyword` (blank for NULL); `.get` keeps a bare
    # view safe too. A blank or unknown keyword has no map and so no gear,
    # which is why neither read below looks at view["keyword"] again.
    keyword = str(view.get("keyword") or "")
    map_id = dungeonpath.PORTAL_MAPS.get(keyword.lower())
    if map_id is None:
        return []
    holes = ", ".join(["%s"] * len(members))
    items = _event_gear(reader, members, holes, view, map_id)
    items.extend(_council_gear(reader, members, holes, view, keyword))
    return sorted(items, key=lambda item: item["at"], reverse=True)


# Boss kills for this run: the same overseer_event rows the progress count
# already uses, narrowed to the run's map and window.
_BOSS_KILLS_SQL = (
    "SELECT character_name AS member, subject_id AS entry, subject_name AS name, "
    "last_seen AS at FROM overseer_event "
    "WHERE character_name IN ({names}) AND map = %s AND kind = 'boss_kill' "
    "AND last_seen >= %s AND last_seen <= COALESCE(%s, NOW()) "
    "ORDER BY last_seen"
)
# Deaths inside the run, for spotting wipes on a boss.
_BOSS_DEATHS_SQL = (
    "SELECT character_name, killer_name, killer_entry, created_at "
    "FROM overseer_death "
    "WHERE character_name IN ({names}) AND map = %s "
    "AND created_at >= %s AND created_at <= COALESCE(%s, NOW()) "
    "ORDER BY created_at"
)
# Deaths this close together are one wipe event.
_WIPE_GAP_SECONDS = 60
# A wipe needs at least this many deaths in one cluster.
_WIPE_MIN_DEATHS = 2


def _map_id(view: dict) -> int | None:
    """The dungeon map id for this run's keyword, or None."""
    keyword = str(view.get("keyword") or "")
    return dungeonpath.PORTAL_MAPS.get(keyword.lower())


def _boss_creatures(map_id: int) -> list[tuple[int, str]]:
    """The ordered boss list for this dungeon, or [] when none is held."""
    entry = achievements.DUNGEONS.get(map_id) or {}
    return list(entry.get("bosses", []))


def _parse_time(value) -> datetime.datetime | None:
    """A database datetime as a Python datetime, or None."""
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None


def _boss_kills(reader, members: list, holes: str, view: dict, map_id: int) -> list:
    rows = reader.rows(
        _BOSS_KILLS_SQL.format(names=holes),
        tuple(members) + (map_id, view["created_at"], view["ended_at"] or None),
        what="overseer_event",
    )
    return [
        {
            "entry": int(row.get("entry") or 0),
            "name": str(row.get("name") or ""),
            "by": str(row.get("member") or ""),
            "at": _parse_time(row.get("at")),
        }
        for row in rows
    ]


def _death_rows(reader, members: list, holes: str, view: dict, map_id: int) -> list:
    rows = reader.rows(
        _BOSS_DEATHS_SQL.format(names=holes),
        tuple(members) + (map_id, view["created_at"], view["ended_at"] or None),
        what="overseer_death",
    )
    return [
        {
            "name": str(row.get("character_name") or ""),
            "killer": str(row.get("killer_name") or ""),
            "entry": int(row.get("killer_entry") or 0),
            "at": _parse_time(row.get("created_at")),
        }
        for row in rows
        if _parse_time(row.get("created_at")) is not None
    ]


def _wipe_clusters(deaths: list, boss_entries: set) -> list:
    """Clusters of deaths to a boss that read as wipes on that boss."""
    clusters: list = []
    current: list = []
    for d in deaths:
        if d["entry"] not in boss_entries:
            continue
        if (
            current
            and (d["at"] - current[-1]["at"]).total_seconds() > _WIPE_GAP_SECONDS
        ):
            if len(current) >= _WIPE_MIN_DEATHS:
                clusters.append(current)
            current = []
        current.append(d)
    if len(current) >= _WIPE_MIN_DEATHS:
        clusters.append(current)
    return clusters


def _wipes(
    reader, members: list, holes: str, view: dict, map_id: int, bosses: list
) -> list:
    """One entry per cluster where the group wiped on a boss."""
    boss_entries = {entry for entry, _ in bosses}
    deaths = _death_rows(reader, members, holes, view, map_id)
    clusters = _wipe_clusters(deaths, boss_entries)
    out = []
    for cluster in clusters:
        # The boss is the first death's killer; all deaths in a cluster are
        # to bosses, and the first sets the time on the timeline.
        first = cluster[0]
        out.append(
            {
                "entry": first["entry"],
                "name": first["killer"],
                "at": first["at"].isoformat(sep=" ", timespec="seconds"),
                "deaths": len(cluster),
            }
        )
    return out


def _bosses(reader, view: dict) -> tuple[list, list]:
    """The dungeon's bosses in order with kill state, plus wipe clusters.

    Returns (bosses, wipes). Either list is empty when the dungeon has no
    known boss list, the run has no seats, or the keyword has no map.
    """
    members = [member["name"] for member in view["members"]]
    if not members:
        return [], []
    map_id = _map_id(view)
    if map_id is None:
        return [], []
    bosses = _boss_creatures(map_id)
    if not bosses:
        return [], []
    holes = ", ".join(["%s"] * len(members))
    kills = _boss_kills(reader, members, holes, view, map_id)
    kill_by_entry = {k["entry"]: k for k in kills}
    out = []
    for entry, name in bosses:
        kill = kill_by_entry.get(entry)
        out.append(
            {
                "entry": entry,
                "name": name,
                "killed": kill is not None,
                "at": kill["at"].isoformat(sep=" ", timespec="seconds")
                if kill
                else None,
                "by": kill["by"] if kill else None,
            }
        )
    # Wipes are only read for ended runs: a run still out has not wiped yet.
    if view.get("state") != "ended":
        return out, []
    wipes = _wipes(reader, members, holes, view, map_id, bosses)
    return out, wipes


_ID_MAX_DIGITS = 10


def run_id(value: str) -> int | None:
    """`value` as a run id, or None when it is not one."""
    value = (value or "").strip()
    if (
        not value
        or len(value) > _ID_MAX_DIGITS
        or not value.isascii()
        or not value.isdigit()
    ):
        return None
    n = int(value)
    return n if n > 0 else None


def run(query: dict, ctx) -> tuple[int, dict]:
    wanted = run_id((query.get("id") or [""])[0])
    if wanted is None:
        return 400, {"error": "id must be a positive whole number"}
    view = guildrun.by_id(ctx.read, wanted)
    if view is None:
        return 404, {"error": "no such run", "id": wanted}
    view["gear"] = _gear(ctx.read, view)
    view["bosses"], view["wipes"] = _bosses(ctx.read, view)
    return 200, {"run": view}


ROUTES = {"/api/v2/run": run}
