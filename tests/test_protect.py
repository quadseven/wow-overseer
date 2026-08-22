"""Keeping Grug from being re-rolled.

RandomPlayerbotMgr re-randomizes an idle bot when its `randomize` event
row has expired: FindEvent drops the row once
`NowSeconds() - time >= validIn`, GetEventValue then returns 0, and the
update loop calls Randomize(). Below level 3 that routes to
RandomizeFirst(), which assigns a level and re-gears - which would erase
the character Evan is actually growing (infra#2656).

Suppression is therefore just: keep a row whose validIn has not elapsed.
This module decides WHICH rows need writing; bridge.py does the writing.
"""
import unittest

import protect

HORIZON = protect.PROTECT_HORIZON_SECONDS
NOW = 1_800_000_000


class NeedsRefreshTest(unittest.TestCase):
    def test_a_character_with_no_row_needs_one(self):
        self.assertEqual(
            protect.rows_needing_refresh({101: "Grug"}, {}, NOW), [101]
        )

    def test_a_freshly_written_row_is_left_alone(self):
        rows = {101: {"time": NOW - 10, "validIn": HORIZON}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [])

    def test_a_row_nearing_expiry_is_refreshed_before_it_lapses(self):
        # Refresh once less than a third of the horizon remains, so a missed
        # cycle (or ten) cannot let the protection lapse silently.
        rows = {101: {"time": NOW - int(HORIZON * 0.8), "validIn": HORIZON}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [101])

    def test_a_short_validIn_written_by_the_server_is_overwritten(self):
        # The manager's own scheduling uses hours; ours must win.
        rows = {101: {"time": NOW, "validIn": 7200}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [101])

    def test_an_already_expired_row_is_refreshed(self):
        rows = {101: {"time": NOW - HORIZON - 1, "validIn": HORIZON}}
        self.assertEqual(protect.rows_needing_refresh({101: "Grug"}, rows, NOW), [101])

    def test_unprotected_characters_are_never_touched(self):
        # 999 has a long-expired row and is NOT protected; it must never
        # appear in the write list, even though the manager would randomize
        # it (which is correct for an ordinary bot).
        rows = {999: {"time": 0, "validIn": 1}}
        out = protect.rows_needing_refresh({101: "Grug"}, rows, NOW)
        self.assertNotIn(999, out)

    def test_several_protected_characters_are_all_considered(self):
        out = protect.rows_needing_refresh({101: "Grug", 102: "Bork"}, {}, NOW)
        self.assertEqual(sorted(out), [101, 102])

    def test_the_horizon_is_long_enough_to_outlive_a_weekend_outage(self):
        # The manager's slowest natural randomize is 14 days; ours must be
        # comfortably longer or protection is a race we sometimes lose.
        self.assertGreater(HORIZON, 30 * 24 * 3600)


class ReportTest(unittest.TestCase):
    def test_the_report_names_who_is_protected_and_until_when(self):
        line = protect.report({101: "Grug"}, [101], NOW)
        self.assertIn("Grug", line)
        self.assertIn("1", line)

    def test_a_quiet_cycle_still_says_who_is_covered(self):
        # Silence would make a lapsed protection indistinguishable from a
        # working one - the failure mode this repo keeps meeting.
        line = protect.report({101: "Grug"}, [], NOW)
        self.assertIn("Grug", line)
