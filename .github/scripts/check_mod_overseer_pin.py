"""Fail when the checked-out mod-overseer pin is not on origin/main."""

import argparse
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submodule", nargs="?", default="mod-overseer")
    args = parser.parse_args(argv)

    subprocess.run(
        ["git", "-C", args.submodule, "fetch", "--quiet", "origin", "main"],
        check=True,
    )
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
