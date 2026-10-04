"""/api/item: shaping loot, quest, vendor, craft and chest rows into sources.

Fake rows, no database. map_server imports pymysql, so the route and its
refusals are asserted against the source, as the Armory tab's suite does.
"""

import pathlib
import unittest

import itemsource

HERE = pathlib.Path(__file__).resolve().parent.parent
DUNGEONS = {329: "Stratholme"}
ZONES = {10: "Duskwood"}
SKILLS = {164: "Blacksmithing"}


def build(**rows):
    shaped = {
        "name": "Cape",
        "quality": 4,
        "tooltip": {"name": "Cape"},
        "wowhead": "https://www.wowhead.com/wotlk/item=1",
    }
    return itemsource.build_item(
        1,
        shaped,
        rows,
        craftbook={},
        skill_names=SKILLS,
        dungeons=DUNGEONS,
        zones=ZONES,
    )


class Chance(unittest.TestCase):
    def test_a_stated_chance_is_that_chance(self):
        self.assertEqual(itemsource.row_chance({"chance": 8.7}), 8.7)

    def test_a_zero_chance_group_row_shares_what_the_group_leaves(self):
        row = {"chance": 0, "group_id": 1, "zeros": 5, "explicit": 13}
        self.assertAlmostEqual(itemsource.row_chance(row), 17.4)

    def test_a_zero_chance_row_outside_a_group_never_drops(self):
        self.assertEqual(itemsource.row_chance({"chance": 0, "group_id": 0}), 0.0)

    def test_a_reference_multiplies_the_roll_by_the_chance_inside_it(self):
        out = itemsource.loot_chances(
            [],
            [{"entry": 35028, "chance": 0, "group_id": 1, "zeros": 4, "explicit": 20}],
            [{"entry": 10440, "reference": 35028, "chance": 100}],
        )
        self.assertAlmostEqual(out[10440], 20.0)

    def test_a_reference_row_with_no_chance_rolls_for_certain(self):
        out = itemsource.loot_chances(
            [],
            [{"entry": 9, "chance": 40}],
            [{"entry": 7, "reference": 9, "chance": 0}],
        )
        self.assertAlmostEqual(out[7], 40.0)

    def test_direct_and_reference_chances_combine_as_independent_rolls(self):
        out = itemsource.loot_chances(
            [{"entry": 7, "chance": 50}],
            [{"entry": 9, "chance": 50}],
            [{"entry": 7, "reference": 9, "chance": 100}],
        )
        self.assertAlmostEqual(out[7], 75.0)


class Drops(unittest.TestCase):
    def test_a_boss_in_an_instance_is_named_with_its_dungeon_and_map(self):
        got = build(
            loot_direct=[{"entry": 10, "chance": 8.7}],
            creatures=[{"lootid": 10, "name": "Baron Rivendare", "map": 329}],
        )
        self.assertEqual(
            got["sources"],
            [
                {
                    "kind": "drop",
                    "boss": "Baron Rivendare",
                    "where": "Stratholme",
                    "map": 329,
                    "chance": 8.7,
                }
            ],
        )

    def test_sub_one_percent_world_drops_fold_into_one_line(self):
        got = build(
            loot_direct=[{"entry": 1, "chance": 0.4}, {"entry": 2, "chance": 0.9}],
            creatures=[
                {"lootid": 1, "name": "Wolf", "map": 0, "zone": 10},
                {"lootid": 2, "name": "Bear", "map": 0, "zone": 10},
            ],
        )
        self.assertEqual(got["sources"], [{"kind": "world", "chance_max": 0.9}])

    def test_an_outdoor_creature_names_its_zone_or_world(self):
        got = build(
            loot_direct=[{"entry": 1, "chance": 5}, {"entry": 2, "chance": 3}],
            creatures=[
                {"lootid": 1, "name": "Wolf", "map": 0, "zone": 10},
                {"lootid": 2, "name": "Bear", "map": 999, "zone": 0},
            ],
        )
        self.assertEqual([s["where"] for s in got["sources"]], ["Duskwood", "World"])

    def test_an_outdoor_creature_with_no_zone_names_its_continent(self):
        got = build(
            loot_direct=[{"entry": 1, "chance": 5}],
            creatures=[{"lootid": 1, "name": "Wolf", "map": 1}],
        )
        self.assertEqual(got["sources"][0]["where"], "Kalimdor")

    def test_creatures_sharing_a_name_collapse_to_the_best_chance(self):
        got = build(
            loot_direct=[{"entry": 1, "chance": 2}, {"entry": 2, "chance": 6}],
            creatures=[
                {"lootid": 1, "name": "Wolf", "map": 0, "zone": 10},
                {"lootid": 2, "name": "Wolf", "map": 0, "zone": 10},
            ],
        )
        self.assertEqual([s["chance"] for s in got["sources"]], [6.0])


class Ordering(unittest.TestCase):
    def test_instance_drops_then_quest_then_vendor_then_craft_then_world(self):
        shaped = {"name": "X", "quality": 3, "tooltip": None, "wowhead": "w"}
        got = itemsource.build_item(
            1,
            shaped,
            {
                "loot_direct": [
                    {"entry": 1, "chance": 2},
                    {"entry": 2, "chance": 0.5},
                    {"entry": 3, "chance": 40},
                ],
                "creatures": [
                    {"lootid": 1, "name": "Wolf", "map": 0},
                    {"lootid": 2, "name": "Bat", "map": 0},
                    {"lootid": 3, "name": "Boss", "map": 329},
                ],
                "quests": [{"title": "Q", "giver": "G", "zone_id": 10}],
                "vendors": [{"npc": "V", "map": 0, "zone": 10}],
                "buy_price": 500,
                "objects": [{"name": "Chest", "chance": 100, "map": 329}],
            },
            craftbook={"164": {"9": ["Make X", 1, 150, 1, 1]}},
            skill_names=SKILLS,
            dungeons=DUNGEONS,
            zones=ZONES,
        )
        self.assertEqual(
            [s["kind"] for s in got["sources"]],
            ["drop", "drop", "object", "quest", "vendor", "craft", "world"],
        )
        self.assertEqual(got["sources"][0]["boss"], "Boss")
        self.assertEqual(got["sources"][-1], {"kind": "world", "chance_max": 0.5})

    def test_the_list_is_capped_and_keeps_the_world_line(self):
        creatures = [{"lootid": n, "name": "B%d" % n, "map": 329} for n in range(1, 30)]
        quests = [{"title": "Q%d" % n, "zone_id": 10} for n in range(10)]
        vendors = [{"npc": "V%d" % n, "map": 0} for n in range(10)]
        got = build(
            loot_direct=[{"entry": n, "chance": 5} for n in range(1, 30)]
            + [{"entry": 99, "chance": 0.2}],
            creatures=creatures + [{"lootid": 99, "name": "Rat", "map": 0}],
            quests=quests,
            vendors=vendors,
            buy_price=100,
        )
        kinds = [s["kind"] for s in got["sources"]]
        self.assertLessEqual(len(kinds), itemsource.MAX_SOURCES)
        self.assertEqual(kinds[-1], "world")
        self.assertLessEqual(kinds.count("drop"), itemsource.PER_KIND_CAP)

    def test_no_sources_is_an_empty_list(self):
        self.assertEqual(build()["sources"], [])


class Quests(unittest.TestCase):
    def test_a_quest_names_its_giver_and_zone(self):
        got = build(quests=[{"title": "Saving", "giver": "Bob", "zone_id": 10}])
        self.assertEqual(
            got["sources"],
            [{"kind": "quest", "quest": "Saving", "giver": "Bob", "zone": "Duskwood"}],
        )

    def test_faction_twins_collapse(self):
        got = build(
            quests=[
                {"title": "A", "giver": "B", "zone_id": 10},
                {"title": "A", "giver": "B", "zone_id": 10},
            ]
        )
        self.assertEqual(len(got["sources"]), 1)


class Vendors(unittest.TestCase):
    def test_a_plain_gold_vendor_carries_copper(self):
        got = build(
            vendors=[{"npc": "Mira", "map": 0, "zone": 10, "extended_cost": 0}],
            buy_price=1234,
        )
        self.assertEqual(
            got["sources"],
            [{"kind": "vendor", "npc": "Mira", "zone": "Duskwood", "copper": 1234}],
        )

    def test_an_extended_cost_vendor_omits_what_it_cannot_decode(self):
        got = build(
            vendors=[
                {"npc": "Quartermaster", "map": 0, "zone": 10, "extended_cost": 77}
            ],
            buy_price=1234,
        )
        self.assertEqual(
            got["sources"],
            [{"kind": "vendor", "npc": "Quartermaster", "zone": "Duskwood"}],
        )


class Crafts(unittest.TestCase):
    def test_the_craftbook_maps_a_created_item_to_its_recipe(self):
        book = {"164": {"9": ["Make X", 1, 150, 1, 1], "8": ["Other", 1, 5, 1, 2]}}
        self.assertEqual(
            itemsource.craft_sources(1, book, SKILLS),
            [
                {
                    "kind": "craft",
                    "profession": "Blacksmithing",
                    "skill": 150,
                    "recipe": "Make X",
                    "_id": 164,
                }
            ],
        )


class Cache(unittest.TestCase):
    def test_it_evicts_the_least_recently_used_entry(self):
        cache = itemsource.BoundedCache(2)
        cache.put(1, "a")
        cache.put(2, "b")
        cache.get(1)
        cache.put(3, "c")
        self.assertIsNone(cache.get(2))
        self.assertEqual((cache.get(1), cache.get(3)), ("a", "c"))
        self.assertEqual(len(cache), 2)


class TheRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()
        start = cls.server.index("    def _item(self")
        cls.handler = cls.server[start : cls.server.index("    GET_ROUTES", start)]

    def test_it_is_routed(self):
        self.assertIn('"/api/item": _item,', self.server)

    def test_entry_must_be_a_positive_integer(self):
        self.assertIn("isdigit()", self.handler)
        self.assertIn("0 < int(wanted)", self.handler)
        self.assertIn("send(400", self.handler.replace("self._", ""))

    def test_unknown_item_is_404_and_a_failed_read_is_503(self):
        self.assertIn("send(404", self.handler.replace("self._", ""))
        self.assertIn("send(503", self.handler.replace("self._", ""))

    def test_the_sql_is_parameterized(self):
        start = self.server.index("def _fetch_item_sources")
        sql = self.server[start : self.server.index("def _item_payload", start)]
        self.assertNotIn("% entry", sql)
        self.assertIn("WHERE it.entry = %s", sql)


if __name__ == "__main__":
    unittest.main()
