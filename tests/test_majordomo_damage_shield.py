import pathlib
import unittest


PATCH = (
    pathlib.Path(__file__).parents[1]
    / "patches/mod-playerbots"
    / "0018-majordomo-melee-steps-off-damage-shield.patch"
)


class MajordomoDamageShieldPatchTest(unittest.TestCase):
    def test_patch_reads_damage_shield_by_spell_id(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("SPELL_DAMAGE_SHIELD = 21075", source)

    def test_patch_steps_melee_off_a_damage_shield_add(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("MajordomoDamageShieldMultiplier", source)
        self.assertIn("PlayerbotAI::IsMelee(bot)", source)
        self.assertIn("dynamic_cast<MeleeAction*>(action)", source)
        self.assertIn("target->HasAura(SPELL_DAMAGE_SHIELD)", source)
        self.assertIn("return 0.0f", source)

    def test_patch_registers_the_multiplier(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("new MajordomoDamageShieldMultiplier(botAI)", source)


if __name__ == "__main__":
    unittest.main()
