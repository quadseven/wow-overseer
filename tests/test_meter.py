"""The family meter's site half: the probe answer made safe, and the route.

mod-overseer's `meter` probe answers for a whole family. meter.normalize keeps
only known fields with known types, and /api/meter asks one member per family.
"""

import pathlib
import unittest

import meter

ROOT = pathlib.Path(__file__).resolve().parents[1]

ANSWER = {
    "live": True,
    "seconds": 30,
    "target": "Skeletal Flayer",
    "top_threat": 500.0,
    "members": [
        {
            "name": "Ugga",
            "damage": 40,
            "dps": 1,
            "healing": 900,
            "hps": 30,
            "taken": 0,
            "threat": 125.0,
            "threat_pct": 25,
        },
        {
            "name": "Grug",
            "damage": 3000,
            "dps": 100,
            "healing": 0,
            "hps": 0,
            "taken": 900,
            "threat": 500.0,
            "threat_pct": 100,
        },
        {"name": "Og", "damage": "x", "threat": None},
        {"damage": 5},
        "junk",
    ],
}


class NormalizeKeepsWhatItKnows(unittest.TestCase):
    def test_highest_damage_first(self):
        got = meter.normalize(ANSWER)
        self.assertEqual(["Grug", "Ugga", "Og"], [m["name"] for m in got["members"]])

    def test_bad_values_become_defaults(self):
        og = meter.normalize(ANSWER)["members"][2]
        self.assertEqual(0, og["damage"])
        self.assertEqual(-1.0, og["threat"])
        self.assertEqual(-1, og["threat_pct"])

    def test_fight_fields(self):
        got = meter.normalize(ANSWER)
        self.assertTrue(got["live"])
        self.assertEqual(30, got["seconds"])
        self.assertEqual("Skeletal Flayer", got["target"])

    def test_seconds_is_never_zero(self):
        self.assertEqual(1, meter.normalize({"members": [], "seconds": 0})["seconds"])

    def test_not_a_meter_answer_raises(self):
        for bad in (None, [], {"live": True}, {"members": "x"}):
            with self.assertRaises(ValueError):
                meter.normalize(bad)


class ThePayloadNamesEveryFamily(unittest.TestCase):
    def test_online_and_missing(self):
        got = meter.payload(
            ["Grug", "Zug"],
            {"Grug": {"status": "online", "meter": meter.normalize(ANSWER)}},
            123,
        )
        self.assertEqual(123, got["sampled_at"])
        self.assertEqual(["Grug", "Zug"], [f["family"] for f in got["families"]])
        self.assertEqual("online", got["families"][0]["status"])
        self.assertEqual("error", got["families"][1]["status"])
        self.assertEqual([], got["families"][1]["members"])


class TheRouteIsWired(unittest.TestCase):
    def test_route_and_probe(self):
        source = (ROOT / "map_server.py").read_text(encoding="utf-8")
        self.assertIn('"/api/meter": _meter,', source)
        self.assertIn("'meter', 'probe', 'api:meter'", source)

    def test_the_image_carries_the_module(self):
        self.assertIn(" meter.py ", (ROOT / "Dockerfile").read_text(encoding="utf-8"))

    def test_the_page_polls_it(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="family-meter"', page)
        self.assertIn('fetch(u("/api/meter")', page)


if __name__ == "__main__":
    unittest.main()
