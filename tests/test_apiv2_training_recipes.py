"""GET /api/v2/training lists the recipes a member knows in each held trade."""

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import guildjobs  # noqa: E402
from apiv2 import training  # noqa: E402

TAILORING = next(k for k, v in guildjobs.SKILL_NAMES.items() if v == "Tailoring")
BOOK = {TAILORING: {3: "Bolt B", 1: "Bolt A", 2: "Bolt A", 9: "Unknown to me"}}


def _fetch(known):
    return {
        "char": {"guid": 1, "level": 30, "class_id": 1, "money": 0},
        "known": [{"spell": s} for s in known],
        "skills": [{"skill": TAILORING, "value": 100, "max": 150}],
        "trainer": [],
    }


class Recipes(unittest.TestCase):
    def test_lists_known_by_name_then_id(self):
        r = training.recipes(TAILORING, {3, 2, 1, 77}, BOOK)
        self.assertEqual(r["recipe_count"], 3)
        self.assertEqual(
            r["recipes"],
            [
                {"spell": 1, "name": "Bolt A"},
                {"spell": 2, "name": "Bolt A"},
                {"spell": 3, "name": "Bolt B"},
            ],
        )

    def test_capped_but_counted(self):
        book = {TAILORING: {i: "R%04d" % i for i in range(1, 500)}}
        r = training.recipes(TAILORING, set(range(1, 500)), book)
        self.assertEqual(r["recipe_count"], 499)
        self.assertEqual(len(r["recipes"]), training.MAX_RECIPES)

    def test_none_known(self):
        self.assertEqual(
            training.recipes(TAILORING, set(), BOOK),
            {"recipe_count": 0, "recipes": []},
        )

    def test_payload_carries_field_per_trade(self):
        out = training.build("Grug", _fetch([]))
        trade = out["trades"][0]
        self.assertIn("recipes", trade)
        self.assertIn("recipe_count", trade)

    def test_payload_lists_real_craftbook_recipe(self):
        book = training._craftbook()
        spell = next(iter(book[TAILORING]))
        out = training.build("Grug", _fetch([spell]))
        trade = out["trades"][0]
        self.assertEqual(trade["recipe_count"], 1)
        self.assertEqual(trade["recipes"][0]["spell"], spell)


if __name__ == "__main__":
    unittest.main()
