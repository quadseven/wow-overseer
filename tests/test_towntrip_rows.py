"""Turning the bridge's rows into the facts the town trip plans from.

tests/test_towntrip.py exercises `plan` against the measured roster and is not
touched here. What is tested below is the seam between the database and that
planner: four queries in, `Member` and `Town` out. It is the same seam
bank.members_from_rows sits on, and it is worth its own suite for the same
reason, which is that every mistake it can make is silent. A member dropped
because a row was missing plans nothing and looks exactly like a member who
needs nothing.
"""
import unittest

import towntrip
from towntrip import Town


def worn_row(holder, entry=1, durability=90, maximum=100, **kw):
    row = {
        "holder": holder,
        "klass": "Warrior",
        "level": 29,
        "money": 1706343,
        "entry": entry,
        "item_name": "a worn thing",
        "durability": durability,
        "max_durability": maximum,
    }
    row.update(kw)
    return row


class TheTownIsReadFromWhereTheyStand(unittest.TestCase):
    def test_nothing_in_reach_is_an_empty_town(self):
        """Which is what a party still walking to the counter looks like.

        An empty Town makes `plan` write no rows and say why, which is the
        whole mechanism for not queueing errands that would be refused.
        """
        got = towntrip.town_from_rows([])
        self.assertEqual(got, Town(repairs=False, stocks=frozenset()))

    def test_a_repairer_in_reach_is_the_only_thing_repairs_needs(self):
        got = towntrip.town_from_rows([{"npcflag": towntrip.NPC_FLAG_REPAIR, "item": None}])
        self.assertTrue(got.repairs)
        self.assertEqual(got.stocks, frozenset())

    def test_a_vendor_contributes_what_it_sells(self):
        rows = [
            {"npcflag": towntrip.NPC_FLAG_VENDOR, "item": 787},
            {"npcflag": towntrip.NPC_FLAG_VENDOR, "item": 159},
        ]
        self.assertEqual(towntrip.town_from_rows(rows).stocks, frozenset({787, 159}))

    def test_one_npc_can_be_both(self):
        """The commonest shape in a small town is one goods vendor who repairs."""
        both = towntrip.NPC_FLAG_VENDOR | towntrip.NPC_FLAG_REPAIR
        got = towntrip.town_from_rows([{"npcflag": both, "item": 4592}])
        self.assertTrue(got.repairs)
        self.assertEqual(got.stocks, frozenset({4592}))

    def test_stock_on_a_spawn_that_is_not_a_vendor_is_not_stock(self):
        """A npc_vendor row on something that cannot sell is not a purchase.

        Planning a buy against it produces a row the executor refuses, which
        this module exists to avoid, and the refusal would read like a broken
        vendor rather than like a bad plan.
        """
        got = towntrip.town_from_rows([{"npcflag": towntrip.NPC_FLAG_REPAIR, "item": 787}])
        self.assertEqual(got.stocks, frozenset())

    def test_a_spawn_with_no_flags_contributes_nothing(self):
        got = towntrip.town_from_rows([{"npcflag": 0, "item": 787}])
        self.assertEqual(got, Town(repairs=False, stocks=frozenset()))

    def test_unreadable_rows_do_not_crash_the_pass(self):
        """A NULL npcflag is a spawn whose template row is missing.

        Fail closed: it contributes nothing rather than raising and taking the
        whole trip down with it.
        """
        got = towntrip.town_from_rows([{"npcflag": None, "item": None}, {}])
        self.assertEqual(got, Town(repairs=False, stocks=frozenset()))


class EveryNameComesBackAsAMember(unittest.TestCase):
    def test_a_name_with_no_rows_at_all_is_still_a_member(self):
        got = towntrip.members_from_rows([], [], [], {}, ["Grug", "Bork"])
        self.assertEqual([m.name for m in got], ["Grug", "Bork"])

    def test_duplicate_names_are_collapsed(self):
        got = towntrip.members_from_rows([], [], [], {}, ["Grug", "Grug"])
        self.assertEqual(len(got), 1)

    def test_rows_for_somebody_not_asked_about_are_ignored(self):
        got = towntrip.members_from_rows(
            [worn_row("Stranger")], [], [], {}, ["Grug"])
        self.assertEqual([m.name for m in got], ["Grug"])
        self.assertEqual(got[0].equipped, ())


class TheFactsSurviveTheCrossing(unittest.TestCase):
    def test_class_is_lowercased_for_the_mana_test(self):
        """towntrip.MANA_CLASSES is lowercase and the database is not.

        A priest who arrives as "Priest" is not in that set, so the healer -
        the one member whose water decides whether a dungeon finishes - would
        be sent home with nothing to drink.
        """
        got = towntrip.members_from_rows(
            [worn_row("Ugga", klass="Priest")], [], [], {}, ["Ugga"])
        self.assertEqual(got[0].klass, "priest")
        self.assertIn(got[0].klass, towntrip.MANA_CLASSES)

    def test_durability_becomes_an_equipped_item(self):
        got = towntrip.members_from_rows(
            [worn_row("Grug", durability=94, maximum=100)], [], [], {}, ["Grug"])
        self.assertEqual(got[0].equipped[0].durability, 94)
        self.assertAlmostEqual(got[0].worst, 0.94)

    def test_an_item_that_cannot_break_is_not_counted_as_broken(self):
        """MaxDurability 0 is cloth, a ring, a trinket. It is not damage.

        Counting it would drag `worst` to zero for every member and plan a
        repair on a family that has nothing to repair.
        """
        got = towntrip.members_from_rows(
            [worn_row("Og", durability=0, maximum=0)], [], [], {}, ["Og"])
        self.assertEqual(got[0].equipped, ())
        self.assertEqual(got[0].worst, 1.0)

    def test_food_and_drink_are_counted_against_the_right_tables(self):
        carried = [
            {"holder": "Bork", "entry": 787, "carried": 3},     # food
            {"holder": "Bork", "entry": 159, "carried": 5},     # drink
            {"holder": "Bork", "entry": 12345, "carried": 40},  # neither
        ]
        got = towntrip.members_from_rows([worn_row("Bork")], carried, [], {}, ["Bork"])
        self.assertEqual(got[0].food_carried, 3)
        self.assertEqual(got[0].drink_carried, 5)

    def test_stacks_of_the_same_thing_add_up(self):
        """Twenty of something is two stacks of ten as often as one of twenty."""
        carried = [
            {"holder": "Bork", "entry": 787, "carried": 12},
            {"holder": "Bork", "entry": 787, "carried": 8},
        ]
        got = towntrip.members_from_rows([worn_row("Bork")], carried, [], {}, ["Bork"])
        self.assertEqual(got[0].food_carried, 20)

    def test_spells_reach_the_conjure_check(self):
        spells = [{"holder": "Og", "spell": 5504}, {"holder": "Og", "spell": 990}]
        got = towntrip.members_from_rows([worn_row("Og")], [], spells, {}, ["Og"])
        self.assertTrue(got[0].spells & towntrip.CONJURE_WATER)
        self.assertTrue(got[0].spells & towntrip.CONJURE_FOOD)

    def test_free_slots_arrive_and_default_to_none(self):
        got = towntrip.members_from_rows(
            [worn_row("Grug")], [], [], {"Grug": 14}, ["Grug", "Bork"])
        by_name = {m.name: m for m in got}
        self.assertEqual(by_name["Grug"].free_slots, 14)
        # Unmeasured room is zero room, which stops a purchase rather than
        # planning one into bags that may be full.
        self.assertEqual(by_name["Bork"].free_slots, 0)


class ThePlannerAcceptsWhatThisProduces(unittest.TestCase):
    """The two halves have to fit, and nothing else checks that they do."""

    def test_a_measured_family_and_town_produce_the_expected_errands(self):
        rows = [
            worn_row("Grug", klass="Warrior", durability=94, maximum=100),
            worn_row("Ugga", klass="Priest", level=24, durability=100, maximum=100),
        ]
        carried = []
        spells = []
        # The tiers these two LEVELS actually open, not the cheapest rows in
        # the table. A town stocking only tier one supplies nobody past level
        # five, and a fixture that made that mistake would prove nothing.
        town = towntrip.town_from_rows(
            [
                {"npcflag": towntrip.NPC_FLAG_REPAIR, "item": None},
                {"npcflag": towntrip.NPC_FLAG_VENDOR, "item": 4594},  # food, 25+
                {"npcflag": towntrip.NPC_FLAG_VENDOR, "item": 4593},  # food, 15+
                {"npcflag": towntrip.NPC_FLAG_VENDOR, "item": 1205},  # drink, 15+
            ]
        )
        members = towntrip.members_from_rows(
            rows, carried, spells, {"Grug": 14, "Ugga": 4}, ["Grug", "Ugga"])
        got = towntrip.plan(members, town)

        kinds = {(e.member, e.kind) for e in got.errands}
        # Grug has a damaged item and Ugga does not, so only Grug repairs.
        self.assertIn(("Grug", "repair"), kinds)
        self.assertNotIn(("Ugga", "repair"), kinds)
        # Both carry no food; the priest also drinks.
        self.assertIn(("Grug", "buy"), kinds)
        self.assertIn(("Ugga", "buy"), kinds)

    def test_the_commands_are_the_grammars_the_executors_parse(self):
        """A row the executor cannot parse is refused as malformed, forever.

        `repair all` and `entry:<n> count:<n> max:<n>` are pinned in
        tests/test_towntrip.py against the C++ headers; this checks the rows
        that come out of THIS path have the same shape, because a constructor
        that fed `plan` a broken Member could produce a broken command.
        """
        members = towntrip.members_from_rows(
            [worn_row("Grug", durability=50, maximum=100)],
            [], [], {"Grug": 10}, ["Grug"])
        town = towntrip.town_from_rows(
            [{"npcflag": towntrip.NPC_FLAG_REPAIR | towntrip.NPC_FLAG_VENDOR,
              "item": 4594}])
        got = towntrip.plan(members, town)
        for errand in got.errands:
            with self.subTest(errand=errand):
                if errand.kind == "repair":
                    self.assertEqual(errand.command, "all")
                else:
                    self.assertRegex(errand.command,
                                     r"^entry:\d+ count:\d+ max:\d+$")


if __name__ == "__main__":
    unittest.main()
