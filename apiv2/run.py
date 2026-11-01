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


# Boss kills for this run: overseer_event rows of kind 'boss_kill' (subject_id
# the boss's creature entry, character_name who landed the killing blow),
# narrowed to the run's map and window. THE MODULE WRITES THIS ONLY FOR A ROSTER
# KILLER (RecordBossKill), so a guild run usually holds few or none of these
# rows, which _bosses below answers as "not recorded" rather than "alive"
# (#1130).
_BOSS_KILLS_SQL = (
    "SELECT character_name AS member, subject_id AS entry, subject_name AS name, "
    "last_seen AS at FROM overseer_event "
    "WHERE character_name IN ({names}) AND map = %s AND kind = 'boss_kill' "
    "AND last_seen >= %s AND last_seen <= COALESCE(%s, NOW()) "
    "ORDER BY last_seen"
)
# The dungeon's bosses off the world database (#1130): the kill-credit rows of
# instance_encounters, which are the encounters the module counts into
# bosses_total, named by creature_template. `{ids}` is sized by ENCOUNTER_IDS.
_BOSS_LIST_SQL = (
    "SELECT ie.entry AS encounter, ie.creditEntry AS entry, ct.name AS name "
    "FROM acore_world.instance_encounters ie "
    "JOIN acore_world.creature_template ct ON ct.entry = ie.creditEntry "
    "WHERE ie.creditType = 0 AND ie.entry IN ({ids}) ORDER BY ie.entry"
)
# WHICH ENCOUNTERS ARE WHICH DUNGEON'S, by map id. instance_encounters.entry is
# a DungeonEncounter.dbc id and the map an encounter belongs to lives only in
# that client file (acore_world.dungeonencounter_dbc is empty here, see
# agenda.ENCOUNTERS), so the ids are frozen. They are the pinned core's own
# instance_encounters rows for each map: each block runs up to the row whose
# lastEncounterDungeon marks the dungeon's final boss, and every credit
# creature in a block that has a spawn stands on that map. Sneed (162) and
# Mutanus (592) are summoned, not spawned, which is why a join through
# acore_world.creature cannot stand in for this table. The Deadmines' block is
# the seven rows agenda.ENCOUNTERS measured on wow-dev.
#
# ONE DOOR PER MAP ONLY. Scarlet Monastery (189), Stratholme (329), Maraudon
# (349), Dire Maul (429) and Blackrock Spire (229) are wings on one map, and a
# wing run would be shown the other wings' bosses as not killed; they keep the
# empty list until a run knows its wing's encounters.
ENCOUNTER_IDS = {
    36: tuple(range(161, 168)),  # The Deadmines
    43: tuple(range(585, 593)),  # Wailing Caverns
    389: tuple(range(430, 434)),  # Ragefire Chasm
    33: tuple(range(464, 472)),  # Shadowfang Keep
    34: tuple(range(536, 541)),  # The Stockade
    48: tuple(range(219, 227)),  # Blackfathom Deeps
    47: tuple(range(438, 444)) + (883,),  # Razorfen Kraul; 883 is Agathelos
    129: tuple(range(434, 438)),  # Razorfen Downs
    90: tuple(range(378, 383)),  # Gnomeregan
    70: tuple(range(547, 555)),  # Uldaman
    209: tuple(range(593, 601)),  # Zul'Farrak
    109: tuple(range(485, 494)),  # Sunken Temple
    230: tuple(range(227, 246)),  # Blackrock Depths
    289: tuple(range(451, 464)),  # Scholomance
}
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


def _frozen_bosses(map_id: int) -> list[tuple[int, str]]:
    """achievements.DUNGEONS' (creature entry, name) pairs for this map, or []."""
    entry = achievements.DUNGEONS.get(map_id) or {}
    return list(entry.get("bosses", []))


def _boss_creatures(reader, map_id: int) -> list[tuple[int, str]]:
    """The dungeon's bosses as (creature entry, name), in encounter order.

    Read from the world database for a map ENCOUNTER_IDS knows. A map it does
    not know, or a world without the tables (the read answers no rows), falls
    back to achievements.DUNGEONS, which is [] for most maps.
    """
    ids = ENCOUNTER_IDS.get(map_id)
    if ids:
        rows = reader.rows(
            _BOSS_LIST_SQL.format(ids=", ".join(["%s"] * len(ids))),
            tuple(ids),
            what="instance_encounters",
        )
        found = [
            (int(row["entry"]), str(row.get("name") or ""))
            for row in rows
            if row.get("entry")
        ]
        if found:
            return found
    return _frozen_bosses(map_id)


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
    """One entry per cluster where the group wiped on a boss.

    A boss is any creature in the listed bosses or in achievements.DUNGEONS
    for the map: Sneed's Shredder kills a party as Sneed's encounter and holds
    no credit row of its own.
    """
    boss_entries = {entry for entry, _ in bosses}
    boss_entries |= {entry for entry, _ in _frozen_bosses(map_id)}
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

    THE LIST IS LEFT EMPTY WHEN THE KILL ROWS DO NOT ACCOUNT FOR THE RUN'S
    COUNT (#1130). bosses_done is the module's own count; a boss it counted
    that no kill row names was killed all the same, so listing it as not
    killed would be false, and a cleared run read as every boss alive. An
    empty list is what a realm missing the rows answers, and the page then
    draws its counted bar. Wipes are told either way.
    """
    members = [member["name"] for member in view["members"]]
    if not members:
        return [], []
    map_id = _map_id(view)
    if map_id is None:
        return [], []
    bosses = _boss_creatures(reader, map_id)
    if not bosses:
        return [], []
    holes = ", ".join(["%s"] * len(members))
    kills = _boss_kills(reader, members, holes, view, map_id)
    kill_by_entry = {k["entry"]: k for k in kills}
    out = []
    for entry, name in bosses:
        kill = kill_by_entry.get(entry)
        at = kill["at"] if kill else None
        out.append(
            {
                "entry": entry,
                "name": name,
                "killed": kill is not None,
                # A kill row whose time did not parse is still a kill.
                "at": at.isoformat(sep=" ", timespec="seconds") if at else None,
                "by": kill["by"] if kill else None,
            }
        )
    killed = sum(1 for boss in out if boss["killed"])
    # A cleared run's last boss is down whatever its count says, so a cleared
    # run with no kill row at all is also one the rows do not account for.
    cleared_unrecorded = view.get("outcome") == guildrun.CLEARED and not killed
    if killed < int(view.get("bosses_done") or 0) or cleared_unrecorded:
        out = []
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
