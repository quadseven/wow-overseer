"""The step after a class quest take is not held by the class cooldown (2026-10-09).

Brug took The Emblazoned Runeblade at 10:06 and stood by a Runeforge. The class
cooldown (10 minutes) and the 15 minute cycle put the sword's use after the time
he had wandered off the platform and into a fight on the ground. A take that went
through frees the next class step; the pass after it comes in FOLLOW_UP_SECONDS.
"""

import unittest

import classquest
import guildjobs
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

    def test_the_loop_comes_back_sooner_after_a_take(self):
        import pathlib
        import re

        text = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        loop = re.search(
            r"async def _guild_jobs_loop.*?async def _mail_once", text, re.S
        )
        self.assertIn("guildjobs.FOLLOW_UP_SECONDS", loop.group(0))
        self.assertLess(guildjobs.FOLLOW_UP_SECONDS, 900)


if __name__ == "__main__":
    unittest.main()
