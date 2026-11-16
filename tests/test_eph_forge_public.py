"""The forge ships no deployment-specific name (AGENTS.md: a public repository).

Every value tied to one deployment, such as a backup file prefix, a registry or a
host, must come from configuration with a visibly fake placeholder in the example.
This scans the forge's own files for the shapes that gave the first versions
away: a realm or namespace name, internal host suffixes, node names and
private-range addresses.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Files the scan covers: the package, its data, its tests and fixtures. This file
# lists the forbidden shapes, so it is not scanned.
SCANNED = (
    [*sorted((ROOT / "forge").glob("*.py"))]
    + [*sorted((ROOT / "data" / "forge").glob("*"))]
    + [*sorted((ROOT / "tests").glob("test_eph_forge_*.py"))]
    + [*sorted((ROOT / "tests" / "fixtures").glob("forge_*"))]
)
SELF = pathlib.Path(__file__).resolve()

FORBIDDEN = {
    "a realm or namespace name": re.compile(r"wow-(?:dev|rehearsal|ephemeral)"),
    "an internal host suffix": re.compile(r"\.(?:svc|local|internal|lan|ts\.net)\b"),
    "a node or machine name": re.compile(r"\b(?:srv|nuc)-?[0-9a-z]+\b"),
    "a private-range address": re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
    ),
    "a user path": re.compile(r"(?:/Users/|C:[/\\]Users)[A-Za-z]"),
}


class NoDeploymentNames(unittest.TestCase):
    def test_the_scan_covers_the_forge(self) -> None:
        names = {p.name for p in SCANNED}
        for expected in (
            "build.py",
            "restore.py",
            "table-classes.yaml",
            "config.example.env",
            "test_eph_forge_build.py",
            "forge_acore_characters_tables.txt",
        ):
            self.assertIn(expected, names)

    def test_no_forge_file_names_a_deployment(self) -> None:
        hits = []
        for path in SCANNED:
            if path.resolve() == SELF or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for label, pattern in FORBIDDEN.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    hits.append(
                        f"{path.relative_to(ROOT)}:{line} {label}: {match.group(0)!r}"
                    )
        self.assertEqual(hits, [])

    def test_the_example_config_uses_visibly_fake_values(self) -> None:
        example = (ROOT / "data" / "forge" / "config.example.env").read_text(
            encoding="utf-8"
        )
        values = [
            line.split("=", 1)[1]
            for line in example.splitlines()
            if line and not line.startswith("#") and "=" in line
        ]
        self.assertGreaterEqual(len(values), 2)
        for value in values:
            self.assertRegex(value, r"example", value)

    def test_the_scan_catches_what_it_is_for(self) -> None:
        samples = {
            "a realm or namespace name": "wow-" + "dev",
            "an internal host suffix": "mysql.x." + "svc",
            "a node or machine name": "srv-" + "box",
            "a private-range address": "10." + "1.2.3",
        }
        for label, sample in samples.items():
            self.assertRegex(sample, FORBIDDEN[label], label)


if __name__ == "__main__":
    unittest.main()
