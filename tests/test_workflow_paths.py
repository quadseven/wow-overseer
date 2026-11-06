"""check.yml and build.yml trigger on every file their jobs depend on (#1845).

Both workflows carry `paths` filters. A pull request that touches only files
outside those filters runs no tests and builds no image, so the next pull
request that does match goes red for a change it did not make. Two gaps of
that kind existed: check.yml skipped app/, index.html, docs/, README.md and
other files that test modules read as text, and build.yml skipped app/,
which the Dockerfile copies into the image.

These tests read both workflows as text (the suite is stdlib only, so no YAML
parser) and match real tracked files against the filters with GitHub's glob
rules: `**` crosses directories, `*` does not.

They also hold the two check.python.yml callers in check.yml to one pinned
SHA, so a bump cannot reach one job and miss the other.
"""

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CHECK_YML = WORKFLOWS / "check.yml"
BUILD_YML = WORKFLOWS / "build.yml"
DOCKERFILE = ROOT / "Dockerfile"


def _trigger_paths(text, event):
    """The `paths:` list under `on: <event>:` in a workflow file."""
    lines = text.splitlines()
    out = []
    in_event = in_paths = False
    for line in lines:
        if re.match(rf"^  {event}:\s*$", line):
            in_event, in_paths = True, False
            continue
        if in_event and re.match(r"^  \S", line):
            break
        if in_event and re.match(r"^    paths:\s*$", line):
            in_paths = True
            continue
        if in_paths:
            m = re.match(r"^      - '([^']+)'\s*$", line)
            if m:
                out.append(m.group(1))
            elif line.strip():
                in_paths = False
    if not out:
        raise AssertionError(f"no paths list under on.{event}")
    return out


def _glob_regex(pattern):
    """GitHub path-filter glob to a regex: `**` crosses `/`, `*` and `?` do not."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _matches(path, patterns):
    return any(_glob_regex(p).match(path) for p in patterns)


def _tracked(*pathspecs):
    out = subprocess.run(
        ["git", "ls-files", "--", *pathspecs],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if p]


def _dockerfile_copy_sources():
    """Every source path named by a COPY in the Dockerfile (without --from)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    joined = re.sub(r"\\\n", " ", text)
    sources = []
    for line in joined.splitlines():
        parts = line.split()
        if not parts or parts[0] != "COPY":
            continue
        if any(a.startswith("--from") for a in parts[1:]):
            continue
        args = [a for a in parts[1:] if not a.startswith("--")]
        sources.extend(args[:-1])
    return sources


class GlobTest(unittest.TestCase):
    def test_glob_rules(self):
        self.assertTrue(_matches("a/b/c.py", ["**.py"]))
        self.assertTrue(_matches("app/ui.js", ["app/**"]))
        self.assertTrue(_matches("index.html", ["*.html"]))
        self.assertFalse(_matches("app/ui.js", ["*.js"]))
        self.assertFalse(_matches("mod-overseer/x.cpp", ["mod-overseer"]))


class CheckPathsTest(unittest.TestCase):
    # Files the tests read as text. Each must trigger check.yml, or a change
    # to it alone runs none of the tests that read it.
    READ_AS_TEXT = (
        "app/ui.js",
        "app/api.js",
        "index.html",
        "README.md",
        "docs/HISTORY.md",
        "AGENTS.md",
        "Dockerfile",
        "manifest.webmanifest",
        "scripts/check-locally.sh",
        ".loom/validation.conf",
        ".github/workflows/build.yml",
        "tests/fixtures/strategy_names.txt",
        "data/bis/NOTICE.txt",
    )

    def setUp(self):
        self.text = CHECK_YML.read_text(encoding="utf-8")

    def _assert_covered(self, paths):
        for event in ("push", "pull_request"):
            patterns = _trigger_paths(self.text, event)
            missed = [p for p in paths if not _matches(p, patterns)]
            self.assertEqual(missed, [], f"check.yml on.{event} skips these")

    def test_files_the_tests_read_trigger_check(self):
        for path in self.READ_AS_TEXT:
            self.assertTrue((ROOT / path).exists(), f"{path} is gone; update this list")
        self._assert_covered(self.READ_AS_TEXT)

    def test_every_app_and_docs_file_triggers_check(self):
        tracked = _tracked("app", "docs", "*.html", "*.css", "*.js")
        self.assertTrue(tracked, "git ls-files found nothing to check")
        self._assert_covered(tracked)

    def test_push_and_pull_request_filters_agree(self):
        self.assertEqual(
            _trigger_paths(self.text, "push"),
            _trigger_paths(self.text, "pull_request"),
        )

    def test_one_pinned_sha_for_check_python(self):
        shas = re.findall(
            r"uses: quadseven/infra-public/\.github/workflows/check\.python\.yml@(\S+)",
            self.text,
        )
        self.assertEqual(len(shas), 2, "expected the unittest and lint callers")
        self.assertEqual(len(set(shas)), 1, f"check.python.yml pinned at {shas}")
        self.assertRegex(shas[0], r"^[0-9a-f]{40}$")

    def test_requirements_comment_names_every_pin(self):
        reqs = (ROOT / "tests" / "requirements.txt").read_text(encoding="utf-8")
        names = [
            re.split(r"[=<>~!\[ ]", line, maxsplit=1)[0]
            for line in reqs.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(names)
        for name in names:
            self.assertIn(
                name.lower(), self.text.lower(), f"{name} unnamed in check.yml"
            )


class BuildPathsTest(unittest.TestCase):
    def setUp(self):
        self.text = BUILD_YML.read_text(encoding="utf-8")

    def test_every_dockerfile_copy_source_triggers_build(self):
        sources = _dockerfile_copy_sources()
        self.assertIn("app", sources)
        files = []
        for src in sources:
            found = _tracked(src)
            self.assertTrue(found, f"Dockerfile copies {src}, which git does not track")
            files.extend(found)
        for event in ("push", "pull_request"):
            patterns = _trigger_paths(self.text, event)
            missed = sorted({f for f in files if not _matches(f, patterns)})
            self.assertEqual(missed, [], f"build.yml on.{event} skips these")

    def test_push_and_pull_request_filters_agree(self):
        self.assertEqual(
            _trigger_paths(self.text, "push"),
            _trigger_paths(self.text, "pull_request"),
        )

    def test_token_comment_names_the_real_variable(self):
        stale = re.search(r"\bDISCORD_TOKEN\b", self.text)
        self.assertIsNone(stale, "build.yml still names DISCORD_TOKEN")
        self.assertIn("DISCORD_BOT_TOKEN", self.text)


if __name__ == "__main__":
    unittest.main()
