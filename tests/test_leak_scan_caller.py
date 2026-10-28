"""The leak-scan caller allows the public sibling repos in both ref forms.

The shared scanner (infra-public, _reusable.leak-scan.yml) exempts an
`<owner>/<name>#N` ref only when `allowed-repo-refs` lists `<owner>/<name>`;
a bare `<name>` entry exempts the bare `<name>#N` form alone. This repo cites
the module ticket tracker owner-qualified all over its code, so a bare entry
turns every new qualified ref into an enforced `[private-issue-ref]` failure
(#1493, seen on #1492).
"""

import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
CALLER = HERE / ".github" / "workflows" / "check.leak-scan.yml"
OWN_REPO = "quadseven/wow-overseer"
QUALIFIED_REF = re.compile(r"\b(quadseven/[A-Za-z0-9_.-]+)#[0-9]+")
# Trees that are not this repo's own source: the module submodule and tooling.
SKIP_DIRS = {"mod-overseer", "node_modules"}


def allowed_repo_refs() -> list[str]:
    match = re.search(r"^\s*allowed-repo-refs:\s*(.+?)\s*$", CALLER.read_text(), re.M)
    if match is None:
        raise AssertionError(f"no allowed-repo-refs line in {CALLER}")
    return [name.strip() for name in match.group(1).split(",") if name.strip()]


def own_python_files():
    for path in sorted(HERE.rglob("*.py")):
        parts = path.relative_to(HERE).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
            continue
        yield path


class LeakScanCallerTest(unittest.TestCase):
    def test_every_qualified_ref_in_the_code_is_allowed_in_that_form(self):
        allowed = set(allowed_repo_refs()) | {OWN_REPO}
        flagged = {}
        for path in own_python_files():
            for repo in QUALIFIED_REF.findall(path.read_text(errors="replace")):
                if repo not in allowed:
                    flagged.setdefault(repo, str(path.relative_to(HERE)))
        self.assertEqual(
            flagged,
            {},
            "list these repos owner-qualified in allowed-repo-refs, or the "
            "enforced leak scan fails each new qualified ref to them",
        )

    def test_the_public_module_repos_are_listed_owner_qualified(self):
        refs = allowed_repo_refs()
        for name in ("mod-overseer", "mod-playerbots", "infra-public"):
            with self.subTest(name=name):
                self.assertIn(f"quadseven/{name}", refs)
                self.assertNotIn(name, refs)


if __name__ == "__main__":
    unittest.main()
