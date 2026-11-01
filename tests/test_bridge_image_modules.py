"""The image ships its runtime entry points and their imports, and no dead module.

The Dockerfile copies runtime modules explicitly. The bridge's imports must
be present, and the scheduled collector must start from those copied files.
`death_dismiss.py` used to be copied without any runtime caller; that dead
module stays outside the image.

The bridge is headless - it owns no pixels, no client and no screen
capture - so a death-dialog dismissal (which needs a detector measuring a
click point from a captured frame) cannot be called by any bridge pass.
That decision lives with the screen-owning client, not here.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
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
# (bridge.py, map_server.py, the apiv2 endpoints and the metric collector). Each is used only by
# tools/ or by tests, or is not wired yet. The list may only shrink: wire a
# module in or stop copying it, then delete its name here.
KNOWN_UNREACHED = {
    "bag_economy",
    "bonkers",
    "dungeonladder",
    "enroll",
    "lootcard",
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

    apiv2 endpoints and the scheduled metric collector are roots too.
    """
    roots = [pathlib.Path("bridge.py"), pathlib.Path("map_server.py")]
    roots.append(pathlib.Path("tools/metric_watcher.py"))
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
    def test_scheduled_metric_watcher_starts_from_image_files(self):
        dockerfile = pathlib.Path("Dockerfile").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            target = root / "tools"
            target.mkdir()
            for sources in re.findall(r"^COPY (.+) /app/tools/$", dockerfile, re.M):
                for source in sources.split():
                    shutil.copyfile(source, target / pathlib.Path(source).name)
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            for args in (["tools/metric_watcher.py"], ["-m", "tools.metric_watcher"]):
                with self.subTest(args=args):
                    result = subprocess.run(
                        [sys.executable, "-u", *args, "--help"],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--api-root", result.stdout)

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
