"""The per-role gear floor table (#2110)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import raidfloor  # noqa: E402
import raidready  # noqa: E402

LINEUP_ROLES = ("tank", "healer", "dps")


class TheFloorTable(unittest.TestCase):
    def test_every_role_in_the_lineup_has_a_floor(self):
        for role in LINEUP_ROLES:
            self.assertTrue(raidfloor.FLOORS.get(role), "no floor for %s" % role)

    def test_the_roles_a_card_reports_are_the_roles_with_floors(self):
        self.assertEqual(set(LINEUP_ROLES), set(raidfloor.FLOORS))
        self.assertTrue(hasattr(raidready, "raidfloor"))

    def test_every_floor_cites_the_encounter_damage_it_comes_from(self):
        text = " ".join(
            why for stats in raidfloor.FLOORS.values() for _f, why in stats.values()
        )
        self.assertIn("Ragnaros", text)
        self.assertIn("Magma Blast", text)
        self.assertIn("Majordomo", text)
        for stats in raidfloor.FLOORS.values():
            for floor, why in stats.values():
                self.assertGreater(floor, 0)
                self.assertTrue(why)

    def test_the_tank_health_floor_is_computed_from_the_damage_inputs(self):
        floor = raidfloor.FLOORS["tank"]["effective health"][0]
        self.assertEqual(
            raidfloor.HITS_BEFORE_HEAL * raidfloor.RAGNAROS_MELEE_HIT
            + raidfloor.MAGMA_BLAST_HIT,
            floor,
        )

    def test_armor_lowers_the_damage_so_raises_effective_health(self):
        bare = raidfloor.worn_stats([{"stat_type1": 7, "stat_value1": 100}])
        armored = raidfloor.worn_stats(
            [{"stat_type1": 7, "stat_value1": 100, "armor": 5500}]
        )
        self.assertEqual(1000, bare["effective health"])
        self.assertEqual(2000, armored["effective health"])

    def test_no_worn_rows_is_no_verdict(self):
        self.assertEqual([], raidfloor.shortfalls("tank", []))


if __name__ == "__main__":
    unittest.main()
