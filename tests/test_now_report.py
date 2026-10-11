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
    def test_report_section_presents_all_five_lines_for_both_guilds(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, app)
            (app / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            script = """
const M = await import(%s);
const guild = (name) => ({data: {now: 200000, count: 1,
  members: [{name: name + "Member"}],
  dungeons: [{place: "Wailing Caverns", floor: 22, ceiling: 32, runs: 4, cleared: 2},
             {place: "Deadmines", floor: 17, ceiling: 26, runs: 2, cleared: 1}]}});
const series = (name) => ({data: {level: [[1, 20], [86401, 21]],
  xp_to_level_60_by_member: {[name + "Member"]: 360000},
  by_member: {[name + "Member"]: {xp_per_hour_24h: 10000, xp_hours_measured: 24}}}});
const reads = {
  "/api/v2/guild?guild=cave": guild("Cave"),
  "/api/v2/guild?guild=bonkers": guild("Bonkers"),
  "/api/v2/series?guild=cave": series("Cave"),
  "/api/v2/series?guild=bonkers": series("Bonkers"),
  "/api/v2/stuck": {data: {members: [{name: "CaveMember", blocker: "bag room", since: 192800}]}},
};
const ctx = {get: (key) => reads[key]};
const html = M.reportSection(ctx,
  [{name: "Cave", slug: "cave"}, {name: "Bonkers", slug: "bonkers"}],
  [{data: {queue: {line: "Next: Deadmines", entries: [{status: "active"}, {place: "Deadmines"}]}}},
   {data: {queue: {line: "Next: Wailing Caverns", entries: []}}}],
  {data: {shipped: ["Report page"]}}).s;
console.log(JSON.stringify(html));
""" % json.dumps((app / "views/now/report.js").as_uri())
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        markup = json.loads(result.stdout)
        for content in (
            "Cave", "Bonkers", "median levels / 7d", "clears / attempt",
            "Deadmines", "Wailing Caverns", "member-hours", "Shipped changes",
            "Verification", "Next actions", "Level 60 projection",
            "measured 24h XP rate",
            "Refreshes every 30 seconds",
        ):
            self.assertIn(content, markup)
        self.assertLess(markup.index("Deadmines"), markup.index("Wailing Caverns"))

    def test_report_facts_include_progress_blocker_and_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, app)
            (app / "package.json").write_text('{"type":"module"}', encoding="utf-8")
            # These fields match apiv2.guild.dungeon_rows/_tally,
            # apiv2.series.guild_series, and apiv2.members.stuck_view.
            script = """
const M = await import(%s);
const now = 200000;
const got = M.reportFacts({guild: {count: 1, members: [{name: "MemberA"}], dungeons: [{place: "Wailing Caverns", floor: 22, ceiling: 32, runs: 3, cleared: 1}, {place: "Deadmines", floor: 17, ceiling: 26, runs: 4, cleared: 2, wiped: 2}]}, series: {level: [[1, 20], [86401, 21]], xp_to_level_60_by_member: {MemberA: 360000}, by_member: {MemberA: {xp_per_hour_24h: 10000, xp_hours_measured: 24}}}, stuck: {members: [{name: "MemberA", blocker: "bag room", since: now - 7200}]}, now});
const unknownCount = M.reportFacts({guild: {members: [{name: "MemberA"}]}, series: {xp_to_level_60_by_member: {MemberA: 360000}, by_member: {MemberA: {xp_per_hour_24h: 10000, xp_hours_measured: 24}}}, now});
console.log(JSON.stringify({got, unknownCount}));
""" % json.dumps((app / "views/now/report.js").as_uri())
            result = subprocess.run(
                [shutil.which("node"), "--input-type=module", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["got"]["dungeons"][0]["attempts"], 4)
        self.assertEqual(data["got"]["dungeons"][0]["clearRate"], 0.5)
        self.assertEqual(
            [d["place"] for d in data["got"]["dungeons"]],
            ["Deadmines", "Wailing Caverns"],
        )
        self.assertEqual(data["got"]["dungeons"][0]["clearsPerAttempt"], 0.5)
        self.assertEqual(data["got"]["topBlocker"]["memberHours"], 2)
        self.assertIsNotNone(data["got"]["projectedAt"])
        self.assertIsNone(data["unknownCount"]["projectedAt"])


if __name__ == "__main__":
    unittest.main()
