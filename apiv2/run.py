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

import guildrun
import dungeonpath

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
    return 200, {"run": view}


ROUTES = {"/api/v2/run": run}
