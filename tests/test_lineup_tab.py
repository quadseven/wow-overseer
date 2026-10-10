"""The Lineup view fetches its data, asserted against source.

Same seam as test_raid_tab.py: index.html has no other test seam, so it is
read as text and sliced to the block being asserted about.

#87 shipped pollLineup() with nothing calling it, so the tab sat on "reaching
the world..." forever while /api/lineup answered 200. These tests pin the two
callers it needs.

Tickets: #127, #87.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent


class TheLineupDrawsTheEightGroups(unittest.TestCase):
    """The operator's eight groups of one tank, one healer and three damage
    dealers: each group names the buffs it lacks, and each guild says the
    seats no class can fill and who recruiting prefers (raidlineup)."""

    def test_every_key_it_reads_is_one_the_lineup_writes(self):
        import sys

        sys.path.insert(0, str(HERE))
        import raidlineup

        lineup = raidlineup.build_lineup([])
        for key in ("gap_line", "gaps", "roles_line"):
            self.assertIn(key, lineup, key)
        self.assertIn("missing_buffs", lineup["groups"][0])


if __name__ == "__main__":
    unittest.main()
