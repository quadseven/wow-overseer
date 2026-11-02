"""GET /api/v2/gear/changes?since=&member=&guild= - recent loot and equips."""

from __future__ import annotations

import datetime

CHANGES_SQL = (
    "SELECT e.character_name AS member_name, COALESCE(g.name, '') AS guild, "
    "e.kind, e.subject_id AS entry, e.subject_name AS item, e.subject_quality AS quality, "
    "e.subject_item_level AS item_level, e.prior_state, "
    "e.prior_id AS prior_entry, e.prior_name AS prior_item, e.prior_quality, e.prior_item_level, "
    "e.last_seen AS at FROM overseer_event e "
    "LEFT JOIN characters c ON c.name = e.character_name "
    "LEFT JOIN guild_member gm ON gm.guid = c.guid "
    "LEFT JOIN guild g ON g.guildid = gm.guildid "
    "WHERE e.kind IN ('item_loot', 'item_equip') AND e.last_seen > %s "
    "AND (%s = '' OR e.character_name = %s) "
    "AND (%s = '' OR g.name = %s) "
    "ORDER BY e.last_seen DESC, e.id DESC LIMIT 500"
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


def gear_changes(query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/gear/changes?since=&member=&guild= - recent loot and equips."""
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
    rows = ctx.read.rows(
        CHANGES_SQL,
        (since, member_raw, member_raw, guild_raw, guild_raw),
        what="overseer_event",
    )
    member, guild = member_raw.casefold(), guild_raw.casefold()
    changes = [_change(row) for row in rows or ()]
    if member:
        changes = [row for row in changes if row["character"].casefold() == member]
    if guild:
        changes = [row for row in changes if row["guild"].casefold() == guild]
    return 200, {"changes": changes[:500]}


ROUTES = {"/api/v2/gear/changes": gear_changes}
