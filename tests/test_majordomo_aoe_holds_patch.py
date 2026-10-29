"""Follow-up to patches 0017 and 0018: the holds also cover area targets.

The patch lives under patches/mod-playerbots/ and is applied to the pinned
fork when the realm image is built, after patches 0017 to 0020, which edit the
same function. This repo's CI carries no fork source, so these tests read the
patch as text and prove the series applies two ways:

- always: the pre-image of patch 0017 is rebuilt from the patch itself, then
  0017 to 0021 are applied in order with `git apply`, which fails on a
  malformed hunk or on context that does not follow from 0020;
- when a checkout of the pinned fork is given in PLAYERBOTS_SRC: the whole
  series from 0004 on, in order, applied to a copy of that tree.

At the pinned fork the base function returns early only for `Aoe` of a tank
(patch 0020 narrows it to that), so every `Aoe` selection that reaches the
chain is a non-tank. The caster hold and the melee step-off accept `Aoe` as
well as `DpsTarget`; each guard is pinned below as one statement. Nothing here
is compiled: no compile of the fork is possible where these tests run.
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
FOURTH = (
    SERIES_DIR
    / "0020-the-tank-retakes-the-majordomo-adds-it-held-after-teleport-target.patch"
)
PATCH = (
    SERIES_DIR / "0021-majordomo-add-holds-also-apply-to-area-target-selection.patch"
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
    FOURTH.name,
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


class MajordomoAoeHoldsPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.added = "\n".join(added_lines(cls.text))
        cls.removed = "\n".join(removed_lines(cls.text))
        cls.folded = folded(cls.added)

    def test_patch_exists_and_is_numbered_after_0020(self):
        self.assertTrue(PATCH.is_file())
        self.assertTrue(PATCH.name.startswith("0021-"))

    def test_caster_hold_guard_covers_damage_and_area_targets(self):
        self.assertIn(
            "bool const casterHolds = (type == TargetValueExclusionType::DpsTarget "
            "|| type == TargetValueExclusionType::Aoe) && "
            "PlayerbotAI::IsCaster(bot);",
            self.folded,
        )

    def test_melee_step_off_guard_covers_damage_and_area_targets(self):
        self.assertIn(
            "bool const meleeStepsOff = (type == TargetValueExclusionType::DpsTarget "
            "|| type == TargetValueExclusionType::Aoe) && "
            "PlayerbotAI::IsMelee(bot);",
            self.folded,
        )

    def test_the_guards_replace_the_damage_only_guards(self):
        self.assertEqual(
            "bool const casterHolds = type == TargetValueExclusionType::DpsTarget "
            "&& PlayerbotAI::IsCaster(bot); "
            "bool const meleeStepsOff = type == TargetValueExclusionType::DpsTarget "
            "&& PlayerbotAI::IsMelee(bot);",
            folded(self.removed),
        )

    def test_exactly_two_guards_change(self):
        self.assertEqual(2, len(re.findall(r"bool const \w+ =", self.added)))
        self.assertEqual(2, self.folded.count("TargetValueExclusionType::Aoe)"))
        self.assertEqual(2, self.folded.count("TargetValueExclusionType::DpsTarget"))

    def test_the_conditions_of_0017_and_0018_are_not_touched(self):
        self.assertNotIn("HasAura", self.added)
        self.assertNotIn("exclusions.insert", self.added)
        self.assertNotIn("SPELL_MAGIC_REFLECTION", self.added)
        self.assertNotIn("SPELL_DAMAGE_REFLECTION", self.added)
        self.assertNotIn("NPC_FLAMEWAKER", self.added)

    def test_kill_order_and_tank_block_are_untouched(self):
        self.assertNotIn("healersFirst", self.added)
        self.assertNotIn("healerInReach", self.added)
        self.assertNotIn("looseAdd", self.added)
        self.assertNotIn("TankTarget", self.added)
        self.assertNotIn("IsTank", self.added)
        self.assertNotIn("TankTarget", self.removed)

    def test_the_tank_aoe_return_stays_in_the_series(self):
        # The reason Aoe is safe to add: tanks never reach the guards.
        fourth = folded("\n".join(added_lines(FOURTH.read_text(encoding="utf-8"))))
        self.assertIn(
            "if (type == TargetValueExclusionType::Aoe && "
            "PlayerbotAI::IsTank(botAI->GetBot()))",
            fourth,
        )

    def test_patch_touches_only_the_molten_core_strategy_file(self):
        files = re.findall(r"^diff --git a/(\S+) b/", self.text, re.M)
        self.assertEqual([TARGET], files)

    def test_patch_is_ascii(self):
        self.text.encode("ascii")


class MajordomoAoeHoldsPatchAppliesTest(unittest.TestCase):
    def _fill_gaps(self, tree, patch_file=FOURTH):
        """Patch 0017 shows only parts of the function; the rest of the
        rebuilt pre-image is filler. Patch 0020 edits the top of the function
        and its hunk holds the lines it needs, so the filler it covers is
        replaced with them, by line number, before 0020 is applied. Patch 0021 needs no filling: its
        context is all lines that 0017 and 0018 show."""
        pre, start = [], None
        for line in patch_file.read_text(encoding="utf-8").splitlines():
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

    def _tree_with(self, *patches):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tree = pathlib.Path(tmp.name)
        self._preimage_of_first(tree)
        for patch in patches:
            if patch is FOURTH:
                self._fill_gaps(tree)
            result = git_apply(tree, patch)
            self.assertEqual(0, result.returncode, patch.name + result.stderr)
        if FOURTH not in patches:
            self._fill_gaps(tree)
        return tree

    def test_series_applies_in_order_to_the_preimage_of_0017(self):
        tree = self._tree_with(FIRST, SECOND, THIRD, FOURTH)
        result = git_apply(tree, PATCH)
        self.assertEqual(0, result.returncode, result.stderr)
        strategy = (tree / TARGET).read_text(encoding="utf-8")
        self.assertIn("looseAdd", strategy)
        self.assertEqual(
            2,
            folded(strategy).count(
                "(type == TargetValueExclusionType::DpsTarget || "
                "type == TargetValueExclusionType::Aoe) &&"
            ),
        )

    def test_patch_does_not_apply_without_0020(self):
        tree = self._tree_with(FIRST, SECOND, THIRD)
        self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_patch_does_not_apply_without_0019(self):
        tree = self._tree_with(FIRST, SECOND)
        self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_patch_does_not_apply_without_0018(self):
        tree = self._tree_with(FIRST)
        self.assertNotEqual(0, git_apply(tree, PATCH, check=True).returncode)

    def test_patch_does_not_apply_without_the_series(self):
        tree = self._tree_with()
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
            self.assertIn("type == TargetValueExclusionType::Aoe) &&", strategy)


if __name__ == "__main__":
    unittest.main()
