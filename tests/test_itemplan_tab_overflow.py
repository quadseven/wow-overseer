"""A full vault tab overflows to another bought tab in the item plan (#2657 follow-up).

Measured on the dev realm on 2026-11-15: both family guilds stood at 98 of 98
in Materials with a second tab bought and empty, and the plan still logged
"first choice failed: GUILD_BANK: guild bank tab is full" for every recipe and
keeper. The bank pass already overflowed (#2657); the plan's GUILD_BANK option
carried one fixed tab and never looked at another.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan  # noqa: E402
from test_itemplan import decide, stack  # noqa: E402
from test_itemplan_recipe_exit import UZZA, recipe  # noqa: E402

GUILD_BANK = itemplan.GUILD_BANK


def ctx(free):
    return itemplan.Context(
        fire_gear=frozenset(),
        guild_free={("Fam", tab): n for tab, n in free.items()},
    )


def libram():
    return stack(
        holder="Uzza",
        entry=9500,
        name="Libram of Fire",
        item_class=itemplan.C_RECIPE,
        subclass=0,
        quality=2,
        sell=2000,
        required_skill_rank=0,
        required_skill=0,
    )


class TheOverflow(unittest.TestCase):
    def one(self, item, free):
        by_key, _ = decide([item], [UZZA], ctx(free))
        return by_key[item.key]

    def test_a_full_materials_tab_sends_a_seat_recipe_to_the_second_tab(self):
        d = self.one(recipe(rank=250), {0: 0, 1: 98})
        self.assertEqual((d.route, d.tab), (GUILD_BANK, 1))
        self.assertIn("tab 0 was full", d.reason)

    def test_the_first_tab_is_kept_while_it_has_room(self):
        d = self.one(recipe(rank=250), {0: 5, 1: 98})
        self.assertEqual((d.route, d.tab), (GUILD_BANK, 0))

    def test_overflow_is_spent_as_stacks_land(self):
        items = [recipe(entry=9600 + i, rank=100 + i) for i in range(3)]
        by_key, _ = decide(items, [UZZA], ctx({0: 0, 1: 2}))
        tabs = [by_key[i.key].tab for i in items if by_key[i.key].route == GUILD_BANK]
        self.assertEqual(tabs, [1, 1])

    def test_raid_supplies_never_take_the_overflow_of_another_tab(self):
        d = self.one(libram(), {0: 98, 1: 98})
        self.assertNotEqual(d.route, GUILD_BANK)

    def test_nothing_overflows_into_the_raid_tab(self):
        d = self.one(recipe(rank=250), {0: 0, 1: 0, 2: 98})
        self.assertNotEqual((d.route, d.tab), (GUILD_BANK, 2))


if __name__ == "__main__":
    unittest.main()
