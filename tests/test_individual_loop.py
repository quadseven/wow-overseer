"""An individual family in the profession loop gathers per member (#2498).

The loop keeps the phase order; its GATHER phase hands each member its own
farm target when the family is individual, and one family-wide job when not.
The craft rhythm writes nothing while the loop owns the family.
"""

import asyncio
import os
import pathlib
import types
import unittest
from unittest import mock

from test_family_crafting import FAKE_ASYNCIO, _load, _Log
from test_farm_target import SKILLS, FakeBridge

import individual
import jobs
import profloop

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = {individual.ENV: "Grug"}
GATHER_ROWS = {n: "farm:mining" for n in SKILLS}


class TheGatherPhaseHandsOutMemberTargets(unittest.TestCase):
    def test_an_individual_family_gets_distinct_member_jobs(self):
        got = individual.gather_targets(GATHER_ROWS, SKILLS, "Grug", "farm:mining", ENV)
        self.assertEqual(got["Ugga"], "farm:herbalism")
        self.assertEqual(got["Grug"], "farm:mining")
        self.assertGreater(len(set(got.values())), 1)

    def test_a_member_with_no_node_trade_keeps_the_loops_job(self):
        got = individual.gather_targets(GATHER_ROWS, SKILLS, "Grug", "farm:mining", ENV)
        self.assertEqual(got["Og"], "farm:mining")
        self.assertEqual(got["Bork"], "farm:mining")

    def test_a_family_not_named_stays_family_wide(self):
        got = individual.gather_targets(GATHER_ROWS, SKILLS, "Zug", "farm:mining", ENV)
        self.assertEqual(set(got.values()), {"farm:mining"})
        self.assertEqual(sorted(got), sorted(SKILLS))

    def test_an_item_order_or_quest_is_the_familys_and_goes_to_all(self):
        for job in ("farm:2592", "quest"):
            got = individual.gather_targets(GATHER_ROWS, SKILLS, "Grug", job, ENV)
            self.assertEqual(set(got.values()), {job})

    def test_a_linked_family_stays_family_wide(self):
        rows = dict(GATHER_ROWS, Og="dungeon")
        got = individual.gather_targets(rows, SKILLS, "Grug", "farm:mining", ENV)
        self.assertEqual(set(got.values()), {"farm:mining"})

    def test_a_member_with_its_own_kill_drop_order_gets_it_alone(self):
        # Og is thin on Silk Cloth; nobody else in the family needs it.
        got = individual.gather_targets(
            GATHER_ROWS,
            SKILLS,
            "Grug",
            "farm:4306",
            ENV,
            member_orders={"Og": "farm:4306"},
        )
        self.assertEqual(got["Og"], "farm:4306")
        self.assertEqual(got["Ugga"], "farm:herbalism")
        self.assertEqual(got["Grug"], "farm:mining")

    def test_the_others_keep_their_own_skill_not_the_familys_item(self):
        got = individual.gather_targets(
            GATHER_ROWS,
            SKILLS,
            "Grug",
            "farm:4306",
            ENV,
            member_orders={"Og": "farm:4306"},
        )
        self.assertEqual(
            {n for n, j in got.items() if j == "farm:4306"}, {"Og", "Bork"}
        )

    def test_a_member_order_for_a_family_not_named_is_ignored(self):
        got = individual.gather_targets(
            GATHER_ROWS,
            SKILLS,
            "Zug",
            "farm:mining",
            ENV,
            member_orders={"Og": "farm:4306"},
        )
        self.assertEqual(set(got.values()), {"farm:mining"})

    def test_a_linked_family_ignores_member_orders(self):
        rows = dict(GATHER_ROWS, Og="dungeon")
        got = individual.gather_targets(
            rows,
            SKILLS,
            "Grug",
            "farm:mining",
            ENV,
            member_orders={"Bork": "farm:4306"},
        )
        self.assertEqual(set(got.values()), {"farm:mining"})

    def test_a_member_order_the_job_table_refuses_is_not_used(self):
        got = individual.gather_targets(
            GATHER_ROWS,
            SKILLS,
            "Grug",
            "farm:mining",
            ENV,
            member_orders={"Og": "farm:nonsense"},
        )
        self.assertEqual(got["Og"], "farm:mining")

    def test_a_member_sitting_out_is_left_out(self):
        got = individual.gather_targets(
            GATHER_ROWS, SKILLS, "Grug", "farm:mining", ENV, exempt=("Og",)
        )
        self.assertNotIn("Og", got)


class TheLoopWritesTheTargets(unittest.TestCase):
    def write(self, targets, mode="farm:mining"):
        inserted = []
        ns = _load(
            ["_prof_loop_write"],
            {
                "asyncio": FAKE_ASYNCIO,
                "jobs": jobs,
                "log": _Log(),
                "profloop": profloop,
                "_insert_job": lambda n, m, s: inserted.append((n, m)),
            },
        )
        me = types.SimpleNamespace()
        asyncio.run(ns["_prof_loop_write"](me, "Grug", sorted(SKILLS), mode, targets))
        return dict(inserted)

    def test_each_member_is_written_its_own_job(self):
        targets = individual.gather_targets(
            GATHER_ROWS, SKILLS, "Grug", "farm:mining", ENV
        )
        got = self.write(targets)
        self.assertEqual(got["Ugga"], "farm:herbalism")
        self.assertEqual(got["Grug"], "farm:mining")

    def test_without_targets_every_member_gets_the_one_job(self):
        got = self.write(None)
        self.assertEqual(set(got.values()), {"farm:mining"})
        self.assertEqual(sorted(got), sorted(SKILLS))

    def test_the_pass_asks_for_targets_only_in_the_gather_phase(self):
        text = (ROOT / "bridge.py").read_text(encoding="utf-8")
        a = text.index("    async def _prof_loop_for(")
        body = text[a : text.index("    async def _prof_loop_facts(", a)]
        self.assertIn("profloop.GATHER", body)
        self.assertLess(body.index("gather_targets("), body.index("_prof_loop_write("))
        self.assertIn("member_orders=facts.member_orders", body)


def _run_farm_individual(phase):
    world = FakeBridge(GATHER_ROWS)
    inserted = world.inserted
    ns = _load(
        ["_farm_individual"],
        {
            "asyncio": FAKE_ASYNCIO,
            "individual": individual,
            "jobs": jobs,
            "log": _Log(),
            "time": __import__("time"),
            "FARM_SOURCE": "overseer:farm",
            "FARM_RETELL_SECONDS": 300.0,
            "_individual_family": lambda c=None: "Grug",
            "_standing_jobs": lambda key=None: dict(world.rows),
            "_queue_owns_job": lambda fam=None, dungeon=False: False,
            "_fetch_trade_skills": lambda names: {n: SKILLS[n] for n in names},
            "_insert_job": lambda name, mode, source: inserted.append((name, mode)),
            "_family_leader": lambda c=None: "Grug",
            "_standin_out": frozenset,
            "_prof_loop_family": lambda key=None: "Grug",
            "_PROF_LOOPS": {"Grug": profloop.State(phase=phase)},
            "profloop": profloop,
        },
    )
    with mock.patch.dict(os.environ, ENV):
        handed = asyncio.run(ns["_farm_individual"](world, None))
    return world, handed


class TheMemberFarmPassRunsUnderTheLoopOnlyInGather(unittest.TestCase):
    def test_in_gather_the_members_are_farmed_each_for_itself(self):
        world, handled = _run_farm_individual(profloop.GATHER)
        self.assertTrue(handled)
        self.assertEqual(world.inserted, [("Ugga", "farm:herbalism")])
        self.assertTrue(world.passes)

    def test_in_any_other_phase_the_family_is_handed_back(self):
        for phase in (profloop.CRAFT, profloop.TOWN, profloop.TRAIN):
            world, handled = _run_farm_individual(phase)
            self.assertFalse(handled)
            self.assertEqual((world.inserted, world.passes), ([], []))


class TheRhythmStaysSilentUnderTheLoop(unittest.TestCase):
    JOBS = {
        "Oz": "quest",
        "Uzza": "train",
        "Zork": "quest",
        "Zrog": "fish",
        "Zug": "quest",
    }

    def run_rhythm(self, looped):
        from test_individual_drives import HORDE, MixedFamily, _individual_rhythm

        world = MixedFamily(self.JOBS, linen=30)
        me, once = _individual_rhythm(world, _Log())
        once.__globals__.update(
            {
                "_prof_loop_family": lambda key=None: "Zug" if looped else "",
                "_PROF_LOOPS": {"Zug": profloop.State(phase=profloop.CRAFT)},
                "profloop": profloop,
                "dataclasses": __import__("dataclasses"),
            }
        )
        with mock.patch.dict(os.environ, {individual.ENV: "Zug"}):
            asyncio.run(once(me, HORDE))
        return world

    def test_under_the_loop_no_member_job_is_written(self):
        self.assertEqual([], self.run_rhythm(True).jobs)

    def test_without_the_loop_the_individual_path_still_writes(self):
        self.assertEqual(
            [("Oz", "craft", "overseer:craft_rhythm")], self.run_rhythm(False).jobs
        )


if __name__ == "__main__":
    unittest.main()
