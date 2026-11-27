"""The scheduled watch reports early actions and observed family wedges."""

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import apiv2
import dungeonstall
from tools import metric_watcher


class PreWedgeAPI(unittest.TestCase):
    def test_counts_recorded_early_actions_within_the_day(self):
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.create_function("NOW", 0, lambda: "2026-01-02 00:00:00")
            db.create_function("LOCATE", 2, lambda needle, hay: hay.find(needle) + 1)
            db.execute("CREATE TABLE overseer_guild_ask (kind, said, created_at)")
            db.execute(
                "CREATE TABLE overseer_dungeon_pace (decision, reason, created_at)"
            )
            db.executemany(
                "INSERT INTO overseer_guild_ask VALUES (?, ?, ?)",
                [
                    (
                        "deathloop",
                        "I've already died 3 times in an hour in this zone.",
                        "2026-01-01 12:00:00",
                    ),
                    (
                        "deathloop",
                        "Keep dying here, 5 times in an hour.",
                        "2026-01-01 12:00:00",
                    ),
                    (
                        "quest",
                        "I've already died 3 times in an hour in this zone.",
                        "2026-01-01 12:00:00",
                    ),
                    (
                        "deathloop",
                        "I've already died 3 times in an hour in this zone.",
                        "2026-01-01 00:00:00",
                    ),
                ],
            )
            slopes = dungeonstall.door_restart_slope("deadmines", (3, 3))
            breaker = dungeonstall.door_unreachable("deadmines", (10, 10))
            db.executemany(
                "INSERT INTO overseer_dungeon_pace VALUES (?, ?, ?)",
                [
                    (dungeonstall.DECISION, slopes.why, "2026-01-01 02:00:00"),
                    (dungeonstall.ORDER_DECISION, slopes.why, "2026-01-01 03:00:00"),
                    (dungeonstall.DECISION, breaker.why, "2026-01-01 04:00:00"),
                    ("advance", slopes.why, "2026-01-01 04:00:00"),
                    (dungeonstall.DECISION, slopes.why, "2025-12-31 04:00:00"),
                ],
            )

            def rows(sql, params, *, what):
                # Run the same filters against a fixed database clock.
                sql = sql.replace(
                    "NOW() - INTERVAL 24 HOUR", "datetime(NOW(), '-24 hours')"
                )
                return db.execute(sql.replace("%s", "?"), params).fetchall()

            status, payload = apiv2.handle(
                "/api/v2/pre-wedge",
                {},
                SimpleNamespace(read=SimpleNamespace(rows=rows)),
            )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload, {"death_slope_asks": 1, "restart_slope_stand_downs": 2}
        )

    def test_missing_action_read_is_unknown_and_empty_read_counts_zero(self):
        def rows(sql, params, *, what):
            return [{"n": 0}] if what == "overseer_dungeon_pace" else []

        status, payload = apiv2.handle(
            "/api/v2/pre-wedge", {}, SimpleNamespace(read=SimpleNamespace(rows=rows))
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload, {"death_slope_asks": None, "restart_slope_stand_downs": 0}
        )


class PreWedgeWatch(unittest.TestCase):
    def test_appends_action_counts_and_observed_family_episodes(self):
        family = "SampleFamily"
        now = 172800
        stalled = [
            {"name": "SampleLeader", "family": family, "stuck": True, "since": now},
            {"name": "SampleFollower", "family": family, "stuck": True, "since": now},
            {"name": "SampleSolo", "stuck": True, "since": now},
            {"name": "SampleUnknown", "family": "OtherFamily", "stuck": True},
            {
                "name": "SampleNormal",
                "family": "NormalFamily",
                "stuck": False,
                "since": now,
            },
        ]

        sample = {}

        def fetch(url):
            if url.endswith("/roster"):
                return dict(sample)
            if url.endswith("/pre-wedge"):
                return {"death_slope_asks": 1, "restart_slope_stand_downs": 2}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            args = [
                "metric_watcher",
                "--api-root",
                "https://example.com/api/v2",
                "--output",
                str(path),
            ]
            with patch.object(metric_watcher.realm_state_audit, "fetch_json", fetch):
                with patch.object(sys, "argv", args):
                    for elapsed, members in (
                        (1800, stalled),
                        (3600, stalled),
                        (3600, []),
                        (5400, stalled),
                        (7200, []),
                        (9000, stalled),
                        (3600 + 86400, stalled),
                    ):
                        sample.update(checked_at=now + elapsed, members=members)
                        metric_watcher.main()
            raw = path.read_text(encoding="utf-8")

        rows = [json.loads(line)["pre_wedge"] for line in raw.splitlines()]
        self.assertEqual(
            [row["family_wedges_over_30m"] for row in rows], [0, 1, 0, 1, 0, 1, 1]
        )
        self.assertEqual(
            [row["wedges_formed_anyway_24h"] for row in rows], [0, 1, 1, 1, 1, 2, 1]
        )
        self.assertEqual(rows[-1]["wedge_observed_since"], "1970-01-03T01:00:00Z")
        self.assertEqual(
            rows[-1]["preemptions_24h"],
            {
                "death_slope_asks": 1,
                "restart_slope_stand_downs": 2,
                "total": 3,
            },
        )
        self.assertNotIn("Sample", raw)

    def test_action_endpoint_failure_keeps_the_snapshot(self):
        def fetch(url):
            if url.endswith("/roster"):
                return {"checked_at": 3600, "members": []}
            if url.endswith("/pre-wedge"):
                raise RuntimeError("endpoint unavailable")
            return {}

        with patch.object(metric_watcher.realm_state_audit, "fetch_json", fetch):
            record, _ = metric_watcher.collect("https://example.com/api/v2")

        self.assertEqual(
            record["pre_wedge"]["preemptions_24h"],
            {
                "death_slope_asks": None,
                "restart_slope_stand_downs": None,
                "total": None,
            },
        )
