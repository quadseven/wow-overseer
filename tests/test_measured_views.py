"""Values the app used to print as "not measured" although the server had them:
XP per hour on a member's profile and in the members table (/api/v2/series),
and the boss count of a guild run that never went in (its own outcome).

Each view is rendered under node from canned reads, the way
test_economy_view.py renders the Economy view.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

PRELUDE = (
    "globalThis.window = {setTimeout: (f) => f(), addEventListener() {},"
    " matchMedia: () => ({matches: false})};\n"
    "globalThis.location = {hash: %s};\n"
    "globalThis.document = {querySelector: () => null, addEventListener() {}};\n"
    "globalThis.history = {replaceState() {}};\n"
    "function ctx(view, params, reads) {\n"
    "  return {view, section: 'members', params, query: {}, hash: location.hash,\n"
    "    isPhone: false, get: (p) => (p in reads ? {data: reads[p], at: 1, error: null}"
    " : {data: undefined, at: 0, error: null, loading: true})};\n"
    "}\n"
)


# The families and guilds /api/realm reports; app/families.js learns them
# before a view is drawn, as main.js does before the first route.
REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


def learn(root):
    """The line that teaches the copied app the realm's families and guilds."""
    return "(await import(%s)).learn(%s);\n" % (
        json.dumps((root / "families.js").as_uri()),
        json.dumps(REALM),
    )


def seeded(root, seed):
    """The lines that answer each read in `seed` (path -> payload) through the
    copied app's own api.js, as a fetch would, before the view is drawn."""
    if not seed:
        return ""
    return (
        "const SEED = %s;\n"
        "globalThis.fetch = async (url) => {\n"
        "  const text = JSON.stringify(SEED[url]);\n"
        "  return {ok: true, status: 200, text: async () => text};\n"
        "};\n"
        "const API = await import(%s);\n"
        "await Promise.all(Object.keys(SEED).map((p) => API.load(p)));\n"
    ) % (json.dumps(seed), json.dumps((root / "api.js").as_uri()))


def render(module, script, hash_="#/members", seed=None):
    """Run `script` with the app copied to a module package; M is `module`.
    `seed` (path -> payload) is what the app's fetch layer already holds."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            PRELUDE % json.dumps(hash_)
            + learn(root)
            + seeded(root, seed)
            + "const M = await import(%s);\n" % json.dumps((root / module).as_uri())
            + script
        )
        out = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", code],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def member(name, guild, level=20):
    return {
        "name": name,
        "guild": guild,
        "family": "",
        "level": level,
        "class": "Warrior",
        "race": "Orc",
        "zone": "Durotar",
        "online": True,
        "life": "alive",
        "stuck": False,
        "step": "Questing",
        "blocker": "",
        "since": None,
    }


ROSTER = {
    "members": [member("Grug", "Cave", 42), member("Zug", "Bonkers", 29)],
    "checked_at": 1_800_000_000,
    "basis": "",
}


def series_for(guild, by_member):
    return {"guild": guild, "members": len(by_member), "by_member": by_member}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheMembersTable(unittest.TestCase):
    def _render(self, reads):
        return render(
            "views/members.js",
            "const reads = %s;\n" % json.dumps(reads)
            + "console.log(JSON.stringify(String(M.default.render(ctx('members', {}, reads)))));",
        )

    def test_the_xp_column_prints_each_members_measured_rate(self):
        out = self._render(
            {
                "/api/v2/roster": ROSTER,
                "/api/v2/series?guild=cave": series_for(
                    "Cave", {"Grug": {"xp_per_hour_24h": 1874, "xp_hours_measured": 24}}
                ),
                "/api/v2/series?guild=bonkers": series_for(
                    "Bonkers",
                    {"Zug": {"xp_per_hour_24h": None, "xp_hours_measured": 0}},
                ),
            }
        )
        self.assertIn('<td class="num">1,874</td>', out)
        # Zug has no measured hour: not measured, never 0.
        self.assertIn(
            '<td class="num"><span class="unmeasured">not measured</span></td>', out
        )
        self.assertIn("XP/h 1,874", out)
        self.assertIn("1 of 2 members have a level change on record", out)
        self.assertNotIn("XP per hour is not measured yet", out)

    def test_without_the_series_reads_every_rate_is_not_measured(self):
        out = self._render({"/api/v2/roster": ROSTER})
        self.assertNotIn("1,874", out)
        self.assertIn("the series reads have not answered", out)

    def test_the_table_sorts_by_xp_per_hour(self):
        out = render(
            "views/members.js",
            "const reads = %s;\n"
            % json.dumps(
                {
                    "/api/v2/roster": ROSTER,
                    "/api/v2/series?guild=cave": series_for(
                        "Cave",
                        {"Grug": {"xp_per_hour_24h": 10, "xp_hours_measured": 3}},
                    ),
                    "/api/v2/series?guild=bonkers": series_for(
                        "Bonkers",
                        {"Zug": {"xp_per_hour_24h": 900, "xp_hours_measured": 24}},
                    ),
                }
            )
            + "console.log(JSON.stringify(String(M.default.render(ctx('members', {}, reads)))));",
            hash_="#/members?sort=xp",
        )
        table = out[out.index("<table") :]
        self.assertLess(table.index(">Zug<"), table.index(">Grug<"))


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheMemberProfile(unittest.TestCase):
    ACTIVITY = {
        "name": "Grug",
        "commands": [],
        "levels": [],
        "level": 42,
        "start_level": 41,
        "days": 7,
        "checked_at": 1_800_000_000,
    }

    def _render(self, ser):
        reads = {
            "/api/v2/roster": ROSTER,
            "/api/v2/activity?name=Grug": self.ACTIVITY,
        }
        if ser is not None:
            reads["/api/v2/series?name=Grug"] = ser
        return render(
            "views/member.js",
            "const reads = %s;\n" % json.dumps(reads)
            + "const c = ctx('member', {name: 'Grug', tab: 'overview'}, reads);\n"
            + "console.log(JSON.stringify([M.default.reads(c), String(M.default.render(c))]));",
            hash_="#/m/Grug",
        )

    def test_the_overview_reads_the_members_series(self):
        reads, _ = self._render(None)
        self.assertIn("/api/v2/series?name=Grug", reads)

    def test_xp_per_hour_is_the_series_rate(self):
        _, out = self._render(
            {"name": "Grug", "xp_per_hour_24h": 874, "xp_hours_measured": 24}
        )
        self.assertIn('<span class="mb-b num">874</span>', out)
        self.assertIn("XP per hour, 24h: 874<", out)
        self.assertNotIn('XP per hour</span><span class="mb-b num"><span', out)

    def test_a_rate_over_part_of_the_day_says_how_many_hours(self):
        _, out = self._render(
            {"name": "Grug", "xp_per_hour_24h": 1500, "xp_hours_measured": 9}
        )
        self.assertIn("XP per hour, 24h: 1,500, over the 9 hours measured", out)

    def test_no_measured_hour_stays_not_measured(self):
        _, out = self._render(
            {"name": "Grug", "xp_per_hour_24h": None, "xp_hours_measured": 0}
        )
        self.assertIn(
            'XP per hour, 24h: <span class="unmeasured">not measured</span>', out
        )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheRunBossLine(unittest.TestCase):
    def test_a_run_that_never_went_in_says_so(self):
        got = render(
            "models/guildruns.js",
            """
console.log(JSON.stringify([
  M.bossText({outcome: "refused", seconds_inside: 0, bosses_total: 0}),
  M.bossText({outcome: "not entered", seconds_inside: 0, bosses_total: 0}),
  M.bossText({outcome: "wiped", seconds_inside: 900, bosses_total: 0}),
  M.bossText({outcome: "cleared", seconds_inside: 900, bosses_done: 7, bosses_total: 7}),
]));""",
        )
        self.assertEqual(
            got,
            [
                "never went in",
                "never went in",
                "bosses not measured",
                "7 of 7 bosses down",
            ],
        )


RUN = {
    "id": 930,
    "place": "The Deadmines",
    "state": "ended",
    "outcome": "wiped",
    "bosses_done": 2,
    "bosses_total": 7,
    "deaths": 5,
    "seconds_inside": 2400,
    "loot_items": 0,
    "members": [
        {"name": "Grug", "seat": "tank", "class": "warrior", "level": 24},
        {"name": "Ugga", "seat": "healer", "class": "priest", "level": 23},
        {"name": "Og", "seat": "dps", "class": "mage", "level": 23},
    ],
    "created_at": "2026-10-13 10:00:00",
    "ended_at": "2026-10-13 10:40:00",
    "bosses": [
        {
            "entry": 644,
            "name": "Rhahk'Zor",
            "killed": True,
            "at": "2026-10-13 10:12:00",
            "by": "Grug",
        },
        {
            "entry": 642,
            "name": "Sneed's Shredder",
            "killed": True,
            "at": "2026-10-13 10:28:00",
            "by": "Ugga",
        },
        {"entry": 643, "name": "Sneed", "killed": False, "at": None, "by": None},
    ],
    "wipes": [
        {
            "entry": 642,
            "name": "Sneed's Shredder",
            "at": "2026-10-13 10:30:00",
            "deaths": 3,
        },
    ],
    "gear": [],
}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheRunPageBosses(unittest.TestCase):
    def test_the_progress_bar_names_every_boss(self):
        got = render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.bossPips(%s))));" % json.dumps(RUN),
        )
        self.assertIn("Rhahk&#39;Zor", got)
        self.assertIn("Sneed&#39;s Shredder", got)
        self.assertIn("Sneed", got)
        self.assertIn('aria-label="2 of 3 bosses down"', got)

    def test_killed_bosses_are_marked_done(self):
        got = render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.bossPips(%s))));" % json.dumps(RUN),
        )
        self.assertIn('class="g-r-pip done"', got)

    def test_the_boss_list_shows_kill_times_and_killers(self):
        got = render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.bossRows(%s))));" % json.dumps(RUN),
        )
        self.assertIn("Rhahk&#39;Zor", got)
        # The time is rendered in the browser's local timezone; just check one
        # appears for the first kill.
        self.assertRegex(got, r"\d{1,2}:\d{2}\s*(AM|PM)")
        self.assertIn('class="g-r-boss killed"', got)
        self.assertIn("no kill recorded", got)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheRunPageTimeline(unittest.TestCase):
    def test_the_timeline_includes_kill_lines(self):
        got = render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.timeline(%s))));" % json.dumps(RUN),
        )
        self.assertIn("The group killed Rhahk&#39;Zor.", got)
        self.assertIn("The group killed Sneed&#39;s Shredder.", got)

    def test_the_timeline_includes_wipe_lines(self):
        got = render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.timeline(%s))));" % json.dumps(RUN),
        )
        self.assertIn("3 deaths to Sneed&#39;s Shredder.", got)


# The /api/guildruns row of RUN: the same run_view, without the gear, bosses
# and wipes only the one-run read (/api/v2/run) carries.
ROW = {k: v for k, v in RUN.items() if k not in ("gear", "bosses", "wipes")}
GEAR = [
    {
        "member": "Grug",
        "entry": 5191,
        "name": "Cruel Barb",
        "quality": 3,
        "source": "looted",
        "at": "2026-10-13 10:29:00",
    }
]


def draw_run(by_id):
    """Render #/runs/930 with RUN in /api/guildruns; `by_id` is what
    /api/v2/run answered, or None while that read is on its way."""
    reads = {"/api/v2/run?id=930": {"run": by_id}} if by_id is not None else {}
    return render(
        "views/run.js",
        'console.log(JSON.stringify(String(M.default.render(ctx("run", {id: "930"}, %s)))));'
        % json.dumps(reads),
        hash_="#/runs/930",
        seed={"/api/guildruns": {"active": [], "recent": [ROW]}},
    )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheRunPageOfARecentRun(unittest.TestCase):
    """#1127: a run /api/guildruns lists is drawn from /api/v2/run once that
    read answers, so its gear, bosses and wipes are shown."""

    def test_its_gear_rows_come_from_the_one_run_read(self):
        got = draw_run(dict(RUN, gear=GEAR))
        self.assertIn("Cruel Barb", got)
        self.assertIn("looted Cruel Barb.", got)
        self.assertNotIn("No gear recorded for this run.", got)

    def test_its_boss_and_wipe_lines_come_from_the_one_run_read(self):
        got = draw_run(dict(RUN, gear=GEAR))
        self.assertIn("The group killed Rhahk&#39;Zor.", got)
        self.assertIn("3 deaths to Sneed&#39;s Shredder.", got)

    def test_while_the_one_run_read_is_on_its_way_the_gear_is_being_read(self):
        got = draw_run(None)
        self.assertIn("The Deadmines", got)
        self.assertIn("Reading the gear...", got)
        self.assertNotIn("No gear recorded for this run.", got)

    def test_a_run_with_no_gear_still_says_so(self):
        got = draw_run(dict(RUN, gear=[]))
        self.assertIn("No gear recorded for this run.", got)


if __name__ == "__main__":
    unittest.main()
