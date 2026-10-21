"""The one gate every test passes through to read the mod-overseer submodule.

A large minority of this suite reads the pinned C++ module (and its SQL) as
TEXT, to assert that a Python-side assumption still matches what the module
actually does. The submodule is not initialised by `git worktree add` or a
plain clone, so each of those reads used to raise FileNotFoundError on its
own: a bare `unittest discover` on such a checkout reported hundreds of
errors that all meant one thing, and buried any real regression among them.

Every read now goes through `read`, `glob`, `exists` (or `require`), which
decide once what a missing submodule means:

- locally it is a clean skip, naming the command that fixes it;
- under CI (GitHub Actions always sets CI) it is a failure, so the suite can
  never go green by skipping the tests the submodule exists for. check.yml
  checks out with `submodules: true`.

unittest turns a SkipTest raised at import time, in setUpClass or in a test
into a skip, so a module-level `SRC = modsource.read(MODULE)` is fine.
tests/test_modsource_gate.py fails if a test opens a mod-overseer path
directly again.
"""

import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUBMODULE = ROOT / "mod-overseer"
SRC = SUBMODULE / "src"
MODULE = SRC / "mod_overseer.cpp"
DECISIONS = SRC / "overseer_decisions.cpp"
DECISIONS_H = SRC / "overseer_decisions.h"
SQL_DIR = SUBMODULE / "data" / "sql" / "characters" / "base"


def require() -> None:
    """Skip (locally) or fail (under CI) unless the submodule is checked out."""
    if (SUBMODULE / "src").is_dir():
        return
    if os.environ.get("CI"):
        raise AssertionError(
            "mod-overseer submodule missing under CI: checkout needs submodules: true"
        )
    raise unittest.SkipTest(
        "mod-overseer submodule not checked out: "
        "git submodule update --init mod-overseer"
    )


def read(path: pathlib.Path, encoding: str = "utf-8", errors=None) -> str:
    """The text of a file inside the submodule, once require() has passed."""
    require()
    return pathlib.Path(path).read_text(encoding=encoding, errors=errors)


def glob(path: pathlib.Path, pattern: str) -> list:
    """path.glob(pattern) inside the submodule, sorted, once require() has
    passed. A list, not a generator, so an empty match is a visible []."""
    require()
    return sorted(pathlib.Path(path).glob(pattern))


def exists(path: pathlib.Path) -> bool:
    """Whether a file inside the submodule exists, once require() has passed:
    a migration that is missing from a checked-out submodule is still a
    failure, a submodule that is not checked out is not."""
    require()
    return pathlib.Path(path).exists()
