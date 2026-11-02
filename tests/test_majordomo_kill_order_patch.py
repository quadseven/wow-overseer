"""Patch 3 of 4 for Majordomo Executus: Flamewaker Healers die first.

The patch lives under patches/mod-playerbots/ and is applied to the pinned
fork when the realm image is built, after patches 0017 (the reflect hold) and
0018 (the Damage Shield step-off), which edit the same function. This repo's
CI carries no fork source, so these tests read the patch as text and prove the
series applies two ways:

- always: the pre-image of patch 0017 is rebuilt from the patch itself, then
  0017, 0018 and 0019 are applied in order with `git apply`, which fails on a
  malformed hunk or on context that does not follow from 0018;
- when a checkout of the pinned fork is given in PLAYERBOTS_SRC: the whole
  series from 0004 on, in order, applied to a copy of that tree.

The mechanism is an exclusion, because the fork exposes no priority hook: the
Flamewaker Elites (11664) are excluded from damage target selection while a
Flamewaker Healer (11663) is alive and within reach of the bot. The bound
against an empty target list is the condition that defines "within reach",
pinned below as one statement.
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
FIRST = SERIES_DIR / "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch"
SECOND = SERIES_DIR / "0018-melee-step-off-a-majordomo-add-with-damage-shield.patch"
PATCH = SERIES_DIR / "0019-majordomo-healers-are-the-first-target-elites-after.patch"
TARGET = "src/Ai/Raid/MC/MCStrategy.cpp"
PREIMAGE_FILES = (
    "src/Ai/Raid/MC/MCHelpers.h",
    "src/Ai/Raid/MC/MCStrategy.cpp",
)
# The series the pinned fork gets, in order, up to and including this patch.
SERIES = (
    "0004-loot-needs-a-free-bag-slot.patch",
    "0005-wander-npc-can-be-aimed.patch",
    "0016-a-mage-only-conjures-food-at-a-usable-rank.patch",
    FIRST.name,
    SECOND.name,
    PATCH.name,
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


def folded(text):
    return " ".join(text.split())


class MajordomoKillOrderPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.added = "\n".join(added_lines(cls.text))
        cls.folded = folded(cls.added)

    def test_patch_exists_and_is_numbered_after_0018(self):
        self.assertTrue(PATCH.is_file())
        self.assertTrue(PATCH.name.startswith("0019-"))

    def _reach_condition(self):
        """The one `if (...)` that decides a healer is within reach."""
        found = re.findall(
            r"if \((unit && unit->GetEntry\(\) == NPC_FLAMEWAKER_HEALER .*?)\) \{ "
            r"healerInReach = true;",
            self.folded,
        )
        self.assertEqual(1, len(found), "expected exactly one healer-in-reach test")
        return found[0]

    def test_healer_in_reach_condition(self):
        self.assertEqual(
            "unit && unit->GetEntry() == NPC_FLAMEWAKER_HEALER && "
            "exclusions.find(guid) == exclusions.end() && "
            "bot->GetDistance(unit) <= sPlayerbotAIConfig.SpellDistance && "
            "bot->IsWithinLOSInMap(unit)",
            self._reach_condition(),
        )

    def test_guard_is_dps_selection(self):
        self.assertIn(
            "bool const healersFirst = type == TargetValueExclusionType::DpsTarget;",
            self.folded,
        )
        self.assertIn("if (healersFirst) {", self.folded)

    def test_elites_are_excluded_only_when_a_healer_is_in_reach(self):
        self.assertIn(
            "if (healerInReach) { for (ObjectGuid const guid : "
            'AI_VALUE(GuidVector, "attackers")) { Unit* unit = botAI->GetUnit(guid); '
            "if (unit && unit->GetEntry() == NPC_FLAMEWAKER_ELITE) "
            "exclusions.insert(guid); } }",
            self.folded,
        )

    def test_healers_are_never_excluded_by_this_patch(self):
        inserts = re.findall(r"exclusions\.insert\(guid\);", self.added)
        self.assertEqual(1, len(inserts))
        self.assertNotIn("NPC_FLAMEWAKER_HEALER) exclusions", self.folded)

    def test_patch_reuses_the_add_entries_from_patch_0017(self):
        previous = "\n".join(added_lines(FIRST.read_text(encoding="utf-8")))
        self.assertIn("NPC_FLAMEWAKER_HEALER = 11663", previous)
        self.assertIn("NPC_FLAMEWAKER_ELITE = 11664", previous)
        self.assertNotIn("NPC_FLAMEWAKER_HEALER =", self.added)
        self.assertNotIn("NPC_FLAMEWAKER_ELITE =", self.added)

    def test_patch_leaves_the_earlier_branches_alone(self):
        self.assertEqual([], removed_lines(self.text))
        self.assertNotIn("SPELL_MAGIC_REFLECTION", self.added)
        self.assertNotIn("SPELL_DAMAGE_REFLECTION", self.added)
        self.assertNotIn("casters holding", self.added)
        self.assertNotIn("20534", self.added)
        self.assertNotIn("MCMultipliers", self.text)

    def test_patch_touches_only_the_molten_core_strategy_file(self):
        files = re.findall(r"^diff --git a/(\S+) b/", self.text, re.M)
        self.assertEqual([TARGET], files)

    def test_patch_is_ascii(self):
        self.text.encode("ascii")


class MajordomoKillOrderPatchAppliesTest(unittest.TestCase):
    def _preimage_of_first(self, tree):
        text = FIRST.read_text(encoding="utf-8")
        files = {}
        for m in re.finditer(
            r"^diff --git a/(\S+) b/.*?(?=^diff --git |\Z)", text, re.M | re.S
        ):
            files[m.group(1)] = m.group(0)
        self.assertEqual(set(PREIMAGE_FILES), set(files))
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
            self._preimage_of_first(tree)
            for patch in (FIRST, SECOND, PATCH):
                result = git_apply(tree, patch)
                self.assertEqual(0, result.returncode, patch.name + result.stderr)
            strategy = (tree / TARGET).read_text(encoding="utf-8")
            self.assertIn("healerInReach", strategy)

    def test_patch_does_not_apply_without_0018(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_first(tree)
            self.assertEqual(0, git_apply(tree, FIRST).returncode)
            self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_patch_does_not_apply_without_the_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_first(tree)
            self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_series_files_exist_in_order(self):
        for name in SERIES:
            self.assertTrue((SERIES_DIR / name).is_file(), name)
        names = sorted(p.name for p in SERIES_DIR.glob("*.patch"))
        self.assertEqual(list(SERIES), [n for n in names if n in SERIES])

    @unittest.skipUnless(
        os.environ.get("PLAYERBOTS_SRC"),
        "set PLAYERBOTS_SRC to a checkout of the pinned fork for the real check",
    )
    def test_series_applies_in_order_to_the_pinned_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "fork"
            shutil.copytree(os.environ["PLAYERBOTS_SRC"], tree)
            for name in SERIES:
                result = git_apply(tree, SERIES_DIR / name)
                self.assertEqual(0, result.returncode, name + ": " + result.stderr)
            strategy = (tree / TARGET).read_text(encoding="utf-8")
            self.assertIn("healerInReach", strategy)


if __name__ == "__main__":
    unittest.main()
