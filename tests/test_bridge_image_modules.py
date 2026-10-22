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


if __name__ == "__main__":
    unittest.main()
