#!/usr/bin/env python3
"""Ask a living character what it is doing, and print the answer.

WHY THIS EXISTS. Checking this family through acore_characters is checking a
photograph: PlayerSaveInterval is 900000 and each player's save timer runs from
its own login, so character_spell and character_talent are up to fifteen minutes
behind the world. After the training pass in infra#2756 the database reported a
paladin with zero spells for a quarter of an hour after he had been taught them.

The other direction is worse and has happened repeatedly. A command row reports
`delivered` the moment the module hands it over, which says nothing about
whether anything happened: `talents spec prot pve` reported delivered and
changed nothing at all. Without a way to ask the character itself, "it worked"
and "the message was passed on" look identical.

A probe reads the live Player* inside the worldserver and mutates nothing, so
it can never be the reason an experiment appears to have succeeded.

USAGE
    probe.py Grug                     # every probe
    probe.py Grug state strategies    # just these
    probe.py --all talents            # every roster character

Connection comes from the same environment the bridge uses, so this runs inside
the cluster or through a port-forward without a second set of settings to keep
in step.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

PROBES = ("state", "spells", "talents", "strategies", "gear", "bags")

# The module polls its command queue every COMMAND_POLL_MS (2s), so anything
# under a few seconds is just racing the tick. Ten seconds is long enough to
# cover a busy world update and short enough that a wedged worldserver is
# obvious rather than something this hangs on.
TIMEOUT_SECONDS = 10.0
POLL_SECONDS = 0.25


def _connect():
    # Imported here, not at module scope, so the pure logic below can be
    # imported and tested by a stdlib-only job. Same seam the metrics emitter
    # uses for the same reason.
    import pymysql

    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def roster(cur) -> list[str]:
    cur.execute("SELECT name FROM overseer_roster WHERE enabled = 1 ORDER BY name")
    return [r["name"] for r in cur.fetchall()]


def ask(cur, name: str, what: str) -> int:
    cur.execute(
        "INSERT INTO overseer_command (target_name, command, kind, source) "
        "VALUES (%s, %s, 'probe', 'probe.py')",
        (name, what),
    )
    return cur.lastrowid


def placeholders(n: int) -> str:
    """`n` bound-parameter markers, comma separated. Never anything else.

    Split out so the claim "the interpolated text carries no data" is a
    function with a test rather than a comment above a format string.
    """
    if n < 1:
        raise ValueError("placeholders needs a positive count")
    return ",".join(["%s"] * n)


def collect(cur, ids: dict[int, tuple[str, str]], deadline: float) -> dict:
    """Poll until every row is finished or the deadline passes.

    Rows are read back by id rather than by "most recent", so two probes running
    at once cannot read each other's answers - which is the sort of bug that
    would make this tool worse than no tool, because it would be confidently
    wrong rather than silent.
    """
    out: dict = {}
    pending = dict(ids)
    while pending and time.monotonic() < deadline:
        # The only thing interpolated is a run of literal placeholders, one per
        # pending id - "%s,%s,%s" and nothing else. It is derived from a COUNT,
        # never from a value, and every id still travels as a bound parameter.
        # An IN clause of unknown width has no other form in DB-API; ruff's S608
        # cannot see that the formatted fragment carries no data, and
        # placeholders() below is asserted in the tests to emit nothing else.
        cur.execute(
            "SELECT id, status, detail, result FROM overseer_command "
            f"WHERE id IN ({placeholders(len(pending))})",  # noqa: S608
            tuple(pending),
        )
        for row in cur.fetchall():
            if row["status"] in ("pending", "claimed"):
                continue
            name, what = pending.pop(row["id"])
            slot = out.setdefault(name, {})
            if row["status"] == "delivered" and row["result"]:
                try:
                    slot[what] = json.loads(row["result"])
                except json.JSONDecodeError as exc:
                    slot[what] = {"error": f"probe returned invalid json: {exc}"}
            else:
                slot[what] = {"error": row["detail"] or row["status"]}
        if pending:
            time.sleep(POLL_SECONDS)

    # A probe that never came back is reported as such rather than omitted. An
    # absent key reads as "nothing to say"; this is "nobody answered".
    for name, what in pending.values():
        out.setdefault(name, {})[what] = {"error": "timed out waiting for the worldserver"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", help="character to ask; omit with --all")
    ap.add_argument("probes", nargs="*", default=None, help=f"any of: {' '.join(PROBES)}")
    ap.add_argument("--all", action="store_true", help="ask every enabled roster character")
    ap.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    args = ap.parse_args()

    wanted = [p for p in (args.probes or PROBES)]
    bad = [p for p in wanted if p not in PROBES]
    if bad:
        print(f"unknown probe(s): {' '.join(bad)}; known: {' '.join(PROBES)}", file=sys.stderr)
        return 2
    if not args.name and not args.all:
        ap.error("give a character name, or --all")

    with _connect() as conn, conn.cursor() as cur:
        names = roster(cur) if args.all else [args.name]
        if not names:
            print("no enabled roster characters", file=sys.stderr)
            return 1
        ids = {}
        for name in names:
            for what in wanted:
                ids[ask(cur, name, what)] = (name, what)
        answers = collect(cur, ids, time.monotonic() + args.timeout)

    print(json.dumps(answers, indent=2, sort_keys=True))
    # Non-zero when anything failed, so this is usable in a check and not only
    # by eye.
    failed = any("error" in v for probes in answers.values() for v in probes.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
