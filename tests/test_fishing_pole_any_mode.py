"""A pole is bought at any counter a member already stands at, on any job
(mod-overseer#530).

Measured 2026-11-17: no roster member owns a fishing pole, and the family jobs
are craft, farm and nothing agreed, never fish. The pole was bought only while
the family stood on job=fish, and the fishing break that reaches job=fish needs
room in every bag, so the purchase waited on a job that never came. A pole costs
23 copper, so a member at a counter that stocks one buys it whatever the job:
no walk is made for it outside job=fish, and nothing is bought for a member who
holds a pole already.

The bridge half is read as TEXT, as test_fishing_pole.py reads it.
"""

import unittest

from test_fishing_pole import _block


class TheBridgeBuysThePoleAtACounterOnAnyJob(unittest.TestCase):
    def setUp(self):
        self.supply = _block("    async def _craft_supply_once(")
        self.poles = _block("    async def _buy_fishing_poles(")

    def test_the_buy_runs_before_the_craft_gate_with_no_walk(self):
        fish = self.supply.index("if mode == craft_supply.FISH_MODE:")
        here = self.supply.index("self._buy_fishing_poles(names, cohort, walk=False)")
        gate = self.supply.index("if mode not in (")
        self.assertLess(fish, here)
        self.assertLess(here, gate)

    def test_a_dungeon_family_shops_for_nothing(self):
        self.assertIn('if not str(mode).startswith("dungeon"):', self.supply)

    def test_the_fish_branch_still_walks_for_the_pole(self):
        self.assertIn("self._buy_fishing_poles(names, cohort)", self.supply)

    def test_a_walk_is_made_only_when_asked_for(self):
        self.assertIn("walk: bool = True", self.poles)
        self.assertIn("if needs and walk:", self.poles)

    def test_a_counter_that_stocks_nothing_is_not_logged_off_the_fish_job(self):
        self.assertIn("if note:\n                if walk:", self.poles)


if __name__ == "__main__":
    unittest.main()
