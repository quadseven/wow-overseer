"""A vendor spawn the world never puts in play is not a counter (#2220).

The world database flags 752 "[DND] TAR Pedestal" creatures as vendors. They
belong to the Arena Tournament game event, which does not run here, so the core
never spawns them and a sale beside one is refused with "vendor not in range".
The module's own travel index already skips them. The bridge read every spawn
carrying the vendor flag as a counter: a family walking past a pedestal in a
capital was read as standing at a counter, its sell rows were written there and
refused (dev realm 2026-11-10 15:05Z: 54 rows, nearest real vendor 22 yards
away), and the member was left out of its next vendor aim.
"""

import ast
import pathlib
import unittest

import towntrip

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

# The queries that answer "where is a vendor counter" for a member or an errand.
COUNTER_QUERIES = (
    "_NEAREST_VENDOR_OFFSET_SQL",
    "_BAG_VENDOR_SQL",
    "_GEAR_VENDOR_SQL",
    "_SUPPLY_VENDOR_SQL",
    "_NEAREST_COUNTER_SQL",
    "_ERRAND_VENDORS_SQL",
    "_TOWN_COUNTERS_SQL",
    "_REAGENT_VENDOR_SQL",
)

# Queries on an npcflag that are not vendor counters, each with its reason.
NOT_COUNTERS = {
    "_JOB_HUB_MASTERS_SQL": "flight masters, read once per process",
    "_FLIGHT_MASTER_SQL": "flight masters",
    "_ERRAND_AUCTIONEERS_SQL": "auctioneers",
    "_AUCTIONEER_IN_REACH_SQL": "auctioneers",
    "_AUCTIONEER_MAPS_SQL": "auctioneers",
    "_AUCTIONEER_SPAWNS_SQL": "auctioneers",
}


def _queries():
    text = BRIDGE.read_text(encoding="utf-8")
    out = {}
    for node in ast.parse(text).body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.endswith("_SQL")
        ):
            out[node.targets[0].id] = ast.get_source_segment(text, node)
    return out


class ThePedestalsAreNotCounters(unittest.TestCase):
    def test_the_fragment_drops_event_only_spawns_and_the_pedestals(self):
        sql = towntrip.REAL_SPAWN_SQL
        self.assertIn("acore_world.game_event_creature", sql)
        self.assertIn("eventEntry > 0", sql)
        self.assertIn("[DND] TAR Pedestal", sql)
        self.assertNotIn("%", sql)  # it rides inside a parameterised query

    def test_the_pedestal_prefix_is_as_long_as_its_length_test(self):
        prefix = "[DND] TAR Pedestal"
        self.assertIn("LEFT(ct.name, %d)" % len(prefix), towntrip.REAL_SPAWN_SQL)

    def test_every_counter_query_carries_the_fragment(self):
        queries = _queries()
        for name in COUNTER_QUERIES:
            with self.subTest(query=name):
                self.assertIn(name, queries)
                self.assertIn("towntrip.REAL_SPAWN_SQL", queries[name])

    def test_a_new_npcflag_query_must_choose(self):
        """A query on an npcflag carries the fragment or is named a non-counter."""
        for name, segment in _queries().items():
            if "npcflag &" not in segment:
                continue
            with self.subTest(query=name):
                self.assertTrue(
                    "towntrip.REAL_SPAWN_SQL" in segment or name in NOT_COUNTERS,
                    "%s reads vendor-flag spawns without REAL_SPAWN_SQL; add it "
                    "or list the query in NOT_COUNTERS with a reason" % name,
                )


if __name__ == "__main__":
    unittest.main()
