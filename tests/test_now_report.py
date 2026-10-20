"""The Now report is assembled from read-only guild and status reads."""

import json
import os
import pathlib
import re
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
            # These fields match apiv2.guild.dungeon_rows/_tally,
            # apiv2.series.guild_series, and apiv2.members.stuck_view.
            script = """
const M = await import(%s);
const now = 200000;
const got = M.reportFacts({guild: {count: 1, members: [{name: "MemberA"}], dungeons: [{place: "Wailing Caverns", floor: 22, ceiling: 32, runs: 3, cleared: 1}, {place: "Deadmines", floor: 17, ceiling: 26, runs: 4, cleared: 2, wiped: 2}]}, series: {level: [[1, 20], [86401, 21]], xp_to_level_60_by_member: {MemberA: 360000}, by_member: {MemberA: {xp_per_hour_24h: 10000, xp_hours_measured: 24}}, level_60_projection: {at: now + 36 * 3600, why: ""}}, stuck: {members: [{name: "MemberA", blocker: "bag room", since: now - 7200}]}, now});
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
        # The projection is the series' own (level_60_projection, #1256),
        # not a sum the page does: a bridge without the field gives none.
        self.assertEqual(
            data["got"]["projection"], {"at": 200000 + 36 * 3600, "why": ""}
        )
        self.assertIsNone(data["unknownCount"]["projection"])
        self.assertNotIn("projectedAt", data["got"])


def guild_report(series):
    """report.js reportSection() for one guild whose series read is `series`,
    under node, as markup. The clock is UTC so a date reads the same anywhere."""
    with tempfile.TemporaryDirectory() as tmp:
        app = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, app)
        (app / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        script = """
const M = await import(%s);
const reads = {
  "/api/v2/guild?guild=cave": {data: {count: 1, now: 1790000000, members: [{name: "MemberA"}], dungeons: []}},
  "/api/v2/series?guild=cave": {data: %s},
  "/api/v2/stuck": {data: {members: []}},
};
const ctx = {get: (path) => reads[path] || {data: undefined, loading: true}};
const out = M.reportSection(ctx, [{name: "Cave", slug: "cave"}]);
console.log(JSON.stringify(String(out.s !== undefined ? out.s : out)));
""" % (json.dumps((app / "views/now/report.js").as_uri()), json.dumps(series))
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": os.environ.get("PATH", ""), "TZ": "UTC"},
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def foot(markup):
    """The text of the card's foot line, or None when the card has none."""
    m = re.search(r'<p class="nr-foot muted">(.*?)</p>', markup, re.S)
    return None if m is None else m.group(1)


SERIES = {
    "level": [[1, 20], [86401, 21]],
    "xp_to_level_60_by_member": {"MemberA": 360000},
    "by_member": {"MemberA": {"xp_per_hour_24h": 10000, "xp_hours_measured": 24}},
}
# 2026-11-02 12:00 UTC.
NOV_2 = 1793620800


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app modules")
class LevelSixtyFoot(unittest.TestCase):
    """The Guild progress card ends with the series' level 60 projection
    (/api/v2/series level_60_projection, #1256) as one muted line."""

    def test_a_date_when_the_series_gives_one(self):
        got = guild_report(dict(SERIES, level_60_projection={"at": NOV_2, "why": ""}))
        self.assertEqual(foot(got), "Level 60 by Nov 2, 2026")

    def test_the_why_when_there_is_no_date(self):
        why = (
            "Not measured: 1 member with no rate (MemberA: no level change on "
            "record in the last 7 days, and one instant is not a rate)."
        )
        got = guild_report(dict(SERIES, level_60_projection={"at": None, "why": why}))
        self.assertEqual(foot(got), "Level 60 | " + why)

    def test_a_date_and_its_note_when_everyone_is_at_60(self):
        got = guild_report(
            dict(
                SERIES,
                level_60_projection={
                    "at": NOV_2,
                    "why": "Every member is at level 60.",
                },
            )
        )
        self.assertEqual(
            foot(got), "Level 60 by Nov 2, 2026 | Every member is at level 60."
        )

    def test_an_older_bridge_without_the_field_shows_nothing(self):
        got = guild_report(SERIES)
        self.assertIsNone(foot(got))
        self.assertNotIn("Level 60", got)
        self.assertNotIn("Projection not measured", got)

    def test_the_why_stays_text(self):
        got = guild_report(
            dict(SERIES, level_60_projection={"at": None, "why": "<b>x</b>"})
        )
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", foot(got))


def ladder(dungeons):
    """report.js ladder() over these rows, run under node."""
    with tempfile.TemporaryDirectory() as tmp:
        app = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, app)
        (app / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        script = """
const M = await import(%s);
console.log(JSON.stringify(M.ladder(%s)));
""" % (json.dumps((app / "views/now/report.js").as_uri()), json.dumps(dungeons))
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def row(place, floor, attempts, cleared, inside=False):
    return {
        "place": place,
        "floor": floor,
        "ceiling": floor + 8,
        "attempts": attempts,
        "cleared": cleared,
        "inside": inside,
    }


# A guild part way up: a low dungeon tried and never cleared, a run of
# clears, and above the highest clear two dungeons on one floor, one tried.
CLIMBING = [
    row("Uldaman", 34, 0, 0),
    row("Ragefire Chasm", 15, 1, 0),
    row("The Deadmines", 17, 149, 50, inside=True),
    row("Razorfen Kraul", 30, 11, 8),
    row("Razorfen Downs", 33, 0, 0),
    row("Scarlet Monastery (the Library)", 33, 1, 0),
    row("Scholomance", 58, 0, 0),
]


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app modules")
class DungeonLadder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = ladder(CLIMBING)

    def test_every_dungeon_in_level_order_with_its_state(self):
        steps = [(s["place"], s["state"]) for s in self.got["steps"]]
        self.assertEqual(
            steps,
            [
                ("Ragefire Chasm", "tried"),
                ("The Deadmines", "cleared"),
                ("Razorfen Kraul", "cleared"),
                ("Razorfen Downs", "open"),
                ("Scarlet Monastery (the Library)", "tried"),
                ("Uldaman", "open"),
                ("Scholomance", "open"),
            ],
        )

    def test_the_counts_add_up(self):
        g = self.got
        self.assertEqual(
            (g["total"], g["cleared"], g["tried"], g["open"]), (7, 2, 2, 3)
        )
        self.assertEqual(len(g["reached"]), 4)
        self.assertEqual(
            [s["place"] for s in g["unreached"]],
            ["Razorfen Downs", "Uldaman", "Scholomance"],
        )

    def test_the_frontier_is_above_the_highest_clear_and_prefers_the_tried_one(self):
        # A low dungeon tried without a clear (Ragefire) is not the frontier.
        self.assertEqual(
            self.got["frontier"]["place"], "Scarlet Monastery (the Library)"
        )
        marked = [s["place"] for s in self.got["steps"] if s["frontier"]]
        self.assertEqual(marked, ["Scarlet Monastery (the Library)"])

    def test_the_rate_and_inside_come_from_the_row(self):
        dm = self.got["steps"][1]
        self.assertAlmostEqual(dm["rate"], 50 / 149)
        self.assertTrue(dm["inside"])
        self.assertIsNone(self.got["steps"][3]["rate"], "no attempts: no rate, not 0")

    def test_nothing_cleared_puts_the_frontier_at_the_bottom(self):
        got = ladder(
            [row("Wailing Caverns", 17, 0, 0), row("Ragefire Chasm", 15, 0, 0)]
        )
        self.assertEqual(got["frontier"]["place"], "Ragefire Chasm")
        self.assertEqual(got["cleared"], 0)

    def test_everything_cleared_has_no_frontier(self):
        got = ladder(
            [row("Ragefire Chasm", 15, 2, 1), row("Wailing Caverns", 17, 3, 3)]
        )
        self.assertIsNone(got["frontier"])
        self.assertEqual(got["unreached"], [])

    def test_no_dungeons_is_an_empty_ladder(self):
        got = ladder([])
        self.assertEqual((got["total"], got["frontier"]), (0, None))

    def test_the_api_rows_count_runs_as_attempts(self):
        # /api/v2/guild sends `runs`; reportFacts renames it `attempts`.
        got = ladder([{"place": "The Stockade", "floor": 24, "runs": 14, "cleared": 0}])
        self.assertEqual(got["steps"][0]["attempts"], 14)
        self.assertEqual(got["steps"][0]["state"], "tried")


if __name__ == "__main__":
    unittest.main()
