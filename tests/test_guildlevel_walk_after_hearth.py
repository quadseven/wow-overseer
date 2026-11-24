"""A death-loop onward walk waits out the landed hearth's remaining hold."""

import asyncio
import unittest
from unittest import mock

import guildjobs
from test_guildsocial_bridge import bridge


class _Loop:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.inserted = []

    async def _await_corps_answer(self, row_id, seconds):
        return next(self.answers)

    async def _corps_row_again(self, step, row, row_id, detail, walk):
        return False

    def _note_job_walk_unsupported(self, step, row, detail):
        pass


_Loop._job_row = bridge.Bridge._job_row


def loop_step():
    hearth = guildjobs.guildcorps.Row("hearth", "use", "", "guildjobs:hearth:Member")
    walk = guildjobs.guildcorps.Row(
        "job", "walk-to-spawn creature:123 max:100", "", "guildjobs:level:Member"
    )
    return guildjobs.guildcorps.Step(
        "Member",
        "hearth",
        0,
        "Member hearths home to town for a town errand, then walks on to a hub",
        rows=(hearth, walk),
    ), walk


class ADeathLoopHearthWalk(unittest.TestCase):
    def run_walk(self, answers):
        loop = _Loop(answers)
        step, row = loop_step()
        ids = iter(range(1, 10))

        def insert(holder, command_row):
            loop.inserted.append((holder, command_row))
            return next(ids)

        async def to_thread(function, *args):
            return function(*args)

        with (
            mock.patch.object(bridge, "_insert_corps_row", insert),
            mock.patch.object(bridge.guildjobs, "LOOP_HEARTH_WALK_RETRY_SECONDS", 0),
            mock.patch.object(bridge.asyncio, "to_thread", to_thread),
        ):
            result = asyncio.run(loop._job_row(step, row, 5000.0))
        return result, loop

    def held(self):
        return {"status": "error", "detail": "character is held by another verb"}

    def test_walk_is_resent_after_the_hearth_hold_clears(self):
        result, loop = self.run_walk([self.held(), {"status": "applied", "detail": ""}])
        self.assertTrue(result)
        self.assertEqual(len(loop.inserted), 2)

    def test_walk_retry_stops_after_its_bound(self):
        result, loop = self.run_walk([self.held(), self.held(), self.held()])
        self.assertFalse(result)
        self.assertEqual(len(loop.inserted), guildjobs.LOOP_HEARTH_WALK_RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
