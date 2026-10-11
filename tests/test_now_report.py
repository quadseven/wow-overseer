"""The Now report is assembled from read-only guild and status reads."""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app modules")
class NowReport(unittest.TestCase):
    def test_report_facts_include_progress_blocker_and_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, app)
            (app / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            script = """
const M = await import(%s);
const now = 200000;
const got = M.reportFacts({guild: {dungeons: [{place: "Deadmines", runs: 4, cleared: 2, wiped: 2}], gaining: [{at: now - 3600}]}, series: {level: [[1, 20], [86401, 21]], xp_to_level_60_by_member: {A: 360000}, xp_per_hour: [[1, 10000]]}, stuck: {members: [{blocker: "bag room", since: now - 7200}]}, now});
console.log(JSON.stringify(got));
""" % json.dumps((app / "views/now/report.js").as_uri())
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["dungeons"][0]["attempts"], 4)
        self.assertEqual(data["dungeons"][0]["clearRate"], 0.5)
        self.assertEqual(data["topBlocker"]["memberHours"], 2)
        self.assertIsNotNone(data["projectedAt"])


if __name__ == "__main__":
    unittest.main()
