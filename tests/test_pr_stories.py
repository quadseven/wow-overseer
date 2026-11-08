"""Tests for collecting player stories from PRs.

The ship PR body should list each included PR with its player story or title.
"""

import unittest


class PRStoryCollectorTest(unittest.TestCase):
    def setUp(self):
        self.title = "Fix bot login crash in flight path system"

    def test_pr_with_story_in_body(self):
        body = """## Player story
Zork and Oz could not enter their guild hall, so the guild hall waited empty for 20 minutes.

## Why
The flight path system crashed on login, preventing guild members from entering.
"""
        story = _story_or_title(self.title, body)
        self.assertIn("Zork and Oz", story)
        self.assertIn("guild hall", story)

    def test_pr_without_story_falls_back_to_title(self):
        body = """## Why
The flight path system crashed on login, preventing guild members from entering.
"""
        story = _story_or_title(self.title, body)
        self.assertEqual(story, self.title)

    def test_pr_with_empty_body_falls_back_to_title(self):
        story = _story_or_title(self.title, "")
        self.assertEqual(story, self.title)

    def test_pr_with_minimal_story(self):
        body = """## Player story
A bot could not sell loot, so Blackrock Depths waited on their bags.
"""
        story = _story_or_title(self.title, body)
        self.assertEqual(
            story,
            "A bot could not sell loot, so Blackrock Depths waited on their bags.",
        )

    def test_pr_with_story_no_punctuation(self):
        body = """## Player story
Bag space was full
"""
        story = _story_or_title(self.title, body)
        self.assertEqual(story, "Bag space was full")

    def test_pr_with_story_only_suffix(self):
        body = """## Player story
...
"""
        story = _story_or_title(self.title, body)
        self.assertEqual(story, "...")

    def test_multiple_prs_with_stories(self):
        prs = [
            {
                "title": "Fix login crash",
                "body": "## Player story\nA bot could not log in.",
            },
            {
                "title": "Fix sell crash",
                "body": "## Player story\nA bot could not sell loot.",
            },
            {"title": "No story PR", "body": "## Why\nJust fixing a bug."},
        ]
        stories = [_story_or_title(p["title"], p["body"]) for p in prs]
        self.assertIn("A bot could not log in.", stories)
        self.assertIn("A bot could not sell loot.", stories)
        self.assertEqual(stories[2], "No story PR")


def _story_or_title(title: str, body: str) -> str:
    """Extract a player story from a PR, or return the title.

    The PR body may contain a Player story section. If present, that section
    should be one sentence in game terms naming who or what was affected and
    the effect. The story is trimmed and returned; if no story exists, the
    PR title is returned.
    """
    if not body:
        return title

    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "## Player story":
            story_lines = []
            for j in range(i + 1, len(lines)):
                next_line = lines[j].strip()
                if next_line.startswith("##"):
                    break
                if next_line:
                    story_lines.append(next_line)
            if story_lines:
                return " ".join(story_lines).strip()
    return title


if __name__ == "__main__":
    unittest.main()
