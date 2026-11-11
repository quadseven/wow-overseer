"""The clip ledger: which events earn a clip request, as rows for overseer_clip.

Pure, like eventclips: rows in, rows out, no database and no clock reads. The
map server reads the realm, calls plan_requests, and writes what comes back.
The policy (what is major, how wide the window is, what retention keeps) stays
in eventclips; this module is the wiring around it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Iterable, Mapping
from urllib.parse import quote

import achievements
import eventclips

STATES = ("pending", "cutting", "ready", "no_view", "failed", "expired", "deleted")

# The request channel and the clip ledger. This module writes requests; the
# stream agent polls pending rows and writes the outcome back. event_key is
# unique, so a restarted scan cannot write an event twice.
DDL = (
    "CREATE TABLE IF NOT EXISTS overseer_clip ("
    " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,"
    " kind VARCHAR(16) NOT NULL,"
    " `character` VARCHAR(24) NOT NULL,"
    " stream_path VARCHAR(64) NOT NULL DEFAULT '',"
    " event_key VARCHAR(96) NOT NULL,"
    " event_at DATETIME NOT NULL,"
    " window_start DATETIME NOT NULL,"
    " window_end DATETIME NOT NULL,"
    " state VARCHAR(12) NOT NULL DEFAULT 'pending',"
    " file_name VARCHAR(128) NULL,"
    " detail TEXT NULL,"
    " created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
    " updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    "   ON UPDATE CURRENT_TIMESTAMP,"
    " UNIQUE KEY uq_event_key (event_key),"
    " KEY idx_state_window (state, window_end)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
)

LOOT_QUALITY_KEY = "subject_quality"
# overseer_event.first_seen is the module's flush time, so it trails the real
# event by up to one flush. The window starts that much earlier.
FLUSH_INTERVAL = timedelta(seconds=5)
# How much recent video the stream agent keeps; older events cannot be cut.
AGENT_BUFFER = timedelta(minutes=10)

# The Chronicle's own "earliest qualifying row" rule, so a first here is the
# same first the Chronicle shows.
earliest = achievements._earliest


def _request(key, kind, who, path_of, at, window, detail):
    start, end = window
    return {
        "event_key": key,
        "kind": kind,
        "character": who,
        "stream_path": path_of(who),
        "event_at": at,
        "window_start": start,
        "window_end": end,
        "state": "pending",
        "detail": detail,
    }


def _window(at, equip_at=None):
    return eventclips.clip_window(
        at, equip_at=equip_at, pre_roll=eventclips.PRE_ROLL + FLUSH_INTERVAL
    )


def _equip_at(loot_row, rows):
    """The first equip of this exact item by this character, or None."""
    guid = loot_row.get("item_guid")
    if not guid:
        return None
    seen = [
        r["first_seen"]
        for r in rows
        if r.get("kind") == "item_equip"
        and r.get("item_guid") == guid
        and r.get("character_name") == loot_row["character_name"]
        and r["first_seen"] >= loot_row["first_seen"]
    ]
    return min(seen) if seen else None


def _loot_requests(rows, guilds, now, path_of):
    out = []
    for row in rows:
        if row.get("kind") != "item_loot":
            continue
        member = row.get("guild") in guilds
        kind = eventclips.trigger_kind(
            {
                "kind": "item_loot",
                "family_member": member,
                "family_guild": member,
                "quality": row.get(LOOT_QUALITY_KEY),
            }
        )
        if kind is None:
            continue
        at = row["first_seen"]
        equip = _equip_at(row, rows)
        if equip is None and now < at + eventclips.EQUIP_WAIT:
            continue  # the window end is not known yet
        out.append(
            _request(
                "loot:%s" % row["id"],
                kind,
                row["character_name"],
                path_of,
                at,
                _window(at, equip),
                row.get("subject_name") or "",
            )
        )
    return out


def _first_kills(rows, roster):
    """The earliest family kill of each boss."""
    by_boss = {}
    for r in rows:
        if r.get("kind") == "boss_kill" and r["character_name"] in roster:
            by_boss.setdefault(r["subject_id"], []).append(r)
    return [earliest(group, "first_seen") for group in by_boss.values()]


def _event_requests(rows, roster, path_of):
    out = []
    for row in _first_kills(rows, roster):
        at = row["first_seen"]
        kind = eventclips.trigger_kind(
            {"kind": "boss_kill", "family_member": True, "first_kill": True}
        )
        out.append(
            _request(
                "boss_kill:%s" % row["subject_id"],
                kind,
                row["character_name"],
                path_of,
                at,
                _window(at),
                row.get("subject_name") or "",
            )
        )
    for row in rows:
        if row.get("kind") != "level_up" or row["character_name"] not in roster:
            continue
        kind = eventclips.trigger_kind(
            {"kind": "level_up", "family_member": True, "level": row.get("level")}
        )
        if kind is None:
            continue
        at = row["first_seen"]
        who = row["character_name"]
        out.append(
            _request("%s:%s" % (kind, who), kind, who, path_of, at, _window(at), "")
        )
    return out


def _clear_requests(runs, roster, path_of):
    out = []
    by_map = {}
    for run in runs:
        by_map.setdefault(run["map_id"], []).append(run)
    for map_id, group in by_map.items():
        run = earliest(group, "at")
        if run["leader"] not in roster:
            continue
        kind = eventclips.trigger_kind(
            {"kind": "clear", "family_member": True, "first_clear": True}
        )
        out.append(
            _request(
                "clear:%s" % map_id,
                kind,
                run["leader"],
                path_of,
                run["at"],
                _window(run["at"]),
                run.get("dungeon") or "",
            )
        )
    return out


def expired_ids(
    rows: Iterable[Mapping],
    *,
    now: datetime,
    max_age: timedelta = eventclips.MAX_AGE,
    max_count: int = eventclips.MAX_CLIPS,
) -> list:
    """Ids of ready ledger rows that fall outside the retention bounds.

    Marks only: the caller sets state to expired. No file is deleted here or
    there. Rows in any other state hold no saved clip, so they neither count
    toward the cap nor expire.
    """
    ready = [
        {"id": r["id"], "saved_at": r["created_at"]}
        for r in rows
        if r.get("state") == "ready"
    ]
    kept = {
        c["id"]
        for c in eventclips.retain(ready, now=now, max_age=max_age, max_count=max_count)
    }
    return [c["id"] for c in ready if c["id"] not in kept]


def plan_requests(
    *,
    loot_rows: Iterable[Mapping],
    event_rows: Iterable[Mapping],
    cleared_runs: Iterable[Mapping],
    family_guilds: Iterable[str],
    roster: Iterable[str],
    now: datetime,
    existing_keys: Iterable[str],
    path_of: Callable[[str], str],
) -> list[dict]:
    """The ledger rows to insert now, oldest event first."""
    guilds = frozenset(family_guilds)
    names = frozenset(roster)
    rows = _loot_requests(list(loot_rows), guilds, now, path_of)
    rows += _event_requests(list(event_rows), names, path_of)
    rows += _clear_requests(list(cleared_runs), names, path_of)
    rows.sort(key=lambda r: r["event_at"])
    seen = set(existing_keys)
    out = []
    for row in rows:
        if row["event_key"] in seen:
            continue
        # Footage older than the agent's buffer no longer exists to be cut.
        if row["window_start"] < now - AGENT_BUFFER:
            continue
        seen.add(row["event_key"])
        if not row["stream_path"]:
            row["state"] = "no_view"
        out.append(row)
    return out


# --- timing out rows the agent never finished ----------------------------

# The agent keeps AGENT_BUFFER of video; a pending row this long past its window
# end can no longer be cut, so it is declared no_view (buffer plus 5 minutes).
PENDING_TIMEOUT = timedelta(minutes=15)
# A cutting row nobody has touched for this long lost its agent mid-cut.
CUTTING_TIMEOUT = timedelta(hours=1)
CUTTING_FAILED_DETAIL = "cutting timed out after an hour"

_STALE_SELECT = (
    "SELECT id, state, window_end, updated_at FROM overseer_clip"
    " WHERE state IN ('pending', 'cutting')"
)
# Each update names the state it replaces, so a row the agent moved on since
# the read (ready, failed, ...) matches nothing and is left alone.
_TO_NO_VIEW = "UPDATE overseer_clip SET state = %s WHERE id = %s AND state = %s"
_TO_FAILED = (
    "UPDATE overseer_clip SET state = %s, detail = %s WHERE id = %s AND state = %s"
)


def stale_changes(rows: Iterable[Mapping], *, now: datetime) -> list[dict]:
    """The state changes owed to rows that sat too long: pending past its
    window end by more than PENDING_TIMEOUT becomes no_view; cutting not
    updated for more than CUTTING_TIMEOUT becomes failed, with a detail."""
    out = []
    for r in rows:
        if r.get("state") == "pending" and r["window_end"] < now - PENDING_TIMEOUT:
            out.append(
                {"id": r["id"], "from": "pending", "to": "no_view", "detail": None}
            )
        elif r.get("state") == "cutting" and r["updated_at"] < now - CUTTING_TIMEOUT:
            out.append(
                {
                    "id": r["id"],
                    "from": "cutting",
                    "to": "failed",
                    "detail": CUTTING_FAILED_DETAIL,
                }
            )
    return out


def time_out(cur, *, now: datetime) -> dict:
    """Read the in-flight rows and time out the stale ones through `cur`.

    Returns how many rows each change actually took (a conditional update that
    matched nothing is not counted)."""
    cur.execute(_STALE_SELECT)
    counts = {"no_view": 0, "failed": 0}
    for change in stale_changes(cur.fetchall(), now=now):
        if change["detail"] is None:
            cur.execute(_TO_NO_VIEW, (change["to"], change["id"], change["from"]))
        else:
            cur.execute(
                _TO_FAILED,
                (change["to"], change["detail"], change["id"], change["from"]),
            )
        counts[change["to"]] += 1 if cur.rowcount else 0
    return counts


# --- reading the ledger back out: the shelf and the story links ----------

CLIPS_PATH = "/clips/"
NO_VIEW_LINE = "No live view was up, so no clip was saved."
SHELF_EMPTY = "No clips have been saved yet."
SHELF_LIMIT = 100


def clip_url(file_name: str) -> str:
    """The path a saved clip is served at, mount-relative (the page adds the
    mount). The name is quoted, so a stored name cannot add a path segment."""
    return CLIPS_PATH + quote(file_name, safe="")


def _iso(t) -> str | None:
    return t.isoformat() if isinstance(t, datetime) else (t or None)


def shelf(rows: Iterable[Mapping]) -> dict:
    """The /api/clips payload: ready rows with a file, newest event first."""
    ready = [r for r in rows if r.get("state") == "ready" and r.get("file_name")]
    ready.sort(
        key=lambda r: (str(_iso(r.get("event_at")) or ""), r["id"]), reverse=True
    )
    return {
        "clips": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "character": r["character"],
                "at": _iso(r.get("event_at")),
                "url": clip_url(r["file_name"]),
            }
            for r in ready[:SHELF_LIMIT]
        ],
        "empty": SHELF_EMPTY,
    }


def link(row: Mapping | None) -> dict:
    """What a story or timeline entry adds for its event's ledger row.

    A ready row with a file adds `clip` (url and kind). A no_view row adds
    `clip_note`, saying no live view was up. Any other state, or no row at
    all, adds nothing: the entry says nothing about clips.
    """
    if not row:
        return {}
    if row.get("state") == "ready" and row.get("file_name"):
        return {"clip": {"url": clip_url(row["file_name"]), "kind": row["kind"]}}
    if row.get("state") == "no_view":
        return {"clip_note": NO_VIEW_LINE}
    return {}
