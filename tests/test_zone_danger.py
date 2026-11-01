"""The page receives routing's answer, never a Python danger-score replica."""

import unittest

import zone_danger


ANSWER = {
    "map_id": 0,
    "party_level": 17,
    "sampled_at": 1000,
    "window_seconds": 86400,
    "level_gap": 8,
    "threshold": 3,
    "zones": [
        {
            "zone_id": 46,
            "name": "Burning Steppes",
            "score": 9,
            "deaths_counted": 9,
            "strongest_killer": 58,
        },
    ],
}


class Projection(unittest.TestCase):
    def test_the_native_score_and_context_are_preserved(self):
        self.assertEqual(ANSWER, zone_danger.normalize(ANSWER))

    def test_empty_is_measured_but_missing_is_unknown(self):
        self.assertEqual([], zone_danger.normalize(dict(ANSWER, zones=[]))["zones"])
        for bad in (None, {}, dict(ANSWER, zones=None), dict(ANSWER, party_level=-1)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                zone_danger.normalize(bad)

    def test_malformed_zones_do_not_disappear_into_an_empty_success(self):
        for row in ({"zone_id": 46}, dict(ANSWER["zones"][0], score="bad"), None):
            with self.subTest(row=row), self.assertRaises(ValueError):
                zone_danger.normalize(dict(ANSWER, zones=[row]))
