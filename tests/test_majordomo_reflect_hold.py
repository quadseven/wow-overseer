import pathlib
import unittest


PATCH = (
    pathlib.Path(__file__).parents[1]
    / "patches/mod-playerbots"
    / "0017-majordomo-casters-hold-on-reflection.patch"
)


class MajordomoReflectHoldPatchTest(unittest.TestCase):
    def test_patch_reads_magic_reflection_by_spell_id(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("SPELL_MAGIC_REFLECTION = 20619", source)

    def test_patch_holds_caster_spells_on_a_reflection_add(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("MajordomoReflectionMultiplier", source)
        self.assertIn("dynamic_cast<CastSpellAction*>(action)", source)
        self.assertIn("target->HasAura(SPELL_MAGIC_REFLECTION)", source)
        self.assertIn("return 0.0f", source)

    def test_patch_logs_the_hold_line(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("[MC] majordomo: ", source)
        self.assertIn("casters holding, magic reflection on ", source)
        self.assertIn("botAI->TellError", source)

    def test_patch_registers_the_multiplier(self):
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("new MajordomoReflectionMultiplier(botAI)", source)


if __name__ == "__main__":
    unittest.main()
