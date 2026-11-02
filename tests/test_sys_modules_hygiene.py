"""No test module leaves sys.modules different from how it found it (#1648).

The parallel runner (#1290) puts several modules in one process, so a stub
one module leaves in sys.modules, or a module it drops after importing it,
reaches whichever modules share its batch. A module then passed or failed by
how the batches fell: a bare `pymysql` stub left behind turned an except
clause into `AttributeError: module 'pymysql' has no attribute 'err'`, and a
`mock.patch.dict(sys.modules)` around an import dropped the modules that
import pulled in, so the next module imported a second copy whose classes
compared unequal to the first.

Each check runs in a fresh interpreter, so what this process already holds
cannot hide or cause a finding.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent


def _run(script, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(TESTS), env.get("PYTHONPATH")])
    )
    done = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(script), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=600,
    )
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        raise AssertionError(
            f"exit {done.returncode}\n{done.stdout[-3000:]}\n{done.stderr[-3000:]}"
        )
    return json.loads(lines[-1])


# Loads and runs the named modules in order, in one process, as one batch of
# the parallel runner would, and records each module's result.
PAIR = """
    import io, json, sys, unittest
    sys.path.insert(0, "")
    out = []
    for name in sys.argv[1:]:
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        problems = [str(t) + "\\n" + tb for t, tb in result.errors + result.failures]
        out.append({
            "module": name,
            "ok": result.wasSuccessful(),
            "problems": problems,
        })
    print(json.dumps(out))
"""


class TwoModulesInOneProcess(unittest.TestCase):
    """Two modules that share a batch pass in either order."""

    PAIRS = [
        ("test_low_bag_sales", "test_standin"),
    ]

    def test_each_pair_passes_in_both_orders(self):
        for pair in self.PAIRS:
            for order in (pair, pair[::-1]):
                with self.subTest(order=order):
                    for got in _run(PAIR, *order):
                        self.assertTrue(got["ok"], "\n".join(got["problems"]))


# Imports every test module in turn, in one process, and reports what each
# import did to sys.modules that outlives it:
# - an entry it replaced or removed;
# - a new entry with no spec that a repository module holds (a stub);
# - a module it holds, or a fresh copy it made holds, under a name
#   sys.modules maps to a different object (a second copy of a module).
# _stub_modules.FRESH_COPIES lists the private copies made on purpose.
# The driver entry, "pymysql", is exempt until no module installs a stub of
# its own and _stub_modules restores it too (#1648, part three).
GUARD = """
    import json, pathlib, sys, types
    sys.path.insert(0, "")
    ROOT = pathlib.Path.cwd().resolve()
    me = sys.argv[1]
    SHARED = {"pymysql"}
    names = sorted(
        p.stem for p in (ROOT / "tests").glob("test_*.py")
        if p.stem.isidentifier() and p.stem != me
    )

    def fresh():
        mod = sys.modules.get("_stub_modules")
        return {id(m) for m in getattr(mod, "FRESH_COPIES", ())}

    def ours(m):
        path = getattr(m, "__file__", None)
        if not isinstance(m, types.ModuleType) or not path:
            return False
        try:
            return pathlib.Path(path).resolve().is_relative_to(ROOT)
        except (OSError, ValueError):
            return False

    findings = []
    for name in names:
        before = dict(sys.modules)
        try:
            __import__(name)
        except Exception:
            pass
        for key, value in before.items():
            if key not in SHARED and sys.modules.get(key) is not value:
                findings.append(f"{name}: replaced or removed sys.modules[{key!r}]")
        added = {k: v for k, v in sys.modules.items() if k not in before}
        # A stand-in: a new entry with no spec that a repository module
        # imported in the same step holds, directly or through a module it
        # holds (a private bridge copy). Libraries register spec-less
        # entries of their own (typing.io, a C extension's submodules);
        # nothing here holds those.
        holders = [m for m in added.values() if ours(m)]
        holders += [v for m in holders for v in list(vars(m).values()) if ours(v)]
        held = {id(v) for m in holders for v in list(vars(m).values())}
        for key, value in added.items():
            if key in SHARED:
                continue
            if getattr(value, "__spec__", None) is None and id(value) in held:
                findings.append(f"{name}: left a stub in sys.modules[{key!r}]")

    copies = fresh()
    todo = [m for m in list(sys.modules.values()) if ours(m)]
    walked = {id(m) for m in todo}
    flagged = set()
    while todo:
        root = todo.pop()
        for attr, value in list(vars(root).items()):
            if not ours(value):
                continue
            current = sys.modules.get(value.__name__)
            if current is not value and id(value) not in walked:
                # A copy sys.modules does not hold: walk what it holds too.
                walked.add(id(value))
                todo.append(value)
            if id(value) in copies or id(value) in flagged:
                continue
            if current is not None and current is not value:
                flagged.add(id(value))
                findings.append(
                    f"{root.__name__}.{attr}: a second copy of {value.__name__}"
                )
    print(json.dumps(findings))
"""


class EveryModuleRestoresSysModules(unittest.TestCase):
    def test_no_module_import_leaves_sys_modules_changed(self):
        findings = _run(GUARD, pathlib.Path(__file__).stem)
        self.assertEqual([], findings, "\n".join(findings))


if __name__ == "__main__":
    unittest.main()
