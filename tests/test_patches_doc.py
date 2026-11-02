"""docs/HISTORY.md says what patches/ holds and where realm patches apply (#1781).

patches/mod-playerbots/ is read by tests only. The realm build applies
patches from the infrastructure repo's tree, so a patch added here and not
named in the doc reads as if it ships. These tests keep the doc's list of
patches in step with the directory, and keep the one line that says where
the realm's patches really come from.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HISTORY = ROOT / "docs" / "HISTORY.md"
PATCHES = ROOT / "patches" / "mod-playerbots"


def _vendored_section():
    text = HISTORY.read_text(encoding="utf-8")
    match = re.search(r"^## Vendored copies\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if match is None:
        raise AssertionError("docs/HISTORY.md has no '## Vendored copies' section")
    return match.group(1)


def _named_numbers(section):
    """Every NNNN the section names, with `A` to `B` ranges expanded."""
    named = set(re.findall(r"`(\d{4})`", section))
    for low, high in re.findall(r"`(\d{4})` to `(\d{4})`", section):
        named.update(f"{n:04d}" for n in range(int(low), int(high) + 1))
    return named


class TheDocNamesEveryPatchHere(unittest.TestCase):
    def test_every_patch_number_is_named(self):
        named = _named_numbers(_vendored_section())
        for patch in sorted(PATCHES.glob("*.patch")):
            number = patch.name.split("-", 1)[0]
            with self.subTest(patch=patch.name):
                self.assertIn(number, named)

    def test_it_says_where_realm_patches_apply(self):
        section = " ".join(_vendored_section().split())
        self.assertIn("applied only from the infrastructure repo's tree", section)
        self.assertIn("production/docker/azerothcore-playerbots/patches/", section)


if __name__ == "__main__":
    unittest.main()
