"""Retire the factory-made random bots, a few rows a pass (2026-10-05).

WHY. mod-playerbots' old pre-levelling default made random-bot characters at
levels nobody on the realm reached naturally. The operator chose to retire them
(delete them); the factory death knights stay. The delete is mod-overseer's
`retire` verb (a kind='job' row whose command is `retire`), which calls the
core's own Player::DeleteFromDB and refuses anyone the rules below would not
pick. This module only decides which names to ask for, and how fast.

WHO. Exactly the module's own rules, read with one read-only query: a character
on a random-bot account (RNDBOT...), not a death knight, at level 42 or above
(the realm's highest natural level is 41), not in Cave or Bonkers, and not on
the roster. The module asks every rule again before it deletes, so this query
is a shortlist, not the authority.

PACE. A few rows per pass, never a second row for a name already in flight,
and a name whose row was refused waits REFUSED_BACKOFF_MINUTES before it is
asked again, so a slow worldserver is not flooded and a standing refusal is
not asked every pass.

PURE: plain values in, names and lines out.
"""

from __future__ import annotations

import math

SOURCE = "retire"
COMMAND = "retire"
ROWS_PER_PASS = 10
CYCLE_SECONDS = 120
MIN_LEVEL = 42
DEATH_KNIGHT = 6
KEPT_GUILDS = ("Cave", "Bonkers")
ACCOUNT_PREFIX = "RNDBOT"
REFUSED_BACKOFF_MINUTES = 30

# READ-ONLY. The eligible names, oldest character first. The account table is
# the auth database's, read across from the characters connection the way the
# uptime read does. LIKE ignores case under the default collation.
ELIGIBLE_SQL = (
    "SELECT c.name FROM characters c "
    "JOIN acore_auth.account a ON a.id = c.account "
    "LEFT JOIN guild_member gm ON gm.guid = c.guid "
    "LEFT JOIN guild g ON g.guildid = gm.guildid "
    "WHERE a.username LIKE %s AND c.class <> %s AND c.level >= %s "
    "AND (g.name IS NULL OR g.name NOT IN (%s, %s)) "
    "AND NOT EXISTS (SELECT 1 FROM overseer_roster r WHERE r.name = c.name) "
    "ORDER BY c.guid"
)


def pace(rows_raw, cycle_raw) -> tuple:
    """(rows per pass, seconds per cycle) from the two environment values.
    Anything unreadable, not finite or not above zero falls back to the
    default, so a typo slows nothing down to zero and never kills the loop."""
    try:
        rows = int(rows_raw)
    except (TypeError, ValueError):
        rows = ROWS_PER_PASS
    if rows <= 0:
        rows = ROWS_PER_PASS
    try:
        cycle = float(cycle_raw)
    except (TypeError, ValueError):
        cycle = float(CYCLE_SECONDS)
    if not math.isfinite(cycle) or cycle <= 0:
        cycle = float(CYCLE_SECONDS)
    return rows, cycle


def eligible_params() -> tuple:
    """The parameters ELIGIBLE_SQL is run with, in its placeholder order."""
    return (ACCOUNT_PREFIX + "%", DEATH_KNIGHT, MIN_LEVEL) + KEPT_GUILDS


# The retire rows this pass needs to know about: in flight (never asked again
# while one runs), refused recently (asked again later), and done.
ROWS_SQL = (
    "SELECT target_name, status, "
    "updated_at > NOW() - INTERVAL %s MINUTE AS recent "
    "FROM overseer_command WHERE kind = 'job' AND source = %s AND command = %s"
)

IN_FLIGHT = frozenset({"pending", "claimed", "verifying"})


def rows_params() -> tuple:
    return (REFUSED_BACKOFF_MINUTES, SOURCE, COMMAND)


def read_rows(rows) -> tuple:
    """(in_flight names, recently refused names, done count) from ROWS_SQL rows."""
    in_flight, refused = set(), set()
    done = 0
    for r in rows:
        name = str(r.get("target_name") or "")
        status = str(r.get("status") or "")
        if status in IN_FLIGHT:
            in_flight.add(name)
        elif status == "applied":
            done += 1
        elif status == "error" and r.get("recent"):
            refused.add(name)
    return in_flight, refused, done


def plan(eligible, in_flight, refused, per_pass: int = ROWS_PER_PASS) -> list:
    """The names to write a retire row for this pass, in eligible order: none
    already in flight, none refused within the backoff, at most `per_pass`."""
    if per_pass <= 0:
        return []
    out = []
    for name in eligible:
        if name in in_flight or name in refused or name in out:
            continue
        out.append(name)
        if len(out) >= per_pass:
            break
    return out


def progress_line(done: int, remaining: int, queued: int, in_flight: int) -> str:
    """'retire: 120 of 877 done', with what this pass did. The total is the
    retired plus the still eligible, so it holds across restarts."""
    total = done + remaining
    return "retire: %d of %d done (%d queued this pass, %d in flight)" % (
        done,
        total,
        queued,
        in_flight,
    )
