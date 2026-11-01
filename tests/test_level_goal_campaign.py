"""Execute the real level strategy adapter while dungeon ownership changes."""

import ast
import asyncio
import logging
from pathlib import Path
import unittest

import core
import goals


class LevelGoalCampaign(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse(Path("bridge.py").read_text(encoding="utf-8"))
        node = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_goal_strategy"
        )
        self.commands = []
        self.owned = {"Family"}
        self.reads = []
        self.failed = False

        def cohort(name):
            if self.failed:
                raise RuntimeError("roster unavailable")
            return {"Mage": "Family", "Other": "OtherFamily"}.get(name)

        def owns(family, dungeon):
            self.reads.append((family, dungeon))
            return family in self.owned

        namespace = dict(
            asyncio=asyncio,
            core=core,
            goals=goals,
            _cohort_of=cohort,
            _queue_owns_job=owns,
            _insert_command=self.commands.append,
            log=logging.getLogger(__name__),
        )
        module = ast.Module(body=[node], type_ignores=[])
        exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
        self.strategy = namespace["_goal_strategy"]
        self.row = dict(
            id=1,
            character_name="Mage",
            kind="level",
            status="active",
            target=46,
            last_report="45/4",
        )

    async def apply(self, row=None, observed=45):
        row = row or self.row
        actions = goals.reconcile(row, observed)
        for action in actions:
            if isinstance(action, goals.StrategyCommand):
                await self.strategy(None, row, action)
        return actions

    async def test_stalled_level_goal_does_not_grant_grind(self):
        actions = await self.apply()
        self.assertEqual([], self.commands)
        self.assertEqual([("Family", False)], self.reads)
        self.assertTrue(any(isinstance(a, goals.RecordProgress) for a in actions))

    async def test_first_observation_does_not_grant_grind(self):
        await self.apply(dict(self.row, last_report=""))
        self.assertEqual([], self.commands)

    async def test_other_family_campaign_does_not_suppress_leveling(self):
        await self.apply(dict(self.row, character_name="Other"))
        self.assertEqual(
            [core.InsertCommand("Other", "nc +grind", "overseer:goal")], self.commands
        )

    async def test_ordinary_leveling_and_release_resume_grind(self):
        await self.apply()
        self.owned.clear()
        await self.apply()
        self.assertEqual(
            [core.InsertCommand("Mage", "nc +grind", "overseer:goal")], self.commands
        )
        self.assertEqual("active", self.row["status"])

    async def test_progress_and_completion_still_reconcile(self):
        progress = await self.apply(dict(self.row, last_report="44/0"))
        self.assertTrue(any(isinstance(a, goals.RecordProgress) for a in progress))
        complete = await self.apply(observed=46)
        self.assertTrue(any(isinstance(a, goals.MarkComplete) for a in complete))
        self.assertEqual([], self.commands)

    async def test_roster_failure_does_not_grant_grind(self):
        self.failed = True
        with self.assertRaisesRegex(RuntimeError, "roster unavailable"):
            await self.apply()
        self.assertEqual([], self.commands)


class CampaignGrindWithdrawal(unittest.TestCase):
    def test_every_campaign_member_withdraws_old_grind(self):
        for leads in (False, True):
            for aimed in (False, True):
                for travelling in (False, True):
                    for in_town in (False, True):
                        with self.subTest(
                            leads=leads,
                            aimed=aimed,
                            travelling=travelling,
                            in_town=in_town,
                        ):
                            cmds = goals.life_strategies(
                                leads=leads,
                                aimed=aimed,
                                travelling=travelling,
                                in_town=in_town,
                                campaign=True,
                            )
                            self.assertIn(goals.GRIND_OFF, cmds)
                            self.assertNotIn("nc +grind", cmds)
                            self.assertIn(goals.RETREAT_STRATEGY, cmds)
                            if not leads:
                                self.assertIn("nc +follow", cmds)
                            if travelling and leads:
                                self.assertIn(goals.LIFE_STRATEGY, cmds)

    def test_ordinary_leader_still_grinds(self):
        cmds = goals.life_strategies(leads=True)
        self.assertIn("nc +grind", cmds)
        self.assertNotIn(goals.GRIND_OFF, cmds)
