"""A campaign leader is never handed the level grind between errands.

wow-dev 2026-10-03: the life pass granted Grug `nc +grind` every ten minutes
while his job was `dungeon:scarlet-armory`. He fought on alone in Western
Plaguelands, and campaign 72 failed 25 attempts in a row because the reset
waits for him to leave combat.
"""

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import goals  # noqa: E402

LEVEL_GRIND = goals.strategy_for({"kind": "level"})


def _code(name: str) -> str:
    tree = ast.parse((ROOT / "bridge.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(
                (ROOT / "bridge.py").read_text(encoding="utf-8"), node
            )
    raise AssertionError(f"{name} not found in bridge.py")


class CampaignLeaderDoesNotGrind(unittest.TestCase):
    def test_waiting_leader_has_grind_taken_off(self):
        got = goals.life_strategies(leads=True, campaign=True)
        self.assertNotIn(LEVEL_GRIND, got)
        self.assertIn(goals.GRIND_OFF, got)
        self.assertIn(goals.FLEE_STRATEGY, got)

    def test_an_errand_still_walks_the_campaign_leader(self):
        self.assertEqual(
            goals.life_strategies(leads=True, travelling=True),
            goals.life_strategies(leads=True, travelling=True, campaign=True),
        )

    def test_followers_are_unchanged(self):
        for aimed in (True, False):
            self.assertEqual(
                goals.life_strategies(leads=False, aimed=aimed),
                goals.life_strategies(leads=False, aimed=aimed, campaign=True),
            )

    def test_a_leader_waiting_in_town_loses_grind_too(self):
        self.assertIn(goals.GRIND_OFF, goals.life_strategies(leads=True, in_town=True))

    def test_the_life_pass_passes_the_dungeon_job(self):
        code = _code("_give_them_a_life")
        self.assertIn("jobs.is_dungeon_job(mode)", code)
        self.assertIn("campaign=(name in campaigning)", code)


if __name__ == "__main__":
    unittest.main()
