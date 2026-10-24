#!/usr/bin/env python3
"""Diagnose a health finding from its runs and logs (#1311).

    scripts/diagnose_finding.py family-run-loop:Zug:48 [--ticket N]
                                [--revision SHA] [--hours H]

WHY. The family-run-loop finding (apiv2/health.py) says why its runs ended
"most often" from the run row's `ended_reason`. For a stalled run that is the
cleanup (the hearth out), not the reason the run stopped. The reason is in the
worldserver's log, where the dungeon module wrote "Dungeon clear stopped:
..." when it gave up, and lanes that only had the finding fixed the cleanup
three times. This prints what the finding cannot carry, for the planner to
attach when it files or re-briefs the finding's ticket.

WHAT IT PRINTS, for a `family-run-loop:<family>:<map>` key: a header, a Stops
line counting the stalled runs by the reason they stopped, a Deploy line, a
Not read line per source that could not be read, then the family's runs of
that map started in the last --hours (the finding's LOOP_HOURS by default),
newest first: id, start and end, outcome, furthest encounter mask, the last
phase change, the `stalled` row's detail, and every "Dungeon clear stopped"
line a family member logged during the run (identical reasons merged, with
their members). Plain ASCII, under MAX_LINES lines; the oldest runs give way.
Any other key prints "no diagnosis for this kind of finding". Exit 0 either
way: a source that could not be read is part of the diagnosis.

THE SOURCES, all read-only. Each failure is named on stdout by source and a
reason that carries no host, path or credential; the full error goes to
stderr for the operator.

  runs    overseer_dungeon_run, its timeline and the roster, through
          realmread (the site's one read path), connected as the bridge
          connects (MYSQL_HOST, MYSQL_ROOT_PASSWORD).
  logs    the realm's archived worldserver log, through the deployment's
          read-only archive helper. OVERSEER_REALM_LOGS names it; it is run
          as `<helper> cat worldserver <SINCE>`.
  revision
          the mod-overseer commit the realm runs: --revision, else the
          "mod-overseer" pin in OVERSEER_UPSTREAM_PINS (as /api/v2/upstream
          reads it). The realm's own build report does not carry it.
  pull requests
          mod-overseer's merged pull requests whose title or body names the
          finding's key or cites --ticket (TICKET_FORMS), through `gh`, and
          for each whether the revision holds its merge commit.
"""

from __future__ import annotations

import argparse
import calendar
import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import traceback
from typing import Callable, Iterable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pymysql  # noqa: E402

import achievements  # noqa: E402
import dungeonstall  # noqa: E402
import realmread  # noqa: E402
from apiv2 import health, upstream  # noqa: E402

NO_DIAGNOSIS = "no diagnosis for this kind of finding"
MAX_LINES = 39
WIDTH = 200
STOPS_PER_RUN = 3
MOD_REPO = "quadseven/mod-overseer"
ENV_LOGS = "OVERSEER_REALM_LOGS"
WORKLOAD = "worldserver"
GH_TIMEOUT = 60
ARCHIVE_TIMEOUT = 120
STOP_TEXT = "Dungeon clear stopped: "
NO_STOP = "no Dungeon clear stopped line"
# How a mod-overseer pull request cites a ticket here: "wow-overseer#N", or
# the issue's URL.
TICKET_FORMS = ("wow-overseer#%d", "wow-overseer/issues/%d")

NOW_SQL = health.NOW_SQL
ROSTER_SQL = (
    "SELECT name FROM overseer_roster WHERE family = %s ORDER BY `lead` DESC, name"
)
# A run is the family's whose leader is one of its names (as health reads it).
RUNS_SQL = (
    "SELECT id, leader_name, map_id, state, outcome, ended_reason, "
    "UNIX_TIMESTAMP(started_at) AS started_unix, "
    "UNIX_TIMESTAMP(ended_at) AS ended_unix FROM overseer_dungeon_run "
    "WHERE leader_name IN ({holes}) AND map_id = %s "
    "AND started_at >= NOW() - INTERVAL %s HOUR ORDER BY id"
)
EVENTS_SQL = (
    "SELECT run_id, kind, phase, detail FROM overseer_dungeon_run_event "
    "WHERE run_id IN ({holes}) AND kind IN ('phase', 'boss', 'stalled') ORDER BY id"
)

_KEY = re.compile(r"^family-run-loop:([A-Za-z]{2,12}):(\d+)$")
# The archive keeps the kubelet prefix "<time> <stream> <F|P> <text>". The
# dungeon module's line (DcAdvanceAction, mod-dungeon-clear) is
# "[DC:<bot>] between-pulls wait gave up after ...: Dungeon clear stopped:
# <reason>. (present <n> of <m> alive, healer here=<0|1>)".
_STOP = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S*\s.*?\[DC:([A-Za-z]+)\].*?"
    + re.escape(STOP_TEXT)
    + r"(.+?)\.?(?:\s+\(present \d+ of \d+ alive.*)?$"
)
_WAITING = re.compile(r"Waiting on [A-Za-z]+ \(([^()]+)\)")


class Unreadable(Exception):
    """A source could not be read, for a reason that is safe to print."""


@dataclasses.dataclass(frozen=True)
class Stop:
    """One "Dungeon clear stopped" line: when, whose, and the reason."""

    at: int
    member: str
    reason: str


@dataclasses.dataclass
class Sources:
    """Where each read comes from; main() builds the real ones."""

    realm: Callable[[], realmread.Reader]
    logs: Callable[[str], Iterable[str]]
    revision: Callable[[], str]
    pulls: Callable[[list], list]
    compare: Callable[[str, str], str]


@dataclasses.dataclass
class Realm:
    """What the realm read returned: its clock, the family, runs, timeline."""

    now: int
    names: list
    runs: list = dataclasses.field(default_factory=list)
    events: list = dataclasses.field(default_factory=list)


# -------------------------------------------------------------- the reads --


def _connect():
    """A connection opened the way the bridge opens one (bridge._connect)."""
    password = os.environ.get("MYSQL_ROOT_PASSWORD")
    if not password:
        raise Unreadable("MYSQL_ROOT_PASSWORD is not set")
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        user="root",
        password=password,
        database="acore_characters",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=30,
        write_timeout=10,
    )


def realm_session() -> realmread.Reader:
    return realmread.Session(_connect)


def archived_logs(since: str) -> list:
    """The archived worldserver lines from `since` that hold a stop, through
    the helper ENV_LOGS names. The helper's own errors pass to stderr."""
    helper = os.environ.get(ENV_LOGS, "").strip()
    if not helper:
        raise Unreadable("%s is not set" % ENV_LOGS)
    with subprocess.Popen(
        [helper, "cat", WORKLOAD, since],
        stdout=subprocess.PIPE,
        text=True,
        errors="replace",
    ) as proc:
        try:
            out, _ = proc.communicate(timeout=ARCHIVE_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise Unreadable("the log archive helper timed out") from exc
        except BaseException:
            proc.kill()
            raise
    if proc.returncode:
        raise Unreadable("the log archive helper exited %d" % proc.returncode)
    return [line for line in (out or "").splitlines() if STOP_TEXT in line]


def declared_revision() -> str:
    pin = upstream.env_pins().get("mod-overseer", "")
    if not pin:
        raise Unreadable(
            "no --revision, and %s names no mod-overseer pin" % upstream.ENV_PINS
        )
    return pin


def gh(*args: str) -> str:
    """`gh`'s stdout; its stderr passes through to ours."""
    try:
        done = subprocess.run(
            ["gh", *args],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
            timeout=GH_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise Unreadable("gh is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise Unreadable("gh exited %d" % exc.returncode) from exc
    return done.stdout


def github_pulls(terms: list) -> list:
    """mod-overseer's merged pull requests a search for any of `terms` finds."""
    found: dict = {}
    for term in terms:
        listed = json.loads(
            gh(
                "pr", "list", "-R", MOD_REPO, "--state", "merged",
                "--search", '"%s"' % term,
                "--json", "number,title,body,mergedAt,mergeCommit",
                "--limit", "100",
            )
        )  # fmt: skip
        found.update((int(p["number"]), p) for p in listed)
    return [found[n] for n in sorted(found)]


def github_compare(base: str, head: str) -> str:
    """GitHub's status of base...head: `ahead` or `identical` when head holds base."""
    path = "repos/%s/compare/%s...%s" % (MOD_REPO, base, head)
    return gh("api", path, "--jq", ".status").strip()


def real_sources() -> Sources:
    return Sources(
        realm=realm_session,
        logs=archived_logs,
        revision=declared_revision,
        pulls=github_pulls,
        compare=github_compare,
    )


# What a source read can truly raise; a programming fault is not one of them
# and surfaces instead of printing as a missing source.
READ_ERRORS = (
    Unreadable,
    OSError,
    getattr(pymysql, "MySQLError", OSError),  # a test's stub may lack it
    realmread.Gap,
    json.JSONDecodeError,
    subprocess.SubprocessError,
)


def read(unread: list, err, name: str, how: Callable):
    """`how()`, or None with `name` noted in `unread`. The note carries an
    Unreadable's own reason, else only the error's class: a driver's message
    can name the host it could not reach. The whole error goes to `err`."""
    try:
        return how()
    except READ_ERRORS as exc:  # named on stdout, whole on stderr
        traceback.print_exception(exc, file=err)
        why = str(exc) if isinstance(exc, Unreadable) else type(exc).__name__
        unread.append("Not read: %s (%s)" % (name, why))
        return None


def read_realm(open_reader: Callable, family: str, map_id: int, hours: int) -> Realm:
    with open_reader() as rd:
        now = int(rd.must(NOW_SQL)[0]["now_at"])
        roster = rd.rows(ROSTER_SQL, (family,), what="overseer_roster")
        names = [str(r["name"]) for r in roster] or [family]
        runs = rd.rows(
            RUNS_SQL.format(holes=dungeonstall.holes(len(names))),
            (*names, map_id, hours),
            what="overseer_dungeon_run",
        )
        ids = tuple(int(r["id"]) for r in runs)
        events = []
        if ids:
            events = rd.rows(
                EVENTS_SQL.format(holes=dungeonstall.holes(len(ids))),
                ids,
                what="overseer_dungeon_run_event",
            )
    return Realm(now, names, [dict(r) for r in runs], [dict(e) for e in events])


# ------------------------------------------------------------- the stops --


def stop_of(line: str) -> Stop | None:
    """The stop a log line records, or None for any other line."""
    found = _STOP.match(str(line).strip())
    if not found:
        return None
    at = calendar.timegm(time.strptime(found.group(1), "%Y-%m-%dT%H:%M:%S"))
    return Stop(at, found.group(2), found.group(3).strip())


def stop_kind(reason: str) -> str:
    """A stop reason without its members and numbers, for counting."""
    if "never became ready" in reason:
        waiting = _WAITING.search(reason)
        return "party never ready" + (
            ", waiting on %s" % waiting.group(1) if waiting else ""
        )
    return re.sub(r"\d+", "N", reason.split(" (")[0]).strip()


def stops_in(run: dict, stops: list, now: int) -> list:
    start = int(run.get("started_unix") or 0)
    end = int(run.get("ended_unix") or 0) or now
    return [s for s in stops if start <= s.at <= end]


def stalled(realm: Realm) -> list:
    return [r for r in realm.runs if dungeonstall.stall_of(r, realm.events)]


def stops_line(realm: Realm | None, stops: list | None) -> str:
    if realm is None or stops is None:
        return "Stops: not counted (%s not read)" % (
            "runs" if realm is None else "logs"
        )
    stalls = stalled(realm)
    if not stalls:
        return "Stops: no run in the window stalled"
    counts: dict = {}
    for run in stalls:
        mine = stops_in(run, stops, realm.now)
        kind = stop_kind(mine[-1].reason) if mine else NO_STOP
        counts[kind] = counts.get(kind, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "Stops: " + "; ".join(
        "%d of %d stalls: %s" % (n, len(stalls), kind) for kind, n in ranked
    )


# ------------------------------------------------------------ the deploy --


def names_finding(pull: dict, key: str, ticket: int | None) -> bool:
    text = "%s\n%s" % (pull.get("title") or "", pull.get("body") or "")
    if key in text:
        return True
    cited = r"wow-overseer(?:#|/issues/)%d\b" % (ticket or 0)
    return bool(ticket) and re.search(cited, text) is not None


def merge_of(pull: dict) -> str:
    return str((pull.get("mergeCommit") or {}).get("oid") or "")


def pull_text(pull: dict) -> str:
    merged = str(pull.get("mergedAt") or "")[:16].replace("T", " ")
    return "#%d (merged %sZ)" % (int(pull["number"]), merged)


def pending(pulls: list, revision: str, compare: Callable) -> list:
    """The pulls whose merge commit `revision` does not hold."""
    held = ("ahead", "identical")
    return [p for p in pulls if compare(merge_of(p), revision) not in held]


def deploy_line(src: Sources, args, unread: list, err) -> str:
    revision = read(unread, err, "revision", lambda: args.revision or src.revision())
    terms = [args.key] + [form % args.ticket for form in TICKET_FORMS if args.ticket]
    found = read(unread, err, "pull requests", lambda: src.pulls(terms))
    pulls = None
    if found is not None:
        pulls = [p for p in found if names_finding(p, args.key, args.ticket)]
    if pulls is not None and revision:
        named = pulls
        pulls = read(
            unread, err, "pull requests", lambda: pending(named, revision, src.compare)
        )
    listed = "not read" if pulls is None else ", ".join(map(pull_text, pulls)) or "none"
    if not revision:
        return (
            "Deploy: mod-overseer revision not read; merged naming this finding: "
            + listed
        )
    return "Deploy: the realm runs mod-overseer %s; merged and not in it: %s" % (
        revision[:12],
        listed,
    )


# ------------------------------------------------------------- the runs --


def hhmm(at) -> str:
    if not at:
        return "open"
    return time.strftime("%m-%d %H:%MZ", time.gmtime(int(at)))


def mask_text(mask: int) -> str:
    if not mask:
        return "no encounter credited"
    count = bin(mask).count("1")
    return "mask %d (%d encounter%s)" % (mask, count, "" if count == 1 else "s")


def last_phase(run_id: int, events: list) -> str:
    phases = [
        e.get("detail") or e.get("phase")
        for e in events
        if e.get("kind") == "phase" and int(e.get("run_id") or 0) == run_id
    ]
    return str(phases[-1]) if phases else "none on record"


def stop_lines(mine: list) -> list:
    """One line per distinct reason, its members in the order they said it."""
    grouped: dict = {}
    for s in mine:
        _at, members = grouped.setdefault(s.reason, (s.at, []))
        if s.member not in members:
            members.append(s.member)
    lines = [
        "stop %s %s: %s" % (hhmm(at)[6:], ", ".join(members), reason)
        for reason, (at, members) in grouped.items()
    ]
    if len(lines) > STOPS_PER_RUN:
        extra = len(lines) - STOPS_PER_RUN
        lines = lines[:STOPS_PER_RUN] + ["+%d more stop reasons" % extra]
    return lines


def run_block(run: dict, realm: Realm, stops: list | None) -> list:
    rid = int(run["id"])
    outcome = str(run.get("outcome") or "") or str(run.get("state") or "open")
    mask = health.furthest_mask({rid}, realm.events)
    stall = dungeonstall.stall_of(run, realm.events)
    lines = [
        say(
            "Run %d %s to %s, %s, %s"
            % (
                rid,
                hhmm(run.get("started_unix")),
                hhmm(run.get("ended_unix")),
                outcome,
                mask_text(mask),
            )
        ),
        say(
            "last phase %s; stalled: %s"
            % (last_phase(rid, realm.events), stall.reason if stall else "no"),
            "  ",
        ),
    ]
    if stops is None:
        return lines
    mine = stops_in(run, stops, realm.now)
    return lines + [say(t, "  ") for t in stop_lines(mine) or [NO_STOP]]


def fit(blocks: list, room: int) -> list:
    """The blocks, newest first, that fit in `room` lines with a closing line
    for the ones that do not."""
    out: list = []
    for shown, block in enumerate(blocks):
        left = len(blocks) - shown - 1
        if len(out) + len(block) + (1 if left else 0) > room:
            out.append("... %d older runs not shown" % (len(blocks) - shown))
            return out
        out.extend(block)
    return out


# -------------------------------------------------------------- the whole --


def say(text: str, indent: str = "") -> str:
    return indent + health.ascii_text(text, WIDTH - len(indent))


def diagnose(args, family: str, map_id: int, src: Sources, err) -> list:
    unread: list = []
    realm = read(
        unread, err, "runs", lambda: read_realm(src.realm, family, map_id, args.hours)
    )
    now = realm.now if realm else int(time.time())
    names = set(realm.names if realm else [family])
    since = health.iso(now - args.hours * 3600) or ""
    lines = read(unread, err, "logs", lambda: list(src.logs(since)))
    stops = None
    if lines is not None:
        stops = [s for s in map(stop_of, lines) if s and s.member in names]
    count = "runs not read" if realm is None else "%d runs" % len(realm.runs)
    head = [
        say(
            "Finding %s: %s's family in %s, runs started in the last %d hours (%s)"
            % (args.key, family, achievements.dungeon_name(map_id), args.hours, count)
        ),
        say(stops_line(realm, stops)),
        say(deploy_line(src, args, unread, err)),
    ] + [say(u) for u in unread]
    if realm is None:
        return head
    if not realm.runs:
        return head + ["No run of this map started in the window."]
    blocks = [run_block(r, realm, stops) for r in reversed(realm.runs)]
    return head + fit(blocks, MAX_LINES - len(head))


def parse(argv) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("key", help="the health finding's key")
    ap.add_argument("--ticket", type=int, help="the finding's ticket number")
    ap.add_argument("--revision", help="the mod-overseer commit the realm runs")
    ap.add_argument(
        "--hours",
        type=int,
        default=health.LOOP_HOURS,
        help="how far back runs are read (default: the finding's window)",
    )
    return ap.parse_args(argv)


def main(argv=None, sources: Sources | None = None, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = parse(argv)
    key = _KEY.match(args.key)
    if not key:
        print(NO_DIAGNOSIS, file=out)
        return 0
    family, map_id = key.group(1), int(key.group(2))
    for line in diagnose(args, family, map_id, sources or real_sources(), err):
        print(line, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
