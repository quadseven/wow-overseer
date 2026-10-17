"""The family member assigned a trade is its master and is seated first.

Operator, 2026-10-04: "the family should be the master crafters and have
priority for recipes and crafting ... and then there can be others designated
the backup crafters". Before this, any family member with skill counted, and a
designated guildmate who could learn a recipe now beat a family member a few
points short.

Operator, 2026-10-17 (#1095): within the family, crafting fans out instead of
funneling to the master. The register still seats the master first, but the
route gives the recipe to the family member who benefits most (lowest skill
that can still do it), so crafting XP spreads across the family.
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

    def test_a_family_member_who_can_learn_now_beats_a_short_master(self):
        # #1095: the master no longer funnels every recipe. Bork (family, 60)
        # can learn a rank-55 recipe now; Grug (master, 40) is 15 short.
        # Learning now beats waiting, and within the family the member who
        # benefits most wins.
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(55), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Bork", picks[0].taker)

    def test_the_closest_family_member_wins_when_both_can_learn_now(self):
        # Both Grug (master, 40) and Bork (family, 60) can learn a rank-35
        # recipe now. Grug is closer to the rank (benefit 5 vs 25), so Grug
        # wins on benefit, not on master status.
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(35), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Grug", picks[0].taker)

    def test_the_backup_takes_what_the_master_cannot(self):
        reg = crafters.register(PEOPLE, n=2)
        picks = crafters.candidates(recipe(85), reg, PEOPLE, crafters.Known(), 25)
        self.assertEqual("Smithy", picks[0].taker)


if __name__ == "__main__":
    unittest.main()
