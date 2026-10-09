"""A bag's tooltip says how many slots it holds.

Grug's Journeyman's Backpack read "Item Level 45 / Bag" with no number
(operator, 2026-10-08). The client draws "16 Slot Bag" under the binding line.
"""

import unittest
from pathlib import Path

import armory

HERE = Path(__file__).resolve().parent.parent
BOOK = armory.ItemBook.load(".")


def bag(**kw):
    row = {
        "entry": 900002,
        "item_name": "Journeyman's Backpack",
        "quality": 1,
        "item_level": 45,
        "max_durability": 0,
        "class": 1,
        "subclass": 0,
        "inventory_type": 18,
        "required_level": 0,
        "allowable_class": -1,
        "sell_price": 62_50,
        "container_slots": 16,
    }
    row.update(kw)
    return row


class TheBagSizeIsOnTheTooltip(unittest.TestCase):
    def test_a_bag_says_its_slots(self):
        tip = armory.template_tooltip(bag(), BOOK)
        self.assertEqual(tip["container"], "16 Slot Bag")

    def test_a_special_bag_names_its_kind(self):
        tip = armory.template_tooltip(bag(subclass=2, container_slots=14), BOOK)
        self.assertEqual(tip["container"], "14 Slot Herb Bag")

    def test_a_quiver_says_its_slots(self):
        tip = armory.template_tooltip(
            bag(**{"class": 11, "subclass": 2, "container_slots": 18}), BOOK
        )
        self.assertEqual(tip["container"], "18 Slot Quiver")

    def test_a_non_container_has_no_line(self):
        tip = armory.template_tooltip(
            bag(**{"class": 4, "subclass": 3, "container_slots": 0}), BOOK
        )
        self.assertIsNone(tip["container"])

    def test_the_page_draws_the_line(self):
        page = (HERE / "classic.html").read_text()
        self.assertIn('if (t.container) add("", t.container);', page)


if __name__ == "__main__":
    unittest.main()
