"""The town trip decides what it should, for the roster it was measured on.

Every fixture below is the live roster on the day this was written, not an
invention: the levels, the durability percentages, the empty food and drink
counts, the free bag slots, and the mage's actual conjure ranks all came out
of `characters`, `item_instance`, `character_inventory` and `character_spell`.
That matters because the two decisions this module makes are both about
thresholds, and a threshold tested only against numbers chosen to make it
fire proves nothing.
"""
import unittest

import towntrip
from towntrip import Equipped, Member, Town


def worn(fraction, maximum=100):
    return Equipped(1, "worn", int(round(maximum * fraction)), maximum)


# What a reachable neutral town actually stocks: the food and drink tiers a
# general-goods vendor, a fisherman and an innkeeper carry between them.
RATCHET = Town(repairs=True, stocks=frozenset({787, 4592, 4593, 4594, 159, 1179, 1205, 1708}))

# The five, as measured. Og's spells are the six conjure ranks he really has.
GRUG = Member("Grug", "warrior", 29, 1706343, 14, (worn(0.943, 35), worn(0.985, 65)))
GROG = Member("Grog", "paladin", 27, 1724617, 7, (worn(0.967, 30), worn(0.971, 35)))
OG = Member("Og", "mage", 26, 1595527, 9, (worn(0.95, 20),),
            spells=frozenset({587, 597, 990, 5504, 5505, 5506}))
BORK = Member("Bork", "rogue", 26, 1458619, 4, (worn(1.0, 50),), food_carried=1)
UGGA = Member("Ugga", "priest", 24, 1689925, 4, (worn(0.95, 20), worn(0.975, 40)))
FAMILY = (GRUG, GROG, OG, BORK, UGGA)


class TheMeasuredRoster(unittest.TestCase):
    def test_a_family_fresh_from_a_clear_still_repairs(self):
        """99% is not 100%, and the trip is happening anyway.

        The tempting threshold is "only repair below some percentage", and it
        is wrong: repair cost is linear in the points missing, so nothing is
        saved by waiting, and the walk to the repairer has already been paid
        for. Four of the five have something damaged and all four get a row.
        """
        got = towntrip.plan(FAMILY, RATCHET)
        repairs = [e for e in got.errands if e.kind == "repair"]
        self.assertEqual([e.member for e in repairs], ["Grog", "Grug", "Og", "Ugga"])
        self.assertEqual({e.command for e in repairs}, {"all"})

    def test_the_one_at_full_durability_is_not_sent_to_the_repairer(self):
        got = towntrip.plan(FAMILY, RATCHET)
        self.assertNotIn("Bork", [e.member for e in got.errands if e.kind == "repair"])

    def test_the_floor_is_about_deaths_and_not_about_looks(self):
        """A death costs 10% of an item. The floor leaves room for three."""
        fine = towntrip.plan((Member("A", "warrior", 29, 10 ** 6, 8, (worn(0.40),)),), RATCHET)
        self.assertNotIn("floor", fine.errands[0].why)

        thin = towntrip.plan((Member("A", "warrior", 29, 10 ** 6, 8, (worn(0.30),)),), RATCHET)
        self.assertIn("floor", thin.errands[0].why)
        self.assertEqual(thin.errands[0].kind, "repair")

    def test_the_worst_item_and_not_the_average_is_what_the_floor_reads(self):
        """A character in one broken boot and nine perfect pieces averages
        well above the floor and is still one death from losing the boot."""
        member = Member("A", "warrior", 29, 10 ** 6, 8,
                        tuple([worn(0.20)] + [worn(1.0)] * 9))
        self.assertGreater(member.durability, towntrip.FLOOR)
        self.assertLess(member.worst, towntrip.FLOOR)
        self.assertIn("floor", towntrip.plan((member,), RATCHET).errands[0].why)


class WhatTheTownCanAndCannotSupply(unittest.TestCase):
    def test_the_two_mana_users_who_carry_nothing_are_bought_drink(self):
        got = towntrip.plan(FAMILY, RATCHET)
        buys = {(e.member, e.command) for e in got.errands if e.kind == "buy"}
        self.assertIn(("Ugga", "entry:1205 count:20 max:10000"), buys)
        self.assertIn(("Grog", "entry:1708 count:20 max:20000"), buys)

    def test_the_healer_is_one_level_short_of_the_better_drink(self):
        """Ugga is 24 and Sweet Nectar opens at 25. That is a real cost of a
        real level and the row says so rather than silently buying the
        cheaper tier."""
        got = towntrip.plan((UGGA,), RATCHET)
        drink = [e for e in got.errands if e.kind == "buy" and "1205" in e.command]
        self.assertEqual(len(drink), 1)
        self.assertIn("one level short of Sweet Nectar", drink[0].why)

    def test_the_mage_is_sold_neither_food_nor_water(self):
        """He knows Conjure Food and Conjure Water. Selling him either is
        spending gold on something he makes for free."""
        got = towntrip.plan((OG,), RATCHET)
        self.assertEqual([e.kind for e in got.errands], ["repair"])
        self.assertTrue(any("conjures food" in n for n in got.notes))
        self.assertTrue(any("conjures drink" in n for n in got.notes))

    def test_a_warrior_is_bought_food_and_never_drink(self):
        got = towntrip.plan((GRUG,), RATCHET)
        buys = [e for e in got.errands if e.kind == "buy"]
        self.assertEqual([e.command for e in buys], ["entry:4594 count:20 max:20000"])

    def test_the_rogues_single_bowl_of_soup_is_counted(self):
        """He carries one. He is sold nineteen, not twenty."""
        got = towntrip.plan((BORK,), RATCHET)
        buys = [e for e in got.errands if e.kind == "buy"]
        self.assertEqual([e.command for e in buys], ["entry:4594 count:19 max:19000"])

    def test_nothing_is_bought_that_the_vendor_does_not_stock(self):
        """The measured town stocks no reagent, no poison and no bandage. A
        planner that emitted a row for one would be queueing a refusal."""
        bare = Town(repairs=True, stocks=frozenset())
        got = towntrip.plan(FAMILY, bare)
        self.assertEqual([e.kind for e in got.errands], ["repair"] * 4)
        self.assertTrue(any("no reachable vendor stocks" in n for n in got.notes))

    def test_the_reagent_table_is_empty_on_purpose(self):
        """No class on this roster consumes a reagent at these levels, and the
        rogue knows no poison spell at all. An empty table is the measurement,
        not an omission."""
        self.assertEqual(towntrip.REAGENT_SPELLS, {})


class WhatIsSaidInsteadOfQueued(unittest.TestCase):
    def test_an_unreachable_repairer_blocks_rather_than_queues(self):
        """The nearest repairers to this roster's instance are the other
        faction's, and the core refuses those for being unfriendly however
        close the character stands. That is a fact about the town, so it is
        reported and not tried."""
        got = towntrip.plan((GRUG,), Town(repairs=False, stocks=RATCHET.stocks))
        self.assertEqual([e.kind for e in got.errands], ["buy"])
        self.assertEqual(len(got.blocked), 1)
        self.assertIn("no repairer is reachable", got.blocked[0])

    def test_full_bags_are_a_sell_problem_and_are_named_as_one(self):
        packed = Member("A", "priest", 24, 10 ** 6, 0, (worn(1.0),))
        got = towntrip.plan((packed,), RATCHET)
        self.assertEqual(got.errands, ())
        self.assertEqual(len(got.notes), 2)
        self.assertTrue(all("a sell pass has to run first" in n for n in got.notes))

    def test_an_empty_purse_is_named_and_not_queued(self):
        broke = Member("A", "warrior", 29, 10, 8, (worn(1.0),))
        got = towntrip.plan((broke,), RATCHET)
        self.assertEqual(got.errands, ())
        self.assertTrue(any("cannot afford" in n for n in got.notes))


class TheOrderIsTheReservation(unittest.TestCase):
    def test_every_repair_comes_before_every_purchase(self):
        """This side cannot price a repair, so it cannot hold money back for
        one. Putting the repairs first is the whole of the reservation: the
        executor refuses a purchase it cannot afford rather than overdrawing,
        so the gear wins the coin toss."""
        got = towntrip.plan(FAMILY, RATCHET)
        kinds = [e.kind for e in got.errands]
        self.assertEqual(sorted(set(kinds)), ["buy", "repair"])
        self.assertEqual(kinds.index("buy"), kinds.count("repair"))

    def test_the_plan_does_not_depend_on_the_order_the_members_arrive_in(self):
        forwards = towntrip.plan(FAMILY, RATCHET)
        backwards = towntrip.plan(tuple(reversed(FAMILY)), RATCHET)
        self.assertEqual(forwards, backwards)

    def test_every_command_is_one_the_executors_grammar_accepts(self):
        """The C++ side parses `all` for a repair and
        `entry:<n> [count:<n>] [max:<copper>]` for a buy, and refuses anything
        else. A plan that emitted a command those parsers reject would be a
        queue full of malformed rows."""
        for errand in towntrip.plan(FAMILY, RATCHET).errands:
            if errand.kind == "repair":
                self.assertEqual(errand.command, "all")
                continue
            words = errand.command.split()
            self.assertEqual(len(words), 3)
            self.assertTrue(words[0].startswith("entry:"))
            self.assertTrue(words[1].startswith("count:"))
            self.assertTrue(words[2].startswith("max:"))
            for word in words:
                self.assertTrue(word.split(":", 1)[1].isdigit())
                self.assertGreater(int(word.split(":", 1)[1]), 0)

    def test_the_ceiling_is_the_undiscounted_price(self):
        """The reputation discount at the counter only ever lowers the bill,
        so a ceiling computed from BuyPrice is always reachable."""
        got = towntrip.plan((GRUG,), RATCHET)
        buy = [e for e in got.errands if e.kind == "buy"][0]
        count = int(buy.command.split("count:")[1].split()[0])
        ceiling = int(buy.command.split("max:")[1])
        self.assertEqual(ceiling, count * 1000)
        self.assertEqual(buy.spend, ceiling)


class TheEmptyCases(unittest.TestCase):
    def test_no_members_is_an_empty_plan_and_not_a_crash(self):
        self.assertEqual(towntrip.plan((), RATCHET), towntrip.Plan())

    def test_a_character_wearing_nothing_that_wears_out_is_not_repaired(self):
        naked = Member("A", "mage", 26, 10 ** 6, 8, (), spells=frozenset({990, 5506}))
        self.assertEqual(towntrip.plan((naked,), RATCHET).errands, ())


if __name__ == "__main__":
    unittest.main()
