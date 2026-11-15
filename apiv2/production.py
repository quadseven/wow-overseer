"""GET /api/v2/production: per family member, is its job producing?

One row per roster member of the families: job, each profession and its skill
now, last craft time, last skill gain time, last gather time, whether the job
made something in the last six hours, and a one-line `stuck_because`. The
rules, and what each time means, are production.py's header. Nothing from the
request reaches the SQL: the read takes no parameter. Read-only.

A time is Unix seconds, or null when nothing measured it. `measured` is false
for a member the bridge has not yet watched, whose skill gain and gather times
are then unknown rather than old.
"""

from __future__ import annotations

import json

import goals
import production

from ._scope import holes

ROSTER_SQL = (
    "SELECT name, family, job, craft_spell, enabled FROM overseer_roster "
    "WHERE name IN ({holes}) ORDER BY family, `lead` DESC, name"
)
SKILLS_SQL = (
    "SELECT c.name, k.skill, k.value, k.max FROM character_skills k "
    "JOIN characters c ON c.guid = k.guid "
    "WHERE c.name IN ({holes}) AND k.skill IN ({skills})"
)
EVENTS_SQL = (
    "SELECT character_name AS name, kind, subject_name, detail, "
    "UNIX_TIMESTAMP(last_seen) AS at FROM overseer_event "
    "WHERE character_name IN ({holes}) "
    "AND kind IN ('craft', 'craft-deferred', 'material-request') "
    "AND last_seen > NOW() - INTERVAL 7 DAY ORDER BY last_seen"
)
MEMO_SQL = (
    "SELECT subject AS name, value FROM overseer_bridge_memo "
    "WHERE kind = %s AND expires > UNIX_TIMESTAMP()"
)
CLOCK_SQL = "SELECT UNIX_TIMESTAMP() AS now_at"

_NAMES = {number: name for name, number in goals.SKILL_IDS.items()}


def _skills(rows: list) -> dict:
    out: dict = {}
    for row in rows:
        name = _NAMES.get(int(row["skill"]))
        if name:
            out.setdefault(row["name"], {})[name] = (
                int(row["value"] or 0),
                int(row["max"] or 0),
            )
    return out


def _events(rows: list) -> dict:
    """name -> the newest craft time and the newest request and deferral rows.
    The rows arrive oldest first, so a later one overwrites an earlier one."""
    out: dict = {}
    for row in rows:
        seen = out.setdefault(row["name"], {})
        at = int(row["at"] or 0)
        if row["kind"] == "craft":
            seen["craft"] = at
            continue
        key = "deferred" if row["kind"] == "craft-deferred" else "request"
        seen[key] = {
            "at": at,
            "subject": str(row.get("subject_name") or ""),
            "detail": str(row.get("detail") or ""),
        }
    return out


def _memos(rows: list) -> dict:
    out: dict = {}
    for row in rows:
        try:
            value = json.loads(row["value"])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            out[row["name"]] = value
    return out


def fetch(ctx) -> dict:
    rd = ctx.read
    names = list(ctx.families.names())
    if not names:
        return {"members": [], "skills": {}, "events": {}, "memos": {}, "now_at": 0}
    h = holes(len(names))
    ids = sorted(goals.SKILL_IDS.values())
    clock = rd.must(CLOCK_SQL)
    return {
        "members": rd.rows(
            ROSTER_SQL.format(holes=h), tuple(names), what="overseer_roster"
        ),
        "skills": _skills(
            rd.rows(
                SKILLS_SQL.format(holes=h, skills=holes(len(ids))),
                (*names, *ids),
                what="character_skills",
            )
        ),
        "events": _events(
            rd.rows(EVENTS_SQL.format(holes=h), tuple(names), what="overseer_event")
        ),
        "memos": _memos(
            rd.rows(MEMO_SQL, (production.MEMO_KIND,), what="overseer_bridge_memo")
        ),
        "now_at": int(clock[0]["now_at"]) if clock else 0,
    }


def view(found: dict) -> dict:
    now = found["now_at"]
    return {
        "checked_at": now,
        "window_seconds": production.PRODUCING_SECONDS,
        "members": production.build(
            found["members"], found["skills"], found["events"], found["memos"], now
        ),
    }


def production_report(_query: dict, ctx) -> tuple[int, dict]:
    """GET /api/v2/production: per member, job, last craft, skill gain, gather."""
    return 200, view(fetch(ctx))


ROUTES = {"/api/v2/production": production_report}
