"""The first-clear gate: no raid for other guilds before a family guild's clear."""

import unittest

import raidgate


class RefusesUntilTheMilestoneExists(unittest.TestCase):
    def test_other_guild_is_refused_and_family_allowed_with_no_milestone(self):
        self.assertTrue(raidgate.refusal("Wanderers", "moltencore", set()))
        self.assertEqual("", raidgate.refusal("Cave", "moltencore", set()))
        self.assertEqual("", raidgate.refusal("Bonkers", "moltencore", set()))

    def test_other_guild_is_allowed_once_its_tier_is_cleared(self):
        self.assertEqual(
            "", raidgate.refusal("Wanderers", "moltencore", {"moltencore"})
        )


class AKillWritesTheMilestoneOnce(unittest.TestCase):
    def test_family_ragnaros_kill_writes_it_once(self):
        for guild in ("Cave", "Bonkers"):
            first = raidgate.record_kill(guild, 11502, set())
            self.assertEqual(frozenset({"moltencore"}), first)
            self.assertEqual(first, raidgate.record_kill(guild, 11502, first))

    def test_other_guild_kill_writes_none(self):
        self.assertEqual(frozenset(), raidgate.record_kill("Wanderers", 11502, set()))

    def test_a_non_final_boss_writes_none(self):
        self.assertEqual(frozenset(), raidgate.record_kill("Cave", 12118, set()))


class OneTierDoesNotOpenAnother(unittest.TestCase):
    def test_molten_core_does_not_open_later_raids(self):
        done = {"moltencore"}
        self.assertTrue(raidgate.refusal("Wanderers", "blackwinglair", done))
        self.assertTrue(raidgate.refusal("Wanderers", "aq", done))
        self.assertEqual("", raidgate.refusal("Wanderers", "moltencore", done))

    def test_each_final_boss_opens_only_its_own_tier(self):
        self.assertEqual(
            frozenset({"blackwinglair"}), raidgate.record_kill("Cave", 11583, set())
        )
        self.assertEqual(
            frozenset({"aq"}), raidgate.record_kill("Bonkers", 15727, set())
        )


if __name__ == "__main__":
    unittest.main()
