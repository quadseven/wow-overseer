"""The Dungeons tab's run timeline, asserted against the module and the page.

The rows come from mod-overseer's overseer_dungeon_run_event (mod-overseer#616).
The cases below are mostly about how rows become runs, because a run row does
not exist until somebody is on the instance map and the early phases carry run
id 0: the split has to come from what the rows say.
"""

import pathlib
import unittest
from datetime import datetime, timezone

import runtimeline

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
NOW = datetime(2026, 9, 23, 20, 0, 0, tzinfo=timezone.utc)

_ids = iter(range(1, 10_000))


def row(
    kind,
    detail,
    phase="",
    campaign=8,
    number=1,
    run_id=0,
    age=60,
    family="Zug",
    character="",
):
    return {
        "id": next(_ids),
        "family": family,
        "leader_name": "Zug",
        "character_name": character,
        "run_id": run_id,
        "campaign_id": campaign,
        "run_number": number,
        "portal": "ragefire",
        "phase": phase,
        "kind": kind,
        "detail": detail,
        "age_seconds": age,
    }


def a_failed_run(number=1, run_id=0):
    return [
        row(
            "phase",
            "IDLE -> RESET (ragefire, run %d of campaign 8)" % number,
            "RESET",
            number=number,
        ),
        row("phase", "RESET -> GATHERING", "GATHERING", number=number),
        row("phase", "GATHERING -> BARRIER", "BARRIER", number=number),
        row(
            "ended",
            "staging_failed: BARRIER held for more than 12 minutes",
            "BARRIER",
            number=number,
            run_id=run_id,
        ),
        row("phase", "BARRIER -> IDLE", "IDLE", number=number),
    ]


class HowRowsBecomeRuns(unittest.TestCase):
    def test_one_run_from_open_to_close_is_one_run(self):
        runs = runtimeline.split_runs(a_failed_run())
        self.assertEqual(len(runs), 1)
        self.assertEqual(len(runs[0]["rows"]), 5)

    def test_the_phase_back_to_idle_belongs_to_the_run_it_ends(self):
        runs = runtimeline.split_runs(a_failed_run())
        self.assertEqual(runs[0]["rows"][-1]["detail"], "BARRIER -> IDLE")

    def test_two_attempts_with_the_same_numbers_are_two_runs(self):
        """Campaign 0, run 1, three times in a row is what a staging that never
        opens looks like. The numbers cannot split them; the ends do."""
        rows = a_failed_run() + a_failed_run()
        self.assertEqual(len(runtimeline.split_runs(rows)), 2)

    def test_a_rearm_opens_the_next_run_without_passing_idle(self):
        rows = [
            row("phase", "CLEARING -> EXIT", "EXIT", number=1, run_id=5),
            row(
                "ended",
                "complete: every encounter credited",
                "EXIT",
                number=1,
                run_id=5,
            ),
            row("phase", "EXIT -> REPAIRING", "REPAIRING", number=2),
            row("phase", "REPAIRING -> RESET", "RESET", number=2),
        ]
        runs = runtimeline.split_runs(rows)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[1]["key"], (8, 2))

    def test_a_run_adopted_after_a_restart_is_a_new_run(self):
        rows = [
            row("phase", "GATHERING -> BARRIER", "BARRIER"),
            row("phase", "IDLE -> STAGED_INSIDE", "STAGED_INSIDE"),
        ]
        self.assertEqual(len(runtimeline.split_runs(rows)), 2)


class ThePayload(unittest.TestCase):
    def build(self, rows, families=None):
        return runtimeline.build_run_timeline(
            rows, families if families is not None else {"Zug": ["Zug", "Oz"]}, now=NOW
        )

    def test_newest_run_first_and_only_it_open(self):
        rows = a_failed_run(1, run_id=11) + a_failed_run(2, run_id=12)
        fam = self.build(rows)["families"][0]
        self.assertEqual(len(fam["runs"]), 2)
        self.assertIn("run row 12", fam["runs"][0]["title"])
        self.assertTrue(fam["runs"][0]["open"])
        self.assertFalse(fam["runs"][1]["open"])

    def test_an_ended_run_says_how_in_the_modules_words(self):
        fam = self.build(a_failed_run())["families"][0]
        run = fam["runs"][0]
        self.assertIn(
            "staging_failed: BARRIER held for more than 12 minutes", run["line"]
        )
        self.assertEqual(run["tone"], "bad")

    def test_a_run_still_going_says_where_it_is(self):
        rows = a_failed_run()[:3]
        run = self.build(rows)["families"][0]["runs"][0]
        self.assertIn("under way, now BARRIER", run["line"])
        self.assertEqual(run["tone"], "live")

    def test_only_the_last_few_runs_are_drawn(self):
        rows = []
        for number in range(1, 8):
            rows += a_failed_run(number)
        fam = self.build(rows)["families"][0]
        self.assertEqual(len(fam["runs"]), runtimeline.RUNS_PER_FAMILY)

    def test_a_dc_on_row_names_its_character(self):
        rows = a_failed_run()[:2] + [
            row(
                "dc_on_refused",
                "'dc on' refused for 'Oz'; retrying",
                "CLEARING",
                character="Oz",
            )
        ]
        events = self.build(rows)["families"][0]["runs"][0]["events"]
        self.assertTrue(events[-1]["line"].startswith("Oz: "))
        self.assertEqual(events[-1]["tone"], "warn")

    def test_every_family_on_the_roster_gets_a_block_even_with_no_rows(self):
        payload = self.build([], {"Grug": ["Grug"], "Zug": ["Zug"]})
        self.assertEqual([f["title"] for f in payload["families"]], ["Grug", "Zug"])
        self.assertIn("No run in the last", payload["families"][0]["line"])

    def test_the_row_time_is_the_age_from_the_database_clock(self):
        rows = [row("phase", "IDLE -> RESET", "RESET", age=3600)]
        event = self.build(rows)["families"][0]["runs"][0]["events"][0]
        self.assertRegex(event["at"], r"^\d\d:\d\d:\d\d$")

    def test_a_realm_without_the_table_says_so(self):
        payload = runtimeline.build_run_timeline(
            [], {"Zug": ["Zug"]}, now=NOW, present=False
        )
        self.assertIn("overseer_dungeon_run_event", payload["line"])
        self.assertEqual(payload["families"], [])


class ThePageAndTheEndpoint(unittest.TestCase):
    def test_it_is_routed_and_read_without_parameters(self):
        self.assertIn('"/api/runtimeline": _run_timeline,', SERVER)
        handler = SERVER[SERVER.index("def _run_timeline") : SERVER.index("def _recap")]
        self.assertNotIn("query.get", handler)
        self.assertIn("self._send(503", handler)

    def test_the_read_is_guarded_and_bounded(self):
        fetch = SERVER[SERVER.index("def _fetch_run_timeline") :]
        fetch = fetch[: fetch.index("\n\n\n")]
        self.assertNotIn("cur.execute", fetch)
        self.assertIn("runtimeline.ROW_LIMIT", fetch)
        sql = SERVER[SERVER.index("_RUN_TIMELINE = (") :]
        self.assertIn("LIMIT %s", sql[: sql.index(")\n")])

    def test_the_page_prints_the_modules_strings(self):
        block = PAGE[
            PAGE.index("function rtlRender") : PAGE.index(
                "setInterval(() => { if (view === DUNGEONS_VIEW) pollRunTimeline(); }"
            )
        ]
        for key in (
            "p.line",
            "f.title",
            "f.line",
            "run.title",
            "run.line",
            "ev.at",
            "ev.line",
        ):
            self.assertIn(key, block, key)
        self.assertIn('fetch(u("/api/runtimeline"),', block)
        self.assertIn("rtlPulling = false;", block[block.index("} finally {") :])

    def test_opening_the_tab_pulls_it(self):
        show = PAGE[PAGE.index("if (isDgn) {") :]
        self.assertIn("pollRunTimeline();", show[: show.index("return;")])

    def test_the_markup_is_on_the_dungeons_tab(self):
        section = PAGE[PAGE.index('<section id="dungeons">') :]
        section = section[: section.index("</section>")]
        self.assertIn('id="rtlfamilies"', section)
        self.assertIn('id="rtlline"', section)

    def test_the_module_is_copied_into_the_container(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("runtimeline.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
