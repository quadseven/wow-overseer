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

import ast
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
# the parallel runner would, and records each module's result and whether
# sys.modules["pymysql"] was the same object after it as before it.
PAIR = """
    import io, json, sys, unittest
    sys.path.insert(0, "")
    out = []
    for name in sys.argv[1:]:
        before = sys.modules.get("pymysql")
        suite = unittest.defaultTestLoader.loadTestsFromName(name)
        result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        problems = [str(t) + "\\n" + tb for t, tb in result.errors + result.failures]
        out.append({
            "module": name,
            "ok": result.wasSuccessful(),
            "problems": problems,
            "pymysql_restored": sys.modules.get("pymysql") is before,
        })
    print(json.dumps(out))
"""


class TwoModulesInOneProcess(unittest.TestCase):
    """Two modules that share a batch pass in either order and leave
    sys.modules["pymysql"] as they found it."""

    PAIRS = [
        ("test_apiv2_social", "test_low_bag_sales"),
        ("test_low_bag_sales", "test_standin"),
    ]

    def test_each_pair_passes_in_both_orders(self):
        for pair in self.PAIRS:
            for order in (pair, pair[::-1]):
                with self.subTest(order=order):
                    for got in _run(PAIR, *order):
                        self.assertTrue(got["ok"], "\n".join(got["problems"]))
                        self.assertTrue(got["pymysql_restored"], got["module"])


# Imports every test module in turn, in one process, and reports what each
# import did to sys.modules that outlives it:
# - an entry it replaced or removed;
# - a new entry with no spec that a repository module holds (a stub);
# - a module it holds, or a fresh copy it made holds, under a name
#   sys.modules maps to a different object (a second copy of a module).
# _stub_modules.FRESH_COPIES lists the private copies made on purpose.
GUARD = """
    import json, pathlib, sys, types
    sys.path.insert(0, "")
    ROOT = pathlib.Path.cwd().resolve()
    me = sys.argv[1]
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
            if sys.modules.get(key) is not value:
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


# sys.modules methods that change it.
_WRITES = {"setdefault", "update", "pop", "popitem", "clear", "__setitem__"}


def _top_level_writes(tree):
    """Line numbers of statements run at import time, outside any function
    or class, that change sys.modules directly. A write inside a
    `with stub_modules(...)` block is restored by the helper and is not one."""

    def is_sys_modules(node):
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "modules"
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        )

    def writes(node):
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in _WRITES
                and is_sys_modules(sub.func.value)
            ):
                yield sub.lineno
            targets = []
            if isinstance(sub, (ast.Assign, ast.Delete)):
                targets = sub.targets
            elif isinstance(sub, (ast.AugAssign, ast.AnnAssign)):
                targets = [sub.target]
            for target in targets:
                if isinstance(target, ast.Subscript) and is_sys_modules(target.value):
                    yield sub.lineno

    def statements(body):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.With) and any(
                isinstance(item.context_expr, ast.Call)
                and getattr(item.context_expr.func, "id", None) == "stub_modules"
                for item in stmt.items
            ):
                continue
            yield stmt

    for stmt in statements(tree.body):
        yield from writes(stmt)


class NoModuleWritesSysModulesAtImport(unittest.TestCase):
    """The import guard above runs with whatever driver is installed, so a
    `sys.modules.setdefault("pymysql", ...)` is a no-op there when PyMySQL
    is installed and still leaves a stub where it is not. Read the source
    instead: no test module changes sys.modules at import time except
    through stub_modules."""

    def test_no_test_module_writes_sys_modules_at_import(self):
        findings = []
        for path in sorted(TESTS.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            findings += [f"{path.name}:{line}" for line in _top_level_writes(tree)]
        self.assertEqual([], findings, "\n".join(findings))

    def test_the_check_sees_a_bare_stub_and_skips_a_helper_block(self):
        source = textwrap.dedent(
            """
            import sys, types
            sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
            sys.modules["x"] = types.ModuleType("x")
            with stub_modules(pymysql=PYMYSQL):
                sys.modules["y"] = None
            def later():
                sys.modules["z"] = None
            """
        )
        self.assertEqual([3, 4], list(_top_level_writes(ast.parse(source))))


if __name__ == "__main__":
    unittest.main()
