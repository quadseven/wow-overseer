"""A family on a town stop walks to the station a standing craft needs.

quadseven/wow-overseer#1786. The forge pass served job='craft' alone while the
errand is written for a town run too, so a leader in a capital held a smelt with
19 casts of ore and no walk would ever come. Walking the family is only worth it
with materials in hand and a station inside the town.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import craft  # noqa: E402
import craft_rhythm  # noqa: E402
import raidsupply  # noqa: E402
import travel  # noqa: E402

SMELT_COPPER = 2657
COPPER_ORE = craft_rhythm.GATHERED[SMELT_COPPER][0].entry
RUNED_COPPER_BELT = next(
    r.spell_id for r in craft.known_recipes() if r.focus == 1 and r.tool
)


def load_bridge():
    """The bridge, over a stub of the discord library CI does not install."""
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    stub.Intents = mock.Mock()
    stub.Message = object
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


class TheDemand(unittest.TestCase):
    def test_a_smelt_with_ore_in_the_bags_is_demand(self):
        self.assertEqual(
            craft_rhythm.town_stop_crafts(
                {"Lead": SMELT_COPPER}, {"Lead": {COPPER_ORE: 19}}
            ),
            {"Lead": SMELT_COPPER},
        )

    def test_a_smelt_with_no_ore_walks_nobody(self):
        self.assertEqual(
            craft_rhythm.town_stop_crafts({"Lead": SMELT_COPPER}, {"Lead": {}}), {}
        )

    def test_a_recipe_with_no_world_station_walks_nobody(self):
        linen = next(r.spell_id for r in craft.known_recipes() if not r.focus)
        cook = next(r.spell_id for r in craft.known_recipes() if r.focus == 4)
        self.assertEqual(
            craft_rhythm.town_stop_crafts({"A": linen, "B": cook}, {}), {}
        )


class TheTown(unittest.TestCase):
    def test_a_forge_across_a_capital_is_in_town(self):
        self.assertTrue(travel.station_in_town({"d2": 700.0**2}))

    def test_a_forge_a_zone_away_is_not(self):
        self.assertFalse(travel.station_in_town({"d2": 2000.0**2}))

    def test_no_forge_is_not_in_town(self):
        self.assertFalse(travel.station_in_town(None))


class ThePass(unittest.TestCase):
    """`_forge_once` itself, over fake reads: the town stop's walk or none."""

    def run_pass(self, standing, spawn):
        bridge = load_bridge()
        claims = []

        async def claim(_slot, leader, aim, cohort=None):
            claims.append((leader, aim))
            return True

        async def mid_run(_names):
            return False

        fake = mock.Mock(_claim_town_slot=claim, _mid_run=mid_run)
        fake._town_stop_demand = lambda cohort: bridge.Bridge._town_stop_demand(
            fake, cohort
        )
        reads = {
            "_forge_errands": lambda *_: {},
            "_town_stop_errands": lambda *_: standing,
            "_fetch_item_counts": lambda pairs: {
                ("Lead", COPPER_ORE): 19 for _ in pairs
            },
            "_family_of": lambda *_: (["Lead", "Kin"], "Lead"),
            "_fetch_positions": lambda names: {"Lead": {"map_id": 0}},
            "_nearest_forge": lambda name, focus: spawn,
            "_cohort_key": lambda cohort: None,
        }
        with mock.patch.multiple(bridge, **reads):
            asyncio.run(bridge.Bridge._forge_once(fake))
        return claims

    SPAWN = {"map_id": 0, "x": 1.0, "y": 2.0, "z": 3.0, "radius": 10, "d2": 400.0**2}

    def test_the_leader_walks_to_the_forge_in_town(self):
        claims = self.run_pass({"Lead": SMELT_COPPER}, dict(self.SPAWN))
        self.assertEqual(claims, [("Lead", "at:0:1.0,2.0,3.0")])

    def test_a_forge_out_of_town_is_deferred(self):
        spawn = dict(self.SPAWN, d2=3000.0**2)
        self.assertEqual(self.run_pass({"Lead": SMELT_COPPER}, spawn), [])

    def test_no_standing_craft_is_no_walk(self):
        self.assertEqual(self.run_pass({}, dict(self.SPAWN)), [])


class TheRaidCook(unittest.TestCase):
    def test_a_raid_cook_lights_its_fire_first(self):
        cook = next(s.make for s in raidsupply.SUPPLIES
                    if s.make and s.make.skill == raidsupply.COOKING)
        crafter = mock.Mock(known={cook.spell}, count=lambda _e: 50)
        crafter.name = "Cook"
        step = raidsupply.craft_step(crafter, cook, "Soup", 5, {}, 0)
        self.assertEqual([r.command for r in step.rows][0], "818")
        self.assertEqual([r.command for r in step.rows][1], str(cook.spell))


if __name__ == "__main__":
    unittest.main()
