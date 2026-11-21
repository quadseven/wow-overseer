"""A member a gear fetch has walking is busy to every other walking pass (#2503).

The gear fetch planner (`gearfetch`) sends a holder and a wearer to one
mailbox and holds the first to arrive there. Another pass that hands either
one a second walk spends the step's cooldown, so every pass that builds a busy
set names `_gear_fetch_walks` in it, and the trainer pass drops a fetch past
its stay. bridge.py is read as text, as for the other bridge-only seams.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")

WALKS = 'getattr(self, "_gear_fetch_walks", ())'


def method(name: str) -> str:
    body = BRIDGE.split("def %s(" % name, 1)[1]
    return body.split("\n    async def ", 1)[0].split("\n    def ", 1)[0]


class TheFetchWalkIsBusy(unittest.TestCase):
    def test_the_set_starts_empty(self):
        self.assertIn("self._gear_fetch_walks: dict = {}", BRIDGE)

    def test_the_guild_busy_set_drops_a_fetch_past_its_stay(self):
        body = method("_guild_walkers_busy")
        self.assertIn("guildroute.live_runs", body)
        self.assertIn("gearfetch.MEET_STAY_SECONDS", body)
        self.assertIn("self._gear_fetch_walks", body)

    def test_every_pass_that_builds_a_busy_set_reads_it(self):
        for name in (
            "_gear_routing_walks",
            "_guild_dues_once",
            "_crafter_mail_for",
            "_guild_post_for",
            "_guild_corps_once",
            "_start_guild_job_pass",
            "_guild_social_once",
        ):
            with self.subTest(name):
                self.assertIn(WALKS, method(name))

    def test_the_bridge_imports_the_module(self):
        # Image membership is pinned centrally by test_image_closure.
        self.assertIn("import gearfetch", BRIDGE)


if __name__ == "__main__":
    unittest.main()
