"""Darkmoon deck cards, Aces and decks are never sold, banked away or destroyed.

A card has no start quest, so the quest-needed test let it go as a leftover once
the quest log was read. The deck quest hands a level 60 trinket out, so every
copy is kept. One entry list (bag_pressure.DARKMOON_ENTRIES) feeds the bag SQL,
the bank policy SQL and the item plan.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import bag_pressure  # noqa: E402
import bankpolicy  # noqa: E402
import itemplan  # noqa: E402
from itemplan import KEEP_CARRY, Context  # noqa: E402
from test_itemplan import decide, member, stack  # noqa: E402

ACE_OF_BEASTS, TWO_OF_PORTALS, WARLORDS_DECK = 19227, 19278, 19257


class TheEntryList(unittest.TestCase):
    def test_it_holds_every_ace_card_and_deck_of_the_four_suits(self):
        # 4 suits x (Ace + Two..Eight) = 32 cards, plus 4 decks.
        self.assertEqual(len(bag_pressure.DARKMOON_ENTRIES), 36)
        for entry in (ACE_OF_BEASTS, TWO_OF_PORTALS, WARLORDS_DECK, 19284, 19267):
            self.assertIn(entry, bag_pressure.DARKMOON_ENTRIES)

    def test_it_holds_no_trinket(self):
        for trinket in (19287, 19288, 19289, 19290):
            self.assertNotIn(trinket, bag_pressure.DARKMOON_ENTRIES)


class TheSql(unittest.TestCase):
    def test_the_shared_quest_needed_sql_names_every_entry(self):
        for entry in bag_pressure.DARKMOON_ENTRIES:
            self.assertIn(str(entry), bag_pressure.STACK_QUEST_NEEDED_SQL)
        self.assertEqual(
            bag_pressure.STACK_QUEST_NEEDED_SQL.count("("),
            bag_pressure.STACK_QUEST_NEEDED_SQL.count(")"),
        )

    def test_both_sql_lists_are_exactly_the_entry_set(self):
        for sql in (bag_pressure.STACK_QUEST_NEEDED_SQL, bankpolicy.ITEMS_SQL):
            body = sql.split("ii.itemEntry IN (", 1)[1].split(")", 1)[0]
            ids = {int(x) for x in body.replace(" ", "").split(",")}
            self.assertEqual(ids, set(bag_pressure.DARKMOON_ENTRIES))

    def test_the_bank_policy_copy_names_every_entry(self):
        for entry in bag_pressure.DARKMOON_ENTRIES:
            self.assertIn(str(entry), bankpolicy.ITEMS_SQL)


class ThePlan(unittest.TestCase):
    def test_a_card_is_kept_even_when_the_quest_log_was_read_and_names_it_not(self):
        card = stack(
            entry=TWO_OF_PORTALS, name="Two of Portals", item_class=12, sell=12500
        )
        ctx = Context(open_quest_items={"Ana": frozenset()}, fire_gear=frozenset())
        by_key, _ = decide([card], [member(carried_slots=1)], ctx)
        d = by_key[card.key]
        self.assertEqual((d.route, d.goal), (KEEP_CARRY, itemplan.QUEST))
        self.assertNotIn(d.route, itemplan.IRREVERSIBLE)

    def test_an_ordinary_leftover_is_still_a_leftover(self):
        junk = stack(entry=9999, name="Odd Rune", item_class=12, sell=300)
        ctx = Context(open_quest_items={"Ana": frozenset()}, fire_gear=frozenset())
        by_key, _ = decide([junk], [member(carried_slots=1)], ctx)
        self.assertNotEqual(by_key[junk.key].goal, itemplan.QUEST)


if __name__ == "__main__":
    unittest.main()
