"""A death knight stranded in its starting zone is not held busy (2026-10-08).

Cave's Brug had no row for two and a half hours although the planner, given the
same facts, gives him a step: the passes that mark a member busy (a gear
hand-over run, a crafter walk, a guild run) name a character that can reach
nobody and hold it for good. The bridge frees such a knight, keeping only the
step it is itself running, and logs the sets that held it. bridge.py is
read as text by the tests, as for the other bridge-only seams.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


class TheFreedKnight(unittest.TestCase):
    def test_the_pass_subtracts_the_freed_knights_from_busy(self):
        self.assertIn("busy -= self._stranded_knights_freed(members)", BRIDGE)

    def test_only_a_knight_in_its_start_zone_not_on_its_own_step_is_freed(self):
        body = BRIDGE.split("def _stranded_knights_freed", 1)[1].split(
            "async def _plan_guild_jobs", 1
        )[0]
        self.assertIn("classquest.DEATH_KNIGHT", body)
        self.assertIn("classquest.DEATH_KNIGHT_START_MAP", body)
        self.assertIn("m.name not in self._job_steps", body)

    def test_the_sets_that_held_it_are_logged(self):
        body = BRIDGE.split("def _stranded_knights_freed", 1)[1]
        for word in ("guild run", "hand-over run", "crafter walk"):
            self.assertIn(word, body)


if __name__ == "__main__":
    unittest.main()
