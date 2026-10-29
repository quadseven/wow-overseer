"""Patch 1 of 4 for Majordomo Executus: casters hold on a Magic Reflection add.

The patch lives under patches/mod-playerbots/ and is applied to the pinned
fork when the realm image is built. This repo's CI carries no fork source, so
these tests read the patch as text and prove it applies two ways:

- always: the pre-image of every hunk is rebuilt from the patch itself and
  `git apply --check` runs on it, which fails on a malformed hunk (wrong line
  counts, mangled context);
- when a checkout of the pinned fork is given in PLAYERBOTS_SRC: the real
  `git apply --check` against that tree.
"""

import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = (
    ROOT
    / "patches/mod-playerbots"
    / "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch"
)
TARGETS = (
    "src/Ai/Raid/MC/MCHelpers.h",
    "src/Ai/Raid/MC/MCStrategy.cpp",
)


def added_lines(text):
    return [
        line[1:]
        for line in text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def removed_lines(text):
    return [
        line[1:]
        for line in text.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]


class MajordomoReflectPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.added = "\n".join(added_lines(cls.text))

    def test_patch_keys_on_magic_reflection_by_spell_id(self):
        self.assertIn("SPELL_MAGIC_REFLECTION = 20619", self.added)
        self.assertIn("unit->HasAura(SPELL_MAGIC_REFLECTION)", self.added)

    def test_patch_names_both_add_entries(self):
        self.assertIn("NPC_FLAMEWAKER_HEALER = 11663", self.added)
        self.assertIn("NPC_FLAMEWAKER_ELITE = 11664", self.added)

    def test_only_casters_hold(self):
        self.assertIn("PlayerbotAI::IsCaster(bot)", self.added)
        self.assertIn("TargetValueExclusionType::Dps", self.added)

    def test_reflecting_add_is_excluded_from_damage_targets(self):
        self.assertIn("exclusions.insert(guid);", self.added)
        self.assertIn("reflecting = unit;", self.added)

    def test_patch_logs_the_holding_line(self):
        self.assertIn(
            '"[MC] majordomo: {} casters holding, magic reflection on {}"',
            self.added,
        )
        self.assertIn("getMSTimeDiff(lastLogMs, nowMs) >= 3000", self.added)

    def test_patch_keeps_majordomo_and_core_rager_exclusions(self):
        self.assertNotIn("NPC_MAJORDOMO_EXECUTUS", "\n".join(removed_lines(self.text)))
        self.assertNotIn("NPC_CORE_RAGER", "\n".join(removed_lines(self.text)))

    def test_patch_stays_out_of_the_other_three_patches(self):
        self.assertNotIn("21075", self.added)
        self.assertNotIn("20534", self.added)
        self.assertNotIn("MCMultipliers", self.text)

    def test_patch_touches_only_the_molten_core_strategy_files(self):
        files = tuple(re.findall(r"^diff --git a/(\S+) b/", self.text, re.M))
        self.assertEqual(TARGETS, files)

    def test_patch_is_ascii(self):
        self.text.encode("ascii")


class MajordomoReflectPatchAppliesTest(unittest.TestCase):
    def _git_apply_check(self, tree):
        return subprocess.run(
            ["git", "apply", "--check", str(PATCH)],
            cwd=tree,
            capture_output=True,
            text=True,
        )

    def test_patch_applies_to_its_own_preimage(self):
        text = PATCH.read_text(encoding="utf-8")
        starts = {}
        for m in re.finditer(
            r"^diff --git a/(\S+) b/.*?(?=^diff --git |\Z)", text, re.M | re.S
        ):
            starts[m.group(1)] = m.group(0)
        self.assertEqual(set(TARGETS), set(starts))
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            for name, body in starts.items():
                # Rebuild each file as its hunks expect it: pad to the first
                # hunk's start line, then the hunk's pre-image lines.
                out = []
                for hunk in re.split(r"(?m)^(?=@@ )", body)[1:]:
                    head, *rest = hunk.splitlines()
                    start = int(re.match(r"@@ -(\d+)", head).group(1))
                    while len(out) < start - 1:
                        out.append("// filler")
                    for line in rest:
                        if line.startswith((" ", "-")):
                            out.append(line[1:])
                        elif line == "":
                            out.append("")
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(out) + "\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=tree, check=True)
            result = self._git_apply_check(tree)
            self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(
        os.environ.get("PLAYERBOTS_SRC"),
        "set PLAYERBOTS_SRC to a checkout of the pinned fork for the real check",
    )
    def test_patch_applies_cleanly_to_the_pinned_fork(self):
        result = self._git_apply_check(os.environ["PLAYERBOTS_SRC"])
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
