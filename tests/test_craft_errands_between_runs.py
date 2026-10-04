"""A family on a campaign job gets its craft errand written (2026-10-04).

mod-overseer#832 lets DriveCraft cast between runs for 'town run' and dungeon
jobs. The bridge wrote craft errands only for job 'craft', so the Horde
family on a dungeon job had none to cast.
"""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TheCraftingRosterIncludesCampaignJobs(unittest.TestCase):
    def test_the_query_names_every_campaign_job(self):
        source = (ROOT / "bridge.py").read_text(encoding="utf-8")
        body = source[source.index("def _crafting_roster(") :]
        body = body[: body.index("\ndef ")]
        for job in ('"craft"', '"town run"', '"dungeon"', '"dungeon:%"'):
            self.assertIn(job, body)
        self.assertIn("job LIKE %s", body)


if __name__ == "__main__":
    unittest.main()
