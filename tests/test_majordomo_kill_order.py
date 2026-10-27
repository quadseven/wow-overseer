import pathlib
import unittest


PATCH = (
    pathlib.Path(__file__).parents[1]
    / "patches/mod-playerbots"
    / "0019-majordomo-kill-order-and-re-taunt.patch"
)


class MajordomoKillOrderPatchTest(unittest.TestCase):
    def test_patch_reads_the_add_entries(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("NPC_FLAMEWAKER_HEALER = 11663", source)
        self.assertIn("NPC_FLAMEWAKER_ELITE = 11664", source)

    def test_patch_reads_teleport_target_by_spell_id(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("SPELL_TELEPORT_TARGET = 20534", source)

    def test_patch_orders_healers_before_elites(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("Kill order: Flamewaker healers", source)
        self.assertIn("NPC_FLAMEWAKER_HEALER", source)
        self.assertIn("NPC_FLAMEWAKER_ELITE", source)
        self.assertIn("exclusions.insert(guid)", source)

    def test_patch_re_taunts_after_teleport_target(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("MajordomoReTauntMultiplier", source)
        self.assertIn("PlayerbotAI::IsTank(bot)", source)
        self.assertIn("bot->HasAura(SPELL_TELEPORT_TARGET)", source)
        self.assertIn(
            "dynamic_cast<AttackAction*>(action) || dynamic_cast<MeleeAction*>(action)",
            source,
        )
        self.assertIn("return 2.0f", source)

    def test_patch_registers_the_re_taunt_multiplier(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("new MajordomoReTauntMultiplier(botAI)", source)


if __name__ == "__main__":
    unittest.main()
