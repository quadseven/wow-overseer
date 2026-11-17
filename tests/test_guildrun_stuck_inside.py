"""A run that reads 'inside' for hours is ended as lost (Refs #2654).

`_follow_guild_runs` swept a run as lost only when its command row gave no
answer. A row that kept saying `verifying` with phase `inside` answered every
poll, so its run kept its five seats for ever. The bound is `INSIDE_LOST_MINUTES`.
"""

import pathlib
import unittest

import guildrun

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

INSIDE_ROW = {
    "status": "verifying",
    "result": '{"phase":"inside","bosses_done":2,"deaths":1,"seconds_inside":400}',
    "bosses_done": 2,
    "bosses_total": 7,
}


class AnInsideRunHasABound(unittest.TestCase):
    def seen(self, **row):
        row = dict(INSIDE_ROW, **row)
        return row, guildrun.outcome_from_row(row)

    def test_a_run_inside_past_the_bound_is_lost(self):
        row, seen = self.seen(stuck=1)
        self.assertEqual(guildrun.INSIDE, seen["state"])
        lost = guildrun.lost_verdict(row, seen)
        self.assertEqual(guildrun.ENDED, lost["state"])
        self.assertEqual("lost", lost["outcome"])
        self.assertIn(str(guildrun.INSIDE_LOST_MINUTES), lost["why"])
        self.assertEqual(2, lost["bosses_done"])
        self.assertEqual(7, lost["bosses_total"])

    def test_a_run_inside_within_the_bound_is_left_alone(self):
        row, seen = self.seen(stuck=0)
        self.assertIsNone(guildrun.lost_verdict(row, seen))

    def test_a_row_with_no_answer_is_lost_at_the_old_bound(self):
        row = {"stale": 1, "bosses_done": 0, "bosses_total": 5}
        lost = guildrun.lost_verdict(row, None)
        self.assertEqual("lost", lost["outcome"])
        self.assertIn(str(guildrun.LOST_AFTER_MINUTES), lost["why"])
        self.assertIsNone(guildrun.lost_verdict(dict(row, stale=0), None))

    def test_an_ended_answer_is_never_overridden(self):
        row = {
            "status": "applied",
            "result": '{"phase":"done","outcome":"cleared"}',
            "stuck": 1,
            "stale": 1,
        }
        seen = guildrun.outcome_from_row(row)
        self.assertIsNone(guildrun.lost_verdict(row, seen))

    def test_the_bound_outlasts_the_longest_real_run(self):
        self.assertGreater(guildrun.INSIDE_LOST_MINUTES, guildrun.LOST_AFTER_MINUTES)

    def test_the_bridge_reads_the_bound_and_asks_the_verdict(self):
        body = BRIDGE[BRIDGE.index("def _follow_guild_runs") :]
        body = body[: body.index("\ndef ", 10)] if "\ndef " in body[10:] else body
        self.assertIn("AS stuck", body)
        self.assertIn("guildrun.INSIDE_LOST_MINUTES", body)
        self.assertIn("guildrun.lost_verdict(row, seen)", body)
