"""Tests for append-only realm metric snapshots."""

import json
from datetime import datetime, timezone

from tools.metric_watcher import (
    _previous,
    append_jsonl,
    build_metrics,
    collect,
    estimate_level_60_date,
)
from tools import metric_watcher


def report(levels, checked_at=1800):
    return {
        "snapshot_at": datetime.fromtimestamp(checked_at, timezone.utc).isoformat(),
        "snapshot_epoch": checked_at,
        "guilds": {
            "Cave": {
                "level_distribution": {
                    "seat_count": len(levels),
                    "levels_with_data": len(levels),
                    "median": 20,
                    "lowest": min(levels) if levels else None,
                    "histogram": {
                        str(level): levels.count(level) for level in set(levels)
                    },
                },
                "offline_members": [{"member_id": "Cave-001"}],
                "ghost_members": [],
                "stuck_members": [],
            }
        },
    }


def guild_payload():
    return {
        "Cave": {
            "gaining": [{"name": "Sample", "level": 21, "at": 1800}],
            "deaths": {"total": 3},
            "class_quests": {"done": 7, "blocked": 2},
            "dungeons": [{"runs": 4, "cleared": 2, "wiped": 1}],
        }
    }


def test_metrics_are_per_guild_and_use_counts_without_member_names():
    payloads = guild_payload()
    payloads["Cave"]["series"] = {"xp_per_hour": [[100, 120], [200, None], [300, 180]]}
    records = build_metrics(report([20, 30]), payloads)

    cave = records["guilds"]["Cave"]
    assert cave["level_gainers_24h"] == 1
    assert cave["deaths_24h"] == 3
    assert cave["class_quests"] == {"done": 7, "blocked": 2}
    assert cave["runs"] == {"started": 0, "entered": 4, "cleared": 2, "wiped": 1}
    assert cave["offline"] == 1
    assert cave["xp_per_hour_24h"] == 150
    assert cave["xp_hours_measured"] == 2
    assert "Sample" not in json.dumps(records)
    assert records["xp_source"] == "measured by /api/v2/series"


def test_collect_reads_the_read_only_guild_series_endpoint(monkeypatch):
    requested = []

    def fetch(url):
        requested.append(url)
        if url.endswith("/roster"):
            return {"checked_at": 1800, "members": []}
        if "/raidteams?" in url:
            return {"members": {}}
        if "/series?" in url:
            return {"xp_per_hour": [[1800, 90]]}
        return {}

    monkeypatch.setattr(metric_watcher.realm_state_audit, "fetch_json", fetch)

    record, _ = collect("https://example.com/api/v2")

    assert "https://example.com/api/v2/series?guild=Cave" in requested
    assert "https://example.com/api/v2/series?guild=Bonkers" in requested
    assert record["guilds"]["Cave"]["xp_per_hour_24h"] == 90


def test_xp_projection_uses_seated_remaining_experience_and_guild_rate():
    payloads = {
        "Cave": {
            "seat_members": ["A"],
            "series": {
                "xp_per_hour": [[1800, 100]],
                "xp_to_level_60_by_member": {"A": 100},
                "level_60_total_xp": 1000,
            },
        },
        "Bonkers": {
            "seat_members": ["B"],
            "series": {
                "xp_per_hour": [[1800, 100]],
                "xp_to_level_60_by_member": {"B": 200},
                "level_60_total_xp": 1000,
            },
        },
    }

    projection = metric_watcher._xp_projection(payloads, 1800)

    assert projection["remaining_xp"] == 38300
    assert projection["xp_per_hour_24h"] == 200
    assert projection["projected_at"] == "1970-01-09T00:00:00Z"


def test_xp_projection_reports_now_when_all_40_seats_are_level_60():
    names = [f"Member{index}" for index in range(40)]
    payloads = {
        "Cave": {
            "seat_members": names,
            "series": {
                "xp_to_level_60_by_member": dict.fromkeys(names, 0),
                "level_60_total_xp": 1000,
            },
        },
    }

    projection = metric_watcher._xp_projection(payloads, 1800)

    assert projection["remaining_xp"] == 0
    assert projection["projected_at"] == "1970-01-01T00:30:00Z"


def test_projection_uses_snapshot_level_rate_and_targets_40_level_60_seats():
    previous = report([58] * 40, checked_at=0)
    current = report([59] * 40, checked_at=86400)

    projection = estimate_level_60_date(previous, current)

    assert projection["target_seats"] == 40
    assert projection["remaining_level_steps"] == 40
    assert projection["level_steps_per_day"] == 40
    assert projection["projected_at"] == "1970-01-03T00:00:00Z"


def test_jsonl_append_preserves_prior_records(tmp_path):
    path = tmp_path / "metrics.jsonl"
    append_jsonl(path, {"snapshot_at": "one"})
    append_jsonl(path, {"snapshot_at": "two"})

    assert [
        json.loads(line)["snapshot_at"] for line in path.read_text().splitlines()
    ] == [
        "one",
        "two",
    ]


def test_previous_reads_last_record_when_jsonl_ends_with_newline(tmp_path):
    path = tmp_path / "metrics.jsonl"
    append_jsonl(path, {"level_snapshot": {"id": "one"}})
    append_jsonl(path, {"level_snapshot": {"id": "two"}})

    assert _previous(path) == {"id": "two"}
