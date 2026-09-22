"""Regression coverage for elemental weapon damage in armory tooltips."""

import unittest
from pathlib import Path

import armory
from tests.test_armory_profile import IRONPATCH, build, member, slot_of, worn


class SecondaryDamageTest(unittest.TestCase):
    def test_secondary_damage_is_carried_in_the_pure_tooltip_payload(self):
        row = worn(15, dict(IRONPATCH, dmg_min2=5, dmg_max2=7, dmg_type2=2))
        tooltip = slot_of(member(build([row])), "main hand")["tooltip"]
        self.assertEqual(
            tooltip["secondary_damage"], [{"min": 5, "max": 7, "school": "Fire"}]
        )

    def test_all_supported_secondary_schools_have_names(self):
        for school_id, school in armory._DAMAGE_SCHOOLS.items():
            self.assertEqual(
                armory._secondary_damage(
                    {"dmg_min2": 1, "dmg_max2": 2, "dmg_type2": school_id}
                ),
                [{"min": 1, "max": 2, "school": school}],
            )

    def test_query_and_renderer_request_and_draw_secondary_damage(self):
        here = Path(__file__).parents[1]
        query = (here / "map_server.py").read_text(encoding="utf-8")
        page = (here / "index.html").read_text(encoding="utf-8")
        self.assertIn("it.dmg_min2, it.dmg_max2, it.dmg_type2", query)
        self.assertIn("t.secondary_damage", page)
        self.assertIn('damage.school + " Damage"', page)


if __name__ == "__main__":
    unittest.main()
