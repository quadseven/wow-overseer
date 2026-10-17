"""Master crafters get first priority; duplicates fan out to others.

Ticket #1095 (refined): Og (and other family masters) get first priority for
recipes in their profession. The SECOND copy of the same recipe goes to
someone else in the guild so it doesn't go to waste. This is master-first
for the first copy, fan-out for duplicates.
"""

import unittest

import crafters

BLACKSMITHING = 164


def person(name, skills, family=False, assigned=()):
    return crafters.Person(name, skills, 30, family, True, assigned=frozenset(assigned))


# Grug is the assigned master (high skill). Bork holds the trade but is not
# assigned, with lower skill. Both can learn a rank-50 recipe right now.
GRUG = person("Grug", {BLACKSMITHING: 90}, family=True, assigned={BLACKSMITHING})
BORK = person("Bork", {BLACKSMITHING: 55}, family=True, assigned=set())
SMITHY = person("Smithy", {BLACKSMITHING: 60})
PEOPLE = [GRUG, BORK, SMITHY]


def recipe(guid, rank=50):
    return crafters.Recipe(
        "Ugga", guid, 2851, "Plans: Runed Copper Belt", BLACKSMITHING, rank, 2666
    )


class MasterFirstDuplicateFansOut(unittest.TestCase):
    def test_master_gets_first_copy(self):
        # Grug is the master. First copy goes to Grug (master-first).
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.route([recipe(1)], reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Grug", picks[1].taker)

    def test_duplicate_goes_to_someone_else(self):
        # Two copies of the same recipe. First goes to Grug (master).
        # Second excludes Grug, goes to Bork (next best).
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.route([recipe(1), recipe(2)], reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Grug", picks[1].taker)
        self.assertEqual("Bork", picks[2].taker)
        self.assertNotEqual(picks[1].taker, picks[2].taker)

    def test_triplicate_fans_out_further(self):
        # Three copies: Grug, then Bork, then Smithy (designated).
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.route(
            [recipe(1), recipe(2), recipe(3)], reg, PEOPLE, crafters.Known(), 25
        )
        takers = [picks[i].taker for i in (1, 2, 3)]
        self.assertEqual(len(set(takers)), 3, "each copy should go to someone different")


if __name__ == "__main__":
    unittest.main()
