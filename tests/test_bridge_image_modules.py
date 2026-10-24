"""The image ships the modules the bridge imports, and no dead module.

The Dockerfile's own comment states the image ships only what bridge.py
imports. `death_dismiss.py` used to violate that: it was copied into the
image but imported by nothing, so it shipped no behavior. This test pins
the invariant: every module bridge.py imports is present in the image, and
a module nothing imports is not shipped.

The bridge is headless - it owns no pixels, no client and no screen
capture - so a death-dialog dismissal (which needs a detector measuring a
click point from a captured frame) cannot be called by any bridge pass.
That decision lives with the screen-owning client, not here.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import unittest

THIRD_PARTY = {"discord", "pymysql", "apiv2"}


def dockerfile_modules() -> set[str]:
    """The Python modules the image copies, from its COPY list."""
    dockerfile = pathlib.Path("Dockerfile").read_text(encoding="utf-8")
    return {m for m in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.py", dockerfile)}


def python_module_names(source: str) -> set[str]:
    """Top-level module names reached by `import X` or `from X import`."""
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def bridge_modules() -> set[str]:
    """The local modules bridge.py imports, excluding stdlib and third-party."""
    bridge = pathlib.Path("bridge.py").read_text(encoding="utf-8")
    names = python_module_names(bridge)
    stdlib = set(sys.stdlib_module_names)
    return {n for n in names if n not in stdlib and n not in THIRD_PARTY}


# Shipped today but reached by no import from the image's entry points
# (bridge.py, map_server.py, the apiv2 endpoints). Each is used only by
# tools/ or by tests, or is not wired yet. The list may only shrink: wire a
# module in or stop copying it, then delete its name here.
KNOWN_UNREACHED = {
    "bag_economy",
    "bonkers",
    "dungeonladder",
    "enroll",
    "lootcard",
    "realmroller",
    "realmroller_act",
    "realmroller_plan",
    "realmroller_world",
    "strands_server",  # a standalone localhost HTTP server, run as its own process
}


def _imported_names(path: pathlib.Path) -> set[str]:
    """Every dotted module name a file imports, `from X import Y` as X and X.Y."""
    out: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update("%s.%s" % (node.module, a.name) for a in node.names)
    return out


def _source_for(name: str) -> pathlib.Path | None:
    base = name.replace(".", "/")
    for candidate in (base + ".py", base + "/__init__.py"):
        if pathlib.Path(candidate).exists():
            return pathlib.Path(candidate)
    return None


def reached_modules() -> set[str]:
    """Module names reachable by imports from the image's entry points.

    apiv2 endpoints are loaded by the package, so each is a root too.
    """
    roots = [pathlib.Path("bridge.py"), pathlib.Path("map_server.py")]
    roots += sorted(pathlib.Path("apiv2").glob("*.py"))
    seen: set[pathlib.Path] = set()
    todo = list(roots)
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        for name in _imported_names(path):
            source = _source_for(name)
            if source is not None:
                todo.append(source)
    return {p.stem for p in seen}


class ImageModuleWiring(unittest.TestCase):
    def test_every_module_bridge_imports_is_in_the_image(self):
        image = dockerfile_modules()
        missing = sorted(bridge_modules() - image)
        self.assertEqual(
            missing,
            [],
            "bridge.py imports a module the image does not ship: %s"
            % ", ".join(missing),
        )

    def test_death_dismiss_is_not_shipped(self):
        """A module imported by nothing ships no behavior and is not copied."""
        self.assertNotIn("death_dismiss", dockerfile_modules())

    def test_every_shipped_module_has_an_importer(self):
        """No module is copied into the image that nothing imports."""
        reached = reached_modules()
        orphans = sorted(
            m
            for m in dockerfile_modules()
            if pathlib.Path(m + ".py").exists()
            and m not in reached
            and m not in KNOWN_UNREACHED
        )
        self.assertEqual(
            orphans, [], "shipped modules with no importer: %s" % ", ".join(orphans)
        )

    def test_known_unreached_list_only_shrinks(self):
        """A listed module that is now imported (or gone) leaves the list."""
        reached = reached_modules()
        stale = sorted(
            m for m in KNOWN_UNREACHED if m in reached or m not in dockerfile_modules()
        )
        self.assertEqual(stale, [], "drop from KNOWN_UNREACHED: %s" % ", ".join(stale))


if __name__ == "__main__":
    unittest.main()
