"""Capabilities require the realm's learned level, not just a class (#1484)."""

import copy
import json
from pathlib import Path
import unittest

from test_app_shell import node_module

from tools import mc_spell_facts

import mcencounters as mc


def lucifron(members):
    return next(row for row in mc.compose(members) if row["boss"] == "Lucifron")


class CapabilityLevels(unittest.TestCase):
    def test_underlevel_mage_is_not_a_curse_dispeller(self):
        member = {"class_id": mc.MAGE, "seat": "dps", "level": 17}
        self.assertEqual(lucifron([member])["have"][mc.CURSE_DISPEL], 0)
        member["level"] = 18
        self.assertEqual(lucifron([member])["have"][mc.CURSE_DISPEL], 1)

    def test_missing_member_level_does_not_claim_a_capability(self):
        member = {"class_id": mc.MAGE, "seat": "dps"}
        self.assertEqual(lucifron([member])["have"][mc.CURSE_DISPEL], 0)

    def test_raid_line_names_the_level_shortfall(self):
        report = mc.compose([{"class_id": mc.MAGE, "seat": "dps", "level": 17}])
        line = mc.encounter_line(report)
        self.assertIn("curse dispeller", line)
        self.assertIn("level 18", line)


class MeasuredCapabilities(unittest.TestCase):
    def test_every_class_capability_has_a_positive_floor_and_boundary(self):
        for name, capability in mc.CAPABILITIES.items():
            if name == mc.TANKS:
                continue
            self.assertEqual(set(capability.levels), set(capability.classes))
            for klass, floor in capability.levels.items():
                with self.subTest(capability=name, klass=klass):
                    self.assertGreater(floor, 0)
                    member = {"class_id": klass, "seat": "dps", "level": floor - 1}
                    report = mc.compose([member])
                    row = next(row for row in report if name in row["have"])
                    self.assertEqual(row["have"][name], 0)
                    member["level"] = floor
                    row = next(
                        row for row in mc.compose([member]) if name in row["have"]
                    )
                    self.assertEqual(row["have"][name], 1)

    def test_boss_dispel_facts_match_the_capability_answering_each_spell(self):
        answers = {
            19703: (2, mc.CURSE_DISPEL, "Lucifron"),
            19702: (1, mc.MAGIC_DISPEL, "Lucifron"),
            19716: (2, mc.CURSE_DISPEL, "Gehennas"),
            19713: (2, mc.CURSE_DISPEL, "Shazzrah"),
            19714: (1, mc.OFFENSIVE_DISPEL, "Shazzrah"),
            19659: (1, mc.MAGIC_DISPEL, "Baron Geddon"),
            19776: (1, mc.MAGIC_DISPEL, "Sulfuron Harbinger"),
        }
        for spell, (dispel, capability, boss) in answers.items():
            self.assertEqual(mc.BOSS_SPELLS[spell]["dispel"], dispel)
            encounter = next(row for row in mc.ENCOUNTERS if row.boss == boss)
            self.assertIn(capability, encounter.needs)


class FactProjection(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / "data" / "mc-spells.json"
        self.facts = json.loads(path.read_text())
        self.training = {
            klass: {
                "class": klass,
                "spells": {
                    "above": [
                        {"spell": int(spell), "level": row["level"]}
                        for spell, row in rows.items()
                    ]
                },
                "money": 123,
                "guild": "ExampleGuild",
            }
            for klass, rows in self.facts["learned"].items()
        }
        self.spells = {
            int(spell): {"name": row["name"], "dispel": 0}
            for rows in self.facts["learned"].values()
            for spell, row in rows.items()
        }
        self.spells.update({int(k): v for k, v in self.facts["boss_spells"].items()})

    def test_projection_reproduces_only_public_spell_facts(self):
        result = mc_spell_facts.project(self.training, self.spells)
        self.assertEqual(result["learned"], self.facts["learned"])
        self.assertEqual(result["boss_spells"], self.facts["boss_spells"])
        self.assertNotIn("ExampleGuild", json.dumps(result))
        self.assertNotIn("money", json.dumps(result))

    def test_missing_or_conflicting_required_training_refuses_generation(self):
        missing = copy.deepcopy(self.training)
        missing["Mage"]["spells"]["above"] = []
        with self.assertRaisesRegex(ValueError, "missing required"):
            mc_spell_facts.project(missing, self.spells)
        contradictory = copy.deepcopy(self.training)
        contradictory["Mage"]["spells"]["above"].append({"spell": 475, "level": 99})
        with self.assertRaisesRegex(ValueError, "conflicting"):
            mc_spell_facts.project(contradictory, self.spells)

    def test_missing_boss_data_refuses_generation(self):
        del self.spells[19703]
        with self.assertRaisesRegex(ValueError, "missing boss"):
            mc_spell_facts.project(self.training, self.spells)

    def test_truncated_dbc_refuses_generation(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            mc_spell_facts.dbc_rows(b"WDBC")


class RaidCapabilityRendering(unittest.TestCase):
    def test_actual_raid_view_renders_the_composed_level_explanation_safely(self):
        report = mc.compose([{"class_id": mc.MAGE, "seat": "dps", "level": 17}])
        line = mc.encounter_line(report)
        card = {"guild": "Example", "encounter_line": line + " <script>bad()</script>"}
        text = node_module(
            "views/raid.js",
            """
const card = %s;
const ready = data => ({data, error: null, loading: false, at: 1});
const get = path => path === '/api/raidgoals'
  ? ready({guilds: [card]}) : ready({seats: []});
console.log(JSON.stringify(M.default.render({get, params: {guild: 'example'}, query: {}}).s));
"""
            % json.dumps(card),
            realm={"families": [], "guilds": []},
        )
        self.assertIn("curse dispeller needs level 18", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>bad()", text)


if __name__ == "__main__":
    unittest.main()
