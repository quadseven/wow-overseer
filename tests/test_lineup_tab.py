"""The Lineup view fetches its data, asserted against source.

Same seam as test_raid_tab.py: index.html has no other test seam, so it is
read as text and sliced to the block being asserted about.

#87 shipped pollLineup() with nothing calling it, so the tab sat on "reaching
the world..." forever while /api/lineup answered 200. These tests pin the two
callers it needs.

Tickets: #127, #87.
"""
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")


def _show_view():
    show = PAGE[PAGE.index("function showView"):]
    return show[:show.index("// Read once, at startup")]


class TheLineupFetches(unittest.TestCase):

    def test_it_fetches_on_the_way_in_rather_than_waiting_for_the_timer(self):
        """A placeholder under a heading is indistinguishable from a broken
        view, which is exactly what the operator saw."""
        show = _show_view()
        self.assertIn("  if (isLineup) {", show)
        branch = show[show.index("  if (isLineup) {"):]
        self.assertIn("pollLineup();", branch[:branch.index("  }")])

    def test_it_stops_the_grid_and_closes_the_panel_like_every_read_view(self):
        show = _show_view()
        branch = show[show.index("  if (isLineup) {"):]
        branch = branch[:branch.index("  }")]
        self.assertIn("closePanel();", branch)
        self.assertIn("stopBroadcasts();", branch)

    def test_it_refreshes_while_open(self):
        self.assertRegex(
            PAGE,
            re.compile(r"setInterval\(\(\) => \{ if \(view === LINEUP_VIEW\) "
                       r"pollLineup\(\); \}, \d+\);"))

    def test_the_view_is_in_the_routing_table(self):
        listed = PAGE[PAGE.index("const HASH_VIEWS = ["):]
        self.assertIn("LINEUP_VIEW", listed[:listed.index("]")])


if __name__ == "__main__":
    unittest.main()
