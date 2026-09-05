#!/usr/bin/env python3
"""Put the family's status in front of the five game clients.

infra#3334. The in-game addon shows what a client can see for itself with no
help at all - offline, dead, out of sight, fighting, out of spell range. The
rest of the answer, which is the part the operator asked for first, lives in
`overseer_roster` and `overseer_dungeon_run` and has to be carried in.

WHAT IT DOES. Asks the map server for one already-composed line
(`GET /api/party-status`, which is `partystatus.build_push`), and enqueues it
as an `overseer_command` row. mod_overseer.cpp's DoChat drains that queue every
two seconds and broadcasts a `channel='party'` row to the whole group as a
packet it builds itself, so ONE row reaches all five sessions.

IT DECIDES NOTHING. Every word in the line was chosen in partystatus.py and is
covered by tests/test_partystatus.py. This is a pipe with a schedule.

WHY IT IS RUN BY HAND AND NOT A DAEMON. It puts machine text into party chat.
The addon filters those lines out of every chat frame, and relay.py's
control-byte filter already keeps them out of Discord and the thought store -
but a client WITHOUT the addon shows them, and starting an unattended writer
into a live realm's command queue is a decision for whoever owns the realm
rather than a side effect of installing an addon. Run it under whatever
supervisor that person prefers, or not at all.

The route worth having instead is the same packet sent with LANG_ADDON, which
no chat frame renders in the first place. That is a few lines in DoChat, in
quadseven/mod-overseer, and it would leave everything here unchanged: the
addon already reads both.

USAGE
    push_party_status.py --dry-run           # show the line, write nothing
    push_party_status.py                     # enqueue it once
    push_party_status.py --every 30          # and keep it fresh

Connection comes from the same environment the bridge uses, so this runs inside
the cluster or through a port-forward with no second set of settings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

# Must be shorter than partystatus.PUSH_STALE_SECONDS or the addon blanks
# every label between pushes. Deliberately well under it: the module drains
# its queue every two seconds, so thirty leaves the sender two whole missed
# rounds before a viewer is told anything.
DEFAULT_EVERY = 30

URL = os.environ.get("WOW_OVERSEER_URL", "http://localhost:8080")


def compose(url: str, timeout: float = 10.0) -> dict:
    """The line and its command rows, straight from the endpoint.

    S310: the URL comes from this process's own environment or its argv, never
    from a request, and there is no scheme but http on this path.
    """
    with urllib.request.urlopen(  # noqa: S310
            url.rstrip("/") + "/api/party-status", timeout=timeout) as answer:
        return json.loads(answer.read().decode())


def _connect():
    # Imported here, not at module scope, so --dry-run works on a box with no
    # driver installed. Same seam probe.py uses for the same reason.
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


def enqueue(rows: list[dict], source: str) -> int:
    """Insert the command rows. Returns how many were written.

    `source` is stamped so these are separable from a person's chat and from
    the Discord bridge's, which is what makes them retirable later without
    guessing which rows were ours.
    """
    if not rows:
        return 0
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    "INSERT INTO overseer_command "
                    "(target_name, command, kind, channel, source) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (row["target_name"], row["command"], row["kind"],
                     row["channel"], source),
                )
    finally:
        conn.close()
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=URL, help="map server base URL")
    ap.add_argument("--every", type=float, default=0,
                    help="seconds between pushes; 0 means once and stop")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the line and write nothing")
    ap.add_argument("--source", default="party-status",
                    help="the source column stamped on every row")
    args = ap.parse_args()

    while True:
        try:
            payload = compose(args.url)
        except Exception as exc:
            # A sentence, and then carry on. The endpoint answers 503 while the
            # world is unreachable, and a sender that exited on that would need
            # restarting by hand every time MySQL rolled - while the addon has
            # already gone quiet on its own, which is the correct behaviour and
            # needs no help from here.
            print("could not compose: %s" % exc, file=sys.stderr)
            if not args.every:
                return 1
            time.sleep(args.every)
            continue

        line = payload.get("line", "")
        print(line.replace("\t", " | "))
        if not args.dry_run:
            wrote = enqueue(payload.get("commands", []), args.source)
            if not wrote:
                print("nobody to speak: no enabled roster, or no leader",
                      file=sys.stderr)

        if not args.every:
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
