"""The mod-overseer gate (tests/modsource.py) and that every read uses it.

A checkout without the submodule (every `git worktree add`, every plain
clone) used to fail hundreds of tests with FileNotFoundError, all for that
one reason. modsource turns that into a clean local skip and a hard CI
failure. These tests pin both halves, and that no test opens a mod-overseer
path on its own again, which is how the hundreds came about.
"""

import ast
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import warnings
from unittest import mock

import modsource

TESTS = pathlib.Path(__file__).resolve().parent
REPO = TESTS.parent
PIN_CHECK = REPO / ".github" / "scripts" / "check_mod_overseer_pin.py"

# Path methods that touch the filesystem. Calling one on a mod-overseer path
# outside modsource bypasses the gate.
FS_METHODS = {
    "read_text",
    "read_bytes",
    "open",
    "glob",
    "rglob",
    "iterdir",
    "exists",
    "is_file",
    "is_dir",
    "stat",
}


class TheGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        empty = pathlib.Path(tmp.name)
        patcher = mock.patch.object(modsource, "SUBMODULE", empty)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.missing = empty / "src" / "mod_overseer.cpp"

    def _env_without_ci(self):
        return {k: v for k, v in os.environ.items() if k != "CI"}

    def test_a_missing_submodule_is_a_skip_locally(self):
        with mock.patch.dict(os.environ, self._env_without_ci(), clear=True):
            for call in (
                lambda: modsource.read(self.missing),
                lambda: modsource.glob(self.missing.parent, "*.sql"),
                lambda: modsource.exists(self.missing),
                modsource.require,
            ):
                with self.assertRaises(unittest.SkipTest) as caught:
                    call()
                self.assertIn("git submodule update --init", str(caught.exception))

    def test_a_missing_submodule_fails_under_ci(self):
        """CI must never go green by skipping the tests the submodule is for."""
        with mock.patch.dict(os.environ, {"CI": "true"}):
            with self.assertRaises(AssertionError) as caught:
                modsource.read(self.missing)
            self.assertNotIsInstance(caught.exception, unittest.SkipTest)
            self.assertIn("submodules: true", str(caught.exception))

    def test_a_checked_out_submodule_reads_through(self):
        (modsource.SUBMODULE / "src").mkdir()
        self.missing.write_text("// module\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CI": "true"}):
            self.assertEqual(modsource.read(self.missing), "// module\n")
            self.assertTrue(modsource.exists(self.missing))
            self.assertEqual(
                modsource.glob(self.missing.parent, "*.cpp"), [self.missing]
            )


def _tainted_names(tree: ast.AST) -> set:
    """Names bound, anywhere in the file, to an expression built from a
    'mod-overseer' string, from modsource's own path constants, or from
    another such name (SQL = SQL_DIR / "x.sql")."""
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "modsource":
            names.update(a.asname or a.name for a in node.names)
    assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if node.value is None or not _is_tainted(node.value, names):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name) and sub.id not in names:
                        names.add(sub.id)
                        changed = True
    return names


def _is_tainted(expr: ast.AST, names: set) -> bool:
    for sub in ast.walk(expr):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value == "mod-overseer" or sub.value.startswith("mod-overseer/"):
                return True
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        # A class attribute bound to such a path, read back as self.MODULE.
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id in ("self", "cls")
            and sub.attr in names
        ):
            return True
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == "modsource"
            and sub.attr.isupper()
        ):
            return True
    return False


def direct_reads(source: str) -> list:
    """(line, method) for every filesystem call on a mod-overseer path."""
    with warnings.catch_warnings():
        # Parsing is all this needs; an escape a test file gets away with is
        # that file's business, not this scan's.
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source)
    names = _tainted_names(tree)
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in FS_METHODS
            and _is_tainted(node.func.value, names)
        ):
            found.append((node.lineno, node.func.attr))
    return sorted(found)


class EveryReadGoesThroughTheGate(unittest.TestCase):
    def test_the_scan_sees_the_shapes_it_must(self):
        """A scan that finds nothing proves nothing: pin what it catches."""
        caught = direct_reads(
            "import modsource, pathlib\n"
            'ROOT = pathlib.Path(".")\n'
            "MODULE = modsource.MODULE\n"
            'SQL_DIR = ROOT / "mod-overseer" / "data"\n'
            'MIGRATION = SQL_DIR / "x.sql"\n'
            "a = MODULE.read_text()\n"
            'b = list(SQL_DIR.glob("*.sql"))\n'
            "c = MIGRATION.exists()\n"
            "d = modsource.DECISIONS.read_text()\n"
            "e = modsource.read(MODULE)\n"
            'f = ROOT.joinpath("bridge.py").read_text()\n'
            "class T:\n"
            "    SRC = modsource.MODULE\n"
            "    def t(self):\n"
            "        return self.SRC.read_text()\n"
        )
        self.assertEqual(
            caught,
            [
                (6, "read_text"),
                (7, "glob"),
                (8, "exists"),
                (9, "read_text"),
                (15, "read_text"),
            ],
        )

    def test_no_test_opens_a_mod_overseer_path_directly(self):
        offenders = []
        for path in sorted(TESTS.glob("*.py")):
            if path.name in ("modsource.py", "test_modsource_gate.py"):
                continue
            for line, method in direct_reads(path.read_text(encoding="utf-8")):
                offenders.append("%s:%d .%s()" % (path.name, line, method))
        self.assertEqual(
            offenders,
            [],
            "read mod-overseer files through tests/modsource.py "
            "(modsource.read / glob / exists), so a checkout without the "
            "submodule skips locally and fails under CI",
        )


class TheSubmodulePin(unittest.TestCase):
    def _git(self, directory, *args):
        return subprocess.run(
            ["git", "-C", str(directory), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_a_pin_outside_main_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            remote = root / "remote.git"
            seed = root / "seed"
            checkout = root / "checkout"
            self._git(root, "init", "--bare", str(remote))
            self._git(root, "init", str(seed))
            self._git(seed, "config", "user.name", "Test")
            self._git(seed, "config", "user.email", "test@example.com")
            (seed / "file").write_text("main\n", encoding="utf-8")
            self._git(seed, "add", "file")
            self._git(seed, "commit", "-m", "main")
            self._git(seed, "branch", "-M", "main")
            self._git(seed, "remote", "add", "origin", str(remote))
            self._git(seed, "push", "origin", "main")
            self._git(seed, "checkout", "--orphan", "off-main")
            self._git(seed, "rm", "-rf", ".")
            (seed / "file").write_text("off-main\n", encoding="utf-8")
            self._git(seed, "add", "file")
            self._git(seed, "commit", "-m", "off main")
            off_main = self._git(seed, "rev-parse", "HEAD").stdout.strip()
            self._git(seed, "push", "origin", "HEAD:off-main")
            self._git(remote.parent, "clone", str(remote), str(checkout))
            self._git(checkout, "checkout", off_main)

            result = subprocess.run(
                [sys.executable, str(PIN_CHECK), str(checkout)],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
