"""A member on a class trainer walk is busy to every other guild walking pass.

The trainer pass skipped a member another pass had on a walk, but no other pass
skipped a member the trainer pass had walking: the jobs pass, the corps, the
dues, the post, the crafter mail and the social pass each built their busy set
without `_train_walks`. A member sent to its class trainer was handed a second
walk inside the same 45 minutes, which the module refuses, spending the step's
cooldown. bridge.py is read as text, as for the other bridge-only seams.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (HERE / "bridge.py").read_text(encoding="utf-8")


WALKS = 'getattr(self, "_train_walks", ())'


def method(name: str) -> str:
    body = BRIDGE.split("def %s(" % name, 1)[1]
    return body.split("\n    async def ", 1)[0].split("\n    def ", 1)[0]


class TheTrainerWalkIsBusy(unittest.TestCase):
    def test_the_trainer_pass_drops_stale_walks(self):
        body = method("_guild_walkers_busy")
        self.assertIn("guildroute.live_runs", body)
        self.assertIn("guildroute.GUILD_STEP_SECONDS", body)

    def test_every_other_walking_pass_reads_it(self):
        for name in (
            "_guild_dues_once",
            "_crafter_mail_for",
            "_guild_post_for",
            "_guild_corps_once",
            "_start_guild_job_pass",
            "_guild_social_once",
        ):
            with self.subTest(name):
                self.assertIn(WALKS, method(name))


if __name__ == "__main__":
    unittest.main()
