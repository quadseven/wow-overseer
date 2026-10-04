"""The family member assigned a trade is its master and is served first.

Operator, 2026-10-04: "the family should be the master crafters and have
priority for recipes and crafting ... and then there can be others designated
the backup crafters". Before this, any family member with skill counted, and a
designated guildmate who could learn a recipe now beat a family member a few
points short.
"""

import unittest

import crafters

BLACKSMITHING = 164
LEATHER = 165


def person(name, skills, family=False, assigned=()):
    return crafters.Person(name, skills, 30, family, True, assigned=frozenset(assigned))


GRUG = person("Grug", {BLACKSMITHING: 40}, family=True, assigned={BLACKSMITHING, 186})
BORK = person("Bork", {BLACKSMITHING: 60, LEATHER: 30}, family=True, assigned={LEATHER})
SMITHY = person("Smithy", {BLACKSMITHING: 90})
PEOPLE = [GRUG, BORK, SMITHY]


def recipe(rank):
    return crafters.Recipe(
        "Ugga", 1, 2851, "Plans: Runed Copper Belt", BLACKSMITHING, rank, 2666
    )


class TheMasterIsFirst(unittest.TestCase):
    def test_the_register_seats_the_master_first(self):
        reg = crafters.register(PEOPLE, n=2)
        seats = reg[BLACKSMITHING]
        self.assertEqual(("Grug", crafters.MASTER), (seats[0].name, seats[0].seat))
        self.assertEqual(crafters.FAMILY, {s.name: s.seat for s in seats}["Bork"])
        self.assertEqual(crafters.DESIGNATED, {s.name: s.seat for s in seats}["Smithy"])

    def test_a_master_a_little_short_beats_a_backup_who_has_it(self):
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(55), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Grug", picks[0].taker)

    def test_the_master_beats_other_family_too(self):
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(35), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Grug", picks[0].taker)

    def test_the_backup_takes_what_the_master_cannot(self):
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(85), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Smithy", picks[0].taker)


if __name__ == "__main__":
    unittest.main()
