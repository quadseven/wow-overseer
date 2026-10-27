"""A member far behind trains to its level in one visit.

Each trainer visit bought only the next rank of each spell: classtrain.due
counted a spell only when every spell it requires was already known, so a
chain of ranks counted one link at a time. A member several ranks behind
therefore needed several visits, one cooldown apart, and the guild fund
reserved and posted only the next rank's cost.

Pure tests against classtrain.due: the whole chain a trainer can teach in
one sitting, in dependency order, is due at once.
"""

import unittest

import classtrain

# A chain of ranks, deliberately unordered, plus two spells that must
# stay out: one above the member's level, one needing a spell no trainer
# row teaches (a talent).
CHAIN = [
    {"spell": 102, "level": 8, "cost": 30, "req1": 101},
    {"spell": 100, "level": 4, "cost": 10},
    {"spell": 101, "level": 6, "cost": 20, "req1": 100},
    {"spell": 103, "level": 30, "cost": 40, "req1": 102},
    {"spell": 104, "level": 8, "cost": 50, "req1": 999},
]


class DueCountsTheWholeChain(unittest.TestCase):
    def test_a_far_behind_member_owes_every_rank_up_to_its_level(self):
        due = classtrain.due(CHAIN, set(), 10)
        self.assertEqual(due, classtrain.Due(60, 3, 10))

    def test_a_known_link_leaves_the_rest_of_the_chain_due(self):
        due = classtrain.due(CHAIN, {100}, 10)
        self.assertEqual(due, classtrain.Due(50, 2, 20))

    def test_spells_above_level_or_needing_an_untaught_spell_stay_out(self):
        due = classtrain.due(CHAIN, {100, 101, 102}, 10)
        self.assertEqual(due, classtrain.Due(0, 0, 0))
        self.assertFalse(due.affords(10**9))


if __name__ == "__main__":
    unittest.main()
