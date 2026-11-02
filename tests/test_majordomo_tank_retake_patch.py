"""Patch 4 of 4 for Majordomo Executus: the tank re-takes the adds it held.

The patch lives under patches/mod-playerbots/ and is applied to the pinned
fork when the realm image is built, after patches 0017 (the reflect hold),
0018 (the Damage Shield step-off) and 0019 (the kill order), which edit the
same function. This repo's CI carries no fork source, so these tests read the
patch as text and prove the series applies two ways:

- always: the pre-image of patch 0017 is rebuilt from the patch itself, then
  0017, 0018, 0019 and 0020 are applied in order with `git apply`, which fails
  on a malformed hunk or on context that does not follow from 0019;
- when a checkout of the pinned fork is given in PLAYERBOTS_SRC: the whole
  series from 0004 on, in order, applied to a copy of that tree.

The mechanism is an exclusion in tank target selection, because the fork
exposes no priority hook: while a Flamewaker add attacks a player who is not a
tank, Majordomo and the adds a tank already holds are excluded, so the tank
takes the loose add. Teleport Target (20534) leaves no aura on its victim, so
the loose add is the observable key. The condition that defines "a loose
add" is pinned below as one statement. Nothing here is compiled: no compile
of the fork is possible where these tests run.
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
THIRD = SERIES_DIR / "0019-majordomo-healers-are-the-first-target-elites-after.patch"
PATCH = (
    SERIES_DIR
    / "0020-the-tank-retakes-the-majordomo-adds-it-held-after-teleport-target.patch"
)
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
    THIRD.name,
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


class MajordomoTankRetakePatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.added = "\n".join(added_lines(cls.text))
        cls.folded = folded(cls.added)

    def test_patch_exists_and_is_numbered_after_0019(self):
        self.assertTrue(PATCH.is_file())
        self.assertTrue(PATCH.name.startswith("0020-"))

    def test_patch_names_teleport_target(self):
        self.assertIn("Teleport Target (20534)", self.text)

    def _loose_condition(self):
        """The one `if (...)` that decides an add is loose."""
        found = re.findall(
            r"if \((unit && \(unit->GetEntry\(\) == NPC_FLAMEWAKER_HEALER .*?)\) \{ "
            r"looseAdd = true;",
            self.folded,
        )
        self.assertEqual(1, len(found), "expected exactly one loose-add test")
        return found[0]

    def test_loose_add_condition(self):
        self.assertEqual(
            "unit && (unit->GetEntry() == NPC_FLAMEWAKER_HEALER || "
            "unit->GetEntry() == NPC_FLAMEWAKER_ELITE) && victimPlayer && "
            "!PlayerbotAI::IsTank(victimPlayer)",
            self._loose_condition(),
        )

    def test_guard_is_tank_selection_and_aoe_return_is_narrowed(self):
        self.assertIn(
            "if (type == TargetValueExclusionType::Aoe && "
            "PlayerbotAI::IsTank(botAI->GetBot()))",
            self.folded,
        )
        self.assertIn(
            "if (type == TargetValueExclusionType::TankTarget) {", self.folded
        )
        self.assertIn(
            "type == TargetValueExclusionType::TankTarget || (type == "
            "TargetValueExclusionType::Aoe",
            folded("\n".join(removed_lines(self.text))),
        )

    def test_exclusions_apply_only_while_an_add_is_loose(self):
        self.assertIn("if (looseAdd) {", self.folded)
        self.assertEqual(1, len(re.findall(r"exclusions\.insert\(guid\);", self.added)))
        self.assertLess(
            self.folded.index("if (looseAdd) {"),
            self.folded.index("exclusions.insert(guid);"),
        )

    def test_excluded_are_majordomo_and_adds_held_by_a_tank(self):
        self.assertIn(
            "if (unit->GetEntry() == NPC_MAJORDOMO_EXECUTUS || "
            "((unit->GetEntry() == NPC_FLAMEWAKER_HEALER || "
            "unit->GetEntry() == NPC_FLAMEWAKER_ELITE) && victimPlayer && "
            "PlayerbotAI::IsTank(victimPlayer))) exclusions.insert(guid);",
            self.folded,
        )

    def test_tank_block_returns_so_dps_branches_are_not_reached(self):
        self.assertRegex(self.folded, r"exclusions\.insert\(guid\); \} \} return; \}")

    def test_patch_reuses_the_entries_from_patch_0017(self):
        previous = "\n".join(added_lines(FIRST.read_text(encoding="utf-8")))
        self.assertIn("NPC_FLAMEWAKER_HEALER = 11663", previous)
        self.assertIn("NPC_FLAMEWAKER_ELITE = 11664", previous)
        self.assertNotIn("NPC_FLAMEWAKER_HEALER =", self.added)
        self.assertNotIn("NPC_FLAMEWAKER_ELITE =", self.added)

    def test_patch_leaves_the_earlier_branches_alone(self):
        removed = folded("\n".join(removed_lines(self.text)))
        self.assertEqual(
            "if (type == TargetValueExclusionType::TankTarget || (type == "
            "TargetValueExclusionType::Aoe && PlayerbotAI::IsTank(botAI->GetBot())))",
            removed.replace(" return;", ""),
        )
        self.assertNotIn("SPELL_MAGIC_REFLECTION", self.added)
        self.assertNotIn("SPELL_DAMAGE_REFLECTION", self.added)
        self.assertNotIn("casters holding", self.added)
        self.assertNotIn("healerInReach", self.added)
        self.assertNotIn("MCMultipliers", self.text)

    def test_patch_touches_only_the_molten_core_strategy_file(self):
        files = re.findall(r"^diff --git a/(\S+) b/", self.text, re.M)
        self.assertEqual([TARGET], files)

    def test_patch_is_ascii(self):
        self.text.encode("ascii")


class MajordomoTankRetakePatchAppliesTest(unittest.TestCase):
    def _fill_gaps(self, tree):
        """Patch 0017 shows only parts of the function; the rest of the
        rebuilt pre-image is filler. Patch 0020 edits the top of the function
        and its hunk holds the lines it needs, so the filler it covers is
        replaced with them, by line number, before 0020 is applied."""
        pre, start = [], None
        for line in PATCH.read_text(encoding="utf-8").splitlines():
            if line.startswith("@@"):
                pre, start = [], int(re.match(r"@@ -(\d+)", line).group(1))
            elif start is not None and line.startswith((" ", "-")):
                pre.append(line[1:])
            elif start is not None and line == "":
                pre.append("")
        path = tree / TARGET
        lines = path.read_text(encoding="utf-8").split("\n")
        # Patch 0017's line numbers are one off the fork's, which git apply
        # tolerates, so line the hunk up on a line both of them show.
        anchor = "    // through their own target selection."
        start = lines.index(anchor) - pre.index(anchor) + 1
        for i, text in enumerate(pre):
            if start - 1 + i < len(lines) and lines[start - 1 + i] == "// filler":
                lines[start - 1 + i] = text
        path.write_text("\n".join(lines), encoding="utf-8")

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
            for patch in (FIRST, SECOND, THIRD, PATCH):
                if patch is PATCH:
                    self._fill_gaps(tree)
                result = git_apply(tree, patch)
                self.assertEqual(0, result.returncode, patch.name + result.stderr)
            strategy = (tree / TARGET).read_text(encoding="utf-8")
            self.assertIn("looseAdd", strategy)

    def test_patch_does_not_apply_without_0019(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_first(tree)
            self.assertEqual(0, git_apply(tree, FIRST).returncode)
            self.assertEqual(0, git_apply(tree, SECOND).returncode)
            self._fill_gaps(tree)
            self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_patch_does_not_apply_without_0018(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_first(tree)
            self.assertEqual(0, git_apply(tree, FIRST).returncode)
            self._fill_gaps(tree)
            self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_patch_does_not_apply_without_the_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp)
            self._preimage_of_first(tree)
            self._fill_gaps(tree)
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
            self.assertIn("looseAdd", strategy)


if __name__ == "__main__":
    unittest.main()
