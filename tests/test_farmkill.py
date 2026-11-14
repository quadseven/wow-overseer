"""A kill-drop farm order (`farm:<entry>` for cloth or leather a creature drops).

`farmjob.decide` is pure, so most of this drives it with hand-built reads. The
last classes read bridge.py and places.py to pin the wiring: the survey SQL,
the one travel-aim writer, and the zone of a creature spawn.
"""

import pathlib
import re
import unittest

import farmjob
import places
from gatheraim import Spawn

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")

SILK = 4306
FAMILY = ("Grug", "Ugga", "Grog", "Bork", "Og")


def creature(x, y, level=50, zone=33, chance=10.0, map_id=0):
    return farmjob.Creature(
        map_id=map_id,
        zone_id=zone,
        x=float(x),
        y=float(y),
        z=0.0,
        lock_id=0,
        name="Defias Pirate",
        level=level,
        chance=chance,
    )


def node(x, y):
    return Spawn(map_id=0, zone_id=33, x=float(x), y=float(y), z=0.0, lock_id=441)


def order():
    return farmjob.Order(job="farm:%d" % SILK, item=SILK, name="Silk Cloth")


def reads(**kw):
    base = dict(
        skills={name: {} for name in FAMILY},
        levels={name: 60 for name in FAMILY},
        leader_at={"map_id": 0, "zone_id": 1, "pos_x": 0.0, "pos_y": 0.0},
        spawns=(),
        creatures=(creature(1000, 0),),
        zone_levels={33: 55},
        free_slots={name: 20 for name in FAMILY},
        now=60.0,
    )
    base.update(kw)
    return farmjob.Reads(**base)


class ACreatureDropIsAField(unittest.TestCase):
    def test_a_cloth_entry_resolves_to_a_creature_spawn_in_the_band(self):
        step = farmjob.decide(order(), reads())
        self.assertEqual(farmjob.WALK, step.action)
        self.assertIsInstance(step.spawn, farmjob.Creature)
        self.assertEqual(33, step.zone_id)

    def test_it_never_resolves_to_a_node(self):
        step = farmjob.decide(order(), reads(creatures=(creature(2000, 0),), spawns=()))
        self.assertEqual(0, step.spawn.lock_id)

    def test_a_drop_with_nodes_still_walks_to_the_nodes(self):
        step = farmjob.decide(
            order(),
            reads(
                spawns=(node(500, 0),),
                skills={**{n: {} for n in FAMILY}, "Ugga": {"herbalism": 240}},
            ),
        )
        self.assertNotIsInstance(step.spawn, farmjob.Creature)

    def test_the_nearest_safe_creature_field_wins(self):
        step = farmjob.decide(
            order(),
            reads(
                creatures=(creature(3000, 0, zone=44), creature(1000, 0, zone=33)),
                zone_levels={33: 55, 44: 55},
            ),
        )
        self.assertEqual(33, step.zone_id)

    def test_linen_and_wool_lower_kill_band_floor_while_higher_tiers_keep_it(self):
        levels = {"Grug": 60}
        for item, mob_level in ((2589, 12), (2592, 22)):
            self.assertEqual((1, 63), farmjob.kill_band(levels, item))
            ok, refused = farmjob.usable_kills(
                farmjob.Order(job="farm:%d" % item, item=item, name="cloth"),
                (creature(1000, 0, level=mob_level),),
                levels,
            )
            self.assertEqual("", refused)
            self.assertEqual(1, len(ok))
        below = 60 - farmjob.KILL_LEVELS_BELOW - 1
        for item in (4306, 4338, 14047):
            self.assertEqual((30, 63), farmjob.kill_band(levels, item))
            ok, refused = farmjob.usable_kills(
                farmjob.Order(job="farm:%d" % item, item=item, name="cloth"),
                (creature(1000, 0, level=below),),
                levels,
            )
            self.assertEqual([], ok)
            self.assertTrue(refused)


class TheLevelBandIsTheWeakestMembers(unittest.TestCase):
    def test_a_creature_above_the_ceiling_is_never_chosen(self):
        step = farmjob.decide(order(), reads(creatures=(creature(1000, 0, level=70),)))
        self.assertEqual(farmjob.END, step.action)
        self.assertIn("level", step.line)

    def test_the_weakest_member_sets_the_ceiling(self):
        levels = {name: 60 for name in FAMILY}
        levels["Og"] = 40
        weak = reads(levels=levels, creatures=(creature(1000, 0, level=50),))
        self.assertEqual(farmjob.END, farmjob.decide(order(), weak).action)
        ok = reads(
            levels=levels,
            creatures=(creature(1000, 0, level=43),),
            zone_levels={33: 43},
        )
        self.assertEqual(farmjob.WALK, farmjob.decide(order(), ok).action)

    def test_a_creature_far_below_the_family_is_left_out(self):
        low = farmjob.KILL_LEVELS_BELOW + 1
        step = farmjob.decide(
            order(), reads(creatures=(creature(1000, 0, level=60 - low),))
        )
        self.assertEqual(farmjob.END, step.action)

    def test_an_unread_level_fails_closed(self):
        step = farmjob.decide(order(), reads(levels={}))
        self.assertEqual(farmjob.END, step.action)

    def test_a_zone_the_family_died_in_twice_is_struck_off(self):
        step = farmjob.decide(order(), reads(deaths=((33, 0), (33, 0))))
        self.assertEqual(farmjob.END, step.action)

    def test_full_bags_still_go_to_town(self):
        step = farmjob.decide(order(), reads(free_slots={name: 0 for name in FAMILY}))
        self.assertEqual(farmjob.TOWN, step.action)


class TheSurveyIsTheWorldsOwnLootTable(unittest.TestCase):
    SQL = re.search(r"_FARM_ITEM_CREATURE_SQL = \((.*?)\n\)", BRIDGE, re.S)

    def test_the_sql_exists_and_joins_the_loot_table_to_the_spawns(self):
        self.assertIsNotNone(self.SQL)
        text = self.SQL.group(1)
        for part in (
            "creature_loot_template",
            "creature_template",
            "acore_world.creature",
        ):
            self.assertIn(part, text)
        self.assertIn("Reference = 0", text)

    def test_the_read_is_bounded_and_near_the_leader(self):
        text = self.SQL.group(1)
        self.assertIn("LIMIT", text)
        self.assertIn("ORDER BY", text)

    def test_the_reads_fall_back_to_creatures_only_when_there_are_no_nodes(self):
        body = BRIDGE.split("def _farm_reads(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_farm_item_creatures", body)
        self.assertIn("creatures", body)

    def test_the_walk_still_goes_through_the_one_aim_writer(self):
        self.assertEqual(1, BRIDGE.count('state["aim"], state["walking"] = aim, spawn'))
        self.assertNotIn(
            "travel_npc = ", BRIDGE.split("def _farm_item_creatures(", 1)[1][:2500]
        )


class ACreatureSpawnHasAZone(unittest.TestCase):
    def test_a_point_inside_a_zone_rectangle_names_its_area(self):
        self.assertGreater(places.zone_id_at(0, 500.0, 0.0), 0)

    def test_the_id_agrees_with_the_zone_the_name_says(self):
        # On the Duskwood and Deadwind Pass border `zone_at` says Duskwood.
        self.assertEqual("Duskwood", places.zone_at(0, -10265.2, -1237.26))
        self.assertEqual(10, places.zone_id_at(0, -10265.2, -1237.26))

    def test_a_point_off_the_map_names_none(self):
        self.assertEqual(0, places.zone_id_at(0, 1e9, 1e9))

    def test_an_unknown_map_names_none(self):
        self.assertEqual(0, places.zone_id_at(99999, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
