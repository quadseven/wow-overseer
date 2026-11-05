"""No apiv2 handler reads a private name off the server module (#1701).

`ctx.server` is map_server itself (_v2_context). A handler that reads
`ctx.server._X` couples itself to a name map_server is free to rename, and a
fake server in a test has to spell that private name too. Every name an apiv2
handler takes from the server is public. This reads each apiv2 module's
syntax tree, so an alias (`server = ctx.server`) or a parameter that carries
the server (`build(..., server)`) is held to the same rule.
"""

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APIV2 = ROOT / "apiv2"


def _is_ctx_server(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "server"
        and isinstance(node.value, ast.Name)
        and node.value.id == "ctx"
    )


def _private(attr: str) -> bool:
    return attr.startswith("_") and not attr.startswith("__")


def server_reads(source: str) -> list[tuple[int, str]]:
    """(line, name) for each name read off the server in `source`."""
    tree = ast.parse(source)
    # Names the server reaches a handler under: the conventional parameter
    # name, and anything assigned from ctx.server (alone or in a tuple).
    aliases = {"server"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            pairs = []
            if isinstance(target, ast.Name):
                pairs.append((target, node.value))
            elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                pairs.extend(zip(target.elts, node.value.elts, strict=True))
            for name, value in pairs:
                if isinstance(name, ast.Name) and _is_ctx_server(value):
                    aliases.add(name.id)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if _is_ctx_server(base) or (isinstance(base, ast.Name) and base.id in aliases):
            found.append((node.lineno, node.attr))
    return found


def private_reads(source: str) -> list[tuple[int, str]]:
    """(line, name) for each private name read off the server in `source`."""
    return [(line, name) for line, name in server_reads(source) if _private(name)]


class NoPrivateServerNamesTest(unittest.TestCase):
    def test_no_apiv2_module_reads_a_private_server_name(self):
        offenders = []
        for path in sorted(APIV2.glob("*.py")):
            for line, name in private_reads(path.read_text()):
                offenders.append(f"apiv2/{path.name}:{line} reads server.{name}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_every_public_name_the_handlers_read_exists(self):
        # The renamed names are still served by map_server, so a handler
        # that reads one does not fail at request time. Read off the syntax
        # tree, so the check needs none of map_server's imports installed.
        defined = set()
        for node in ast.parse((ROOT / "map_server.py").read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                defined.update(t.id for t in targets if isinstance(t, ast.Name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                defined.update((a.asname or a.name).split(".")[0] for a in node.names)
        read = {
            name
            for path in sorted(APIV2.glob("*.py"))
            for _line, name in server_reads(path.read_text())
            if not name.startswith("_")
        }
        missing = sorted(read - defined)
        self.assertEqual(missing, [])

    # The detector itself: each shape it must catch, and the ones it must not.
    def test_detector_catches_a_direct_read(self):
        self.assertEqual(private_reads("x = ctx.server._A\n"), [(1, "_A")])

    def test_detector_catches_an_alias(self):
        src = "srv = ctx.server\nsrv._B\n"
        self.assertEqual(private_reads(src), [(2, "_B")])

    def test_detector_catches_a_tuple_alias(self):
        src = "s, rd = ctx.server, ctx.read\ns._C\nrd._cursor\n"
        self.assertEqual(private_reads(src), [(2, "_C")])

    def test_detector_catches_a_server_parameter(self):
        src = "def build(q, server):\n    return server._D\n"
        self.assertEqual(private_reads(src), [(2, "_D")])

    def test_detector_passes_public_and_dunder_names(self):
        src = "ctx.server.ITEMS\nserver.__name__\nctx.read._run\n"
        self.assertEqual(private_reads(src), [])


if __name__ == "__main__":
    unittest.main()
