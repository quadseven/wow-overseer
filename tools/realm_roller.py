"""The realm roller's command line. Phase 1 (#590): validate and dry-run only.

    python3 tools/realm_roller.py validate --roller-dir DIR
    python3 tools/realm_roller.py dry-run --roller-dir DIR --deploy-repo REPO \\
        --site-url URL [--ref origin/main] [--status FILE]

`--roller-dir` holds channel.json and releases/*.json (in the deploy repo,
beside the overlay they change). `dry-run` reads the live gates, runs one
tick and prints what the roller WOULD do. It acts on nothing: no build, no
commit, no PR, no realm write. The act side (phase 2) is
`realmroller_act.py`, which the scheduled job runs.

`--status` is the previous tick's status JSON; only its `out_since` is read,
so the settle gate can see how long everyone has been out. Without it the
dry run reports the settle gate as just starting.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import realmroller  # noqa: E402
import realmroller_world as world  # noqa: E402


def _out_since(path: str | None) -> datetime | None:
    if not path:
        return None
    try:
        data = json.loads(pathlib.Path(path).read_text())
        return realmroller.instant(data["out_since"]) if data.get("out_since") else None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logging.warning("status %s unreadable (%s): settle starts now", path, exc)
        return None


def report(channel, releases, w, action) -> list[str]:
    """The dry run's lines: the channel, the readings, then the decision."""
    lines = [
        "channel %s (%s)  %s"
        % (
            channel.channel,
            channel.realm,
            "PAUSED: %s" % (channel.paused_reason or "no reason given")
            if channel.paused
            else "running",
        ),
        "current  %s (%s)" % (channel.current, releases[channel.current].state),
        "previous %s (%s)" % (channel.previous, releases[channel.previous].state),
        "queue    %s"
        % (
            ", ".join("%s %s" % (q, releases[q].state) for q in channel.queue)
            or "empty"
        ),
        "gates    family in instance: %s; guild groups inside: %s; out since: %s; last roll start: %s"
        % (
            "unreadable" if w.family_in_instance is None else w.family_in_instance,
            "unreadable" if w.guild_groups_inside is None else w.guild_groups_inside,
            world.age(w.now, w.out_since),
            world.age(w.now, w.last_roll_started),
        ),
    ]
    verb = (
        "would %s %s" % (action.kind, action.release)
        if action.release
        else "would %s" % action.kind
    )
    line = "dry-run  %s: %s" % (verb, action.why)
    if action.supersedes:
        line += " (supersedes %s)" % ", ".join(action.supersedes)
    if action.kind == "rollback":
        line += " -> %s, then pause" % action.target
    lines.append(line)
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check channel.json and releases/*.json")
    v.add_argument("--roller-dir", required=True, type=pathlib.Path)
    d = sub.add_parser(
        "dry-run", help="read the live gates and print the one next step"
    )
    d.add_argument("--roller-dir", required=True, type=pathlib.Path)
    d.add_argument("--deploy-repo", required=True, type=pathlib.Path)
    d.add_argument("--site-url", required=True, help="the overseer site's base URL")
    d.add_argument(
        "--ref", default="HEAD", help="the deploy-repo ref to read roll marks from"
    )
    d.add_argument("--status", help="previous status JSON (read only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    try:
        channel, releases = world.load(args.roller_dir)
    except (realmroller.Invalid, OSError, ValueError) as exc:
        print("invalid: %s" % exc, file=sys.stderr)
        return 1
    if args.cmd == "validate":
        print("ok: channel %s, %d release(s)" % (channel.channel, len(releases)))
        return 0
    now = datetime.now(timezone.utc)
    w = world.observe(
        channel,
        releases,
        now=now,
        site_url=args.site_url,
        deploy_repo=args.deploy_repo,
        ref=args.ref,
        out_since=_out_since(args.status),
    )
    for line in report(channel, releases, w, world.dry_action(channel, releases, w)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
