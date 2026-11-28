"""The run page's lead card (#3375): a state sentence, three figures and a
stall line, so a stalled run no longer reads like a healthy slow one.

Each view is rendered under node from canned reads, the way
test_measured_views.py renders the run page. The pure helpers are called
directly with a fixed `now` so the stall thresholds are pinned exactly.
"""

import datetime
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

REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


def learn(root):
    return "(await import(%s)).learn(%s);\n" % (
        json.dumps((root / "families.js").as_uri()),
        json.dumps(REALM),
    )


def seeded(root, seed):
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


def render(module, script, hash_="#/runs/7098", seed=None):
    """Run `script` with the app copied to a module package; M is `module`."""
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


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def boss(name, killed=False, at=None, by=None):
    return {"entry": 0, "name": name, "killed": killed, "at": at, "by": by}


def live_run(now):
    """Inside now, 2 of 23 bosses down, the last kill 48 minutes ago."""
    formed = now - datetime.timedelta(minutes=110, seconds=-20)
    bosses = [boss("Boss %02d" % i) for i in range(1, 24)]
    bosses[0] = boss(
        "Boss 01", True, stamp(now - datetime.timedelta(minutes=95)), "Grug"
    )
    bosses[1] = boss(
        "Boss 02", True, stamp(now - datetime.timedelta(minutes=48, seconds=-20)), "Og"
    )
    return {
        "id": 7098,
        "guild": "Cave",
        "place": "Lower Blackrock Spire",
        "state": "inside",
        "run_state": "inside",
        "outcome": "",
        "bosses_done": 2,
        "bosses_total": 23,
        "deaths": 6,
        "seconds_inside": 60,
        "loot_items": 3,
        "members": [
            {"name": "Grug", "seat": "tank", "class": "warrior", "level": 60},
            {"name": "Og", "seat": "dps", "class": "mage", "level": 60},
        ],
        "created_at": stamp(formed),
        "ended_at": "",
        "bosses": bosses,
        "wipes": [],
        "gear": [],
        "lines": [],
    }


def draw(run):
    """Render #/runs/<id> with the run's row in /api/guildruns and the run
    itself as /api/v2/run's answer."""
    row = {k: v for k, v in run.items() if k not in ("bosses", "wipes", "gear")}
    reads = {"/api/v2/run?id=%s" % run["id"]: {"run": run}}
    return render(
        "views/run.js",
        'console.log(JSON.stringify(String(M.default.render(ctx("run", {id: "%s"}, %s)))));'
        % (run["id"], json.dumps(reads)),
        hash_="#/runs/%s" % run["id"],
        seed={"/api/guildruns": {"active": [row], "recent": []}},
    )


NOW = 1_800_000_000


def at(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def stall(r, now=NOW):
    return render(
        "views/run.js",
        "console.log(JSON.stringify(M.stallLine(%s, %s)));" % (json.dumps(r), now),
    )


def inside_run(**over):
    r = {
        "state": "inside",
        "run_state": "inside",
        "bosses_done": 1,
        "bosses_total": 5,
        "created_at": at(NOW - 6600),
        "bosses": [boss("First", True, at(NOW - 600))],
    }
    r.update(over)
    return r


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheStallLine(unittest.TestCase):
    def test_a_recent_kill_reads_plain(self):
        got = stall(inside_run())
        self.assertEqual(got, {"text": "Last boss 10m ago", "tone": ""})

    def test_past_twenty_five_minutes_warns(self):
        r = inside_run(bosses=[boss("First", True, at(NOW - 26 * 60))])
        self.assertEqual(stall(r), {"text": "Last boss 26m ago", "tone": "warn"})

    def test_at_twenty_five_minutes_it_does_not_warn_yet(self):
        r = inside_run(bosses=[boss("First", True, at(NOW - 25 * 60))])
        self.assertEqual(stall(r)["tone"], "")

    def test_past_forty_minutes_is_bad(self):
        r = inside_run(bosses=[boss("First", True, at(NOW - 41 * 60))])
        self.assertEqual(stall(r), {"text": "Last boss 41m ago", "tone": "bad"})

    def test_at_forty_minutes_it_is_still_only_a_warning(self):
        r = inside_run(bosses=[boss("First", True, at(NOW - 40 * 60))])
        self.assertEqual(stall(r)["tone"], "warn")

    def test_no_kill_yet_counts_from_the_start(self):
        r = inside_run(
            bosses_done=0,
            bosses=[boss("First")],
            created_at=at(NOW - 600),
        )
        self.assertEqual(stall(r), {"text": "No boss down yet, 10m in", "tone": ""})

    def test_no_kill_for_thirty_minutes_warns(self):
        r = inside_run(
            bosses_done=0,
            bosses=[boss("First")],
            created_at=at(NOW - 1800),
        )
        self.assertEqual(stall(r), {"text": "No boss down yet, 30m in", "tone": "warn"})

    def test_a_kill_the_count_claims_but_no_row_names_is_not_timed_from_a_kill(self):
        r = inside_run(bosses_done=2, bosses=[], created_at=at(NOW - 3600))
        got = stall(r)
        self.assertEqual(got["text"], "Last boss not named in the record, 1h 0m inside")
        self.assertEqual(got["tone"], "bad")

    def test_an_ended_run_has_no_stall_line(self):
        r = inside_run(state="ended", run_state="wiped", ended_at=at(NOW - 60))
        self.assertIsNone(stall(r))

    def test_no_formed_time_falls_back_to_the_seconds_inside(self):
        r = inside_run(bosses_done=0, bosses=[], created_at="", seconds_inside=3600)
        self.assertEqual(
            stall(r), {"text": "No boss down yet, 1h 0m in", "tone": "bad"}
        )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheStateSentence(unittest.TestCase):
    def sentence(self, r):
        return render(
            "views/run.js",
            "console.log(JSON.stringify(M.stateSentence(%s)));" % json.dumps(r),
        )

    def test_inside(self):
        r = inside_run(
            bosses_done=2,
            bosses_total=23,
            bosses=[boss("B%02d" % i, i < 2) for i in range(23)],
        )
        self.assertEqual(self.sentence(r), "Inside now, 2 of 23 bosses down")

    def test_cleared_in_full(self):
        r = inside_run(
            state="ended",
            run_state="cleared",
            outcome="cleared",
            bosses_done=7,
            bosses_total=7,
            bosses=[boss("B%d" % i, True) for i in range(7)],
        )
        self.assertEqual(self.sentence(r), "Cleared, 7 of 7 bosses down")

    def test_cleared_short_is_finished_not_cleared(self):
        r = inside_run(
            state="ended",
            run_state="cleared",
            outcome="cleared",
            bosses_done=4,
            bosses_total=5,
            bosses=[boss("B%d" % i, i < 4) for i in range(5)],
        )
        self.assertEqual(self.sentence(r), "Finished, 4 of 5 bosses down")

    def test_wiped(self):
        r = inside_run(state="ended", run_state="wiped", outcome="wiped")
        self.assertEqual(self.sentence(r), "Wiped, 1 of 5 bosses down")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheLeadCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = datetime.datetime.now(datetime.timezone.utc)
        cls.page = draw(live_run(now))

    def test_the_state_sentence_leads(self):
        self.assertIn("Inside now, 2 of 23 bosses down", self.page)

    def test_the_three_figures(self):
        self.assertIn("2 / 23", self.page)
        self.assertIn("Bosses", self.page)
        self.assertIn("Time inside", self.page)
        self.assertIn("Deaths", self.page)
        self.assertIn(">6<", self.page)

    def test_time_inside_is_counted_from_the_start_not_the_stale_snapshot(self):
        # The fixture's seconds_inside says 60; the run formed 110 minutes
        # ago, and the figure follows the forming time so it ticks.
        self.assertIn("1h 50m", self.page)

    def test_the_stall_line_is_drawn_with_its_bad_tone(self):
        self.assertRegex(self.page, r"Last boss 4\dm ago")
        self.assertIn('data-gt="bad"', self.page)

    def test_the_header_says_when_the_page_updated(self):
        self.assertIn("updated", self.page)
        self.assertIn("refreshes every 15 seconds", self.page)

    def test_the_runs_own_lines_stay_on_the_page_under_the_lead(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        r = live_run(now)
        r.update(
            {
                "id": 7103,
                "state": "ended",
                "run_state": "wiped",
                "outcome": "wiped",
                "ended_at": stamp(now - datetime.timedelta(minutes=5)),
                "lines": ["dungeon: Lower Blackrock Spire, the levels fit"],
                "cause": "Cause: the tank died",
                "story": "A short tale of the run.",
                "band_line": "levels 55 to 60",
            }
        )
        page = draw(r)
        self.assertIn("dungeon: Lower Blackrock Spire, the levels fit", page)
        self.assertIn("the tank died", page)
        self.assertIn("A short tale of the run.", page)
        self.assertIn("levels 55 to 60", page)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheBossGroups(unittest.TestCase):
    def groups(self, r):
        return render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.bossGroups(%s))));" % json.dumps(r),
        )

    def small_run(self):
        return {
            "bosses_done": 2,
            "bosses_total": 3,
            "bosses": [
                boss("Rhahk'Zor", True, at(NOW - 3600), "Grug"),
                boss("Sneed", True, at(NOW - 1800), "Ugga"),
                boss("Edwin VanCleef"),
            ],
        }

    def test_down_next_and_still_to_come(self):
        got = self.groups(self.small_run())
        self.assertIn("Down", got)
        self.assertIn("Rhahk&#39;Zor", got)
        self.assertIn("Next", got)
        self.assertIn("Edwin VanCleef", got)
        self.assertIn("NEXT", got)
        # A three-boss run needs no fold: every group is on the page.
        self.assertNotIn("<details", got)

    def test_the_next_boss_is_the_first_unkilled(self):
        got = self.groups(self.small_run())
        self.assertRegex(
            got,
            r'<span class="g-r-boss-name">Edwin VanCleef</span>.*NEXT',
        )

    def test_still_to_come_folds_behind_a_toggle_past_eight_bosses(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        got = self.groups(live_run(now))
        self.assertIn("<details", got)
        self.assertIn("Still to come, 20 more bosses", got)
        self.assertIn("Boss 23", got)

    def test_a_full_clear_has_no_next_or_still_to_come(self):
        r = self.small_run()
        r["bosses"][2] = boss("Edwin VanCleef", True, at(NOW - 60), "Grug")
        r["bosses_done"] = 3
        got = self.groups(r)
        self.assertIn("Down", got)
        self.assertNotIn("NEXT", got)
        self.assertNotIn("Still to come", got)

    def test_no_named_list_no_groups(self):
        self.assertEqual(self.groups({"bosses": []}), "")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheUnverifiedRule(unittest.TestCase):
    def unv(self, r):
        return render(
            "views/run.js",
            "console.log(JSON.stringify(M.unverified(%s)));" % json.dumps(r),
        )

    def test_a_count_with_no_named_kill_is_unverified(self):
        r = {"bosses_done": 3, "bosses_total": 4, "bosses": []}
        self.assertEqual(
            self.unv(r),
            "Count says 3 of 4 down, but no boss kills are named in the "
            "record. Treat this run as unverified.",
        )

    def test_a_count_ahead_of_the_named_kills_is_unverified(self):
        r = {
            "bosses_done": 3,
            "bosses_total": 4,
            "bosses": [
                boss("One", True, at(NOW - 60), "Grug"),
                boss("Two"),
                boss("Three"),
                boss("Four"),
            ],
        }
        self.assertEqual(
            self.unv(r),
            "Count says 3 of 4 down, but the record names only 1 boss "
            "kill. Treat this run as unverified.",
        )

    def test_a_list_that_accounts_for_the_count_is_verified(self):
        r = {
            "bosses_done": 2,
            "bosses_total": 3,
            "bosses": [boss("One", True), boss("Two", True), boss("Three")],
        }
        self.assertIsNone(self.unv(r))

    def test_no_named_list_yet_is_not_a_verdict(self):
        self.assertIsNone(self.unv({"bosses_done": 3, "bosses_total": 4}))

    def test_no_count_measured_is_not_a_verdict(self):
        self.assertIsNone(self.unv({"bosses_done": 0, "bosses_total": 0, "bosses": []}))

    def test_the_strip_draws_no_clean_pips_for_an_unverified_run(self):
        got = render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.bossPips(%s))));"
            % json.dumps({"bosses_done": 3, "bosses_total": 4, "bosses": []}),
        )
        self.assertNotIn('class="done"', got)
        self.assertNotIn("g-r-pip", got)
        self.assertEqual(got.count("<span"), 4)
        self.assertEqual(got.count('class="unknown"'), 4)

    def test_the_page_prints_the_sentence_and_never_the_count_as_fact(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        r = live_run(now)
        r.update(
            {
                "id": 7096,
                "state": "ended",
                "run_state": "cleared",
                "outcome": "cleared",
                "bosses_done": 3,
                "bosses_total": 4,
                "bosses": [],
                "ended_at": stamp(now - datetime.timedelta(minutes=5)),
            }
        )
        page = draw(r)
        self.assertIn(
            "Count says 3 of 4 down, but no boss kills are named in the "
            "record. Treat this run as unverified.",
            page,
        )
        self.assertNotIn("3 of 4 bosses down", page)
        self.assertNotIn("3 / 4", page)
        self.assertNotIn('class="done"', page)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheShortfallRule(unittest.TestCase):
    def short(self, r):
        return render(
            "views/run.js",
            "console.log(JSON.stringify(M.shortfall(%s)));" % json.dumps(r),
        )

    def ended(self, **over):
        r = {
            "state": "ended",
            "run_state": "cleared",
            "outcome": "cleared",
            "bosses_done": 4,
            "bosses_total": 5,
            "ended_at": at(NOW - 60),
            "bosses": [
                boss("One", True),
                boss("Two", True),
                boss("Three", True),
                boss("Four", True),
                boss("Five"),
            ],
        }
        r.update(over)
        return r

    def test_a_short_finish_names_the_final_boss_when_it_is_still_up(self):
        self.assertEqual(
            self.short(self.ended()),
            "Ended with 1 of 5 bosses still up, including the final boss.",
        )

    def test_without_a_named_list_the_final_boss_is_not_claimed(self):
        self.assertEqual(
            self.short(self.ended(bosses=[])),
            "Ended with 1 of 5 bosses still up.",
        )

    def test_a_wipe_ends_short_too(self):
        r = self.ended(run_state="wiped", outcome="wiped", bosses_done=2)
        self.assertEqual(
            self.short(r),
            "Ended with 3 of 5 bosses still up, including the final boss.",
        )

    def test_a_full_clear_has_no_shortfall(self):
        self.assertIsNone(self.short(self.ended(bosses_done=5)))

    def test_a_run_still_inside_has_no_shortfall(self):
        r = self.ended(state="inside", run_state="inside", ended_at="")
        self.assertIsNone(self.short(r))

    def test_the_page_prints_the_sentence_and_no_green_check(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        r = live_run(now)
        r.update(
            {
                "id": 7101,
                "state": "ended",
                "run_state": "cleared",
                "outcome": "cleared",
                "bosses_done": 4,
                "bosses_total": 5,
                "bosses": [
                    boss("One", True, at(NOW - 3600), "Grug"),
                    boss("Two", True, at(NOW - 3000), "Grug"),
                    boss("Three", True, at(NOW - 2000), "Og"),
                    boss("Four", True, at(NOW - 1000), "Og"),
                    boss("Five"),
                ],
                "ended_at": stamp(now - datetime.timedelta(minutes=5)),
            }
        )
        page = draw(r)
        self.assertIn(
            "Ended with 1 of 5 bosses still up, including the final boss.", page
        )
        self.assertNotIn("ph-check-circle", page)
        self.assertIn('data-gt="warn"', page)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheDoneCardPips(unittest.TestCase):
    def card(self, r, done):
        return render(
            "views/_runs.js",
            "console.log(JSON.stringify(String(M.runCard(%s, {done: %s}))));"
            % (json.dumps(r), "true" if done else "false"),
        )

    def row(self, **over):
        r = {
            "id": 514,
            "place": "The Deadmines",
            "state": "ended",
            "run_state": "cleared",
            "outcome": "cleared",
            "bosses_done": 2,
            "bosses_total": 7,
            "seconds_inside": 600,
            "members": [],
            "lines": [],
            "created_at": at(NOW - 3600),
            "ended_at": at(NOW - 60),
        }
        r.update(over)
        return r

    def test_a_done_card_draws_pips_with_the_unkilled_in_bad_tone(self):
        got = self.card(self.row(), True)
        self.assertIn("g-pips", got)
        self.assertEqual(got.count('class="done"'), 2)
        self.assertEqual(got.count('class="fail"'), 5)

    def test_a_done_full_clear_draws_no_bad_segment(self):
        got = self.card(self.row(bosses_done=7), True)
        self.assertEqual(got.count('class="done"'), 7)
        self.assertNotIn('class="fail"', got)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheTimeline(unittest.TestCase):
    def timeline(self, r, filter=None):
        call = (
            "M.timeline(%s)" % json.dumps(r)
            if filter is None
            else "M.timeline(%s, %s)" % (json.dumps(r), json.dumps(filter))
        )
        return render(
            "views/run.js",
            "console.log(JSON.stringify(String(%s)));" % call,
        )

    def fixture(self, **over):
        r = {
            "state": "inside",
            "run_state": "inside",
            "bosses_done": 2,
            "bosses_total": 3,
            "members": [],
            "lines": [],
            "created_at": at(NOW - 3600),
            "ended_at": "",
            "bosses": [
                boss("Alpha", True, at(NOW - 3000), "Grug"),
                boss("Beta", True, at(NOW - 600), "Og"),
                boss("Gamma"),
            ],
            "wipes": [{"entry": 0, "name": "Beta", "at": at(NOW - 900), "deaths": 3}],
            "gear": [
                {
                    "member": "Grug",
                    "entry": 1,
                    "name": "Sword",
                    "quality": 3,
                    "source": "looted",
                    "at": at(NOW - 1200),
                }
            ],
        }
        r.update(over)
        return r

    def test_a_live_run_reads_newest_first(self):
        got = self.timeline(self.fixture())
        self.assertLess(got.index("killed Beta"), got.index("killed Alpha"))
        self.assertLess(got.index("killed Alpha"), got.index("Formed"))

    def test_an_ended_run_reads_oldest_first(self):
        r = self.fixture(state="ended", run_state="wiped", ended_at=at(NOW - 60))
        got = self.timeline(r)
        self.assertLess(got.index("Formed"), got.index("killed Alpha"))
        self.assertLess(got.index("killed Alpha"), got.index("killed Beta"))

    def test_the_loot_filter_keeps_only_loot(self):
        got = self.timeline(self.fixture(), "loot")
        self.assertIn("looted Sword.", got)
        self.assertNotIn("killed Alpha", got)
        self.assertNotIn("Formed", got)

    def test_the_boss_filter_keeps_kills_and_wipes(self):
        got = self.timeline(self.fixture(), "boss")
        self.assertIn("killed Alpha", got)
        self.assertIn("3 deaths to Beta.", got)
        self.assertNotIn("looted Sword.", got)

    def test_the_cap_says_so_when_it_bites(self):
        gear = [
            {
                "member": "Grug",
                "entry": i,
                "name": "Item %02d" % i,
                "quality": 2,
                "source": "looted",
                "at": at(NOW - 3500 + i * 60),
            }
            for i in range(45)
        ]
        got = self.timeline(self.fixture(gear=gear))
        self.assertIn("Showing the last 40 events", got)
        self.assertEqual(got.count('class="g-step"'), 40)

    def test_no_cap_note_under_the_cap(self):
        got = self.timeline(self.fixture())
        self.assertNotIn("Showing the last 40 events", got)

    def test_the_page_labels_the_order(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertIn("Newest first", draw(live_run(now)))
        r = live_run(now)
        r.update(
            {
                "id": 7102,
                "state": "ended",
                "run_state": "wiped",
                "outcome": "wiped",
                "ended_at": stamp(now - datetime.timedelta(minutes=5)),
            }
        )
        page = draw(r)
        self.assertIn("Oldest first", page)
        self.assertIn('data-tl-filter="boss"', page)
        self.assertIn('data-tl-filter="loot"', page)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheBossStrip(unittest.TestCase):
    def pips(self, r):
        return render(
            "views/run.js",
            "console.log(JSON.stringify(String(M.bossPips(%s))));" % json.dumps(r),
        )

    def test_past_eight_bosses_the_strip_is_a_segmented_bar_with_no_names(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        got = self.pips(live_run(now))
        self.assertIn('class="g-pips g-pips-lg"', got)
        self.assertNotIn("Boss 01", got)
        self.assertEqual(got.count("<span"), 23)
        self.assertEqual(got.count('class="done"'), 2)

    def test_eight_bosses_still_get_named_cells(self):
        r = {
            "bosses_done": 1,
            "bosses_total": 8,
            "bosses": [boss("Boss %d" % i, i == 1) for i in range(1, 9)],
        }
        got = self.pips(r)
        self.assertIn("g-r-pip", got)
        self.assertIn("Boss 1", got)

    def test_nine_bosses_switch_to_the_bar(self):
        r = {
            "bosses_done": 1,
            "bosses_total": 9,
            "bosses": [boss("Boss %d" % i, i == 1) for i in range(1, 10)],
        }
        got = self.pips(r)
        self.assertIn('class="g-pips g-pips-lg"', got)
        self.assertNotIn("g-r-pip", got)


if __name__ == "__main__":
    unittest.main()
