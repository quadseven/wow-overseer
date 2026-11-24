"""The ship note lists each pull request by its player story (#1994)."""

import unittest

import playerstory

WITH = (
    "## Why\nx\n\n## Player story\n\nTwo members could not\nsell their loot.\n"
    "\n## Size\nS\n"
)


class StoryTest(unittest.TestCase):
    def test_a_pull_request_with_a_story_is_listed_by_it(self):
        self.assertEqual(
            playerstory.line(7, "Fix sale walk", WITH),
            "- #7 Two members could not sell their loot.",
        )

    def test_a_pull_request_without_a_story_is_listed_by_its_title(self):
        self.assertEqual(
            playerstory.line(8, "Fix  the walk", "## Why\nx\n"), "- #8 Fix the walk"
        )

    def test_an_empty_or_missing_body_falls_back_to_the_title(self):
        self.assertEqual(playerstory.line(9, "T", ""), "- #9 T")
        self.assertEqual(playerstory.line(9, "T", None), "- #9 T")

    def test_a_hint_comment_or_empty_section_is_not_a_story(self):
        body = "## Player story\n<!-- one sentence -->\n\n## Size\nS\n"
        self.assertEqual(playerstory.story(body), "")
        self.assertEqual(playerstory.line(3, "T", body), "- #3 T")

    def test_the_story_at_the_end_of_the_body_is_read(self):
        self.assertEqual(playerstory.story("## Player story\nA story."), "A story.")

    def test_collect_gives_one_line_per_row_in_order(self):
        rows = [(1, "A", WITH), (2, "B", "")]
        self.assertEqual(
            playerstory.collect(rows),
            "- #1 Two members could not sell their loot.\n- #2 B",
        )

    def test_the_entry_point_reads_json_rows_and_prints_the_note(self):
        import io

        rows = '[{"number": 4, "title": "T", "body": null}]'
        out = io.StringIO()
        self.assertEqual(playerstory.main(stdin=io.StringIO(rows), stdout=out), 0)
        self.assertEqual(out.getvalue(), "- #4 T\n")


if __name__ == "__main__":
    unittest.main()
