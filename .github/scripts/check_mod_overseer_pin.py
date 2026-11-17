"""Fail when the checked-out mod-overseer pin is not on origin/main."""

import argparse
import os
import subprocess
import sys


def _fetch_failure_reason(fetch):
    """One line naming why a fetch failed: its last stderr line, or its
    exit code when it said nothing."""
    lines = [line.strip() for line in (fetch.stderr or "").splitlines()]
    lines = [line for line in lines if line]
    if lines:
        return " ".join(lines[-1].split())
    return "git fetch exited %d" % fetch.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submodule", nargs="?", default="mod-overseer")
    args = parser.parse_args(argv)

    # CI checks the submodule out at depth 1. Fetching main into such a
    # checkout makes main's tip a new shallow root, so the pin never shows up
    # in its history and every pin looks off main. Deepen to the full history
    # first when the checkout is shallow.
    shallow = subprocess.run(
        ["git", "-C", args.submodule, "rev-parse", "--is-shallow-repository"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fetch = ["git", "-C", args.submodule, "fetch", "--quiet"]
    if shallow == "true":
        fetch.append("--unshallow")
    fetched = subprocess.run(
        [*fetch, "origin", "main"],
        check=False,
        capture_output=True,
        text=True,
    )
    if fetched.returncode != 0:
        # A local checkout can have no network, or a sandbox that refuses
        # the fetch's writes: there the pin cannot be checked, and failing
        # would hold every local run for a check that never ran. Warn and
        # go on. In GitHub Actions the fetch is expected to work, so a
        # failure still fails the check.
        if os.environ.get("GITHUB_ACTIONS") != "true":
            print(
                "WARNING: mod-overseer pin not checked: fetch failed (%s)"
                % _fetch_failure_reason(fetched),
                file=sys.stderr,
            )
            return 0
        if fetched.stderr:
            sys.stderr.write(fetched.stderr)
        return fetched.returncode
    result = subprocess.run(
        [
            "git",
            "-C",
            args.submodule,
            "merge-base",
            "--is-ancestor",
            "HEAD",
            "FETCH_HEAD",
        ],
        check=False,
    )
    if result.returncode == 0:
        return 0
    if result.returncode == 1:
        print(
            "mod-overseer submodule pin is not an ancestor of origin/main",
            file=sys.stderr,
        )
        return 1
    raise subprocess.CalledProcessError(result.returncode, result.args)


if __name__ == "__main__":
    raise SystemExit(main())
