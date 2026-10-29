"""Patch 2 of 4 for Majordomo Executus: melee step off a Damage Shield add.

The patch lives under patches/mod-playerbots/ and is applied to the pinned
fork when the realm image is built, after patch 0017 (the reflect hold),
which edits the same function. This repo's CI carries no fork source, so
these tests read the patch as text and prove the series applies two ways:

- always: the pre-image of patch 0017 is rebuilt from the patch itself, then
  0017 and 0018 are applied in order with `git apply`, which fails on a
  malformed hunk or on context that does not follow from 0017;
- when a checkout of the pinned fork is given in PLAYERBOTS_SRC: the same two
  patches applied in order to a copy of that tree.

The aura id 21075 is SPELL_DAMAGE_REFLECTION in the pinned core's
boss_majordomo_executus.cpp (Majordomo casts it on himself every 30s, as the
alternative to Magic Reflection 20619).
"""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERIES_DIR = ROOT / "patches/mod-playerbots"
PREVIOUS = (
    SERIES_DIR / "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch"
)
PATCH = SERIES_DIR / "0018-melee-step-off-a-majordomo-add-with-damage-shield.patch"
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


def git_apply(tree, patch, check=False):
    cmd = ["git", "apply"] + (["--check"] if check else []) + [str(patch)]
    return subprocess.run(cmd, cwd=tree, capture_output=True, text=True)


class MajordomoDamageShieldPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.added = "\n".join(added_lines(cls.text))

    def test_patch_keys_on_damage_shield_by_spell_id(self):
        self.assertIn("SPELL_DAMAGE_REFLECTION = 21075", self.added)
        self.assertIn("unit->HasAura(SPELL_DAMAGE_REFLECTION)", self.added)

    def _step_off_condition(self):
        """The one `else if (...)` the patch adds, whitespace folded."""
        folded = " ".join(self.added.split())
        found = re.findall(r"else if \((.*?)\) exclusions\.insert\(guid\);", folded)
        self.assertEqual(1, len(found), "expected exactly one added else-if")
        return found[0]

    def test_step_off_condition_needs_melee_aura_and_either_add(self):
        self.assertEqual(
            "meleeStepsOff && unit->HasAura(SPELL_DAMAGE_REFLECTION) && "
            "(unit->GetEntry() == NPC_FLAMEWAKER_HEALER || "
            "unit->GetEntry() == NPC_FLAMEWAKER_ELITE)",
            self._step_off_condition(),
        )

    def test_melee_guard_is_dps_selection_for_a_melee_bot(self):
        folded = " ".join(self.added.split())
        self.assertIn(
            "bool const meleeStepsOff = type == TargetValueExclusionType::Dps "
            "&& PlayerbotAI::IsMelee(bot);",
            folded,
        )

    def test_patch_reuses_the_add_entries_from_patch_0017(self):
        previous = "\n".join(added_lines(PREVIOUS.read_text(encoding="utf-8")))
        self.assertIn("NPC_FLAMEWAKER_HEALER = 11663", previous)
        self.assertIn("NPC_FLAMEWAKER_ELITE = 11664", previous)
        self.assertNotIn("NPC_FLAMEWAKER_HEALER =", self.added)
        self.assertNotIn("NPC_FLAMEWAKER_ELITE =", self.added)

    def test_patch_leaves_the_caster_hold_and_existing_branches_alone(self):
        self.assertEqual([], removed_lines(self.text))
        self.assertNotIn("SPELL_MAGIC_REFLECTION", self.added)
        self.assertNotIn("casters holding", self.added)

    def test_patch_stays_out_of_the_other_patches(self):
        self.assertNotIn("20619", self.added)
        self.assertNotIn("20534", self.added)
        self.assertNotIn("MCMultipliers", self.text)

    def test_patch_touches_only_the_molten_core_strategy_files(self):
        files = tuple(re.findall(r"^diff --git a/(\S+) b/", self.text, re.M))
        self.assertEqual(TARGETS, files)

    def test_patch_is_ascii(self):
        self.text.encode("ascii")


class MajordomoDamageShieldPatchAppliesTest(unittest.TestCase):
    def _preimage_of_previous(self, tree):
        text = PREVIOUS.read_text(encoding="utf-8")
        files = {}
        for m in re.finditer(
            r"^diff --git a/(\S+) b/.*?(?=^diff --git |\Z)", text, re.M | re.S
        ):
            files[m.group(1)] = m.group(0)
        self.assertEqual(set(TARGETS), set(files))
        for name, body in files.items():
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

    def test_series_applies_in_order_to_the_preimage_of_0017(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_previous(tree)
            first = git_apply(tree, PREVIOUS)
            self.assertEqual(0, first.returncode, first.stderr)
            second = git_apply(tree, PATCH)
            self.assertEqual(0, second.returncode, second.stderr)
            strategy = (tree / TARGETS[1]).read_text(encoding="utf-8")
            self.assertIn("unit->HasAura(SPELL_DAMAGE_REFLECTION)", strategy)

    def test_patch_does_not_apply_without_0017(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_previous(tree)
            self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    @unittest.skipUnless(
        os.environ.get("PLAYERBOTS_SRC"),
        "set PLAYERBOTS_SRC to a checkout of the pinned fork for the real check",
    )
    def test_series_applies_in_order_to_the_pinned_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "fork"
            shutil.copytree(os.environ["PLAYERBOTS_SRC"], tree)
            for patch in sorted(SERIES_DIR.glob("*.patch")):
                if patch.name < PREVIOUS.name:
                    continue
                result = git_apply(tree, patch)
                self.assertEqual(
                    0, result.returncode, patch.name + ": " + result.stderr
                )


if __name__ == "__main__":
    unittest.main()
