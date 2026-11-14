"""Per-member farm targets and the individual farm pass (#2498).

The pure rules are plain unit tests. The bridge half loads the real
`_farm_individual` out of bridge.py and runs it against fake adapters, so the
order of the stand-downs and the writes is what is tested.
"""

import asyncio
import os
import pathlib
import time
import unittest
from unittest import mock

from test_family_crafting import FAKE_ASYNCIO, _load, _Log

import farmjob
import individual
import jobs

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = {individual.ENV: "Grug"}

# The five members' skills.
SKILLS = {
    "Grog": {"mining": 8},
    "Grug": {"mining": 28, "blacksmithing": 23},
    "Bork": {"skinning": 14, "leatherworking": 57},
    "Ugga": {"herbalism": 199, "alchemy": 84},
    "Og": {"tailoring": 155},
}


class TheMemberTargetIsItsOwn(unittest.TestCase):
    def test_a_miner_is_sent_mining(self):
        self.assertEqual(
            farmjob.target_for({"mining": 28, "blacksmithing": 23}), "farm:mining"
        )

    def test_a_herbalist_is_sent_herbalism(self):
        self.assertEqual(
            farmjob.target_for({"herbalism": 199, "alchemy": 84}), "farm:herbalism"
        )

    def test_a_member_with_two_gathering_trades_takes_the_lower(self):
        self.assertEqual(
            farmjob.target_for({"mining": 150, "herbalism": 20}), "farm:herbalism"
        )

    def test_a_trade_with_nothing_left_to_give_is_passed_over(self):
        self.assertEqual(
            farmjob.target_for({"mining": 900, "herbalism": 20}), "farm:herbalism"
        )
        self.assertEqual(farmjob.target_for({"mining": 900}), "")

    def test_a_member_with_no_gathering_trade_has_no_target(self):
        self.assertEqual(farmjob.target_for({"skinning": 14, "leatherworking": 57}), "")
        self.assertEqual(farmjob.target_for({"tailoring": 155}), "")
        self.assertEqual(farmjob.target_for(None), "")


class EachMemberIsMovedToItsOwnOrder(unittest.TestCase):
    ALL_MINING = {n: "farm:mining" for n in SKILLS}

    def moves(self, rows, **kw):
        return individual.farm_retargets(rows, SKILLS, "Grug", environ=ENV, **kw)

    def test_only_the_herbalist_changes_when_everyone_was_told_mining(self):
        self.assertEqual(self.moves(self.ALL_MINING), {"Ugga": "farm:herbalism"})

    def test_a_member_with_no_node_trade_is_left_to_end_its_own_order(self):
        got = self.moves(self.ALL_MINING)
        self.assertNotIn("Bork", got)
        self.assertNotIn("Og", got)

    def test_an_item_order_is_never_rewritten(self):
        rows = dict(self.ALL_MINING, Ugga="farm:13463")
        self.assertEqual(self.moves(rows), {})

    def test_a_member_not_farming_is_not_moved(self):
        rows = dict(self.ALL_MINING, Ugga="quest")
        self.assertEqual(self.moves(rows), {})

    def test_a_member_sitting_out_to_craft_keeps_its_job(self):
        self.assertEqual(self.moves(self.ALL_MINING, exempt={"Ugga"}), {})

    def test_a_linked_family_is_not_moved(self):
        rows = dict(self.ALL_MINING, Og="dungeon")
        self.assertEqual(self.moves(rows), {})

    def test_a_family_not_named_is_not_moved(self):
        got = individual.farm_retargets(self.ALL_MINING, SKILLS, "Grug", environ={})
        self.assertEqual(got, {})

    def test_the_farmers_are_the_members_on_a_farm_job(self):
        rows = {"Grug": "farm:mining", "Ugga": "farm:13463", "Og": "quest"}
        self.assertEqual(
            individual.farm_members(rows, "Grug", environ=ENV), ("Grug", "Ugga")
        )
        self.assertEqual(individual.farm_members(rows, "Grug", environ={}), ())


class AMemberIsAFamilyOfOne(unittest.TestCase):
    def test_the_leader_shares_the_familys_slot_and_the_rest_hold_their_own(self):
        lead = individual.solo_of("Grug", "Grug", "Grug", None)
        other = individual.solo_of("Grog", "Grug", "Grug", None)
        self.assertIsNone(lead.slot_key)
        self.assertEqual(other.slot_key, "solo:Grog")
        self.assertEqual(other.names, ("Grog",))
        self.assertTrue(other.solo)

    def test_another_familys_leader_shares_that_familys_slot(self):
        lead = individual.solo_of("Zug", "Zug", "Zug", "Zug")
        self.assertEqual(lead.slot_key, "Zug")
        self.assertNotEqual(lead.key, "Zug")


class FakeBridge:
    """The adapters `_farm_individual` reads and writes through."""

    def __init__(self, rows, held=(), queue=False, mid_run=False):
        self.rows = dict(rows)
        self.held = set(held)
        self.queue = queue
        self.run = mid_run
        self.inserted = []
        self.passes = []
        self._farm_state = {"solo:Og": {"job": "farm:mining"}}

    async def _operator_held(self, keys, writer):
        return set(keys) & self.held

    async def _mid_run(self, names):
        return self.run

    async def _farm_once(self, solo):
        self.passes.append(solo)


def run_individual(world, cohort=None, family="Grug"):
    inserted = world.inserted
    ns = _load(
        ["_farm_individual"],
        {
            "asyncio": FAKE_ASYNCIO,
            "individual": individual,
            "jobs": jobs,
            "log": _Log(),
            "time": time,
            "FARM_SOURCE": "overseer:farm",
            "FARM_RETELL_SECONDS": 300.0,
            "_individual_family": lambda c=None: family,
            "_standing_jobs": lambda key=None: dict(world.rows),
            "_queue_owns_job": lambda fam=None, dungeon=False: world.queue,
            "_fetch_trade_skills": lambda names: {n: SKILLS[n] for n in names},
            "_insert_job": lambda name, mode, source: inserted.append((name, mode)),
            "_family_leader": lambda c=None: "Grug",
            "_standin_out": frozenset,
        },
    )
    return asyncio.run(ns["_farm_individual"](world, cohort))


class TheBridgeFarmsEachMemberItself(unittest.TestCase):
    ROWS = {n: "farm:mining" for n in SKILLS}

    def setUp(self):
        patch = mock.patch.dict(os.environ, ENV)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_herbalist_is_moved_and_the_others_each_get_their_own_pass(self):
        world = FakeBridge(self.ROWS)
        self.assertTrue(run_individual(world))
        self.assertEqual(world.inserted, [("Ugga", "farm:herbalism")])
        passed = sorted(s.leader for s in world.passes)
        self.assertEqual(passed, ["Bork", "Grog", "Grug", "Og"])

    def test_a_moved_member_is_not_run_until_its_new_job_lands(self):
        world = FakeBridge(self.ROWS)
        run_individual(world)
        self.assertNotIn("Ugga", [s.leader for s in world.passes])

    def test_the_same_order_is_not_queued_twice_in_a_row(self):
        world = FakeBridge(self.ROWS)
        run_individual(world)
        run_individual(world)
        self.assertEqual(world.inserted, [("Ugga", "farm:herbalism")])

    def test_an_operator_hold_writes_and_walks_nobody(self):
        world = FakeBridge(self.ROWS, held={"Grug"})
        self.assertTrue(run_individual(world))
        self.assertEqual((world.inserted, world.passes), ([], []))

    def test_a_campaign_queue_or_a_run_writes_and_walks_nobody(self):
        for kw in ({"queue": True}, {"mid_run": True}):
            world = FakeBridge(self.ROWS, **kw)
            self.assertTrue(run_individual(world))
            self.assertEqual((world.inserted, world.passes), ([], []))

    def test_a_linked_family_is_handed_back_to_the_family_pass(self):
        world = FakeBridge(dict(self.ROWS, Og="dungeon"))
        self.assertFalse(run_individual(world))
        self.assertEqual((world.inserted, world.passes), ([], []))

    def test_a_family_not_named_is_handed_back(self):
        world = FakeBridge(self.ROWS)
        self.assertFalse(run_individual(world, family="Zug"))

    def test_a_member_that_stopped_farming_loses_its_state(self):
        world = FakeBridge(dict(self.ROWS, Og="quest"))
        run_individual(world)
        self.assertNotIn("solo:Og", world._farm_state)

    def test_the_leader_walks_through_the_familys_slot(self):
        world = FakeBridge(self.ROWS)
        run_individual(world)
        slots = {s.leader: s.slot_key for s in world.passes}
        self.assertIsNone(slots["Grug"])
        self.assertEqual(slots["Grog"], "solo:Grog")


class TheBridgeAsksTheGate(unittest.TestCase):
    text = (ROOT / "bridge.py").read_text(encoding="utf-8")

    def body(self, start, end):
        a = self.text.index(start)
        return self.text[a : self.text.index(end, a)]

    def test_the_farm_pass_hands_an_individual_family_to_the_member_pass(self):
        body = self.body("    async def _farm_once(", "    async def _farm_individual(")
        self.assertIn("_farm_individual(cohort)", body)
        self.assertLess(
            body.index("_farm_individual(cohort)"), body.index("_farm_job_now(cohort)")
        )

    def test_a_members_walk_is_claimed_for_that_member_alone(self):
        body = self.body("    async def _farm_walk(", "    async def _end_farm(")
        self.assertIn("traveller=leader if solo else None", body)

    def test_the_door_reads_the_named_traveller_as_the_leader(self):
        body = self.body(
            "    async def _claim_town_slot(", "    def _cohort_town_slot("
        )
        self.assertIn("if traveller:\n            leader = traveller", body)
        self.assertIn("_death_disc_refusal", body)

    def test_a_member_pass_reads_only_its_own_row(self):
        body = self.body(
            "    async def _farm_job_now(", "    async def _farm_state_for("
        )
        self.assertIn('getattr(cohort, "solo", False)', body)
        self.assertNotIn("individual.farm_cohort", body)


if __name__ == "__main__":
    unittest.main()
