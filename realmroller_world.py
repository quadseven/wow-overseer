"""What the realm roller reads each tick: the gate readers and the file loader.

#590. Every reader answers None when it cannot read, never a guess, and
realmroller.tick treats None as the unsafe answer. Nothing here writes: no
git commit, no cluster call, no POST. Deployment-specific values (the site's
base URL, the deploy repo's path, which file marks a roll) come from the
caller and the channel file, never from this source.
"""

from __future__ import annotations

import json
import logging
import pathlib
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import realmroller

log = logging.getLogger("realmroller")

_TIMEOUT = 20  # seconds; the family API answers in well under one


def fetch_json(url: str, timeout: float = _TIMEOUT) -> object | None:
    """GET `url` as JSON, or None (logged) on any failure to read or parse it."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                log.warning("GET %s answered %s", url, resp.status)
                return None
            return json.loads(resp.read().decode())
    except (OSError, ValueError) as exc:
        log.warning("GET %s failed: %s", url, exc)
        return None


def family_in_instance(base_url: str, families, fetch=fetch_json) -> int | None:
    """How many members of `families` are in an instance, from /api/family.

    THE API FALLS BACK TO ITS DEFAULT FAMILY FOR A NAME IT DOES NOT KNOW
    (map_server._fetch_family_names), so a renamed or missing family would
    silently report the default family's members. The payload's own `family`
    must name the family asked for, or the read is None: unreadable, which
    the tick treats as inside.
    """
    total = 0
    for name in families:
        url = "%s/api/family?%s" % (
            base_url.rstrip("/"),
            urllib.parse.urlencode({"family": name}),
        )
        data = fetch(url)
        if not isinstance(data, dict) or data.get("family") != name:
            log.warning("family %s: no answer for that family", name)
            return None
        members = data.get("members")
        if not isinstance(members, list) or not members:
            log.warning("family %s: no members in the answer", name)
            return None
        total += sum(1 for m in members if isinstance(m, dict) and m.get("instance"))
    return total


def guild_groups_inside(base_url: str, states, fetch=fetch_json) -> int | None:
    """How many guild groups are in one of `states`, from /api/guildruns `active`."""
    data = fetch("%s/api/guildruns" % base_url.rstrip("/"))
    if not isinstance(data, dict) or not isinstance(data.get("active"), list):
        return None
    return sum(
        1 for g in data["active"] if isinstance(g, dict) and g.get("state") in states
    )


def carry_out_since(
    prev: datetime | None, inside: int | None, now: datetime
) -> datetime | None:
    """When everyone was last seen to leave, carried across ticks.

    The settle gate needs "out for 5 minutes", and one tick sees one instant.
    Inside or unreadable resets it; out keeps the earlier time, or starts the
    clock now when there was none.
    """
    if inside is None or inside > 0:
        return None
    return prev or now


def git_marker_time(
    repo: pathlib.Path, ref: str, path: str, pattern: str, run=subprocess.run
) -> datetime | None:
    """The commit time of the last change on `ref` to a line of `path` matching `pattern`.

    This is the hand-made roll's mark (a digest line moved in the overlay),
    so the hourly gate also counts rolls made before the roller existed.
    None when git fails; the caller then has only the releases' history.
    """
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        "-1",
        "--format=%cI",
        "-G",
        pattern,
        ref,
        "--",
        path,
    ]
    try:
        out = run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("git log failed: %s", exc)
        return None
    if out.returncode != 0:
        log.warning("git log exited %d: %s", out.returncode, out.stderr.strip())
        return None
    text = out.stdout.strip()
    return datetime.fromisoformat(text) if text else None


def load(
    roller_dir: pathlib.Path,
) -> tuple[realmroller.Channel, dict[str, realmroller.Release]]:
    """channel.json and releases/*.json under `roller_dir`, validated as one set.

    Raises realmroller.Invalid (or OSError, ValueError for a missing or
    malformed file). A file named for one release must hold that release.
    """
    channel = realmroller.parse_channel(
        json.loads((roller_dir / "channel.json").read_text())
    )
    releases = {}
    for path in sorted((roller_dir / "releases").glob("*.json")):
        rel = realmroller.parse_release(json.loads(path.read_text()), channel)
        if path.stem != rel.name:
            raise realmroller.Invalid(path.name, ["holds release %s" % rel.name])
        releases[rel.name] = rel
    realmroller.check_set(channel, releases)
    return channel, releases


def observe(
    channel: realmroller.Channel,
    releases: dict,
    *,
    now: datetime,
    site_url: str,
    deploy_repo: pathlib.Path,
    ref: str,
    out_since: datetime | None,
    fetch=fetch_json,
    run=subprocess.run,
) -> realmroller.World:
    """Read the gates for one tick. Phase 1 reads gates only, not a roll in flight."""
    p = channel.policy
    family = family_in_instance(site_url, p.families, fetch)
    guild = guild_groups_inside(site_url, p.guild_run_states, fetch)
    inside = None if family is None or guild is None else family + guild
    marker = git_marker_time(
        deploy_repo, ref, p.roll_marker_path, p.roll_marker_pattern, run
    )
    return realmroller.World(
        now=now,
        family_in_instance=family,
        guild_groups_inside=guild,
        out_since=carry_out_since(out_since, inside, now),
        last_roll_started=realmroller.last_roll_start(releases, marker),
    )


def age(now: datetime, then: datetime | None) -> str:
    """'12m ago' for the dry run's readings; 'never' for None."""
    if then is None:
        return "never"
    mins = int((now - then) / timedelta(minutes=1))
    return "%dh%02dm ago" % divmod(mins, 60) if mins >= 60 else "%dm ago" % mins
