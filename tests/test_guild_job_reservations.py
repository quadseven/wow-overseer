"""Guild craft and mail passes leave a member's active job walk alone."""

import ast
import asyncio
import pathlib
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from test_guildcorps import TRAINABLE, VENDORS, held, tailor


class GuildJobReservations(unittest.TestCase):
    def test_every_affected_pass_keeps_the_active_job_holder_busy(self):
        tree = ast.parse(pathlib.Path("bridge.py").read_text())
        member = SimpleNamespace(
            _job_steps={"Tailor": time.monotonic()},
            _dues_walks={},
            _guild_mail_runs={},
            _crafter_walks={},
            _post_walks={},
            _corps_steps={},
        )
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        }
        for name in (
            "_guild_dues_once",
            "_crafter_mail_for",
            "_guild_post_for",
            "_guild_corps_once",
        ):
            with self.subTest(pass_name=name):
                assignment = next(
                    node
                    for node in ast.walk(methods[name])
                    if isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "busy"
                        for target in node.targets
                    )
                )
                expression = compile(ast.Expression(assignment.value), name, "eval")
                self.assertIn("Tailor", eval(expression, {"self": member}))


class CorpsDuringJobWalk(unittest.IsolatedAsyncioTestCase):
    async def test_only_a_free_tailor_starts_the_ready_craft(self):
        from test_guildsocial_bridge import bridge

        t = tailor(
            "Tailor", 21, 75, known=frozenset({3908, 2963}), carried=(held(2589, 19),)
        )
        facts = dict(
            members=[t], family={}, trainable=TRAINABLE, vendors=VENDORS, recent={}
        )
        for reserved, expected in ((True, 0), (False, 1)):
            with self.subTest(job_walk_active=reserved):
                this = SimpleNamespace(
                    _corps_steps={},
                    _dues_walks={},
                    _guild_mail_runs={},
                    _crafter_walks={},
                    _mail_walk_tasks=set(),
                    _job_steps={"Tailor": time.monotonic()} if reserved else {},
                    _guild_walk_cap=lambda: 40,
                    _corps_mailbox_yards=mock.AsyncMock(return_value={}),
                    _run_corps_step=mock.AsyncMock(),
                    _mail_walk_task_done=mock.Mock(),
                )
                with mock.patch.multiple(
                    bridge,
                    _names_of=lambda cohort: ["Tailor"],
                    _fetch_corps_facts=lambda names: facts,
                    _corps_masters_at_mailbox=lambda members: set(),
                    _guild_bag_corps_enabled=lambda: True,
                ):
                    await bridge.Bridge._guild_corps_once(this, cohort="fixture")
                    await asyncio.gather(*this._mail_walk_tasks)
                self.assertEqual(this._run_corps_step.await_count, expected)
