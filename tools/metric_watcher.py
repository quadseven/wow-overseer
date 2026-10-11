"""Append read-only realm metrics to a JSON Lines log."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from tools import realm_state_audit

TARGET_SEATS = 40
MAX_LEVEL = 60


def _iso(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _run_totals(dungeons: list) -> dict:
    return {
        "started": sum(int(row.get("started") or 0) for row in dungeons),
        "entered": sum(int(row.get("runs") or 0) for row in dungeons),
        "cleared": sum(int(row.get("cleared") or 0) for row in dungeons),
        "wiped": sum(int(row.get("wiped") or 0) for row in dungeons),
    }


def _xp_rate(series: dict) -> tuple[int | None, int]:
    """Return the mean measured guild XP/hour and its measured hour count."""
    values = [
        int(value)
        for _, value in series.get("xp_per_hour") or []
        if value is not None
    ]
    return (round(sum(values) / len(values)) if values else None, len(values))


def build_metrics(report: dict, guild_payloads: dict[str, dict]) -> dict:
    """Shape one aggregate, identity-reduced record per guild."""
    guild_records = {}
    for guild, state in report["guilds"].items():
        source = guild_payloads.get(guild, {})
        levels = state["level_distribution"]
        quests = source.get("class_quests") or {}
        deaths = source.get("deaths") or {}
        xp_per_hour, xp_hours_measured = _xp_rate(source.get("series") or {})
        guild_records[guild] = {
            "seats": levels["seat_count"],
            "median_level": levels["median"],
            "lowest_level": levels["lowest"],
            "level_histogram": levels["histogram"],
            "level_gainers_24h": len(source.get("gaining") or []),
            "xp_per_hour_24h": xp_per_hour,
            "xp_hours_measured": xp_hours_measured,
            "runs": _run_totals(source.get("dungeons") or []),
            "class_quests": {
                "done": quests.get("done"),
                "blocked": quests.get("blocked"),
            },
            "deaths_24h": deaths.get("total"),
            "ghosts": len(state["ghost_members"]),
            "stuck": len(state["stuck_members"]),
            "offline": len(state["offline_members"]),
        }
    return {
        "snapshot_at": report["snapshot_at"],
        "snapshot_epoch": report["snapshot_epoch"],
        "xp_source": "measured by /api/v2/series",
        "guilds": guild_records,
    }


def _level_total(report: dict) -> int:
    """Sum observed seat levels; empty seats contribute zero progress."""
    return sum(
        sum(
            int(level) * int(count)
            for level, count in state["level_distribution"]["histogram"].items()
        )
        for state in report["guilds"].values()
    )


def estimate_level_60_date(previous: dict | None, current: dict) -> dict:
    """Estimate 40 level-60 seats from observed level steps per elapsed day."""
    total = _level_total(current)
    remaining = max(0, TARGET_SEATS * MAX_LEVEL - total)
    rate = None
    projected = None
    if previous is not None:
        elapsed = int(current["snapshot_epoch"]) - int(previous["snapshot_epoch"])
        gained = total - _level_total(previous)
        if elapsed > 0 and gained > 0:
            rate = gained * 86400 / elapsed
            projected = _iso(int(current["snapshot_epoch"]) + remaining / rate * 86400)
        elif remaining == 0:
            rate = 0
            projected = _iso(int(current["snapshot_epoch"]))
    return {
        "target_seats": TARGET_SEATS,
        "remaining_level_steps": remaining,
        "level_steps_per_day": round(rate, 4) if rate is not None else None,
        "projected_at": projected,
        "basis": "observed level steps; raw XP is not exposed by the API",
    }


def append_jsonl(path: Path, record: dict) -> None:
    """Append exactly one compact JSON object and newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        stream.write("\n")


def _previous(path: Path) -> dict | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        end = stream.tell()
        pos = end - 1
        while pos >= 0:
            stream.seek(pos)
            if stream.read(1) == b"\n" and pos != end - 1:
                break
            pos -= 1
        stream.seek(pos + 1)
        line = stream.readline()
    try:
        record = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"last JSONL record in {path} is invalid") from exc
    return record.get("level_snapshot")


def collect(api_root: str) -> tuple[dict, dict]:
    """Fetch the established read-only API endpoints and shape metrics."""
    root = api_root.rstrip("/")
    roster = realm_state_audit.fetch_json(f"{root}/roster")
    raidteams = {
        guild: realm_state_audit.fetch_json(f"{root}/raidteams?guild={guild}")
        for guild in realm_state_audit.GUILDS
    }
    guilds = {
        guild: realm_state_audit.fetch_json(f"{root}/guild?guild={guild}")
        for guild in realm_state_audit.GUILDS
    }
    for guild in realm_state_audit.GUILDS:
        guilds[guild]["series"] = realm_state_audit.fetch_json(
            f"{root}/series?guild={guild}"
        )
    report = realm_state_audit.build_report(roster, raidteams, guilds)
    return build_metrics(report, guilds), report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-root",
        default=os.environ.get("METRIC_WATCHER_API_ROOT"),
        help="Versioned read-only API root URL (or METRIC_WATCHER_API_ROOT)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=os.environ.get("METRIC_WATCHER_OUTPUT"),
        help="JSONL path (or METRIC_WATCHER_OUTPUT)",
    )
    args = parser.parse_args()
    if not args.api_root or not args.output:
        parser.error(
            "--api-root and --output (or their environment variables) are required"
        )
    try:
        record, report = collect(args.api_root)
        record["level_projection"] = estimate_level_60_date(
            _previous(args.output), report
        )
        record["level_snapshot"] = {
            "snapshot_epoch": report["snapshot_epoch"],
            "guilds": {
                guild: {
                    "level_distribution": {
                        "histogram": state["level_distribution"]["histogram"]
                    }
                }
                for guild, state in report["guilds"].items()
            },
        }
        append_jsonl(args.output, record)
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, f"{parser.prog}: error: {exc}\n")


if __name__ == "__main__":
    main()
