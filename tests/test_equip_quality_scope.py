"""Common-quality gear reaches only the holder equip/Jev path."""

import pathlib
import unittest


BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
SOURCE = BRIDGE.read_text(encoding="utf-8")


class EquipQualityScopeTest(unittest.TestCase):
    def test_surplus_query_keeps_its_quality_floor(self):
        sql = SOURCE[
            SOURCE.index("_SURPLUS_GEAR_SQL = (") : SOURCE.index(
                "# Carried RECIPES", SOURCE.index("_SURPLUS_GEAR_SQL = (")
            )
        ]
        self.assertIn("it.Quality >= 2", sql)

    def test_equip_query_reads_supported_gear_without_a_quality_floor(self):
        sql = SOURCE[
            SOURCE.index("_EQUIP_CANDIDATE_GEAR_SQL = (") : SOURCE.index(
                "def _fetch_equip_candidate_gear",
                SOURCE.index("_EQUIP_CANDIDATE_GEAR_SQL = ("),
            )
        ]
        self.assertIn("it.class IN (2, 4)", sql)
        self.assertIn("it.InventoryType IN", sql)
        self.assertNotIn("it.Quality >=", sql)

    def test_only_equip_and_jev_receive_the_broader_rows(self):
        body = SOURCE[SOURCE.index("    async def _vendor_once(self") :]
        self.assertIn(
            "equip_rows = await asyncio.to_thread(_fetch_equip_candidate_gear, names)",
            body,
        )
        self.assertIn("_jev_items_plan(jev_rows, worn, names)", body)
        self.assertIn("_hand_gear(gear_rows, worn, names, jev_plan)", body)
        self.assertIn("_equip_upgrades(equip_rows, worn, names, jev_plan)", body)


if __name__ == "__main__":
    unittest.main()
