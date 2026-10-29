"""README.md follows the public README standard (#1554).

The standard lives in the shared public template repository
(templates/public-repo/README-STANDARD.md in quadseven/infra-public). It asks
for an opening (name, one line, two or three sentences), seven sections in a
fixed order, one Mermaid diagram, a Status section that links one live issue,
and the public-repo text rules: ASCII only, nothing private or stale.

These tests keep a later edit from sliding the README back: a history essay
returning to the page, a section going missing or out of order, box art
replacing the diagram, or a link to a repository that is not public.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CHECK_YML = ROOT / ".github" / "workflows" / "check.yml"

SECTIONS = (
    "What it does",
    "Quick start",
    "How it works",
    "Run and test locally",
    "Configuration",
    "Status",
    "Contributing",
)

# The public repositories the README may link to. Anything else under the
# owner is either private or not meant to be discoverable from here.
PUBLIC_REPOS = {"wow-overseer", "mod-overseer", "infra-public", "mod-playerbots"}


def _sections(text):
    """Map each `## ` heading to the body under it, in file order."""
    out = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


class ReadmeStandardTest(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")
        self.sections = _sections(self.text)

    def test_opening_is_name_line_and_short_prose(self):
        lines = self.text.splitlines()
        self.assertEqual(lines[0], "# wow-overseer")
        self.assertEqual(lines[1], "")
        # Line 2 of the standard: one line that says what it is.
        self.assertTrue(lines[2].strip())
        self.assertEqual(lines[3], "", "the one-line description is a single line")
        opening = self.text.split("\n## ", 1)[0]
        paragraphs = [p for p in opening.split("\n\n")[2:] if p.strip()]
        self.assertTrue(1 <= len(paragraphs) <= 2, paragraphs)

    def test_required_sections_in_order(self):
        names = list(self.sections)
        positions = []
        for name in SECTIONS:
            with self.subTest(section=name):
                self.assertIn(name, names)
                positions.append(names.index(name))
        self.assertEqual(positions, sorted(positions), names)
        self.assertEqual(names[: len(SECTIONS)], list(SECTIONS))

    def test_history_lives_in_a_linked_doc(self):
        for old in ("## Where this came from", "## What did not come with the move"):
            self.assertNotIn(old, self.text)
        self.assertIn("docs/HISTORY.md", self.text)
        self.assertTrue((ROOT / "docs" / "HISTORY.md").is_file())

    def test_how_it_works_has_one_mermaid_diagram(self):
        body = self.sections.get("How it works", "")
        self.assertEqual(body.count("```mermaid"), 1)
        self.assertEqual(self.text.count("```mermaid"), 1)

    def test_ascii_only_and_no_box_art(self):
        for n, line in enumerate(self.text.splitlines(), 1):
            with self.subTest(line=n):
                self.assertTrue(line.isascii(), line)
                # A box corner: `+---` or `---+`. Markdown table rules use `|`.
                self.assertNotRegex(line, r"\+[-=]{3,}|[-=]{3,}\+")

    def test_run_and_test_matches_ci(self):
        ci = CHECK_YML.read_text(encoding="utf-8")
        cmd = re.search(r'test-cmd: "([^"]+)"', ci).group(1)
        body = self.sections.get("Run and test locally", "")
        for part in cmd.split(" && "):
            with self.subTest(part=part):
                self.assertIn(part, body)
        version = re.search(r'ruff-version: "([^"]+)"', ci).group(1)
        self.assertIn(f"uvx ruff@{version} check", body)
        self.assertIn(f"uvx ruff@{version} format --check", body)

    def test_status_links_one_live_issue_in_this_repo(self):
        body = self.sections.get("Status", "")
        links = re.findall(
            r"https://github\.com/quadseven/wow-overseer/issues/\d+", body
        )
        self.assertEqual(len(links), 1, body)
        self.assertNotRegex(body, r"#\d+")

    def test_contributing_names_pr_checks_and_agents(self):
        body = self.sections.get("Contributing", "")
        self.assertIn("pull request", body)
        self.assertIn("AGENTS.md", body)
        for check in ("check.yml", "check.leak-scan.yml"):
            self.assertIn(check, body)

    def test_links_only_public_repos(self):
        for doc in (README, ROOT / "docs" / "HISTORY.md"):
            text = doc.read_text(encoding="utf-8")
            for repo in re.findall(r"github\.com/quadseven/([A-Za-z0-9_.-]+)", text):
                with self.subTest(doc=doc.name, repo=repo):
                    self.assertIn(repo.removesuffix(".git"), PUBLIC_REPOS)

    def test_no_stale_claims(self):
        for stale in (
            "arc-infrastructure",
            "this repo is private",
            "package is private",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale.lower(), self.text.lower())


if __name__ == "__main__":
    unittest.main()
