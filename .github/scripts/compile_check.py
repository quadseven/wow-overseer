#!/usr/bin/env python3
"""Refuse an interpreter older than the declared floor, then compile every
tracked .py file under the current directory, before its tests run
(infra#3440).

`unittest discover` reports a module the interpreter cannot parse as ONE
failing test, and the SyntaxError names no version. A suite running on an
older Python than its code needs therefore reads as a single ordinary
regression. This fails first instead: on the interpreter, by version, and on
syntax the floor did not anticipate, by file and line. It only reads files;
no .pyc is written.

Only tracked files are compiled (`git ls-files`), so a submodule's contents
and untracked scratch are out of scope. check.python-units.yml runs it from
each matrix directory with `--min-python`, and check_python_interpreter.py
guards that declaration.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


class ListingError(Exception):
    """git could not list the directory's tracked files."""


def parse_version(text: str) -> tuple[int, int]:
    major, _, minor = text.partition(".")
    if not (major.isdigit() and minor.isdigit()):
        raise argparse.ArgumentTypeError(f"expected MAJOR.MINOR, got {text!r}")
    return int(major), int(minor)


def tracked_python_files(root: Path) -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        raise ListingError(
            f"cannot list the tracked .py files under {root} with git: {exc}"
        ) from exc
    return [root / name for name in listed.split("\0") if name]


def compile_errors(files: list[Path]) -> list[str]:
    """One message per file that cannot be read or compiled. A bad file is
    reported and the rest still compile, so one failure hides no other."""
    errors: list[str] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{path}: unreadable: {exc}")
            continue
        try:
            compile(source, str(path), "exec", dont_inherit=True)
        except SyntaxError as exc:
            errors.append(f"{path}:{exc.lineno}: {exc.msg}")
        except ValueError as exc:
            # Before 3.12 a NUL byte in the source raised ValueError, not
            # SyntaxError; report it the same way and keep walking.
            errors.append(f"{path}: cannot compile: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse a python3 below the floor, then compile every tracked .py file."
    )
    parser.add_argument(
        "--min-python", type=parse_version, required=True, metavar="X.Y"
    )
    args = parser.parse_args(argv)
    version = "%d.%d.%d" % sys.version_info[:3]
    floor = "%d.%d" % args.min_python
    if sys.version_info[:2] < args.min_python:
        print(
            f"::error::compile-check: python3 here is {version}, below the declared floor {floor} "
            "(check.python-units.yml test-cmd). The runner image changed interpreter; fix the "
            "image, or lower the floor only if FLOORS in check_python_interpreter.py allows it"
        )
        return 1
    try:
        files = tracked_python_files(Path.cwd())
    except ListingError as exc:
        print(f"::error::compile-check: {exc}")
        return 1
    errors = compile_errors(files)
    for error in errors:
        print(
            f"::error::{error} - Python {version} cannot use this file. If it is newer syntax, "
            "raise --min-python in check.python-units.yml and FLOORS in "
            "check_python_interpreter.py to the minor it needs"
        )
    print(
        f"compile-check: {len(files)} tracked .py files, {len(errors)} failed, "
        f"on Python {version} (floor {floor})"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
