"""scripts/check-locally.sh runs the exact command CI gates a PR on (#1293).

CI's unittest job hands check.yml's `test-cmd` to a shell on a checkout with
the mod-overseer submodule. A bare `python3 -m unittest` on a local
interpreter, without the submodule or tests/requirements.txt, reports
hundreds of failures and skips CI never sees. The script reads the command
out of check.yml rather than keeping a copy, so these tests ask it what it
would run and compare that with what check.yml says, line for line: a
change to either side that drifts the two apart fails here.

The script's `print` mode stops before any git, uv or test call, so this
runs in seconds on any machine with bash.
"""

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-locally.sh"
CHECK_YML = ROOT / ".github" / "workflows" / "check.yml"

JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def job_with(job, key):
    """The double-quoted value of `key:` inside check.yml's `job:` block."""
    current = None
    for line in CHECK_YML.read_text().splitlines():
        header = JOB.match(line)
        if header:
            current = header.group(1)
            continue
        if current != job:
            continue
        value = re.match(rf'^\s+{re.escape(key)}:\s*"(.*)"\s*$', line)
        if value:
            return value.group(1)
    raise AssertionError(f"check.yml has no quoted {key} in its {job} job")


def printed():
    """{label: value} from the script's `print` mode."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "print"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(f"print mode failed: {result.stderr}")
    lines = {}
    for line in result.stdout.splitlines():
        label, _, value = line.partition(": ")
        lines[label] = value
    return lines


class CheckLocallyTest(unittest.TestCase):
    def test_script_exists(self):
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT.relative_to(ROOT)}")

    def test_runs_check_yml_unittest_command_verbatim(self):
        expected = job_with("unittest", "test-cmd")
        self.assertIn("unittest", expected)
        self.assertEqual(printed().get("unittest"), expected)

    def test_lints_with_check_yml_ruff_version(self):
        version = job_with("lint", "ruff-version")
        self.assertRegex(version, r"^\d+(\.\d+)*$")
        self.assertEqual(printed().get("ruff"), f"uvx ruff@{version}")

    def test_initializes_the_submodule(self):
        # CI checks out with submodules: true; a fresh worktree has none.
        self.assertIn("git submodule update --init mod-overseer", SCRIPT.read_text())

    def test_agents_md_names_the_script(self):
        self.assertIn("scripts/check-locally.sh", (ROOT / "AGENTS.md").read_text())


if __name__ == "__main__":
    unittest.main()
