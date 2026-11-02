"""Fail when the vendored fork pin differs from the deploy repo's.

UPSTREAM-PINS.env here is a vendored copy of the deploy repo's file. Its
header names that file (owner/repo's path). This compares AC_MODULE_SHA, the
fork revision the realm builds, between the two and exits 1 with both values
when they differ.

The deploy repo is read-only and may be private. With --deploy-file the
comparison is purely local (the unit tests use this). Otherwise it is read
with `gh api`; when it cannot be read (no token on a runner) the check says
so and is skipped, unless --require is given, which turns that into a
failure.
"""

import argparse
import base64
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SHA_LINE = re.compile(r"^AC_MODULE_SHA=([0-9a-f]{40})$", re.M)
SOURCE = re.compile(r"^#\s+([\w.-]+/[\w.-]+)'s (\S*UPSTREAM-PINS\.env)\s*$", re.M)


def module_sha(text):
    found = SHA_LINE.search(text)
    if not found:
        raise ValueError("no well-formed AC_MODULE_SHA line")
    return found.group(1)


def deploy_source(vendored_text):
    found = SOURCE.search(vendored_text)
    if not found:
        raise ValueError("the vendored header does not name the deploy repo file")
    return found.group(1), found.group(2)


def fetch_deploy(vendored_text):
    slug, path = deploy_source(vendored_text)
    out = subprocess.run(
        ["gh", "api", f"repos/{slug}/contents/{path}", "--jq", ".content"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        return None
    return base64.b64decode(out.stdout).decode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendored", default=str(REPO / "UPSTREAM-PINS.env"))
    parser.add_argument("--deploy-file")
    parser.add_argument("--require", action="store_true")
    args = parser.parse_args(argv)

    vendored_text = pathlib.Path(args.vendored).read_text(encoding="utf-8")
    try:
        mine = module_sha(vendored_text)
        if args.deploy_file:
            deploy_text = pathlib.Path(args.deploy_file).read_text(encoding="utf-8")
        else:
            deploy_text = fetch_deploy(vendored_text)
            if deploy_text is None:
                msg = "fork pin parity: the deploy repo file is not readable here"
                if args.require:
                    print(msg, file=sys.stderr)
                    return 1
                print(msg + "; SKIPPED", file=sys.stderr)
                return 0
        theirs = module_sha(deploy_text)
    except ValueError as err:
        print(f"fork pin parity: {err}", file=sys.stderr)
        return 1
    if mine != theirs:
        print(
            "fork pin parity: the vendored AC_MODULE_SHA is "
            f"{mine} but the deploy repo pins {theirs}; bump "
            "UPSTREAM-PINS.env and re-verify the patches against the new revision",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
