"""Payload-builder tests: snapshot rows in, map JSON out."""
import unittest

from map_core import build_payload
from transform import Geometry

GEO = Geometry.load(".")
ORGRIMMAR = {"name": "Grug", "level": 1, "race": 2, "map_id": 1,
             "pos_x": 1573.0, "pos_y": -4399.0, "in_combat": 0, "is_bot": 0,
             "age_seconds": 4}


def row(**kw):
    d = dict(ORGRIMMAR)
    d.update(kw)
    return d


class BuildPayloadTest(unittest.TestCase):
    def test_dot_carries_position_faction_and_tooltip_fields(self):
        p = build_payload([row()], GEO)
        (dot,) = p["dots"]
        self.assertEqual(dot["continent"], "1")
        self.assertEqual(dot["faction"], "horde")
        self.assertEqual(dot["name"], "Grug")
        self.assertEqual(dot["zone"], "Ogrimmar")  # the client's own spelling
        self.assertFalse(dot["bot"])
        self.assertTrue(0 < dot["u"] < 1 and 0 < dot["v"] < 1)

    def test_alliance_races_are_alliance(self):
        p = build_payload([row(race=4)], GEO)
        self.assertEqual(p["dots"][0]["faction"], "alliance")

    def test_instance_dweller_surfaces_at_entrance_and_is_marked(self):
        p = build_payload([row(map_id=34, pos_x=0.0, pos_y=0.0)], GEO)
        (dot,) = p["dots"]
        self.assertEqual(dot["continent"], "0")
        self.assertTrue(dot["instance"])

    def test_unplaceable_rows_are_counted_not_dropped_silently(self):
        p = build_payload([row(), row(map_id=99999)], GEO)
        self.assertEqual(len(p["dots"]), 1)
        self.assertEqual(p["unplaced"], 1)

    def test_staleness_is_the_freshest_row(self):
        p = build_payload([row(age_seconds=40), row(age_seconds=7)], GEO)
        self.assertEqual(p["freshest_seconds"], 7)

    def test_empty_world_payload_is_honest(self):
        # The page's contract: a SUCCESSFUL poll always carries the dots and
        # unplaced keys, so "empty world" (this shape) is distinguishable
        # from "poll failed" (no payload at all). The banner logic relies on
        # exactly this - see the first live-map review, finding 4.
        p = build_payload([], GEO)
        self.assertEqual(p["dots"], [])
        self.assertEqual(p["unplaced"], 0)
        self.assertIsNone(p["freshest_seconds"])
