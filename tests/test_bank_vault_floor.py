"""The guild vault keeps a floor of free Materials slots for the reagents the
family's crafters need next.

A vault at 97 of 98 stacks of other goods left a crafter on a low rung with no
place for the Rough Stone or Light Leather the corps carried. The floor is read
from each crafter's current recipe, never from a fixed list.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bank  # noqa: E402
from test_bank import row  # noqa: E402

ROUGH_STONE = 2835
LIGHT_LEATHER = 2318
NAMED = {ROUGH_STONE: ("blacksmithing",), LIGHT_LEATHER: ("leatherworking",)}


def guild(items):
    return {
        "purchased_tabs": 1,
        "deposit_rank_ids": [0],
        "member_ranks": {"Ugga": 0, "Zug": 0, "Bork": 0},
        "tab_items": {0: items},
    }


def rows():
    # The agates are the bigger pile, so they are offered to the vault first.
    return [
        row(
            holder="Ugga",
            item_guid=2,
            name="Moss Agate",
            entry=1206,
            item_class=3,
            quality=2,
            count=50,
            slot=23,
        ),
        row(
            holder="Ugga",
            item_guid=1,
            name="Rough Stone",
            entry=ROUGH_STONE,
            item_class=7,
            quality=1,
            count=20,
            slot=24,
        ),
    ]


def plan(items, held):
    names = ["Ugga", "Zug", "Bork"]
    storage = bank.storage_from(held, guild=guild(items), named=NAMED)
    return bank.plan(
        bank.members_from_rows(rows(), names),
        bank.family_from_skills(held),
        storage=storage,
    )


def vaulted(result):
    return sorted(m.item for m in result.guild)


class TheLastFreeSlotIsForTheNextRung(unittest.TestCase):
    HELD = {"Ugga": {"herbalism": 10}, "Zug": {"blacksmithing": 9}}

    def test_a_reagent_takes_the_slot_a_gem_may_not(self):
        self.assertEqual(["Rough Stone"], vaulted(plan(97, self.HELD)))

    def test_the_refused_gem_goes_to_its_holders_own_bank(self):
        result = plan(97, self.HELD)
        self.assertEqual(["Moss Agate"], [m.item for m in result.moves])

    def test_a_tab_above_the_floor_behaves_as_before(self):
        self.assertEqual(["Moss Agate", "Rough Stone"], vaulted(plan(96, self.HELD)))

    def test_a_full_tab_takes_nothing(self):
        self.assertEqual([], vaulted(plan(98, self.HELD)))


class TheFloorFollowsTheCraftersRecipes(unittest.TestCase):
    def test_no_crafter_on_stone_means_no_floor(self):
        held = {"Ugga": {"herbalism": 10}}
        self.assertEqual(["Moss Agate"], vaulted(plan(97, held)))

    def test_a_crafter_past_the_stone_rung_means_no_floor(self):
        # Rough Sharpening Stone is worth casting to skill 29 only.
        held = {"Ugga": {"herbalism": 10}, "Zug": {"blacksmithing": 200}}
        stone = bank.storage_from(held, guild=guild(97), named=NAMED)
        self.assertNotIn(ROUGH_STONE, stone.guild_reagents)

    def test_the_reagents_are_read_from_the_recipe_table(self):
        held = {"Bork": {"leatherworking": 57}}
        stone = bank.storage_from(held, guild=guild(97), named=NAMED)
        self.assertIn(LIGHT_LEATHER, stone.guild_reagents)

    def test_a_vendor_sold_reagent_is_not_reserved(self):
        held = {"Bork": {"leatherworking": 57}}
        stone = bank.storage_from(held, guild=guild(97), named=NAMED)
        self.assertNotIn(2320, stone.guild_reagents)

    def test_a_crafter_outside_the_guild_reserves_nothing(self):
        held = {"Stranger": {"blacksmithing": 9}}
        stone = bank.storage_from(held, guild=guild(97), named=NAMED)
        self.assertEqual(frozenset(), stone.guild_reagents)


if __name__ == "__main__":
    unittest.main()
