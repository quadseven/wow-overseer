"""A long dungeon run keeps its healer in drink: the mage conjures inside it (#2213).

MEASURED LIVE, 2026-11-10, run 1761047: the mage entered with 45 waters, one
20-stack went to the healer ten minutes in, and that was the only give for the
next 80 minutes. Giving left the mage one kept stack, so no whole stack
was spare, and `in_run_drink` planned gives only; the healer's stack lasted 59
minutes and the party stopped twice more on "Waiting on <healer> (low mana)".
A conjure moves nobody and is free, and the module refuses it in combat, so the
in-run pass can ask for one.
"""

import unittest

import towntrip
from towntrip import Member


def water(guid, count):
    return towntrip.Stack(
        guid=guid,
        entry=8077,
        name="Conjured Mineral Water",
        count=count,
        what="drink",
        conjured=True,
    )


def mage(stacks=(), carried=0, free_slots=8):
    return Member(
        "Og",
        "mage",
        51,
        10**6,
        free_slots,
        (),
        food_carried=20,
        drink_carried=carried,
        spells=frozenset({990, 5506}),
        stacks=tuple(stacks),
    )


def paladin(carried=0):
    return Member(
        "Grog", "paladin", 53, 10**6, 8, (), food_carried=20, drink_carried=carried
    )


def priest(carried=12, stacks=()):
    return Member(
        "Ugga",
        "priest",
        52,
        10**6,
        8,
        (),
        food_carried=20,
        drink_carried=carried,
        stacks=tuple(stacks),
    )


def rogue():
    return Member("Bork", "rogue", 52, 10**6, 8, (), food_carried=20)


NEAR = lambda giver, taker: False  # noqa: E731 - every pair in trade range
FAR = lambda giver, taker: True  # noqa: E731 - nobody in trade range


def rows(members, apart=NEAR):
    return [
        (e.member, e.kind, e.command)
        for e in towntrip.in_run_drink(members, apart)
    ]


class TheMageRefillsInsideTheRun(unittest.TestCase):
    def test_a_dry_healer_and_no_spare_stack_plans_a_conjure_for_the_mage(self):
        # After the gives: one kept stack of 20. Nothing is spare.
        og = mage((water(31, 20),), carried=20)
        got = rows((og, paladin(), rogue(), priest()))
        self.assertEqual(got, [("Og", towntrip.CONJURE_KIND, "water up_to:40")])

    def test_it_conjures_even_when_nobody_is_in_trade_range(self):
        # A conjure needs no giver beside the taker; the stack is handed on by
        # the next pass once the mage holds one to spare.
        og = mage((water(31, 20),), carried=20)
        got = rows((og, paladin(), rogue()), FAR)
        self.assertEqual(got, [("Og", towntrip.CONJURE_KIND, "water up_to:40")])

    def test_it_makes_a_stack_for_each_dry_mouth_within_the_free_bag_slots(self):
        og = mage((water(31, 20),), carried=20, free_slots=3)
        got = rows((og, paladin(), priest(carried=0), rogue()))
        self.assertEqual(got, [("Og", towntrip.CONJURE_KIND, "water up_to:60")])
        og = mage((water(31, 20),), carried=20, free_slots=2)
        got = rows((og, paladin(), priest(carried=0), rogue()))
        self.assertEqual(got, [("Og", towntrip.CONJURE_KIND, "water up_to:40")])

    def test_a_mage_below_the_floor_conjures_for_itself(self):
        og = mage((water(31, 4),), carried=4)
        got = rows((og, paladin(carried=30), rogue()))
        self.assertEqual(got, [("Og", towntrip.CONJURE_KIND, "water up_to:20")])


class NothingIsConjuredWithoutANeed(unittest.TestCase):
    def test_a_healer_handed_a_spare_stack_this_pass_causes_no_conjure(self):
        og = mage((water(31, 20), water(32, 20), water(33, 15)), carried=55)
        got = rows((og, paladin(), rogue()))
        self.assertEqual(got, [("Og", towntrip.GIVE_KIND, "guid:31")])

    def test_a_stocked_party_plans_nothing(self):
        og = mage((water(31, 20),), carried=20)
        self.assertEqual(rows((og, paladin(carried=20), rogue())), [])

    def test_a_non_mana_class_never_causes_a_conjure(self):
        og = mage((water(31, 20),), carried=20)
        self.assertEqual(rows((og, rogue())), [])

    def test_a_party_with_no_conjurer_plans_no_conjure(self):
        got = towntrip.in_run_drink((paladin(), rogue(), priest(carried=34)), NEAR)
        self.assertEqual([e for e in got if e.kind == towntrip.CONJURE_KIND], [])

    def test_without_positions_nothing_is_planned(self):
        og = mage((water(31, 20),), carried=20)
        self.assertEqual(towntrip.in_run_drink((og, paladin()), None), [])


if __name__ == "__main__":
    unittest.main()
