"""No test imports the real PyMySQL without a fallback.

CI installs tests/requirements.txt, so a bare `import pymysql` in a test
passes there. The Loom lane check runs the suite on a bare python3 with no
PyMySQL, so the same import fails the lane's base check on an unmodified
main and holds every ticket of this repo (two item-goal tests did this on
2026-11-06). A test that only needs the driver's exception classes uses
`_stub_modules.PYMYSQL`; one that wants the real driver imports it inside a
`try` that catches ImportError, or in a class or test under
`unittest.skipUnless` / `skipIf` (the repo's REAL_PYMYSQL gate).
"""

import ast
import pathlib
import unittest

TESTS = pathlib.Path(__file__).resolve().parent


def _skip_gated(parent):
    """True for a class or function decorated with unittest.skipUnless/skipIf."""
    if not isinstance(parent, (ast.ClassDef, ast.FunctionDef)):
        return False
    for deco in parent.decorator_list:
        func = deco.func if isinstance(deco, ast.Call) else None
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name in ("skipUnless", "skipIf"):
            return True
    return False


def _guarded(node, parents):
    """True when `node` sits in a try body whose handlers catch ImportError,
    or under a skipUnless/skipIf gate."""
    child = node
    for parent in reversed(parents):
        if _skip_gated(parent):
            return True
        if isinstance(parent, ast.Try) and child in parent.body:
            for handler in parent.handlers:
                names = handler.type
                kinds = names.elts if isinstance(names, ast.Tuple) else [names]
                if any(
                    isinstance(k, ast.Name)
                    and k.id in ("ImportError", "ModuleNotFoundError")
                    for k in kinds
                ):
                    return True
        child = parent
    return False


def bare_driver_imports(source):
    """Line numbers of unguarded `import pymysql...` / `from pymysql...`."""
    found = []

    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            is_driver = (
                isinstance(child, ast.Import)
                and any(a.name.split(".")[0] == "pymysql" for a in child.names)
            ) or (
                isinstance(child, ast.ImportFrom)
                and (child.module or "").split(".")[0] == "pymysql"
            )
            if is_driver and not _guarded(child, parents + [node]):
                found.append(child.lineno)
            walk(child, parents + [node])

    walk(ast.parse(source), [])
    return found


class NoBareDriverImport(unittest.TestCase):
    def test_every_test_module_imports_the_driver_with_a_fallback(self):
        offenders = []
        for path in sorted(TESTS.glob("*.py")):
            for line in bare_driver_imports(path.read_text()):
                offenders.append(f"{path.name}:{line}")
        self.assertEqual([], offenders)

    def test_the_scan_finds_a_bare_import_in_a_test_method(self):
        source = "def test_x():\n    import pymysql\n    from pymysql import err\n"
        self.assertEqual([2, 3], bare_driver_imports(source))

    def test_the_scan_allows_an_import_error_fallback(self):
        source = (
            "try:\n    import pymysql\nexcept ImportError:\n    pymysql = None\n"
            "try:\n    import pymysql.err as real\n"
            "except (OSError, ModuleNotFoundError):\n    real = None\n"
        )
        self.assertEqual([], bare_driver_imports(source))

    def test_the_scan_allows_a_skip_gated_class(self):
        source = (
            "@unittest.skipUnless(REAL, 'needs the driver')\n"
            "class T(unittest.TestCase):\n"
            "    def test_x(self):\n        import pymysql.err as real\n"
        )
        self.assertEqual([], bare_driver_imports(source))

    def test_the_scan_still_flags_an_import_in_the_handler(self):
        source = "try:\n    pass\nexcept ImportError:\n    import pymysql\n"
        self.assertEqual([4], bare_driver_imports(source))


if __name__ == "__main__":
    unittest.main()
