"""The vendored fork pin must match the deploy repo's (#1654).

UPSTREAM-PINS.env here is a vendored copy. The fork revision in it
(AC_MODULE_SHA) drifted from the deploy repo's file once, so every patch and
source check ran against a revision the realm no longer builds. The
comparison lives in .github/scripts/check_fork_pin_parity.py, which CI runs
next to the submodule pin gate. These tests drive it with two local files, so
they need no network, and read the real vendored file for the shape checks.
"""

import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
REPO = TESTS.parent
SCRIPT = REPO / ".github" / "scripts" / "check_fork_pin_parity.py"
VENDORED = REPO / "UPSTREAM-PINS.env"

SHA_A = "a" * 40
SHA_B = "b" * 40


def pins(sha):
    return (
        "AC_CORE_SHA=" + "c" * 40 + "\n"
        "AC_MODULE_REPO=https://example.invalid/fork.git\n"
        f"AC_MODULE_SHA={sha}\n"
    )


def load():
    spec = importlib.util.spec_from_file_location("check_fork_pin_parity", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TheComparison(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)

    def _run(self, vendored, deploy):
        v = self.dir / "vendored.env"
        d = self.dir / "deploy.env"
        v.write_text(vendored, encoding="utf-8")
        d.write_text(deploy, encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--vendored",
                str(v),
                "--deploy-file",
                str(d),
            ],
            capture_output=True,
            text=True,
        )

    def test_matching_pins_pass(self):
        result = self._run(pins(SHA_A), pins(SHA_A))
        self.assertEqual(0, result.returncode, result.stderr)

    def test_a_drifted_pin_fails_and_names_both_values(self):
        result = self._run(pins(SHA_A), pins(SHA_B))
        self.assertEqual(1, result.returncode)
        self.assertIn(SHA_A, result.stderr)
        self.assertIn(SHA_B, result.stderr)

    def test_a_missing_pin_is_a_failure_not_a_pass(self):
        result = self._run(pins(SHA_A), "AC_CORE_SHA=" + "c" * 40 + "\n")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("AC_MODULE_SHA", result.stderr)

    def test_other_pins_may_differ(self):
        other = pins(SHA_A).replace("c" * 40, "d" * 40)
        result = self._run(pins(SHA_A), other)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_the_deploy_source_is_read_from_the_vendored_header(self):
        mod = load()
        slug, path = mod.deploy_source(VENDORED.read_text(encoding="utf-8"))
        self.assertRegex(slug, r"^[\w.-]+/[\w.-]+$")
        self.assertTrue(path.endswith("UPSTREAM-PINS.env"), path)


class TheVendoredFile(unittest.TestCase):
    def test_it_carries_a_well_formed_fork_pin(self):
        mod = load()
        sha = mod.module_sha(VENDORED.read_text(encoding="utf-8"))
        self.assertRegex(sha, r"^[0-9a-f]{40}$")

    def test_every_patch_header_that_names_the_fork_names_the_current_pin(self):
        """One bump of the vendored file must move every revision check."""
        mod = load()
        sha = mod.module_sha(VENDORED.read_text(encoding="utf-8"))
        for patch in sorted((REPO / "patches" / "mod-playerbots").glob("*.patch")):
            text = patch.read_text(encoding="utf-8")
            if "mod-playerbots @" in text or "Verified against the pins" in text:
                self.assertIn(sha, text, f"{patch.name} does not name the pin")


ENUM_FILE = pathlib.Path("src/Bot/Engine/Strategy/Strategy.h")
USED = re.compile(r"TargetValueExclusionType::(\w+)")


def enum_members(text):
    body = re.search(
        r"enum class TargetValueExclusionType[^{]*\{(.*?)\};", text, re.S
    ).group(1)
    body = re.sub(r"//[^\n]*", "", body)
    return {m.strip() for m in body.split(",") if m.strip()}


class TheEnumFixture(unittest.TestCase):
    def test_members_are_read_past_comments(self):
        text = (
            "enum class TargetValueExclusionType : uint8\n{\n"
            "    TankTarget,\n    DpsTarget,  // also x, y\n    Aoe,\n};\n"
        )
        self.assertEqual({"TankTarget", "DpsTarget", "Aoe"}, enum_members(text))


@unittest.skipUnless(
    os.environ.get("PLAYERBOTS_SRC"),
    "set PLAYERBOTS_SRC to a checkout of the pinned fork for the real check",
)
class ThePatchesUseTheForksEnum(unittest.TestCase):
    """A patch can apply cleanly and still not compile: the exclusion type was
    renamed in the fork and the patches kept the old spelling. Every
    TargetValueExclusionType member the patches name must exist at the pin."""

    def test_every_member_a_patch_names_exists_at_the_pin(self):
        src = pathlib.Path(os.environ["PLAYERBOTS_SRC"])
        members = enum_members((src / ENUM_FILE).read_text(encoding="utf-8"))
        self.assertTrue(members)
        for patch in sorted((REPO / "patches" / "mod-playerbots").glob("*.patch")):
            for name in USED.findall(patch.read_text(encoding="utf-8")):
                self.assertIn(
                    name, members, f"{patch.name} uses a member the fork lacks"
                )


if __name__ == "__main__":
    unittest.main()
