"""Recent loot and equipment changes."""

from __future__ import annotations

import datetime

CHANGE_LIMIT = 500
_COLUMNS = (
    "SELECT e.id AS event_id, e.occurrences, e.character_name AS member_name, "
    "COALESCE(g.name, '') AS guild, "
    "e.kind, e.subject_id AS entry, e.subject_name AS item, e.subject_quality AS quality, "
    "e.subject_item_level AS item_level, e.prior_state, "
    "e.prior_id AS prior_entry, e.prior_name AS prior_item, e.prior_quality, e.prior_item_level, "
    "e.last_seen AS at"
)
_SCOPED = (
    " FROM overseer_event e "
    "LEFT JOIN characters c ON c.name = e.character_name "
    "LEFT JOIN guild_member gm ON gm.guid = c.guid "
    "LEFT JOIN guild g ON g.guildid = gm.guildid "
    "WHERE e.kind IN ('item_loot', 'item_equip') AND e.last_seen {operator} %s "
    "AND (%s = '' OR e.character_name = %s) "
    "AND (%s = '' OR g.name = %s) "
)


def _changes_sql(operator, order, boundary=0):
    return (
        _COLUMNS
        + f", {boundary} AS boundary_row"
        + _SCOPED.format(operator=operator)
        + f"ORDER BY e.last_seen {order}, e.id {order} LIMIT {CHANGE_LIMIT + 1}"
    )


CHANGES_SQL = _changes_sql(">", "DESC")
BOUNDARY_SQL = _changes_sql(">=", "DESC")
OLDEST_SQL = _changes_sql(">", "ASC")
# Independently cap both scans in one snapshot. Otherwise a complete boundary
# can starve newer rows or an update can land between two autocommitted reads.
OLDEST_BOUNDARY_SQL = (
    f"({_changes_sql('=', 'ASC', boundary=1)}) UNION ALL ({OLDEST_SQL}) "
    "ORDER BY at, event_id"
)


def _one(query: dict, key: str) -> str:
    return str((query.get(key) or [""])[0]).strip()


def _when(value):
    return value.isoformat(sep=" ") if hasattr(value, "isoformat") else str(value)


def _change(row: dict) -> dict:
    kind = "worn" if row.get("kind") == "item_equip" else "looted"
    state = str(row.get("prior_state") or "")
    replaced = (
        str(row.get("prior_item") or "")
        if state == "item"
        else ("was empty" if state == "empty" else "not recorded")
    )
    level = int(row.get("item_level") or 0)
    prior = int(row.get("prior_item_level") or 0) if state == "item" else None
    return {
        "event_id": str(row.get("event_id") or ""),
        "occurrences": int(row.get("occurrences") or 0),
        "character": str(row.get("member_name") or ""),
        "guild": str(row.get("guild") or ""),
        "kind": kind,
        "entry": int(row.get("entry") or 0),
        "item": str(row.get("item") or ""),
        "quality": int(row.get("quality") or 0),
        "item_level": level,
        "replaced": replaced,
        "prior_entry": int(row.get("prior_entry") or 0) if state == "item" else None,
        "prior_quality": int(row.get("prior_quality") or 0)
        if state == "item"
        else None,
        "prior_item_level": prior,
        "item_level_change": level - prior if prior is not None else None,
        "at": _when(row.get("at")),
    }


def _oldest_batch(rows):
    """Bound the inclusive cursor cohort and the forward page independently."""
    boundary_count = sum(bool(row.get("boundary_row")) for row in rows)
    if boundary_count > CHANGE_LIMIT:
        return rows[:CHANGE_LIMIT], True, None
    end = boundary_count + CHANGE_LIMIT
    if len(rows) <= end:
        return rows, False, None
    shown = rows[:end]
    split_at = rows[end].get("at")
    complete_at = next(
        (row.get("at") for row in reversed(shown) if row.get("at") != split_at),
        None,
    )
    return shown, True, _when(complete_at) if complete_at is not None else None


def gear_changes(query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/gear/changes?since=&member=&guild=&oldest_first=&include_boundary= -
    recent loot and equips with event revisions and an optional acknowledgment
    batch that reports its latest complete timestamp.

    The default returns the newest 500 rows after the required ``since``.
    ``oldest_first=1`` returns the oldest 500 forward rows. With
    ``include_boundary=1`` it also returns up to 500 rows at ``since`` in the
    same database snapshot. Each row has a string ``event_id`` and an
    ``occurrences`` revision. A capped oldest-first read reports ``limited``
    and ``complete_through``, which is null if no timestamp is safe to
    acknowledge.
    """
    raw_since = _one(query, "since")
    if not raw_since:
        return 400, {"error": "since is required as an ISO time"}
    try:
        since = datetime.datetime.fromisoformat(raw_since.replace("Z", "+00:00"))
    except ValueError:
        return 400, {"error": "since must be an ISO time"}
    if since.tzinfo is not None:
        since = since.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    member_raw, guild_raw = _one(query, "member"), _one(query, "guild")
    include_boundary = _one(query, "include_boundary") == "1"
    oldest_first = _one(query, "oldest_first") == "1"
    params = (since, member_raw, member_raw, guild_raw, guild_raw)
    if oldest_first:
        sql = OLDEST_BOUNDARY_SQL if include_boundary else OLDEST_SQL
        if include_boundary:
            params *= 2
    else:
        sql = BOUNDARY_SQL if include_boundary else CHANGES_SQL
    rows = ctx.read.rows(sql, params, what="overseer_event") or []
    complete_through = None
    if oldest_first:
        rows, limited, complete_through = _oldest_batch(rows)
    else:
        limited = len(rows) > CHANGE_LIMIT
        rows = rows[:CHANGE_LIMIT]
    member, guild = member_raw.casefold(), guild_raw.casefold()
    changes = [_change(row) for row in rows]
    if member:
        changes = [row for row in changes if row["character"].casefold() == member]
    if guild:
        changes = [row for row in changes if row["guild"].casefold() == guild]
    payload = {"changes": changes, "limited": limited}
    if oldest_first:
        payload["complete_through"] = complete_through
    return 200, payload


ROUTES = {"/api/v2/gear/changes": gear_changes}
