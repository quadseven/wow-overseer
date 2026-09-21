#!/usr/bin/env python3
"""Enrol existing characters into a second `overseer_roster` cohort.

    enroll_cohort.py --cohort Bonkers --name Mozkisdo --name Biannise
    enroll_cohort.py --cohort Bonkers --from-pool 5 --min-level 60
    enroll_cohort.py --cohort Bonkers --name Mozkisdo --apply

DRY RUN BY DEFAULT, AND THAT IS NOT TIMIDITY. `enroll.plan` refuses the whole
batch when the world cannot yet tell two cohorts apart (see `enroll.plan`'s own
docstring for both gates), so the ordinary answer on every world running today
is a refusal with a sentence attached. Printing that, and the SQL that WOULD
run, is the useful output: it can be read before it is run, diffed between two
runs, and pasted into a review - the same argument `seed_roster.py` makes for
being a printer, kept here and given an `--apply` so the mechanism is not
merely a suggestion.

READ-ONLY UNTIL `--apply`, INCLUDING THE PROBES. Everything this tool learns -
whether `overseer_roster` has a `family` column, whether a name is a real
character, its race, its guild, its existing cohort - comes from SELECTs. It
creates no accounts and no characters: `Player::Create` is only wired into
`RandomPlayerbotFactory` in this pinned core, so characters are made by a
person at a game client (see `seed_roster.py` and quadseven/infra's
production/oke/manifests/wow-dev/README.md).

THE ONE FACT THIS TOOL CANNOT PROBE, AND SO REFUSES TO GUESS. Whether the
running worldserver's mod-overseer reads the `family` column is a property of
a container image, not of a table, and no SELECT can answer it. It used to be
the gate that bound outright: `KeepRosterGrouped` took every enabled row into
one party, so a newly enrolled Horde cohort would have been kept in the
Alliance family's party on every poll. mod-overseer#550-#553 changed that for
parties, quests and the one-campaign machinery (see `enroll.plan` for what is
and is not yet true). `--module-is-cohort-aware` remains an explicit operator
assertion about the DEPLOYED image and defaults to off, and
`tests/test_enroll.py` pins what the PINNED submodule actually does so that a
change is a failing test rather than a discovery.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import enroll  # noqa: E402


# WotLK race ids, as `enroll` and `core` already agree them. Restated as a SQL
# fragment rather than re-derived, because the pool query runs in the database
# and the membership test runs in Python, and they must not drift.
_HORDE_MARKS = ", ".join(["%s"] * len(enroll.HORDE_RACES))
_HORDE_IDS = tuple(sorted(enroll.HORDE_RACES))

_POOL_SQL = (
    # noqa anchored on the FIRST line of the expression. ruff reports S608 at
    # the START of a multi-line expression, so the marker that used to sit on
    # the f-string below silenced nothing - the same gotcha `bridge.py` records
    # next to `_BOT_HELD_SQL`.
    "SELECT c.name FROM characters c "  # noqa: S608 - the only thing interpolated is _HORDE_MARKS, which is a run of `%s` placeholders counted from _HORDE_IDS, a literal tuple in this file; every value is bound
    "  LEFT JOIN guild_member gm ON gm.guid = c.guid "
    "  LEFT JOIN overseer_roster r ON r.name = c.name "
    " WHERE gm.guid IS NULL AND r.name IS NULL "
    f"   AND c.race IN ({_HORDE_MARKS}) "
    "   AND c.level >= %s "
    " ORDER BY c.level DESC, c.name "
    " LIMIT %s"
)

_FACTS_SQL = (
    "SELECT c.name, c.race, c.level, COALESCE(gm.guildid, 0) AS guild_id "
    "  FROM characters c "
    "  LEFT JOIN guild_member gm ON gm.guid = c.guid "
    " WHERE c.name IN (%s)"
)

_ROSTER_SQL = "SELECT name, family FROM overseer_roster WHERE name IN (%s)"
# The same question asked of a world that cannot answer the second half of it.
# Whether a character ALREADY HAS a roster row is knowable without the `family`
# column, and it is the half that decides whether enrolling it is even a new
# row; which cohort it is in is not, and this does not pretend otherwise.
_ROSTER_SQL_NO_FAMILY = "SELECT name FROM overseer_roster WHERE name IN (%s)"


def _connect():
    """The same credential and the same bounds as `bridge._connect`.

    PyMySQL's default read timeout is infinite, and a tool that hangs against a
    sick database is worse than one that fails, because an operator reading a
    dry run cannot tell a hang from a slow answer.

    ONE ADDITION THE BRIDGE DOES NOT NEED: `MYSQL_PORT`. The bridge runs in the
    cluster and reaches `mysql:3306` by service DNS, so it has never wanted a
    port. This is an operator tool, and the way an operator reaches that
    database from outside is `kubectl port-forward`, which lands on whatever
    local port is free - 3306 on a workstation is frequently something else
    entirely, and connecting to it produces an access-denied error that reads
    exactly like a wrong password. Defaulting to 3306 keeps in-cluster use
    identical.
    """
    import pymysql  # noqa: PLC0415

    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def has_family_column(cur) -> bool:
    """Whether `overseer_roster` carries mod-overseer#506's `family` column.

    INFORMATION_SCHEMA rather than a `SELECT family` that catches 1054, because
    this is a question and not an attempt: the answer is wanted BEFORE anything
    is planned, and a probe that works by provoking an error logs an error on
    the ordinary path.
    """
    cur.execute(
        "SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS "
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'overseer_roster' "
        "   AND COLUMN_NAME = 'family'"
    )
    row = cur.fetchone() or {}
    return int(row.get("n", 0)) > 0


def home_cohort(cur, head: str, *, present: bool) -> str | None:
    """The cohort this process already drives, read off the head's own row.

    READ, NEVER HARDCODED, which is the rule `bridge._cohort_of` states at
    length and for a reason that applies here identically: the column's DEFAULT
    is the literal 'Grug', but a validation world renames the cast, so a tool
    pinned to that literal would decide the home cohort was absent and cheerfully
    let somebody enrol into it.

    `present` IS NOT BELT AND BRACES, IT IS THE FIX FOR A REAL CRASH. Without
    it this asked `SELECT family` of a world that has no such column, and the
    first live dry run against wow-dev died on MySQL 1054 with a traceback -
    before `enroll.plan` could refuse the batch and say why. An operator's
    first contact with this tool would have been a stack trace that looks like
    a broken tool rather than the sentence describing the gate that is actually
    closed. `has_family_column` has already answered this one line earlier, so
    the question is simply not asked. That is better than catching 1054 the way
    `bridge._cohort_of` has to: the bridge is guessing from an error because it
    has no cheaper way to know, and this does.
    """
    if not head or not present:
        return None
    cur.execute("SELECT family FROM overseer_roster WHERE name = %s", (head,))
    row = cur.fetchone() or {}
    return row.get("family") or None


def pool(cur, wanted: int, min_level: int) -> list[str]:
    """Guildless, un-enrolled Horde characters, strongest first.

    The same population infra#4239 measured (660 guildless Horde characters on
    wow-dev), narrowed by the two things enrollment cares about and bounded by
    a LIMIT. `ORDER BY level DESC, name` makes two runs of the same arguments
    return the same names, so a dry run is evidence about the run that follows
    it rather than a different sample.
    """
    cur.execute(_POOL_SQL, (*_HORDE_IDS, int(min_level), max(0, int(wanted))))
    return [row["name"] for row in cur.fetchall()]


def candidates(cur, names: list[str], *, present: bool) -> list[enroll.Candidate]:
    """What the realm says about each name, including that it has never heard
    of it.

    A NAME WITH NO ROW COMES BACK AS `exists=False` RATHER THAN BEING DROPPED.
    Silently omitting an unknown name would turn a typo into a smaller batch
    that looked like a successful one, and `enroll.plan` is built to refuse it
    by name instead.

    `present` FOR THE SAME REASON `home_cohort` TAKES IT, and found the same
    way: the first live dry run died here too, on `SELECT name, family` against
    a world with no `family` column. On such a world the roster read asks only
    for the name, and a character that HAS a row gets `cohort = ""` - "there is
    a row and this cannot say whose", which `enroll.plan` refuses as another
    cohort's. The batch is refused by the gate regardless; this is so the dry
    run's per-candidate report is honest rather than invented.
    """
    if not names:
        return []
    marks = ", ".join(["%s"] * len(names))
    # Only the NUMBER of placeholders is interpolated, computed from len(names)
    # one line above; every name reaches MySQL as a bound parameter. A
    # variable-width IN list has no other form in DB-API, and this is the same
    # shape `bridge._bot_held_names` uses for the same reason.
    cur.execute(_FACTS_SQL % marks, tuple(names))  # noqa: S608
    facts = {row["name"]: row for row in cur.fetchall()}
    roster_sql = _ROSTER_SQL if present else _ROSTER_SQL_NO_FAMILY
    cur.execute(roster_sql % marks, tuple(names))  # noqa: S608
    enrolled = {row["name"]: (row.get("family") if present else "")
                for row in cur.fetchall()}
    out = []
    for name in names:
        fact = facts.get(name)
        if fact is None:
            out.append(enroll.Candidate(name=name, exists=False))
            continue
        out.append(enroll.Candidate(
            name=fact["name"],
            exists=True,
            race=int(fact["race"]),
            level=int(fact["level"]),
            guild_id=int(fact["guild_id"]),
            # `.get` with a default of None distinguishes "has a roster row
            # whose family is unset" from "has no roster row at all"; only the
            # second is enrollable.
            cohort=enrolled.get(name),
        ))
    return out


def apply(cur, plan_: enroll.Plan) -> int:
    """Execute the plan, returning the rows written.

    ONE STATEMENT PER ROW AND NO `executemany`, so that a duplicate key names
    the character it collided on. The batch is capped at `enroll.DEFAULT_LIMIT`,
    so the cost of not batching is a handful of round trips.

    A BLOCKED PLAN YIELDS NO STATEMENTS, and this trusts `enroll.statements` to
    have said so rather than re-checking `blocked` itself. That is deliberate:
    two places deciding whether a gate holds is two places for them to
    disagree, and the test suite pins that a blocked plan produces an empty
    tuple.
    """
    written = 0
    for sql, params in enroll.statements(plan_):
        cur.execute(sql, params)
        written += cur.rowcount or 0
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cohort", required=True,
                        help="the `family` value the new rows carry")
    parser.add_argument("--name", action="append", default=[],
                        help="a character to enrol; repeatable")
    parser.add_argument("--from-pool", type=int, default=0,
                        help="instead of --name, take this many guildless "
                             "un-enrolled Horde characters")
    parser.add_argument("--min-level", type=int, default=1,
                        help="lowest level --from-pool will draw (default 1)")
    parser.add_argument("--head", default="",
                        help="the head of the family this process drives, used "
                             "only to read the home cohort off its own row so "
                             "this tool refuses to enrol into it")
    parser.add_argument("--limit", type=int, default=enroll.DEFAULT_LIMIT,
                        help="refuse a batch larger than this "
                             "(default %(default)s)")
    parser.add_argument("--module-is-cohort-aware", action="store_true",
                        help="assert that the RUNNING worldserver's "
                             "mod-overseer scopes its roster reads by `family`. "
                             "No SELECT can check this. It is false for every "
                             "image built to date: mod-overseer#506 shipped the "
                             "column with no reader.")
    parser.add_argument("--apply", action="store_true",
                        help="execute the plan instead of printing it")
    args = parser.parse_args(argv)

    if args.name and args.from_pool:
        parser.error("--name and --from-pool choose the batch two different "
                     "ways; pass one of them")
    if not args.name and not args.from_pool:
        parser.error("nothing to enrol: pass --name or --from-pool")

    with _connect() as conn, conn.cursor() as cur:
        family_column = has_family_column(cur)
        home = home_cohort(cur, args.head, present=family_column)
        names = (pool(cur, args.from_pool, args.min_level) if args.from_pool
                 else list(args.name))
        found = candidates(cur, names, present=family_column)
        plan_ = enroll.plan(
            found,
            cohort=args.cohort,
            home_cohort=home,
            has_family_column=family_column,
            module_reads_family=args.module_is_cohort_aware,
            limit=args.limit,
        )
        written = apply(cur, plan_) if args.apply else 0

    report = {
        "cohort": plan_.cohort,
        "home_cohort": home,
        "has_family_column": family_column,
        "module_reads_family": bool(args.module_is_cohort_aware),
        "blocked": plan_.blocked,
        "summary": enroll.report(plan_),
        "would_enrol": [row["name"] for row in plan_.rows],
        "skipped": [{"name": r.name, "reason": r.reason} for r in plan_.skipped],
        "refused": [{"name": r.name, "reason": r.reason} for r in plan_.refused],
        "applied": bool(args.apply),
        "rows_written": written,
        # The row every enrolled character gets, printed in full so that "sane
        # defaults for every column" is something a reviewer reads rather than
        # something this tool claims.
        "row_template": enroll.row_for("<name>", plan_.cohort),
        "sql": enroll.INSERT_SQL,
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    # A REFUSAL IS A NON-ZERO EXIT. A gate that reported success because it
    # successfully refused would be the check that can only report good news.
    if plan_.blocked:
        return 2
    if args.apply and written != len(plan_.rows):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
