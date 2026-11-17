"""Grouping up for an instance step of an individual farm (#2498, slice 3).

The pure rule is a plain unit test. The bridge half loads the real
`_farm_group_up` and reads the real `_farm_once` text, and runs the first
against fake adapters, so the order of the reads, the queue write and the
refusals is what is tested.
"""

import asyncio
import pathlib
import types
import unittest

from test_family_crafting import FAKE_ASYNCIO, _load, _Log

import campaignqueue
import council
import farmjob
import individual
import jobs

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEADMINES_MAP = 36
WAILING_MAP = 43
DOORS = {DEADMINES_MAP: "deadmines", WAILING_MAP: "wailing"}


def door(map_id):
    return DOORS.get(int(map_id), "")


class AMaterialOnlyADungeonGivesNeedsThatDungeon(unittest.TestCase):
    def need(self, drops, item=2318, spawns=(), creatures=()):
        return farmjob.instance_door(item, spawns, creatures, drops, door)

    def test_a_material_only_a_dungeon_drops_names_its_door(self):
        self.assertEqual(self.need([(DEADMINES_MAP, 12.0)]), "deadmines")

    def test_the_best_drop_chance_picks_among_dungeons(self):
        got = self.need([(DEADMINES_MAP, 8.0), (WAILING_MAP, 30.0)])
        self.assertEqual(got, "wailing")

    def test_a_node_anywhere_means_no_instance_is_needed(self):
        spawn = types.SimpleNamespace(map_id=1)
        self.assertEqual(self.need([(DEADMINES_MAP, 12.0)], spawns=[spawn]), "")

    def test_a_creature_the_leader_can_reach_means_no_instance_is_needed(self):
        creature = types.SimpleNamespace(map_id=1)
        self.assertEqual(self.need([(DEADMINES_MAP, 12.0)], creatures=[creature]), "")

    def test_an_open_world_drop_keeps_the_family_outdoors(self):
        self.assertEqual(self.need([(DEADMINES_MAP, 12.0), (1, 9.0)]), "")

    def test_a_faint_open_world_drop_does_not_keep_the_family_outdoors(self):
        self.assertEqual(self.need([(DEADMINES_MAP, 12.0), (1, 0.2)]), "deadmines")

    def test_a_faint_dungeon_drop_is_no_reason_to_enter(self):
        self.assertEqual(self.need([(DEADMINES_MAP, 0.2)]), "")

    def test_a_map_the_overseer_has_no_door_for_is_left_alone(self):
        self.assertEqual(self.need([(999, 50.0)]), "")

    def test_a_skill_order_never_needs_an_instance(self):
        self.assertEqual(self.need([(DEADMINES_MAP, 12.0)], item=0), "")

    def test_nothing_known_to_drop_it_needs_nothing(self):
        self.assertEqual(self.need([]), "")

    def test_the_real_front_door_table_is_what_the_bridge_asks(self):
        got = farmjob.instance_door(
            2318, (), (), [(DEADMINES_MAP, 12.0)], council.front_door
        )
        self.assertEqual(got, "deadmines")
        self.assertIn(got, jobs.PORTAL_KEYWORDS)


class TheSplitRosterTrap(unittest.TestCase):
    """Jobs are family-wide: a split roster stands the family drives down."""

    ENV = {individual.ENV: "Grug"}
    MIXED = {"Grug": "farm:2318", "Ugga": "farm:herbalism", "Og": "quest"}
    GROUPED = {n: "dungeon:deadmines" for n in MIXED}

    def test_individual_members_may_hold_different_farm_jobs(self):
        self.assertTrue(individual.active(self.MIXED, "Grug", self.ENV))

    def test_once_the_run_lands_the_whole_family_is_linked_and_agrees(self):
        self.assertTrue(individual.linked(self.GROUPED))
        got = individual.members_on(
            self.GROUPED, {"dungeon:deadmines"}, "Grug", self.ENV
        )
        self.assertEqual(got, ("Grug", "Og", "Ugga"))

    def test_a_half_landed_run_links_the_family_and_the_old_rule_waits(self):
        half = dict(self.MIXED, Og="dungeon:deadmines")
        self.assertTrue(individual.linked(half))
        self.assertEqual(
            individual.members_on(half, {"farm:2318"}, "Grug", self.ENV), ()
        )
        self.assertEqual(individual.farm_members(half, "Grug", self.ENV), ())


class FakeWorld:
    def __init__(self, drops, queued=False, level=60, roster_has_family=True):
        self.drops = drops
        self.queued = queued
        self.level = level
        self.family = roster_has_family
        self.writes = []
        self.reads = 0
        self.kicked = 0

    async def _campaign_queue_once(self):
        self.kicked += 1


def run_group_up(world, got=None, item=2318, family="Grug"):
    def drops(entry):
        world.reads += 1
        return world.drops

    roster = (
        [
            {
                "name": n,
                "family": family,
                "enabled": 1,
                "lead": int(n == "Grug"),
                "job": "farm:%d" % item,
            }
            for n in ("Grug", "Ugga")
        ]
        if world.family
        else []
    )

    def write(plan, source, ids=None):
        world.writes.append(
            (plan.family, [(e.keyword, e.runs) for e in plan.entries], source)
        )
        return len(plan.entries)

    ns = _load(
        ["_farm_group_up"],
        {
            "asyncio": FAKE_ASYNCIO,
            "farmjob": farmjob,
            "campaignqueue": campaignqueue,
            "council": council,
            "log": _Log(),
            "FARM_SOURCE": "overseer:farm",
            "_farm_item_drops": drops,
            "_queue_owns_job": lambda fam=None, dungeon=False: world.queued,
            "_fetch_queue_roster": lambda: roster,
            "_queue_level_rows": lambda fam: [
                {
                    "name": n,
                    "level": world.level,
                    "lead": int(n == "Grug"),
                    "race": 1,
                    "map_id": 0,
                }
                for n in fam["names"]
            ],
            "_write_queue": write,
        },
    )
    cohort = individual.solo_of("Grug", family, "Grug", None)
    got = got if got is not None else {"spawns": [], "creatures": []}
    return asyncio.run(ns["_farm_group_up"](world, cohort, item, got))


class TheBridgeGroupsTheFamilyUp(unittest.TestCase):
    def test_a_dungeon_only_material_queues_the_dungeon_for_the_family(self):
        world = FakeWorld([(DEADMINES_MAP, 12.0)])
        self.assertTrue(run_group_up(world))
        self.assertEqual(
            world.writes,
            [("Grug", [("deadmines", farmjob.INSTANCE_RUNS)], "overseer:farm")],
        )
        self.assertEqual(world.kicked, 1, "the queue is started at once")

    def test_a_queue_already_pending_is_not_replaced(self):
        world = FakeWorld([(DEADMINES_MAP, 12.0)], queued=True)
        self.assertFalse(run_group_up(world))
        self.assertEqual(world.writes, [])

    def test_a_door_the_family_is_too_low_for_writes_nothing(self):
        world = FakeWorld([(DEADMINES_MAP, 12.0)], level=1)
        self.assertFalse(run_group_up(world))
        self.assertEqual((world.writes, world.kicked), ([], 0))

    def test_an_outdoor_source_asks_the_database_nothing(self):
        world = FakeWorld([(DEADMINES_MAP, 12.0)])
        got = {"spawns": [object()], "creatures": []}
        self.assertFalse(run_group_up(world, got))
        self.assertEqual((world.reads, world.writes), (0, []))

    def test_a_skill_order_asks_the_database_nothing(self):
        world = FakeWorld([(DEADMINES_MAP, 12.0)])
        self.assertFalse(run_group_up(world, item=0))
        self.assertEqual((world.reads, world.writes), (0, []))

    def test_a_family_the_roster_does_not_hold_writes_nothing(self):
        world = FakeWorld([(DEADMINES_MAP, 12.0)], roster_has_family=False)
        self.assertFalse(run_group_up(world))
        self.assertEqual(world.writes, [])


class TheFarmPassGroupsUpOnlyAfterEndingTheOrder(unittest.TestCase):
    text = (ROOT / "bridge.py").read_text(encoding="utf-8")

    def body(self, start, end):
        a = self.text.index(start)
        return self.text[a : self.text.index(end, a)]

    def test_only_a_members_ended_order_asks_to_group_up(self):
        body = self.body("    async def _farm_once(", "    async def _farm_individual(")
        self.assertIn("_farm_group_up(cohort, item, got)", body)
        self.assertIn("farmjob.END", body)
        self.assertIn('getattr(cohort, "solo", False)', body)

    def test_the_order_ends_before_the_queue_is_written(self):
        # Ending a member's order writes its default job; the queue must write
        # last, or that write would knock the member off the run.
        body = self.body("    async def _farm_once(", "    async def _farm_individual(")
        self.assertLess(body.index("_farm_act("), body.index("_farm_group_up("))

    def test_the_survey_is_one_grouped_read_of_creature_loot(self):
        body = self.body("def _farm_item_drops(", "\ndef _farm_item_creatures(")
        self.assertIn("GROUP BY c.map", self.text)
        self.assertIn("creature_loot_template", body + self.text)


if __name__ == "__main__":
    unittest.main()
