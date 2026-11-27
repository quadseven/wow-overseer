"""The rehearsal grant flag lives only in the ephemeral example and its guard.

No tracked file outside the ephemeral package, its example config, the
tests and the docs (so the Dockerfiles, units, env examples and workflows too) may carry the
harness grants line or the variable that carries it, so a copy of one of those
files cannot enable grants there.
"""

import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLAG_TEXT = "grants: enabled"
FLAG_NAME = "EPH_HARNESS_GRANTS"
# The one place the flag is allowed: the ephemeral world's own example config.
ALLOWED = {"data/ephemeral/config.example.env", "data/rehearsal/config.example.env"}
# Not deployment files: the guard, its tests and the docs name the flag by design.
EXEMPT_PREFIXES = ("ephemeral/", "rehearsal/", "tests/", "docs/")


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def is_deployment_file(rel):
    """Every tracked file outside the guard's own package and the tests."""
    return not rel.startswith(EXEMPT_PREFIXES)


def read_file(rel):
    path = ROOT / rel
    if not path.is_file():  # a submodule entry
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def carriers(files, read):
    """The deployment files, outside the allowed one, whose text carries the flag."""
    bad = []
    for rel in files:
        if rel in ALLOWED or not is_deployment_file(rel):
            continue
        text = read(rel)
        if FLAG_TEXT in text or FLAG_NAME in text:
            bad.append(rel)
    return bad


class GrantsFlagScopeTest(unittest.TestCase):
    def test_no_organic_deployment_file_carries_the_grants_line(self):
        files = tracked_files()
        self.assertTrue(
            [f for f in files if is_deployment_file(f)],
            "the scan found no file at all",
        )
        self.assertEqual(carriers(files, read_file), [])

    def test_the_allowed_file_is_the_one_that_carries_it(self):
        text = (ROOT / "data/ephemeral/config.example.env").read_text(encoding="utf-8")
        self.assertIn(FLAG_NAME, text)

    def test_the_allowed_file_is_the_one_that_carries_the_rehearsal_flag(self):
        text = (ROOT / "data/rehearsal/config.example.env").read_text(encoding="utf-8")
        self.assertIn("REHEARSAL_GRANTS_ENABLED", text)
        self.assertIn(FLAG_TEXT, text)

    def test_the_scan_names_a_unit_file_that_gains_the_line(self):
        files = ["systemd/metric-watcher.service", "data/ephemeral/config.example.env"]
        texts = {
            "systemd/metric-watcher.service": "[Service]\nEnvironment=EPH_HARNESS_GRANTS=grants: enabled\n",
            "data/ephemeral/config.example.env": "EPH_HARNESS_GRANTS=grants: enabled\n",
        }
        self.assertEqual(
            carriers(files, texts.__getitem__), ["systemd/metric-watcher.service"]
        )

    def test_the_scan_names_a_workflow_that_gains_the_variable(self):
        files = [".github/workflows/build.yml"]
        texts = {".github/workflows/build.yml": "env:\n  EPH_HARNESS_GRANTS: x\n"}
        self.assertEqual(
            carriers(files, texts.__getitem__), [".github/workflows/build.yml"]
        )


if __name__ == "__main__":
    unittest.main()
