"""Read the overseer API and build a machine-readable realm state report."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


GUILDS = ("Cave", "Bonkers")


def _utc(timestamp: int | float | None) -> str | None:
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _member(row: dict, checked_at: int) -> dict:
    if not isinstance(row, dict):
        raise ValueError("roster member must be an object")
    since = row.get("since")
    stuck_duration = (
        max(0, checked_at - int(since))
        if row.get("stuck") and since is not None
        else None
    )
    return {
        "name": row.get("name"),
        "guild": row.get("guild"),
        "level": row.get("level"),
        "location": row.get("zone") or None,
        "online": bool(row.get("online")),
        "life": row.get("life"),
        "stuck": bool(row.get("stuck")),
        "stuck_kind": row.get("stuck_kind") or None,
        "blocker": _public_blocker(row.get("blocker")),
        "stuck_since": _utc(since) if row.get("stuck") else None,
        "stuck_duration_seconds": stuck_duration,
    }


def _public_blocker(blocker: str | None) -> str | None:
    """Remove character-specific identity from known blocker templates."""
    if blocker is None:
        return None
    return re.sub(r"Waiting for [A-Z][A-Za-z0-9_-]* at", "Waiting for the NPC at", blocker)


def _level_distribution(raidteam: dict) -> dict:
    levels = sorted(
        int(member["level"])
        for member in raidteam.get("members", {}).values()
        if member.get("level") is not None
    )
    histogram = {str(level): 0 for level in range(1, 61)}
    for level in levels:
        histogram[str(level)] += 1
    return {
        "seat_count": len(raidteam.get("members", {})),
        "levels_with_data": len(levels),
        "median": statistics.median(levels) if levels else None,
        "lowest": min(levels) if levels else None,
        "histogram": histogram,
    }


def _public_member(row: dict, member_ids: dict) -> dict:
    return {
        **{key: value for key, value in row.items() if key != "name"},
        "member_id": member_ids[row["name"]],
    }


def build_report(
    roster: dict,
    raidteams: dict[str, dict],
    guilds: dict[str, dict] | None = None,
) -> dict:
    """Build guild rosters and status summaries from read-only API payloads."""
    if roster.get("checked_at") is None:
        raise ValueError("roster response is missing checked_at")
    checked_at = int(roster["checked_at"])
    roster_members = roster.get("members", [])
    if not isinstance(roster_members, list):
        raise ValueError("roster response members must be an array")
    all_members = [_member(row, checked_at) for row in roster_members]
    guilds = guilds or {}
    guild_reports = {}
    for guild in GUILDS:
        members = sorted(
            (row for row in all_members if row["guild"] == guild),
            key=lambda row: row["name"] or "",
        )
        member_ids = {
            row["name"]: f"{guild}-{index:03d}"
            for index, row in enumerate(members, start=1)
        }

        offline = [
            {
                **_public_member(row, member_ids),
                "last_seen": None,
                "last_seen_status": "not exposed by API",
            }
            for row in members
            if not row["online"]
        ]
        guild_reports[guild] = {
            "member_count": len(members),
            "online_count": sum(row["online"] for row in members),
            "online_members": [
                _public_member(row, member_ids) for row in members if row["online"]
            ],
            "offline_members": offline,
            "dead_members": [
                {
                    "member_id": member_ids[row["name"]],
                    "location": row["location"],
                    "duration_seconds": None,
                }
                for row in members
                if row["life"] == "dead"
            ],
            "ghost_members": [],
            "stuck_members": [
                {
                    "member_id": member_ids[row["name"]],
                    "location": row["location"],
                    "duration_seconds": row["stuck_duration_seconds"],
                    "blocker": row["blocker"],
                }
                for row in members
                if row["stuck"]
            ],
            "level_distribution": _level_distribution(raidteams.get(guild, {})),
        }
        ghost_times = {
            row.get("name"): row
            for row in guilds.get(guild, {}).get("deaths", {}).get("ghosts", [])
        }
        for row in members:
            if row["life"] != "ghost":
                continue
            death = ghost_times.get(row["name"], {})
            at = death.get("at")
            guild_reports[guild]["ghost_members"].append(
                {
                    "member_id": member_ids[row["name"]],
                    "location": row["location"] or death.get("where"),
                    "death_at": _utc(at),
                    "duration_seconds": (
                        max(0, checked_at - int(at)) if at is not None else None
                    ),
                }
            )
    return {
        "snapshot_at": _utc(checked_at),
        "snapshot_epoch": checked_at,
        "sources": [
            "/api/v2/roster",
            "/api/v2/raidteams?guild=Cave",
            "/api/v2/raidteams?guild=Bonkers",
            "/api/v2/guild?guild=Cave",
            "/api/v2/guild?guild=Bonkers",
        ],
        "limitations": {
            "online_location": "The API omits a location when the member's zone is unknown.",
            "offline_last_seen": "The API does not expose a last-seen timestamp.",
            "dead_duration": "The API exposes current corpse state but not when it began.",
            "ghost_duration": "A duration is available only when the guild endpoint has a matching death record.",
        },
        "guilds": guild_reports,
    }


def fetch_json(url: str) -> dict:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("API URLs must use http or https and include a host")
    request = urllib.request.Request(  # noqa: S310 - URL scheme is validated above.
        url, headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - URL scheme is validated above.
            request, timeout=30
        ) as response:
            try:
                return json.load(response)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"non-JSON response from {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"request failed for {url}: {reason}") from exc


def collect(api_root: str) -> dict:
    root = api_root.rstrip("/")
    roster = fetch_json(f"{root}/roster")
    raidteams = {
        guild: fetch_json(f"{root}/raidteams?guild={guild}") for guild in GUILDS
    }
    guilds = {guild: fetch_json(f"{root}/guild?guild={guild}") for guild in GUILDS}
    return build_report(roster, raidteams, guilds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path for the JSON report")
    parser.add_argument("--api-root", required=True, help="Versioned API root URL")
    args = parser.parse_args()
    try:
        report = collect(args.api_root)
    except RuntimeError as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(format_json(report) + "\n", encoding="utf-8")


def format_json(value, depth: int = 0) -> str:
    """Pretty-print JSON while keeping record arrays compact and reviewable."""
    indent = " " * depth
    if isinstance(value, dict):
        if not value:
            return "{}"
        entries = []
        for key in sorted(value):
            rendered = format_json(value[key], depth + 2)
            entries.append(f"{indent}  {json.dumps(key)}: {rendered}")
        return "{\n" + ",\n".join(entries) + f"\n{indent}" + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(item, dict) for item in value):
            entries = [
                f"{' ' * (depth + 2)}{json.dumps(item, separators=(',', ':'), sort_keys=True)}"
                for item in value
            ]
        else:
            entries = [
                f"{' ' * (depth + 2)}{format_json(item, depth + 2)}" for item in value
            ]
        return "[\n" + ",\n".join(entries) + f"\n{indent}]"
    return json.dumps(value, sort_keys=True)


if __name__ == "__main__":
    main()
