"""Rare recipes by dungeon: the trades tab's answer to "where do we farm it".

THE OPERATOR'S QUESTION (2026-10-05). The trades page said where each missing
recipe comes from, one trade at a time. What the guild plans from is the other
way round: which dungeon holds which rare recipes, and which of its crafters
still need them. These tests hold the grouping, the rare rule, the "who still
needs it" list, and that /api/trades carries the answer under `dungeons`.

The fixtures are test_guildcraft's real family, reused rather than restated.
"""

import io
import json
import logging
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import achievements  # noqa: E402
import dungeonpath  # noqa: E402
import guildcraft  # noqa: E402
import map_server  # noqa: E402
import test_guildcraft as gc  # noqa: E402

map_server.log.propagate = False
map_server.log.addHandler(logging.NullHandler())

HERE = pathlib.Path(__file__).resolve().parent.parent

DEADMINES = 36
WAILING = 43
# A map that is not a continent and not on dungeonpath.PATH, so it exercises
# the off-path fallback. Asserted below rather than assumed.
OFF_PATH = 540
NAMES = {DEADMINES: "The Deadmines", WAILING: "Wailing Caverns"}


def dungeons(**over) -> dict:
    over.setdefault("names", dict(NAMES))
    return gc.build(**over)["dungeons"]


def card(payload: dict, name: str) -> dict:
    found = [d for d in payload["dungeons"] if d["name"] == name]
    assert len(found) == 1, name
    return found[0]


class TheGrouping(unittest.TestCase):
    def setUp(self):
        self.rows = [
            gc.recipe(70, "Pattern: Red Linen Robe", gc.TAILORING, 10, 900),
            gc.recipe(71, "Pattern: Blue Linen Vest", gc.TAILORING, 20, 901),
        ]

    def test_only_drops_inside_an_instance_are_grouped(self):
        payload = dungeons(
            recipe_rows=self.rows,
            drop_rows=[
                gc.drop(70, "Mr. Smite", map_id=DEADMINES),
                gc.drop(71, "Defias Conjurer"),
            ],
        )
        self.assertEqual([d["name"] for d in payload["dungeons"]], ["The Deadmines"])
        self.assertEqual(
            [r["name"] for r in payload["dungeons"][0]["recipes"]],
            ["Pattern: Red Linen Robe"],
        )

    def test_a_recipe_carries_its_trade_rank_chance_and_creature(self):
        payload = dungeons(
            recipe_rows=self.rows,
            drop_rows=[gc.drop(70, "Mr. Smite", map_id=DEADMINES, chance=12)],
        )
        recipe = payload["dungeons"][0]["recipes"][0]
        self.assertEqual(recipe["trade"], "tailoring")
        self.assertEqual(recipe["rank"], 10)
        self.assertEqual(recipe["chance"], 12.0)
        self.assertIn("from Mr. Smite, level 20 to 21", recipe["creatures"][0])
        self.assertIn("12%", recipe["creatures"][0])

    def test_dungeons_follow_the_dungeon_path_and_not_the_input_order(self):
        self.assertIn(WAILING, dungeonpath.PATH_MAPS)
        self.assertLess(
            dungeonpath.PATH_MAPS.index(WAILING), dungeonpath.PATH_MAPS.index(DEADMINES)
        )
        payload = dungeons(
            recipe_rows=self.rows,
            drop_rows=[
                gc.drop(70, "Mr. Smite", map_id=DEADMINES),
                gc.drop(71, "Deviate Ravager", map_id=WAILING),
            ],
        )
        self.assertEqual(
            [(d["rank"], d["name"]) for d in payload["dungeons"]],
            [(1, "Wailing Caverns"), (2, "The Deadmines")],
        )
        self.assertIn("levels 17 to 24", payload["dungeons"][0]["level_line"])

    def test_a_dungeon_off_the_path_comes_after_it_by_its_lowest_level(self):
        self.assertNotIn(OFF_PATH, dungeonpath.PATH_MAPS)
        self.assertNotIn(OFF_PATH, guildcraft.CONTINENT_MAPS)
        payload = dungeons(
            recipe_rows=self.rows,
            drop_rows=[
                gc.drop(70, "Fel Orc", low=70, high=71, map_id=OFF_PATH),
                gc.drop(71, "Mr. Smite", map_id=DEADMINES),
            ],
        )
        last = payload["dungeons"][-1]
        self.assertEqual(last["name"], "map %d" % OFF_PATH)
        self.assertIn("off the dungeon path", last["level_line"])
        self.assertIn("level 70", last["level_line"])

    def test_a_drop_for_an_item_that_is_not_a_read_recipe_is_skipped(self):
        payload = dungeons(
            recipe_rows=self.rows,
            drop_rows=[gc.drop(99, "Mr. Smite", map_id=DEADMINES)],
        )
        self.assertEqual(payload["dungeons"], [])
        self.assertIn("no recipe drop", payload["line"])

    def test_a_long_dungeon_list_is_trimmed_and_says_so(self):
        many = guildcraft.LISTED_PER_DUNGEON + 2
        rows = [
            gc.recipe(100 + n, "Pattern %02d" % n, gc.TAILORING, 5, 2000 + n)
            for n in range(many)
        ]
        drops = [gc.drop(100 + n, "Trash", map_id=DEADMINES) for n in range(many)]
        dungeon = dungeons(recipe_rows=rows, drop_rows=drops)["dungeons"][0]
        self.assertEqual(len(dungeon["recipes"]), guildcraft.LISTED_PER_DUNGEON)
        self.assertEqual(dungeon["recipe_count"], many)
        self.assertIn("%d recipes drop here" % many, dungeon["line"])
        self.assertIn("are listed", dungeon["line"])


class TheRareRule(unittest.TestCase):
    def test_uncommon_or_better_is_rare_whatever_the_chance(self):
        self.assertTrue(guildcraft.is_rare(2, 40.0))
        self.assertTrue(guildcraft.is_rare(3, 0))

    def test_under_five_percent_is_rare_whatever_the_quality(self):
        self.assertTrue(guildcraft.is_rare(1, 4.9))
        self.assertFalse(guildcraft.is_rare(1, 5.0))

    def test_an_unread_chance_is_not_called_rare(self):
        """Zero is the grouped row whose real chance this page cannot count."""
        self.assertFalse(guildcraft.is_rare(1, 0))

    def test_a_quest_drop_chance_is_read_by_its_size(self):
        """A negative chance is the core's mark for a quest drop."""
        payload = dungeons(
            recipe_rows=[gc.recipe(70, "Pattern: A", gc.TAILORING, 10, 900)],
            drop_rows=[gc.drop(70, "Mr. Smite", map_id=DEADMINES, chance=-3)],
        )
        recipe = payload["dungeons"][0]["recipes"][0]
        self.assertTrue(recipe["rare"])
        self.assertEqual(recipe["chance"], 3.0)
        self.assertIn("3%", recipe["creatures"][0])

    def test_rare_recipes_are_listed_first_and_counted(self):
        payload = dungeons(
            recipe_rows=[
                gc.recipe(70, "Pattern: Common", gc.TAILORING, 1, 900),
                gc.recipe(71, "Pattern: Green", gc.TAILORING, 50, 901, quality=2),
            ],
            drop_rows=[
                gc.drop(70, "Mr. Smite", map_id=DEADMINES, chance=30),
                gc.drop(71, "Mr. Smite", map_id=DEADMINES, chance=30),
            ],
        )
        dungeon = payload["dungeons"][0]
        self.assertEqual(
            [r["name"] for r in dungeon["recipes"]],
            ["Pattern: Green", "Pattern: Common"],
        )
        self.assertEqual(dungeon["rare_count"], 1)
        self.assertIn("2 recipes drop here, 1 of them rare", dungeon["line"])
        self.assertIn("uncommon", dungeon["recipes"][0]["rare_line"])
        self.assertIn("not counted rare", dungeon["recipes"][1]["rare_line"])


class WhoStillNeedsIt(unittest.TestCase):
    def setUp(self):
        self.rows = [gc.recipe(70, "Pattern: A", gc.TAILORING, 10, 900)]
        self.drops = [gc.drop(70, "Mr. Smite", map_id=DEADMINES)]

    def recipe(self, **over):
        payload = dungeons(recipe_rows=self.rows, drop_rows=self.drops, **over)
        return payload["dungeons"][0]["recipes"][0]

    def test_a_holder_who_does_not_know_it_needs_it(self):
        recipe = self.recipe()
        self.assertEqual(recipe["needed_by"], ["Og"])
        self.assertIn("still needed by Og", recipe["need_line"])
        self.assertIn("tailoring 10", recipe["need_line"])

    def test_a_holder_who_knows_it_does_not(self):
        recipe = self.recipe(spell_rows=[{"name": "Og", "spell": 900}])
        self.assertEqual(recipe["needed_by"], [])
        self.assertIn("already knows it", recipe["need_line"])

    def test_only_the_holders_who_lack_it_are_named(self):
        skills = list(gc.FAMILY_SKILLS) + [gc.skill("Ugga", gc.TAILORING, 5)]
        recipe = self.recipe(
            skill_rows=skills, spell_rows=[{"name": "Og", "spell": 900}]
        )
        self.assertEqual(recipe["needed_by"], ["Ugga"])

    def test_a_spell_known_without_the_trade_does_not_make_a_holder(self):
        recipe = self.recipe(spell_rows=[{"name": "Grug", "spell": 900}])
        self.assertEqual(recipe["needed_by"], ["Og"])

    def test_a_trade_nobody_holds_needs_nobody_and_says_why(self):
        rows = [gc.recipe(70, "Schematic: A", gc.ENGINEERING, 10, 900)]
        payload = dungeons(recipe_rows=rows, drop_rows=self.drops)
        recipe = payload["dungeons"][0]["recipes"][0]
        self.assertEqual(recipe["needed_by"], [])
        self.assertIn("nobody here holds engineering", recipe["need_line"])

    def test_the_wanted_count_reaches_the_headline(self):
        payload = dungeons(recipe_rows=self.rows, drop_rows=self.drops)
        self.assertEqual(payload["dungeons"][0]["wanted_count"], 1)
        self.assertIn("1 still wanted", payload["line"])
        for word in ("should", "recommend", "best", "worth"):
            self.assertNotIn(word, payload["line"], word)


class TheEndpointCarriesIt(unittest.TestCase):
    """/api/trades driven through the real handler, with the reads replaced."""

    def fetched(self) -> dict:
        names = list(gc.ROSTER)
        return {
            "families": {
                "cave": {
                    "guild_rows": [],
                    "member_rows": [gc.member(n) for n in names],
                    "skill_rows": list(gc.FAMILY_SKILLS),
                    "spell_rows": [],
                }
            },
            "roster_rows": [],
            "recipe_rows": [gc.recipe(70, "Pattern: A", gc.TAILORING, 10, 900)],
            "trainer_rows": [],
            "vendor_rows": [],
            "drop_rows": [gc.drop(70, "Mr. Smite", map_id=DEADMINES, chance=2)],
            "quest_rows": [],
            "craft_rows": [],
            "roster_read": False,
        }

    def test_the_payload_has_a_dungeons_key_beside_the_old_ones(self):
        sides = [
            {
                "family": "cave",
                "names": list(gc.ROSTER),
                "faction": "alliance",
                "heading": "Cave",
            }
        ]
        handler = TradesHandler("/api/trades")
        with (
            mock.patch.object(map_server, "_faction_sides", return_value=sides),
            mock.patch.object(
                map_server, "_fetch_guildcraft", return_value=self.fetched()
            ),
        ):
            handler.do_GET()
        code, _ctype, body = handler.sent[-1]
        self.assertEqual(code, 200)
        payload = json.loads(body)
        for key in ("line", "trades", "gaps", "basis", "goal", "families"):
            self.assertIn(key, payload, key)
        for side in (payload, payload["families"][0]):
            found = side["dungeons"]["dungeons"]
            self.assertEqual(found[0]["name"], achievements.MAP_NAMES[DEADMINES])
            self.assertTrue(found[0]["recipes"][0]["rare"])
            self.assertEqual(found[0]["recipes"][0]["needed_by"], ["Og"])


class TradesHandler(map_server.Handler):
    """A Handler with the socket amputated, as test_chat_endpoints does it."""

    def __init__(self, path):
        self.path = path
        self.rfile = io.BytesIO(b"")
        self.headers = {}
        self.sent = []

    def _send(self, code, ctype, body):
        self.sent.append((code, ctype, body))


class ThePage(unittest.TestCase):
    """The section is drawn from the module's sentences and composes none."""

    BANNER = "// --- rare recipes by dungeon"

    def test_no_em_dashes_in_this_suite(self):
        text = pathlib.Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn(chr(0x2014), text)


if __name__ == "__main__":
    unittest.main()
