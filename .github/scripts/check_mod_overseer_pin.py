"""Fail when the checked-out mod-overseer pin is not on origin/main."""

import argparse
import subprocess
import sys


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
    subprocess.run([*fetch, "origin", "main"], check=True)
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
