"""A craft errand's reagents are planned before it is judged fed (#774, #769).

Measured on the dev realm 2026-11-13: eight crafters were re-aimed at a recipe
every five minutes for three hours and cast nothing, because every errand
named a reagent with 0 in the bags. The reagents were not missing from the
world: Uzza's 34 Empty Vials sat in her own bank, and Zug's guild vault held
35 Rough Stone while he stood short of one. These tests hold the planner to
naming, per short reagent, where it comes from in the order a person would
look: own bank, mailbox, guild bank, a vendor, a gatherer, the auction house.
"""

from __future__ import annotations

import unittest

import bankforecast
import craft_supply
import reagentplan

PEACEBLOOM, SILVERLEAF, EMPTY_VIAL = 2447, 765, 3371
ROUGH_STONE, COPPER_ORE = 2835, 2770
MINOR_HEALING_POTION = 2330
ROUGH_SHARPENING_STONE = 2660
SMELT_COPPER = 2657

# item_template (class, subclass): herb 7/9, metal and stone 7/7.
KINDS = {
    PEACEBLOOM: (7, 9),
    SILVERLEAF: (7, 9),
    ROUGH_STONE: (7, 7),
    COPPER_ORE: (7, 7),
    EMPTY_VIAL: (7, 11),
}


def stock(**places):
    return reagentplan.Stock(**places)


class TheRecipeNamesEveryReagent(unittest.TestCase):
    def test_a_potion_counts_its_herbs_and_its_bought_vial(self):
        got = {r.entry: r for r in reagentplan.reagents(MINOR_HEALING_POTION)}
        self.assertEqual({PEACEBLOOM, SILVERLEAF, EMPTY_VIAL}, set(got))
        self.assertTrue(got[EMPTY_VIAL].vendor)
        self.assertFalse(got[PEACEBLOOM].vendor)

    def test_a_multi_reagent_vendor_recipe_keeps_its_count(self):
        spell, needed = next(iter(craft_supply.REAGENTS.items()))
        got = {r.entry: r for r in reagentplan.reagents(spell)}
        for entry, _label, _price, qty in needed:
            self.assertEqual(qty, got[entry].per_cast)
            self.assertTrue(got[entry].vendor)

    def test_a_recipe_with_no_table_is_not_judged(self):
        self.assertEqual((), reagentplan.reagents(999999))
        plan = reagentplan.plan("Grug", 999999, {}, KINDS, {})
        self.assertFalse(plan.judged)
        self.assertTrue(plan.fed)


class EachShortReagentHasASource(unittest.TestCase):
    def test_reagents_in_the_bags_feed_the_craft(self):
        plan = reagentplan.plan(
            "Uzza",
            MINOR_HEALING_POTION,
            {
                PEACEBLOOM: stock(bags=20),
                SILVERLEAF: stock(bags=20),
                EMPTY_VIAL: stock(bags=3),
            },
            KINDS,
            {},
        )
        self.assertTrue(plan.fed)
        self.assertEqual(3, plan.casts)
        self.assertEqual((), plan.shorts)

    def test_a_vial_in_her_own_bank_is_fetched_from_the_bank(self):
        """Uzza, measured: 20 Peacebloom and 20 Silverleaf carried, 34 vials banked."""
        plan = reagentplan.plan(
            "Uzza",
            MINOR_HEALING_POTION,
            {
                PEACEBLOOM: stock(bags=20),
                SILVERLEAF: stock(bags=20),
                EMPTY_VIAL: stock(bank=34),
            },
            KINDS,
            {"Uzza": {"alchemy": 52}},
        )
        self.assertFalse(plan.fed)
        (short,) = plan.shorts
        self.assertEqual(
            (EMPTY_VIAL, reagentplan.BANK, "Uzza"),
            (short.reagent.entry, short.source, short.who),
        )

    def test_the_mailbox_is_read_before_the_guild_bank(self):
        plan = reagentplan.plan(
            "Zug",
            ROUGH_SHARPENING_STONE,
            {ROUGH_STONE: stock(mail=5, guild_bank=35)},
            KINDS,
            {},
        )
        self.assertEqual(reagentplan.MAIL, plan.shorts[0].source)

    def test_stone_in_the_guild_vault_is_taken_from_the_vault(self):
        """Zug, measured: 0 Rough Stone carried, 35 in his guild's vault."""
        plan = reagentplan.plan(
            "Zug",
            ROUGH_SHARPENING_STONE,
            {ROUGH_STONE: stock(guild_bank=35)},
            KINDS,
            {"Zug": {"mining": 80, "blacksmithing": 9}},
        )
        self.assertEqual(reagentplan.GUILD_BANK, plan.shorts[0].source)

    def test_a_vendor_reagent_held_nowhere_is_bought(self):
        plan = reagentplan.plan(
            "Ugga",
            MINOR_HEALING_POTION,
            {PEACEBLOOM: stock(bags=5), SILVERLEAF: stock(bags=5)},
            KINDS,
            {},
        )
        (short,) = plan.shorts
        self.assertEqual(reagentplan.VENDOR, short.source)

    def test_ore_held_nowhere_is_gathered_by_the_family_miner(self):
        plan = reagentplan.plan(
            "Grug",
            ROUGH_SHARPENING_STONE,
            {},
            KINDS,
            {"Grug": {"blacksmithing": 22, "mining": 60}},
        )
        (short,) = plan.shorts
        self.assertEqual((reagentplan.GATHER, "Grug"), (short.source, short.who))

    def test_another_member_gathers_when_the_crafter_cannot(self):
        plan = reagentplan.plan(
            "Grog",
            ROUGH_SHARPENING_STONE,
            {},
            KINDS,
            {"Grog": {"engineering": 25}, "Zrog": {"mining": 40}},
        )
        self.assertEqual("Zrog", plan.shorts[0].who)

    def test_a_reagent_nobody_gathers_or_sells_goes_to_the_house(self):
        plan = reagentplan.plan(
            "Grug", ROUGH_SHARPENING_STONE, {}, KINDS, {"Grug": {"blacksmithing": 22}}
        )
        self.assertEqual(reagentplan.AUCTION, plan.shorts[0].source)

    def test_a_bank_too_small_for_one_cast_is_not_the_source(self):
        plan = reagentplan.plan(
            "Og", 2963, {2589: stock(bags=0, bank=1)}, {2589: (7, 5)}, {}
        )
        self.assertNotEqual(reagentplan.BANK, plan.shorts[0].source)


class TheStallIsOnePlainLine(unittest.TestCase):
    def test_the_line_names_what_is_missing_and_where_from(self):
        plan = reagentplan.plan(
            "Zug",
            ROUGH_SHARPENING_STONE,
            {ROUGH_STONE: stock(guild_bank=35)},
            KINDS,
            {},
        )
        line = reagentplan.line(plan)
        self.assertNotIn("\n", line)
        for word in ("Zug", "2660", "Rough Stone", "0 of 1", "guild bank", "35"):
            self.assertIn(word, line)

    def test_every_short_reagent_is_in_the_one_line(self):
        plan = reagentplan.plan(
            "Ugga", MINOR_HEALING_POTION, {}, KINDS, {"Ugga": {"herbalism": 120}}
        )
        line = reagentplan.line(plan)
        for word in ("Peacebloom", "Silverleaf", "Empty Vial", "vendor", "herbalism"):
            self.assertIn(word, line)


class TheBankAndTheVaultAreToldWhatToFetch(unittest.TestCase):
    def test_bank_wants_are_the_bank_sourced_entries_per_crafter(self):
        plans = [
            reagentplan.plan(
                "Uzza",
                MINOR_HEALING_POTION,
                {
                    PEACEBLOOM: stock(bags=9),
                    SILVERLEAF: stock(bags=9),
                    EMPTY_VIAL: stock(bank=34),
                },
                KINDS,
                {},
            ),
            reagentplan.plan(
                "Zug",
                ROUGH_SHARPENING_STONE,
                {ROUGH_STONE: stock(guild_bank=35)},
                KINDS,
                {},
            ),
        ]
        self.assertEqual(
            {"Uzza": frozenset({EMPTY_VIAL})}, reagentplan.bank_wants(plans)
        )

    def _zug_plan(self):
        return reagentplan.plan(
            "Zug",
            ROUGH_SHARPENING_STONE,
            {ROUGH_STONE: stock(guild_bank=35)},
            KINDS,
            {},
        )

    def test_the_crafter_takes_one_vault_stack_for_its_craft(self):
        stacks = [
            bankforecast.Stack(guid=11, entry=ROUGH_STONE, count=20),
            bankforecast.Stack(guid=12, entry=ROUGH_STONE, count=15),
        ]
        taker = bankforecast.Withdrawer("Zug", 1, 3, {0: 5})
        out, notes = reagentplan.vault_withdrawals(
            [self._zug_plan()], {"Zug": stacks}, [taker]
        )
        (taken,) = out
        self.assertEqual("Zug", taken.character)
        self.assertEqual(reagentplan.VAULT_SOURCE, taken.source)
        self.assertEqual("bank withdraw-item guid:11 tab:0", taken.command)
        self.assertIn("2660", taken.line)
        self.assertEqual((), notes)

    def test_no_room_or_no_right_takes_nothing_and_says_so(self):
        stacks = {"Zug": [bankforecast.Stack(guid=11, entry=ROUGH_STONE, count=20)]}
        for taker in (
            [bankforecast.Withdrawer("Zug", 1, 0, {0: 5})],
            [bankforecast.Withdrawer("Zug", 1, 3, {})],
            [],
        ):
            out, notes = reagentplan.vault_withdrawals(
                [self._zug_plan()], stacks, taker
            )
            self.assertEqual((), out)
            self.assertEqual(1, len(notes))
            self.assertIn("Rough Stone", notes[0])

    def test_a_craft_withdrawal_is_never_read_as_one_for_the_house(self):
        self.assertIn(
            "source <> '%s'" % reagentplan.VAULT_SOURCE, bankforecast.WITHDRAWN_SQL
        )

    def test_the_withdrawal_quacks_like_the_queue_expects(self):
        taken = reagentplan.VaultWithdrawal(
            "Zug",
            bankforecast.Stack(guid=11, entry=ROUGH_STONE, count=20),
            "Rough Stone",
            ROUGH_SHARPENING_STONE,
        )
        self.assertIsInstance(taken.line, str)
        self.assertTrue(taken.command.startswith("bank withdraw-item "))
        self.assertEqual(reagentplan.VAULT_SOURCE, taken.source)


if __name__ == "__main__":
    unittest.main()
