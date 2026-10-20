"""A battleground queue holds its member from the moment it goes through (#913).

The PvP pass holds a member it reads as inside or waiting (Move.holds), and
the social pass leaves held members out of its dungeon asks. A member the jobs
pass had just queued was held only from the next PvP pass's read, about 15
minutes later: on 2026-10-20 the social pass asked Hoofhearted, 3 minutes into
an Arathi Basin queue, to Shadowfang Keep, and run 1960 was refused ("is
waiting in a battleground queue"). The step runner now holds the member as
soon as its queue row is answered.
"""

import asyncio
import unittest

import guildjobs
import pvpgear
from test_guildsocial_bridge import bridge


class _Loop:
    """The Bridge methods that run a job step, nothing else."""

    def __init__(self):
        self._job_steps = {}


for _name in ("_follow_up_event", "_note_follow_up", "_run_job_step"):
    setattr(_Loop, _name, getattr(bridge.Bridge, _name))


def step_of(command, action=pvpgear.ACTION, holder="Hoofhearted"):
    row = guildjobs.guildcorps.Row("guild", command, "", "guildjobs:pvp:" + holder)
    return guildjobs.guildcorps.Step(holder, action, 0, holder + " acts", rows=(row,))


def run_step(step, answers=True, held=None):
    loop = _Loop()
    if held is not None:
        loop._pvp_held = held

    async def row(this_step, this_row, cap):
        return answers

    loop._run_step_row = row
    asyncio.run(loop._run_job_step(step, 5000.0))
    return getattr(loop, "_pvp_held", {})


class AQueueHoldsItsMemberAtOnce(unittest.TestCase):
    def test_a_queue_that_went_through_holds_the_member(self):
        self.assertEqual({"Hoofhearted": True}, run_step(step_of("bg-queue ab")))

    def test_the_hold_joins_the_holds_already_kept(self):
        held = run_step(step_of("bg-queue wsg"), held={"Bluk": True})
        self.assertEqual({"Bluk": True, "Hoofhearted": True}, held)

    def test_a_queue_that_failed_holds_nobody(self):
        self.assertEqual({}, run_step(step_of("bg-queue ab"), answers=False))

    def test_a_pvp_step_that_is_not_a_queue_holds_nobody(self):
        self.assertEqual({}, run_step(step_of("buy item:16000")))

    def test_another_action_holds_nobody(self):
        self.assertEqual({}, run_step(step_of("bg-queue ab", action="gear")))

    def test_the_queue_row_is_the_one_pvpgear_writes(self):
        aim = pvpgear.Aim(
            "Hoofhearted", "Horde", 29, 0, "", 300, 46,
            pvpgear.BATTLEGROUNDS["ab"], "", "horde",
        )  # fmt: skip
        self.assertTrue(pvpgear.is_queue_row(pvpgear.queue_command(aim)))
        self.assertFalse(pvpgear.is_queue_row("bg-leave ab"))


if __name__ == "__main__":
    unittest.main()
