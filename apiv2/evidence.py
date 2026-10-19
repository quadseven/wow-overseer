"""GET /api/v2/evidence?name=X&map_id=N&since=D&limit=N - fixed, named read-only questions an agent proves a ticket with.

    {name, params: {...}, rows: [{...}], count, capped}

An agent checking a shipped ticket needs one fixed fact from the realm, such
as the runs on one dungeon since a date or the guild materials letters nobody
has opened. Without this route that fact meant SQL typed into a shell against
the database. Here each question is an entry in QUERIES: fixed SQL that only
reads, the parameters it takes and how each is checked, and a row cap.

THE REQUEST IS CHECKED WHOLE BEFORE ANY SQL RUNS. An unknown `name` is 404
with the list of names. A missing parameter, a value that fails its check, a
parameter the query does not take, or a parameter given twice is 400. Nothing
from the request reaches a statement except as a bound value that has already
passed its check, so no request can change what SQL runs.

`capped` is true when the query had more rows than it returns: the answer is
then the newest `limit` rows, not all of them.

A REALM WITHOUT THE TABLE IS 409, NOT AN EMPTY ANSWER. Evidence that reads
"no rows" must mean the realm has none; a module table the realm predates is
said out loud instead. A query with a thinner statement (`dungeon_runs` on a
realm without the `outcome` column) answers through it first.

Read-only, like every route under /api/v2.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Callable

import realmread

MAX_ROWS = 200
DEFAULT_ROWS = 50

# The subject guildjobs.POST_SUBJECT gives every guild materials letter. A
# literal here so the map server does not import the bridge's job module; a
# test fails if the two ever differ.
GUILD_MATERIALS_SUBJECT = "Guild materials"
# mail.checked is a bit mask; bit 0 is MAIL_CHECK_MASK_READ in the core
# (holdings.MAIL_READ reads the same bit).
MAIL_READ = 1

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?")
_INT = re.compile(r"\d{1,10}")


class Refused(ValueError):
    """A request this route will not run: answered 400 with the reason."""


def _int_in(low: int, high: int) -> Callable[[str], int]:
    def check(raw: str) -> int:
        if not _INT.fullmatch(raw):
            raise Refused("must be a whole number")
        value = int(raw)
        if not low <= value <= high:
            raise Refused(f"must be from {low} to {high}")
        return value

    return check


def _since(raw: str) -> str:
    """An ISO date or date and time, as MySQL's 'YYYY-MM-DD HH:MM:SS'."""
    if not _DATE.fullmatch(raw):
        raise Refused("must be YYYY-MM-DD or YYYY-MM-DDTHH:MM[:SS]")
    try:
        when = datetime.datetime.fromisoformat(raw)
    except ValueError:
        raise Refused("is not a real date") from None
    return when.strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class Param:
    check: Callable[[str], object]
    default: str | None = None  # None: the request must give it


@dataclass(frozen=True)
class Query:
    """One named question: its SQL, its parameters in the order the SQL binds
    them, and an optional thinner SQL for a realm missing a newer column."""

    sql: str
    params: tuple
    takes: dict
    what: str
    fallback: str = ""
    about: str = ""


DUNGEON_RUNS_SQL = (
    "SELECT id, leader_name, map_id, state, outcome, ended_reason, "
    "started_at, ended_at FROM overseer_dungeon_run "
    "WHERE map_id = %s AND started_at >= %s "
    "ORDER BY started_at DESC, id DESC LIMIT %s"
)
# A realm whose module predates the run accounting has no `outcome` column.
DUNGEON_RUNS_THIN_SQL = (
    "SELECT id, leader_name, map_id, state, ended_reason, "
    "started_at, ended_at FROM overseer_dungeon_run "
    "WHERE map_id = %s AND started_at >= %s "
    "ORDER BY started_at DESC, id DESC LIMIT %s"
)
GUILD_MATERIALS_SQL = (
    "SELECT c.name AS recipient, COUNT(*) AS letters, "
    "SUM(m.deliver_time <= UNIX_TIMESTAMP()) AS delivered "
    "FROM mail m JOIN characters c ON c.guid = m.receiver "
    "WHERE m.subject = %s AND (m.checked & %s) = 0 "
    "GROUP BY c.name ORDER BY letters DESC, recipient LIMIT %s"
)

QUERIES = {
    "dungeon_runs": Query(
        sql=DUNGEON_RUNS_SQL,
        fallback=DUNGEON_RUNS_THIN_SQL,
        params=("map_id", "since", "limit"),
        takes={
            "map_id": Param(_int_in(0, 65535)),
            "since": Param(_since),
            "limit": Param(_int_in(1, MAX_ROWS), str(DEFAULT_ROWS)),
        },
        what="overseer_dungeon_run",
        about="runs on one map started at or after `since`, newest first",
    ),
    "guild_materials_unopened": Query(
        sql=GUILD_MATERIALS_SQL,
        params=("subject", "read_bit", "limit"),
        takes={},
        what="mail",
        about="per recipient, unread guild materials letters and how many are delivered",
    ),
}

# Values a query binds that no request supplies.
_FIXED = {"subject": GUILD_MATERIALS_SUBJECT, "read_bit": MAIL_READ}


def _single(query: dict, key: str) -> str:
    values = query.get(key) or []
    if len(values) != 1:
        raise Refused(f"`{key}` must be given exactly once")
    return values[0]


def checked(entry: Query, query: dict) -> dict:
    """The request's parameters, each checked, or Refused."""
    extra = sorted(set(query) - set(entry.takes) - {"name"})
    if extra:
        raise Refused("unexpected parameter: " + ", ".join(extra))
    out = {}
    for key, param in entry.takes.items():
        if key not in query:
            if param.default is None:
                raise Refused(f"`{key}` is required")
            raw = param.default
        else:
            raw = _single(query, key)
        try:
            out[key] = param.check(raw)
        except Refused as why:
            raise Refused(f"`{key}` {why}") from None
    return out


def _plain(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def evidence(query: dict, ctx) -> tuple[int, dict]:
    """One named read-only question, checked whole before any SQL runs."""
    try:
        name = _single(query, "name")
    except Refused as why:
        return 400, {"error": str(why), "names": sorted(QUERIES)}
    entry = QUERIES.get(name)
    if entry is None:
        return 404, {"error": "no such query", "names": sorted(QUERIES)}
    try:
        params = checked(entry, query)
    except Refused as why:
        return 400, {"error": str(why), "takes": sorted(entry.takes)}
    limit = params.get("limit", MAX_ROWS)
    bound = {**_FIXED, **params, "limit": limit + 1}
    values = tuple(bound[key] for key in entry.params)
    rows = None
    for sql in (entry.sql, entry.fallback):
        if not sql:
            continue
        try:
            rows = ctx.read.must(sql, values)
            break
        except realmread.Gap:
            continue
    if rows is None:
        return 409, {"error": f"this realm has no {entry.what} to read", "name": name}
    kept = [{k: _plain(v) for k, v in dict(row).items()} for row in rows[:limit]]
    return 200, {
        "name": name,
        "about": entry.about,
        "params": {k: _plain(v) for k, v in params.items()},
        "rows": kept,
        "count": len(kept),
        "capped": len(rows) > limit,
    }


ROUTES = {"/api/v2/evidence": evidence}
