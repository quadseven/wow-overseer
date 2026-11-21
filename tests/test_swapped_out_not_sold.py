"""A piece a set swap took off is not sold while it waits in the bags (#540).

A member that swaps its worn chest for a banked set piece carries the old chest
until it is put back or banked after the run. The old chest is outgrown or
second-best as far as the vendor rules can tell, so every sale route would
let it go. `Member.swapped_out` names those guids and no sale route takes one.
"""

import dataclasses
import unittest

import guildjobs
from test_redundant_upgrades_sell import member


def old_chest(guid):
    return guildjobs.Carried(
        guid=guid,
        entry=guid,
        name="Old Chest %d" % guid,
        item_class=4,
        subclass=3,
        quality=1,
        sell_price=300,
        item_level=10,
        required_level=5,
        inventory_type=5,
    )


class ASwappedOutPieceStays(unittest.TestCase):
    def setUp(self):
        self.m = member(old_chest(7), old_chest(8))

    def test_without_the_mark_the_outgrown_chests_sell(self):
        names = {c.name for c in guildjobs.vendor_stacks(self.m, None)}
        self.assertEqual({"Old Chest 7", "Old Chest 8"}, names)

    def test_a_marked_chest_is_not_in_the_sale_stacks(self):
        m = dataclasses.replace(self.m, swapped_out=frozenset({7}))
        names = {c.name for c in guildjobs.vendor_stacks(m, None)}
        self.assertEqual({"Old Chest 8"}, names)

    def test_junk_sales_writes_no_row_for_it(self):
        m = dataclasses.replace(self.m, swapped_out=frozenset({7}))
        rows = {r.command for r in guildjobs.junk_sales(m, None)}
        self.assertEqual({"guid:8"}, rows)

    def test_the_item_plans_sale_of_it_is_dropped_too(self):
        m = dataclasses.replace(
            self.m,
            carried=(),
            plan_sales=(old_chest(7), old_chest(8)),
            swapped_out=frozenset({8}),
        )
        names = {c.name for c in guildjobs.vendor_stacks(m, None)}
        self.assertEqual({"Old Chest 7"}, names)


if __name__ == "__main__":
    unittest.main()
