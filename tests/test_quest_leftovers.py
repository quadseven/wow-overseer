"""A quest item is one an open quest still needs, not every class-12 stack (#144).

bridge.py imports discord, so its half is read as text, the same seam
test_profession_stock.py uses. The expression itself lives in bag_pressure so
the vendor pass and the Bags page read one spelling.
"""
import pathlib
import re
import unittest

import bag_pressure

HERE = pathlib.Path(__file__).resolve().parents[1]


def _row(**kw):
    r = {"holder": "A", "item_guid": 7, "count": 20, "name": "Power Crystal",
         "quality": 1, "sell_price": 25, "quest_item": False, "reagent": False,
         "profession_needed": False}
    r.update(kw)
    return r


class TheSaleRule(unittest.TestCase):
    def test_a_leftover_no_quest_needs_is_sold(self):
        self.assertEqual(len(bag_pressure.vendor_candidates([_row()])), 1)

    def test_a_stack_an_open_quest_needs_is_never_sold(self):
        self.assertEqual(bag_pressure.vendor_candidates([_row(quest_item=True)]), ())

    def test_a_leftover_with_no_price_is_still_not_offered(self):
        self.assertEqual(bag_pressure.vendor_candidates([_row(sell_price=0)]), ())


class TheExpression(unittest.TestCase):
    def test_it_asks_the_holders_quest_log_for_every_way_a_quest_names_an_item(self):
        sql = bag_pressure.QUEST_NEEDED_SQL
        self.assertTrue(sql.startswith("(it.class = 12 AND"))
        self.assertIn("it.startquest > 0", sql)
        self.assertIn("FROM character_queststatus qs", sql)
        self.assertIn("WHERE qs.guid = ci.guid AND qs.status <> 0", sql)
        for n in range(1, 7):
            self.assertIn("qt.RequiredItemId%d" % n, sql)
        for n in range(1, 5):
            self.assertIn("qt.ItemDrop%d" % n, sql)
        self.assertIn("qt.StartItem", sql)
        self.assertEqual(sql.count("("), sql.count(")"))


class BothReadersUseIt(unittest.TestCase):
    def test_the_vendor_query_no_longer_calls_every_class_12_stack_a_quest_item(self):
        src = (HERE / "bridge.py").read_text(encoding="utf-8")
        block = src[src.index("_VENDOR_ITEMS_SQL = ("):src.index("_SURPLUS_GEAR_SQL = (")]
        self.assertIn('bag_pressure.QUEST_NEEDED_SQL + " AS quest_item', block)
        self.assertNotIn("(it.class = 12) AS quest_item", block)

    def test_the_bags_page_reads_the_same_answer(self):
        src = (HERE / "map_server.py").read_text(encoding="utf-8")
        self.assertIn('_WEALTH_QUEST_NEEDED = ", " + bag_pressure.QUEST_NEEDED_SQL'
                      ' + " AS quest_needed "', src)
        fetch = src[src.index("def _fetch_wealth"):src.index("# Everything a tooltip draws")]
        self.assertTrue(re.search(r'f"\{_WEALTH_ITEM_COLUMNS\}\{_WEALTH_QUEST_NEEDED\}"', fetch))


if __name__ == "__main__":
    unittest.main()
