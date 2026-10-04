"""The Horde can run the Deadmines; only the Stockade is closed to it.

Operator, 2026-10-04: "Horde CAN run deadmines. Horde cannot run stockades.
Deadmines for horde is hard because you have to run up from the stranglethorn
vale zeppelin." A door is closed to a faction only when it stands inside the
other faction's capital: the Stockade (Stormwind) for the Horde, Ragefire
Chasm (Orgrimmar) for the Alliance.
"""

import unittest

import dungeonpath
import guildrun


def _step(map_id):
    return next(step for step in dungeonpath.PATH if step.map_id == map_id)


class OnlyCapitalDoorsAreClosed(unittest.TestCase):
    def test_the_deadmines_carries_no_faction(self):
        self.assertEqual("", _step(36).inside)

    def test_the_capital_doors_still_do(self):
        self.assertEqual(dungeonpath.ALLIANCE, _step(34).inside)
        self.assertEqual(dungeonpath.HORDE, _step(389).inside)

    def test_the_guild_run_closes_only_the_stockade_to_the_horde(self):
        self.assertEqual(frozenset({34}), guildrun.HOSTILE_CAPITAL_DUNGEONS["Horde"])
        self.assertEqual(frozenset({389}), guildrun.HOSTILE_CAPITAL_DUNGEONS["Alliance"])


if __name__ == "__main__":
    unittest.main()
