"""Patch 0022 for Sulfuron Harbinger and Baron Geddon (#2108).

The patch lives under patches/mod-playerbots/. This repo's CI carries no fork
source, so these tests read the patch as text and pin the three rules:

- Sulfuron is excluded from damage target selection while a Flamewaker Priest
  is in reach, and never otherwise;
- the Dark Mending interrupts go to exactly two assigned bots, not all, not none;
- exactly one healer follows a Living Bomb carrier, and the follow movement is
  allowed while Inferno blocks other movement.

When PLAYERBOTS_SRC names a checkout of the pinned fork, the whole series from
0004 on is applied in order to a copy of that tree.
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
PATCH = SERIES_DIR / "0022-sulfuron-priests-first-interrupts-and-a-bomb-follower.patch"
SERIES = (
    "0004-loot-needs-a-free-bag-slot.patch",
    "0005-wander-npc-can-be-aimed.patch",
    "0016-a-mage-only-conjures-food-at-a-usable-rank.patch",
    "0017-casters-hold-on-a-majordomo-add-with-magic-reflection.patch",
    "0018-melee-step-off-a-majordomo-add-with-damage-shield.patch",
    "0019-majordomo-healers-are-the-first-target-elites-after.patch",
    "0020-the-tank-retakes-the-majordomo-adds-it-held-after-teleport-target.patch",
    "0021-majordomo-add-holds-also-apply-to-area-target-selection.patch",
    PATCH.name,
)


def folded(text):
    return " ".join(text.split())


def added_for(text, filename):
    """The added lines of one file's diff, folded to single spaces."""
    for m in re.finditer(
        r"^diff --git a/(\S+) b/.*?(?=^diff --git |\Z)", text, re.M | re.S
    ):
        if m.group(1).endswith("/" + filename):
            lines = [
                line[1:]
                for line in m.group(0).splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            return folded("\n".join(lines))
    raise AssertionError("patch does not touch " + filename)


class SulfuronGeddonPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.strategy = added_for(cls.text, "MCStrategy.cpp")
        cls.helpers = added_for(cls.text, "MCHelpers.h")
        cls.mults = added_for(cls.text, "MCMultipliers.cpp")
        cls.actions = added_for(cls.text, "MCActions.cpp")
        cls.triggers = added_for(cls.text, "MCTriggers.cpp")

    def test_patch_is_numbered_after_0021_and_ascii(self):
        self.assertTrue(PATCH.name.startswith("0022-"))
        self.text.encode("ascii")

    def test_patch_removes_no_existing_line_but_two_context_edits(self):
        removed = [
            line
            for line in self.text.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        self.assertEqual([], removed)

    def test_priest_in_reach_condition(self):
        found = re.findall(
            r"if \((unit && unit->GetEntry\(\) == NPC_FLAMEWAKER_PRIEST .*?)\) \{ "
            r"priestInReach = true;",
            self.strategy,
        )
        self.assertEqual(1, len(found))
        self.assertEqual(
            "unit && unit->GetEntry() == NPC_FLAMEWAKER_PRIEST && "
            "exclusions.find(guid) == exclusions.end() && "
            "bot->GetDistance(unit) <= sPlayerbotAIConfig.SpellDistance && "
            "bot->IsWithinLOSInMap(unit)",
            found[0],
        )

    def test_sulfuron_is_excluded_only_when_a_priest_is_in_reach(self):
        self.assertIn(
            "if (priestInReach) { for (ObjectGuid const guid : "
            'AI_VALUE(GuidVector, "attackers")) { Unit* unit = botAI->GetUnit(guid); '
            "if (unit && unit->GetEntry() == NPC_SULFURON_HARBINGER) "
            "exclusions.insert(guid); } }",
            self.strategy,
        )
        self.assertEqual(1, len(re.findall(r"exclusions\.insert\(guid\);", self.strategy)))
        self.assertNotIn("NPC_FLAMEWAKER_PRIEST) exclusions", self.strategy)

    def test_priest_rule_is_dps_selection_only(self):
        self.assertIn(
            "if (type == TargetValueExclusionType::DpsTarget) { for (ObjectGuid const guid",
            self.strategy,
        )

    def test_entry_and_spell_ids(self):
        self.assertIn("NPC_SULFURON_HARBINGER = 12098", self.helpers)
        self.assertIn("NPC_FLAMEWAKER_PRIEST = 11662", self.helpers)
        self.assertIn("SPELL_DARK_MENDING = 19775", self.helpers)

    def test_exactly_two_interrupters_are_assigned(self):
        self.assertIn("DARK_MENDING_INTERRUPTER_COUNT = 2", self.helpers)
        self.assertIn("return ahead < DARK_MENDING_INTERRUPTER_COUNT;", self.helpers)
        # The rule counts only living, same-map members that can interrupt.
        self.assertIn(
            "if (!member || member == bot || !member->IsAlive() || "
            "member->GetMapId() != bot->GetMapId() || !CanInterruptCasts(member)) continue;",
            self.helpers,
        )

    def test_unassigned_bots_are_blocked_and_assigned_are_not(self):
        self.assertIn(
            'if (AI_VALUE2(Unit*, "find target", "sulfuron harbinger") && '
            "IsInterruptAction(action) && !IsDarkMendingInterrupter(bot)) return 0.0f;",
            self.mults,
        )
        self.assertIn("return 1.0f;", self.mults)

    def test_strategy_registers_the_multiplier_and_the_follow_trigger(self):
        self.assertIn(
            "multipliers.push_back(new SulfuronInterruptMultiplier(botAI));",
            self.strategy,
        )
        self.assertIn(
            'new TriggerNode("mc living bomb follower", '
            '{ NextAction("mc follow living bomb", ACTION_RAID) })',
            self.strategy,
        )

    def test_one_healer_follows_one_carrier(self):
        self.assertIn(
            "if (!group || !PlayerbotAI::IsHeal(bot) || bot->HasAura(SPELL_LIVING_BOMB)) "
            "return nullptr;",
            self.helpers,
        )
        self.assertIn(
            "else if (PlayerbotAI::IsHeal(member) && (!follower || "
            "member->GetGUID().GetCounter() < follower->GetGUID().GetCounter())) "
            "follower = member;",
            self.helpers,
        )
        self.assertIn("return carrier && follower == bot ? carrier : nullptr;", self.helpers)

    def test_follow_trigger_and_action_use_the_same_target_and_distance(self):
        self.assertIn(
            "Player* carrier = LivingBombFollowTarget(bot); "
            "return carrier && bot->GetDistance2d(carrier) > LIVING_BOMB_FOLLOW_DISTANCE;",
            self.triggers,
        )
        self.assertIn(
            "Player* carrier = LivingBombFollowTarget(bot); "
            "if (!carrier || bot->GetDistance2d(carrier) <= LIVING_BOMB_FOLLOW_DISTANCE) "
            "return false;",
            self.actions,
        )

    def test_follow_distance_is_outside_the_blast_and_inside_healing_range(self):
        value = float(
            re.search(r"LIVING_BOMB_FOLLOW_DISTANCE = ([\d.]+)f", self.helpers).group(1)
        )
        self.assertGreater(value, 10.0)
        self.assertLess(value, 40.0)

    def test_follow_movement_is_allowed_during_inferno(self):
        self.assertIn("!dynamic_cast<McFollowLivingBombAction*>(action) &&", self.mults)

    def test_patch_leaves_other_encounters_alone(self):
        for name in ("golemagg", "core hound", "majordomo", "SPELL_MAGIC_REFLECTION"):
            self.assertNotIn(name, self.mults.lower().replace("sulfuron", ""))
        files = re.findall(r"^diff --git a/(\S+) b/", self.text, re.M)
        self.assertTrue(all(f.startswith("src/Ai/Raid/MC/") for f in files))

    def test_series_files_exist_in_order(self):
        for name in SERIES:
            self.assertTrue((SERIES_DIR / name).is_file(), name)

    @unittest.skipUnless(
        os.environ.get("PLAYERBOTS_SRC"),
        "set PLAYERBOTS_SRC to a checkout of the pinned fork for the real check",
    )
    def test_series_applies_in_order_to_the_pinned_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "fork"
            shutil.copytree(os.environ["PLAYERBOTS_SRC"], tree)
            for name in SERIES:
                result = subprocess.run(
                    ["git", "apply", str(SERIES_DIR / name)],
                    cwd=tree,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, name + ": " + result.stderr)
            self.assertIn(
                "priestInReach",
                (tree / "src/Ai/Raid/MC/MCStrategy.cpp").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
