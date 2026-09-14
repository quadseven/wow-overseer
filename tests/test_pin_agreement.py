"""The pin, the gitlink and the bytes under test must be the same commit.

WHY THIS FILE EXISTS (infra#3093). Seventeen suites in this directory assert
against `mod_overseer.cpp` as TEXT, and every one of them resolves it to
`docker/azerothcore-playerbots/mod-overseer/src/mod_overseer.cpp` - the
SUBMODULE, not the module's own repo. That is the only copy the suite can see,
so whichever commit happens to be checked out there is the subject of the 495
tests those seventeen files contribute.

Nothing checked which commit that was.

Measured 2026-08-31 in a working checkout. Same 1597 tests every time; only the
submodule working tree changed:

    submodule at 4de7824, the pinned commit, 9218 lines   Ran 1597 tests   OK
    submodule at 81d1d1e, two merged PRs back, 8274 lines Ran 1597 tests   OK
    submodule never initialized at all                    314 errors

The middle row is the whole problem. An ABSENT submodule is loud. A merely
WRONG one is silent, and silent is the state a stale checkout is actually in.
In that state the assertions about the dungeon run coordinator were being
satisfied by a coordinator that had no ENTER, no STAGED_INSIDE, no CLEARING and
no EXIT, because all four live in the 944 lines that checkout had never pulled.

THREE STATEMENTS, NOT ONE. There are three separate answers to "which commit of
mod-overseer", and any pair of them can drift apart:

  1. `AC_OVERSEER_SHA` in UPSTREAM-PINS.env - what the image build clones, so
     what actually ships.
  2. The gitlink recorded for the submodule path - what a fresh checkout gets.
  3. The submodule's own checked-out HEAD - what these tests actually read.

1 vs 2 is the drift the module repo's AGENTS.md already names: "Bumping one
without the other leaves the two disagreeing silently." 2 vs 3 is the one that
happened, and it is the worse of the two, because it is not in a diff at all -
it is a state of somebody's disk, invisible to review by construction. Git does
report it, as `modified: ... (new commits)`, which is one line nobody reads
sitting next to `Ran 1597 tests ... OK`, which everybody does.

So both pairs are asserted, separately, and each failure names which pair
diverged and what to do about it. Asserting only 1 vs 2 would have passed in
the checkout described above: there the pin and the gitlink agreed with each
other, and BOTH disagreed with the bytes under test.

Structural and cheap on purpose - no compiler, no network, no cluster. Two of
the three statements are plain text; the remaining comparisons are one `git`
invocation each.
"""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
REPO = pathlib.Path(__file__).resolve().parents[4]
SUBMODULE = ROOT / "docker/azerothcore-playerbots/mod-overseer"
MODULE = SUBMODULE / "src/mod_overseer.cpp"
PINS = ROOT / "docker/azerothcore-playerbots/UPSTREAM-PINS.env"
GITMODULES = REPO / ".gitmodules"

# The submodule path as git records it: relative to the repo root, forward
# slashes, which is what `.gitmodules` and `git ls-tree` both speak on every
# platform. DERIVED from the path the tests actually read rather than written
# out a second time, so moving the directory cannot leave this file agreeing
# with itself about a location nothing else uses.
SUBMODULE_PATH = SUBMODULE.relative_to(REPO).as_posix()

GIT = shutil.which("git")
# The last three comparisons need `git` and a real `.git`. Without both, this
# source tree is not a checkout (an export, a tarball, a COPY into an image)
# and there is no recorded gitlink for anything to disagree with. The
# text-only assertions still run. CI checks out with `submodules: true`
# (check.python-units.yml), so on the gate that matters nothing here skips.
IS_CHECKOUT = bool(GIT) and (REPO / ".git").exists()


def _pins() -> dict:
    """The KEY=VALUE lines of UPSTREAM-PINS.env, comments and blanks dropped."""
    values = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _gitmodules() -> dict:
    """path -> url for every submodule `.gitmodules` declares."""
    entries = {}
    path = url = None
    for line in GITMODULES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("[submodule"):
            path = url = None
        elif line.startswith("path"):
            path = line.split("=", 1)[1].strip()
        elif line.startswith("url"):
            url = line.split("=", 1)[1].strip()
        if path and url:
            entries[path] = url
            path = url = None
    return entries


def _git(*args) -> str:
    """git, failing out loud rather than returning a convincing empty string."""
    proc = subprocess.run([GIT, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(
            "git %s exited %d: %s"
            % (" ".join(args), proc.returncode, proc.stderr.strip())
        )
    return proc.stdout.strip()


def _recorded_gitlink() -> tuple:
    """(mode, sha) that this checkout's HEAD records for the submodule path."""
    line = _git("-C", str(REPO), "ls-tree", "HEAD", "--", SUBMODULE_PATH)
    if not line:
        raise AssertionError(
            "%s is not in HEAD's tree at all - the submodule the whole "
            "C++-as-text suite reads is not tracked here" % SUBMODULE_PATH
        )
    mode, _kind, rest = line.split(" ", 2)
    return mode, rest.split("\t", 1)[0]


class ThePinFileCanBeCompared(unittest.TestCase):
    def test_the_overseer_pin_is_a_full_commit_sha(self):
        """A branch name or an abbreviation makes every check below vacuous.

        It also makes the image non-reproducible, which is the reason
        UPSTREAM-PINS.env's own header gives for pinning by SHA in the first
        place. Both failures are the same typo.

        UPPERCASE is rejected too, on purpose. git accepts an object name in
        either case but only ever PRINTS it in lowercase, and the gitlink
        check below is a plain string comparison against `git ls-tree`
        output. An uppercase pin names the right commit and would still fail
        that comparison, with a message about drift that is not there. It is
        cheaper to say "write it lowercase" here, once, than to explain a
        false drift report later.
        """
        pins = _pins()
        self.assertIn(
            "AC_OVERSEER_SHA", pins,
            "UPSTREAM-PINS.env has no AC_OVERSEER_SHA line; the build clones "
            "nothing and this suite has no pin to compare against",
        )
        self.assertRegex(
            pins["AC_OVERSEER_SHA"], r"^[0-9a-f]{40}$",
            "AC_OVERSEER_SHA=%s is not a full 40-character lowercase commit "
            "SHA (git prints object names in lowercase, and the gitlink check "
            "compares strings)" % pins["AC_OVERSEER_SHA"],
        )


class TheSubmoduleIsTheOneTheSuiteReads(unittest.TestCase):
    def test_gitmodules_declares_the_path_the_tests_resolve(self):
        """A moved submodule leaves the tests reading an empty directory.

        They would not error on the move itself - `unittest discover` reports
        that as ~300 file-not-found ERRORs later, in suites whose names say
        nothing about submodules.
        """
        declared = _gitmodules()
        self.assertIn(
            SUBMODULE_PATH, declared,
            "no submodule declared at %s, which is where every C++-as-text "
            "test in this directory reads mod_overseer.cpp from. Declared: %s"
            % (SUBMODULE_PATH, sorted(declared)),
        )

    def test_the_submodule_is_the_repo_the_build_clones(self):
        """The build clones AC_OVERSEER_REPO; the tests read this submodule.

        If those are two different repositories then the suite is testing
        somebody's fork while the image ships something else, and every
        assertion in this directory is about the wrong project.
        """
        self.assertEqual(
            _gitmodules().get(SUBMODULE_PATH), _pins().get("AC_OVERSEER_REPO"),
            "the submodule at %s and AC_OVERSEER_REPO name different "
            "repositories" % SUBMODULE_PATH,
        )

    def test_the_source_under_test_is_actually_present(self):
        """Said once, here, instead of 314 times as an unrelated ERROR.

        Measured: with the submodule uninitialized this suite reports
        `FAILED (failures=4, errors=314)`, and not one of those 314 lines
        mentions a submodule.
        """
        self.assertTrue(
            MODULE.is_file(),
            "%s is missing: the submodule is not initialized in this "
            "checkout. Run `git submodule update --init` and re-run."
            % MODULE,
        )


@unittest.skipUnless(
    IS_CHECKOUT,
    "not a git checkout with git on PATH: no recorded gitlink to compare",
)
class TheThreeStatementsAgree(unittest.TestCase):
    def test_the_path_is_recorded_as_a_submodule_and_not_a_directory(self):
        """Mode 160000 is what makes the pin binding on this path at all.

        Replace the submodule with an ordinary directory of copied files and
        every other assertion here still passes while the bytes under test
        answer to no pin and no upstream.
        """
        mode, _sha = _recorded_gitlink()
        self.assertEqual(
            mode, "160000",
            "%s is recorded with mode %s, not as a submodule gitlink: the "
            "source this suite reads is no longer pinned to any commit"
            % (SUBMODULE_PATH, mode),
        )

    def test_the_gitlink_is_the_commit_the_pin_file_names(self):
        """Statement 1 against statement 2: bump one, bump both."""
        _mode, gitlink = _recorded_gitlink()
        pinned = _pins().get("AC_OVERSEER_SHA")
        self.assertEqual(
            gitlink, pinned,
            "the two halves of one bump disagree. UPSTREAM-PINS.env says "
            "AC_OVERSEER_SHA=%s, the recorded gitlink for %s says %s. The "
            "image would be built from the first and this suite tested "
            "against the second. Set both, in the same commit."
            % (pinned, SUBMODULE_PATH, gitlink),
        )

    def test_the_checked_out_submodule_is_at_the_recorded_gitlink(self):
        """Statement 2 against statement 3: the state of somebody's disk.

        This is the one that is not in any diff, and the one that was found
        live. Nothing is wrong with the repository when it fails.
        """
        _mode, gitlink = _recorded_gitlink()
        # Asked BEFORE rev-parse and not after, because `git -C` on an empty
        # submodule directory does not fail - it walks up and answers for the
        # SUPERPROJECT. Left unguarded, an uninitialized submodule reports
        # this repo's own HEAD as though it were the module's, which is a
        # wrong answer dressed as a real one.
        self.assertTrue(
            (SUBMODULE / ".git").exists(),
            "%s holds no git checkout of its own: the submodule is not "
            "initialized here. Run `git submodule update --init` and re-run."
            % SUBMODULE,
        )
        head = _git("-C", str(SUBMODULE), "rev-parse", "HEAD")
        self.assertEqual(
            head, gitlink,
            "the submodule working tree is at %s but this checkout records "
            "%s, so every C++-as-text test in this directory is asserting "
            "about source that is not the pinned source. The repository is "
            "fine - this checkout is stale. Run `git submodule update "
            "--init` and re-run." % (head, gitlink),
        )


if __name__ == "__main__":
    unittest.main()
