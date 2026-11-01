"""Standing labels use spell names and keep unknown spell IDs readable."""

import shutil
import unittest

from test_app_shell import node_module


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class StandingSpellNames(unittest.TestCase):
    def test_known_and_unknown_spell_names_keep_spell_links(self):
        out = node_module(
            "models/spellnames.js",
            "console.log(JSON.stringify([M.classSpellName(750), "
            "M.classSpellName(11566), M.classSpellName(999999), "
            "M.wowheadSpellUrl(750), M.wowheadSpellUrl(11566)]));",
        )
        self.assertEqual(
            out,
            [
                "Plate Mail",
                "Heroic Strike (Rank 7)",
                "Spell 999999",
                "https://www.wowhead.com/wotlk/spell=750",
                "https://www.wowhead.com/wotlk/spell=11566",
            ],
        )
