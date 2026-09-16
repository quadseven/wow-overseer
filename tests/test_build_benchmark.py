import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).parents[3] / "docker" / "azerothcore-playerbots" / "tools"
sys.path.insert(0, str(TOOLS))
import build_benchmark  # noqa: E402


class BuildBenchmarkTests(unittest.TestCase):
    def test_writes_record_without_fabricating_cache_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "metrics.json"
            self.assertEqual(build_benchmark.main(["--output", str(output), "--duration-seconds", "12.5"]), 0)
            record = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["wall_clock_seconds"], 12.5)
        self.assertIsNone(record["ccache"]["hit_rate_percent"])
        self.assertIn("host_snapshot", record)

    def test_preserves_reported_cache_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "metrics.json"
            build_benchmark.main(["--output", str(output), "--duration-seconds", "408", "--hit-rate", "87.5", "--cacheable-calls", "200", "--hits", "175", "--misses", "25", "--cold"])
            record = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(record["cache_mode"], "cold")
        self.assertEqual(record["ccache"]["hit_rate_percent"], 87.5)
        self.assertEqual(record["ccache"]["hits"], 175)

    def test_rejects_impossible_hit_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "metrics.json"
            with self.assertRaises(SystemExit):
                build_benchmark.main(["--output", str(output), "--duration-seconds", "1", "--hit-rate", "101"])


if __name__ == "__main__":
    unittest.main()
