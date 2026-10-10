"""The step after a class quest take is not held by the class cooldown (2026-10-09).

Brug took The Emblazoned Runeblade at 10:06 and stood by a Runeforge. The class
cooldown (10 minutes) and the 15 minute cycle put the sword's use after the time
he had wandered off the platform and into a fight on the ground. A take that went
through frees the next class step; the pass after it comes in FOLLOW_UP_SECONDS.
"""

import asyncio
import time
import unittest
from unittest import mock

import classquest
import guildjobs
from test_guildsocial_bridge import bridge
from test_classquest_use_here import SWORD, carried, knight, runeblade


def row(command, age, status="delivered", walk=False):
    source = classquest.ACTION + ("-walk" if walk else "")
    return {
        "target_name": "Brug",
        "command": command,
        "source": guildjobs.source_for(source, "Brug"),
        "status": status,
        "age": age,
        "result": "",
    }


def recent(*rows):
    return guildjobs.recent_from_rows(list(rows))


class TheStepAfterATake(unittest.TestCase):
    def step(self, rows, **over):
        member = knight(carried=carried((SWORD, 1)), **over)
        return guildjobs.class_step(member, runeblade(), rows, 5000)[0]

    def test_a_take_three_minutes_ago_does_not_hold_the_use(self):
        step = self.step(recent(row("take quest:12619", 3)))
        self.assertIsNotNone(step)
        self.assertTrue(step.rows[0].command.startswith("use-item-here"))

    def test_a_walk_three_minutes_ago_still_holds(self):
        rows = recent(row("walk-to-spawn creature:1 max:20", 3, walk=True))
        self.assertIsNone(self.step(rows))

    def test_a_failed_take_still_holds(self):
        rows = recent(row("take quest:12619", 3, status="error"))
        self.assertIsNone(self.step(rows))

    def test_the_use_itself_holds_the_next_step(self):
        rows = recent(
            row("take quest:12619", 8),
            row("use-item-here item:1", 2, status="unchanged"),
        )
        member = knight()
        self.assertFalse(guildjobs.follows_a_take(member, rows))

    def test_the_waiver_ends(self):
        old = recent(row("take quest:12619", guildjobs.FOLLOW_UP_MINUTES))
        self.assertFalse(guildjobs.follows_a_take(knight(), old))

    def test_another_members_take_does_not_free_this_one(self):
        other = row("take quest:12619", 3)
        other["target_name"] = "Other"
        self.assertFalse(guildjobs.follows_a_take(knight(), recent(other)))

    def test_the_row_reads_as_a_take(self):
        self.assertTrue(guildjobs.is_take_row("take quest:12619"))
        self.assertFalse(guildjobs.is_take_row("abandon quest:12619"))
        self.assertFalse(guildjobs.is_take_row("walk-to-spawn creature:1"))

    def test_an_abandon_frees_the_retake(self):
        rows = recent(row("abandon quest:12619", 2))
        self.assertTrue(guildjobs.follows_a_take(knight(), rows))

    def test_a_refused_abandon_does_not(self):
        rows = recent(row("abandon quest:12619", 2, status="error"))
        self.assertFalse(guildjobs.follows_a_take(knight(), rows))

    def test_the_chain_rows(self):
        self.assertTrue(guildjobs.is_chain_row("take quest:12619"))
        self.assertTrue(guildjobs.is_chain_row("abandon quest:12619"))
        self.assertFalse(guildjobs.is_chain_row("turnin quest:12619"))


class TheTakeIsInTheLog(unittest.TestCase):
    """The saved quest log trails a take (2026-10-09): the pass after Brug's take
    read a log without the quest and sent him to take it again."""

    def step(self, rows):
        member = knight(quest_log={}, quests_done=frozenset({12593}))
        return guildjobs.class_step(member, runeblade(), rows, 5000)[0]

    def test_a_take_minutes_ago_goes_on_to_the_next_link(self):
        # Not a second take: the take hands nothing over (#702), so the next
        # link is the Battle-worn Sword chest, then the Runeforge.
        step = self.step(recent(row("take quest:12619", 2)))
        self.assertEqual(step.rows[0].command, "use-gameobject 190584")

    def test_without_the_take_it_is_taken(self):
        step = self.step(())
        self.assertEqual(step.rows[0].command, "take quest:12619")

    def test_a_drop_after_the_take_is_not_undone(self):
        rows = recent(row("take quest:12619", 8), row("abandon quest:12619", 2))
        member = guildjobs.with_recent_takes(
            knight(quest_log={}, quests_done=frozenset({12593})), rows
        )
        self.assertNotIn(12619, member.quest_log)

    def test_a_take_after_a_drop_is_in(self):
        rows = recent(row("abandon quest:12619", 8), row("take quest:12619", 2))
        member = guildjobs.with_recent_takes(
            knight(quest_log={}, quests_done=frozenset({12593})), rows
        )
        self.assertEqual(member.quest_log[12619], classquest.STATUS_INCOMPLETE)


class _Loop:
    """The Bridge methods that pace the jobs loop and run a step, nothing else."""

    def __init__(self):
        self._job_steps = {}


for _name in (
    "_follow_up_event",
    "_note_follow_up",
    "_sleep_until_next_pass",
    "_run_job_step",
    "_run_step_row",
):
    setattr(_Loop, _name, getattr(bridge.Bridge, _name))


def step_of(*commands, action=classquest.ACTION):
    rows = tuple(
        guildjobs.guildcorps.Row("quest", c, "", "guildjobs:classquest:Brug")
        for c in commands
    )
    return guildjobs.guildcorps.Step("Brug", action, 12619, "Brug acts", rows=rows)


class TheLoopWakesForAChainRow(unittest.TestCase):
    """The steps run as tasks after the pass returns (2026-10-09): the take a
    follow-up waits for answers while the loop already sleeps."""

    def test_a_step_that_lands_during_the_sleep_wakes_it(self):
        loop = _Loop()

        async def scenario():
            async def step_lands():
                await asyncio.sleep(0.02)
                loop._note_follow_up()

            started = time.monotonic()
            await asyncio.gather(loop._sleep_until_next_pass(5.0), step_lands())
            return time.monotonic() - started

        with mock.patch.object(guildjobs, "FOLLOW_UP_SECONDS", 0.01):
            took = asyncio.run(scenario())
        self.assertLess(took, 1.0)
        self.assertEqual(loop._follow_ups, 1)

    def test_with_nothing_landed_it_sleeps_the_cycle(self):
        loop = _Loop()
        started = time.monotonic()
        asyncio.run(loop._sleep_until_next_pass(0.05))
        self.assertGreaterEqual(time.monotonic() - started, 0.04)
        self.assertEqual(loop._follow_ups, 0)

    def test_early_passes_are_capped_per_cycle(self):
        loop = _Loop()
        slept = []

        async def nap(seconds):
            slept.append(seconds)

        async def scenario():
            loop._follow_ups = guildjobs.FOLLOW_UPS_PER_CYCLE
            loop._note_follow_up()
            with mock.patch.object(bridge.asyncio, "sleep", nap):
                await loop._sleep_until_next_pass(900.0)

        asyncio.run(scenario())
        self.assertEqual(slept, [900.0])
        self.assertEqual(loop._follow_ups, 0)

    def run_step(self, step, answers=True):
        loop = _Loop()

        async def row(this_step, this_row, cap):
            return answers

        loop._run_step_row = row
        asyncio.run(loop._run_job_step(step, 5000.0))
        return loop._follow_up_event().is_set()

    def test_a_take_that_went_through_wakes_the_loop(self):
        self.assertTrue(self.run_step(step_of("take quest:12619")))

    def test_an_abandon_that_went_through_wakes_the_loop(self):
        self.assertTrue(self.run_step(step_of("abandon quest:12619")))

    def test_a_take_that_failed_does_not(self):
        self.assertFalse(self.run_step(step_of("take quest:12619"), answers=False))

    def test_a_use_that_went_through_wakes_the_loop(self):
        self.assertTrue(self.run_step(step_of("use-gameobject 190584")))
        self.assertTrue(self.run_step(step_of("use-item-here item:38607")))

    def test_a_use_that_failed_does_not(self):
        self.assertFalse(self.run_step(step_of("use-gameobject 190584"), answers=False))

    def test_a_job_step_does_not(self):
        self.assertFalse(self.run_step(step_of("2964", action="job")))

    def test_a_recall_home_wakes_the_loop(self):
        loop = _Loop()

        async def home(step, row):
            return True

        loop._recall_row = home
        recall = guildjobs.guildcorps.Row(
            "hearth", "recall", "", "guildjobs:hearth:Brug"
        )
        went = asyncio.run(loop._run_step_row(step_of(), recall, 5000.0))
        self.assertTrue(went)
        self.assertTrue(loop._follow_up_event().is_set())


if __name__ == "__main__":
    unittest.main()
