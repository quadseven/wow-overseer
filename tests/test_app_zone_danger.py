"""Render the real family view with routing evidence and unavailable samples."""

import json
import pathlib
import shutil
import unittest

from test_app_shell import node_module
from test_zone_danger import ANSWER


def render(entry=None, family="Grug"):
    payload = {"families": [entry] if entry else []}
    return node_module(
        "views/family.js",
        """
const waiting = {data: null, error: null, loading: true, at: 0};
const get = (path) => path === '/api/v2/zone-danger'
  ? {data: %s, error: null, loading: false, at: 1} : waiting;
const out = M.default.render({get, params: {family: %s}, query: {}});
console.log(JSON.stringify(out.s));
"""
        % (json.dumps(payload), json.dumps(family.lower())),
        realm={"families": [{"key": "Grug"}, {"key": "Zug"}], "guilds": []},
    )


@unittest.skipUnless(shutil.which("node"), "node is needed for the actual view")
class FamilyDangerView(unittest.TestCase):
    def test_native_zone_score_count_and_reason_are_visible(self):
        text = render(
            {
                "family": "Grug",
                "sampled_for": "Grug",
                "status": "online",
                "danger": ANSWER,
            }
        )
        for expected in (
            "Travel danger",
            "Burning Steppes",
            "Score 9",
            "9 deaths counted",
            "strongest killer level 58",
            "minimum level 17",
            "24 hours",
            "8 levels",
        ):
            self.assertIn(expected, text)

    def test_empty_and_unavailable_are_different(self):
        text = render(
            {
                "family": "Grug",
                "sampled_for": "Grug",
                "status": "online",
                "danger": dict(ANSWER, zones=[]),
            }
        )
        self.assertIn("No zones meet the routing threshold", text)
        unknown = render(
            {"family": "Grug", "status": "error", "error": "module not reporting"}
        )
        self.assertIn("Travel danger not measured", unknown)
        self.assertIn("module not reporting", unknown)
        self.assertNotIn("No zones meet", unknown)

    def test_other_family_data_and_markup_are_not_injected(self):
        entry = {
            "family": "Grug",
            "sampled_for": "Grug",
            "status": "online",
            "danger": dict(
                ANSWER, zones=[dict(ANSWER["zones"][0], name="<script>bad()</script>")]
            ),
        }
        self.assertNotIn("<script>bad()", render(entry))
        self.assertIn("&lt;script&gt;", render(entry))
        self.assertNotIn("Score 9", render(entry, family="Zug"))


class Route(unittest.TestCase):
    def test_image_carries_the_projection_validator(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertIn(" zone_danger.py ", (root / "Dockerfile").read_text())
