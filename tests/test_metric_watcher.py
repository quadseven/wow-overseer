"""Tests for append-only realm metric snapshots."""

import json
from datetime import datetime, timezone

from tools.metric_watcher import build_metrics, estimate_level_60_date, append_jsonl


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
                    "histogram": {str(level): levels.count(level) for level in set(levels)},
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
    records = build_metrics(report([20, 30]), guild_payload())

    cave = records["guilds"]["Cave"]
    assert cave["level_gainers_24h"] == 1
    assert cave["deaths_24h"] == 3
    assert cave["class_quests"] == {"done": 7, "blocked": 2}
    assert cave["runs"] == {"started": 0, "entered": 4, "cleared": 2, "wiped": 1}
    assert cave["offline"] == 1
    assert "Sample" not in json.dumps(records)
    assert records["xp_source"] == "unavailable: API exposes level changes, not experience"


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

    assert [json.loads(line)["snapshot_at"] for line in path.read_text().splitlines()] == [
        "one",
        "two",
    ]
