"""The Raid tab's read of the metric watcher's log (#891): the tail of the
file, the last week before the newest snapshot, and nothing on a bad path."""

import json
import os
import sys
import tempfile
import types
import unittest

os.environ.setdefault("MYSQL_ROOT_PASSWORD", "test")
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402

DAY = 86400


class TheSnapshotRead(unittest.TestCase):
    def write(self, lines):
        handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        self.addCleanup(os.unlink, handle.name)
        with handle:
            handle.write("\n".join(lines) + "\n")
        return handle.name

    def test_the_last_week_is_read_oldest_first(self):
        path = self.write(
            [
                json.dumps({"snapshot_epoch": 10 * DAY}),
                json.dumps({"snapshot_epoch": 1 * DAY}),
                "not json",
                json.dumps({"snapshot_epoch": 4 * DAY}),
            ]
        )
        got = map_server._metric_snapshots(path)
        self.assertEqual([r["snapshot_epoch"] for r in got], [4 * DAY, 10 * DAY])

    def test_a_cut_first_line_is_dropped(self):
        path = self.write(
            [json.dumps({"snapshot_epoch": n, "pad": "x" * 50}) for n in range(5)]
        )
        old = map_server.METRIC_TAIL_BYTES
        map_server.METRIC_TAIL_BYTES = 100
        self.addCleanup(setattr, map_server, "METRIC_TAIL_BYTES", old)
        got = map_server._metric_snapshots(path)
        self.assertEqual([r["snapshot_epoch"] for r in got], [4])

    def test_a_missing_file_is_no_snapshots(self):
        self.assertEqual(map_server._metric_snapshots("/nonexistent/metrics.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
