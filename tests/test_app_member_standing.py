"""Standing labels use spell names and keep unknown spell IDs readable."""

import json
from pathlib import Path
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

    def test_every_exported_trainer_spell_has_a_name(self):
        # A realm snapshot across all ten classes is a coverage sample, not
        # the generator's input: ranks above the snapshot's cap also belong.
        ids = json.loads(
            (
                Path(__file__).parent / "fixtures/class_trainer_spell_ids.json"
            ).read_text()
        )
        missing = node_module(
            "models/spellnames.js",
            "console.log(JSON.stringify("
            + json.dumps(ids)
            + ".filter(id => M.classSpellName(id) === 'Spell ' + id)));",
        )
        self.assertEqual(len(missing), 0, f"Unnamed trainer spells: {missing[:12]}")
