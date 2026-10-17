"""Crafting work fans out across the family instead of funneling to the master.

Ticket #1095: Og has been the sole crafter all week while the rest of the
family does town runs. The old policy (test_crafter_master_first.py) gave the
assigned master priority over every other family member. The new policy keeps
the family ahead of non-family, but WITHIN the family the member who benefits
most (lowest skill that can still do the recipe) wins, so crafting XP spreads
instead of concentrating on one master.
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


def recipe(rank):
    return crafters.Recipe(
        "Ugga", 1, 2851, "Plans: Runed Copper Belt", BLACKSMITHING, rank, 2666
    )


class FanOutWithinFamily(unittest.TestCase):
    def test_lower_skilled_family_member_beats_the_master(self):
        # Both Grug (master, 90) and Bork (family, 55) can learn a rank-50
        # recipe now. Bork benefits more (55 is closer to 50 than 90 is), so
        # Bork gets it. Under the old master-first policy Grug always won.
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(50), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Bork", picks[0].taker)

    def test_choose_gives_recipe_to_lower_skilled_family_member(self):
        reg = crafters.register(PEOPLE, n=2)
        pick = crafters.choose(recipe(50), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Bork", pick.taker)

    def test_family_still_beats_designated_guildmate(self):
        # The fan-out is WITHIN the family. A family member still beats a
        # non-family guildmate: the family keeps priority as a group.
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(50), reg, PEOPLE, crafters.Known(), 25)
        takers = [p.taker for p in picks]
        self.assertLess(takers.index("Bork"), takers.index("Smithy"))
        self.assertLess(takers.index("Grug"), takers.index("Smithy"))


if __name__ == "__main__":
    unittest.main()
