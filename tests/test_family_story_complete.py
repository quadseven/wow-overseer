"""A family run's story never believes the run's own `complete` word (#2284).

The Blackrock Depths incident: a run's completion flag credited a clear that
its encounter record did not support. The family story used to open "cleared"
on `complete` alone. These runs are invented (a seven-boss dungeon, rows in the
shape `runtimeline.split_runs` yields); nothing here is a realm capture.
"""

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import runstory  # noqa: E402


def a_run(credited_each, outcome="complete"):
    """A run that went inside, credited bosses one row at a time, and ended."""
    rows = [
        {
            "kind": "phase",
            "phase": "GATHERING",
            "detail": "IDLE -> GATHERING (wailing, run 1 of campaign 4)",
            "portal": "wailing",
            "age_seconds": 3000,
        },
        {
            "kind": "phase",
            "phase": "STAGED_INSIDE",
            "detail": "ENTER -> STAGED_INSIDE",
            "age_seconds": 2900,
        },
    ]
    running = 0
    for n, got in enumerate(credited_each):
        running += got
        rows.append(
            {
                "kind": "boss",
                "phase": "CLEARING",
                "detail": "%d encounter%s credited, %d in all"
                % (got, "" if got == 1 else "s", running),
                "age_seconds": 2800 - n * 100,
            }
        )
    ended = {
        "kind": "ended",
        "phase": "CLEARING",
        "detail": outcome + ": every encounter credited",
        "age_seconds": 600,
    }
    rows.append(ended)
    return {"rows": rows, "ended": ended}


def told(run, **kw):
    return runstory.family_story(run, [], ["Grug"], **kw)


class AFlagIsNotAClear(unittest.TestCase):
    def test_a_short_tally_is_not_called_cleared(self):
        out = told(a_run([1] * 6), total=7)
        self.assertNotIn("cleared", out["story"].lower())
        self.assertNotIn("cleared", out["cause"].lower())
        self.assertEqual(
            out["story"], "Finished Wailing Caverns short, 6 of 7 bosses down."
        )
        self.assertEqual(
            out["cause"],
            "Finished short: the run reported complete at 6 of 7 credited encounters.",
        )

    def test_no_known_total_is_not_called_cleared_either(self):
        out = told(a_run([1] * 7))
        self.assertNotIn("cleared", out["story"].lower())
        self.assertNotIn("cleared", out["cause"].lower())
        self.assertEqual(out["story"], "Finished Wailing Caverns, seven bosses down.")
        self.assertEqual(
            out["cause"],
            "Finished: the run reported complete; its 7 credited encounters "
            "were not checked against the dungeon's full count.",
        )

    def test_no_known_total_and_no_credit_names_no_count(self):
        out = told(a_run([]))
        self.assertEqual(out["story"], "Finished Wailing Caverns.")
        self.assertNotIn("cleared", out["cause"].lower())

    def test_a_tally_that_meets_the_known_total_is_cleared(self):
        out = told(a_run([1] * 7), total=7)
        self.assertEqual(out["story"], "Cleared Wailing Caverns, seven bosses down.")
        self.assertEqual(
            out["cause"], "Cleared: every encounter the map credits went down."
        )

    def test_a_credit_row_may_credit_two_encounters_at_once(self):
        run = a_run([1, 2, 2, 1])
        self.assertEqual(
            told(run, total=6)["story"], "Cleared Wailing Caverns, six bosses down."
        )
        self.assertEqual(
            told(run, total=7)["story"],
            "Finished Wailing Caverns short, 6 of 7 bosses down.",
        )


class TheTimelineCard(unittest.TestCase):
    def test_a_complete_run_is_not_called_cleared_on_the_card(self):
        import runtimeline

        rows = []
        for row in a_run([1] * 7)["rows"]:
            rows.append(dict(row, family="Grug", campaign_id=4, run_number=1))
        card = runtimeline.build_run_timeline(
            rows, {"Grug": ["Grug"]}, runs_per_family=2
        )["families"][0]["runs"][0]
        self.assertNotIn("cleared", card["story"].lower())
        self.assertNotIn("cleared", card["cause"].lower())


class OtherEndsAreUntouched(unittest.TestCase):
    def test_a_wipe_still_reads_as_a_wipe(self):
        out = told(a_run([1], outcome="wipe"), total=7)
        self.assertTrue(out["story"].startswith("Went into Wailing Caverns"))
        self.assertNotIn("inished", out["story"])


if __name__ == "__main__":
    unittest.main()
