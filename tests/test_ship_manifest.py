"""Docker COPY sources exist and continuation syntax stays valid."""

from __future__ import annotations

import pathlib
import shlex
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"


def _copy_sources() -> set[pathlib.Path]:
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    sources: set[pathlib.Path] = set()
    instruction: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not instruction:
            if not stripped.upper().startswith("COPY "):
                continue
            instruction.append(stripped)
        else:
            instruction.append(stripped)
        if instruction[-1].endswith("\\"):
            instruction[-1] = instruction[-1][:-1].rstrip()
            continue
        parts = shlex.split(" ".join(instruction))
        instruction.clear()
        if len(parts) < 3:
            continue
        sources.update(
            ROOT / source for source in parts[1:-1] if not source.startswith("--")
        )
    return sources


class ShipManifestTests(unittest.TestCase):
    def test_every_copy_source_exists(self):
        missing = sorted(
            str(path.relative_to(ROOT)) for path in _copy_sources() if not path.exists()
        )
        self.assertEqual(
            missing, [], "Dockerfile COPY sources missing: " + ", ".join(missing)
        )

    def test_every_continuation_is_a_real_line_break(self):
        backslash = chr(92)
        stray = []
        for number, line in enumerate(
            DOCKERFILE.read_text(encoding="utf-8").splitlines(), 1
        ):
            body = line.rstrip()
            if body.endswith(backslash):
                body = body[:-1]
            if backslash in body:
                stray.append((number, line))
        self.assertEqual(stray, [], "backslash not at end of line: %s" % stray)

    def test_jquery_ships_from_the_build_context(self):
        self.assertIn(ROOT / "jquery.min.js", _copy_sources())
