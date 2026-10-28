"""A member with low bags sells priced loot nobody in the guild claims, and
every sale is said in the bridge log (#1592).

Read on the dev realm on 2026-10-10: about 63g of priced items sat in members'
bags (gems, uncommon armor, cloth and meat), and 59 of the 142 members had at
most one free bag slot. The rule that sells them is vendorsale.py's (#771):
a member short of loot room walks to a vendor and sells the white materials,
gems and uncommon gear it will not wear that the guild's bank forecast does
not keep. These tests pin each half of that rule, and the one line per sale
the bridge now writes, naming the member, the item and the price.
"""

import asyncio
import unittest

import guildjobs
import vendorsale
from test_guildsocial_bridge import bridge
from test_member_income import BELT, CAVE_RESERVED, LINEN, TENDERLOIN, TIGERSEYE, bonk


def sold(member, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(member, kept)}


class ALowBagMemberSells(unittest.TestCase):
    def test_it_sells_an_unwearable_green_and_an_unclaimed_gem(self):
        step = guildjobs._sell_step(bonk(), None, 600.0)
        self.assertIsNotNone(step)
        commands = {r.command for r in step.rows}
        self.assertIn("guid:%d" % BELT.guid, commands)
        self.assertIn("guid:%d" % TIGERSEYE.guid, commands)
        self.assertIn("guid:%d" % TENDERLOIN.guid, commands)

    def test_the_full_bag_walk_comes_first(self):
        self.assertTrue(guildjobs.loot_room_short(bonk()))
        step = guildjobs._full_bags_first(bonk(), None, (), 600.0)
        self.assertEqual("sell", step.action)


class AMemberWithRoomSellsNeither(unittest.TestCase):
    def test_no_sale_walk_for_a_green_and_a_gem_with_room_to_spare(self):
        member = bonk(free_slots=10, carried=(BELT, TIGERSEYE))
        self.assertFalse(guildjobs.loot_room_short(member))
        self.assertIsNone(guildjobs._sell_step(member, None, 600.0))
        self.assertIsNone(guildjobs._full_bags_first(member, None, (), 600.0))


class WhatAGuildCrafterClaimsIsKept(unittest.TestCase):
    def test_a_gem_the_forecast_keeps_for_a_crafter_stays(self):
        member = bonk(reserved=CAVE_RESERVED | {TIGERSEYE.entry})
        self.assertNotIn("Tigerseye", sold(member))
        self.assertIn("Wolf Belt", sold(member))

    def test_a_stack_a_crafter_claims_stays(self):
        self.assertNotIn(LINEN.name, sold(bonk()))
        verdict = vendorsale.verdict(LINEN, guildjobs.vendor_judge(bonk()))
        self.assertEqual(
            (vendorsale.KEEP, "the guild's bank forecast keeps it"), verdict
        )


class EverySaleIsNamed(unittest.TestCase):
    def test_each_sell_row_carries_its_sale(self):
        step = guildjobs._sell_step(bonk(), None, 600.0)
        self.assertEqual(
            [r.command for r in step.rows], [s.command for s in step.sales]
        )
        belt = vendorsale.sale_for(step.sales, "guid:%d" % BELT.guid)
        self.assertEqual(
            "Bonk sold Wolf Belt x1 for 2s 30c", vendorsale.sale_line("Bonk", belt)
        )

    def test_a_stack_is_priced_by_its_count(self):
        sale = vendorsale.sale_of("guid:%d" % TENDERLOIN.guid, TENDERLOIN)
        self.assertEqual(
            "Bonk sold Moongraze Stag Tenderloin x22 for 1s 10c",
            vendorsale.sale_line("Bonk", sale),
        )

    def test_the_money_words(self):
        self.assertEqual("13c", vendorsale.money(13))
        self.assertEqual("1g 2s 3c", vendorsale.money(10203))
        self.assertEqual("2g", vendorsale.money(20000))
        self.assertEqual("0c", vendorsale.money(0))

    def test_the_counter_walks_name_their_junk_sales(self):
        member = bonk()
        rows = guildjobs.junk_sales(member, None)
        notes = guildjobs.junk_notes(member, None)
        self.assertEqual([r.command for r in rows], [s.command for s in notes])

    def test_the_make_room_sale_names_its_stacks(self):
        step = guildjobs._room_vendor_step(bonk(), "Bonk makes room", [BELT], 600.0)
        self.assertEqual(("guid:%d" % BELT.guid,), tuple(s.command for s in step.sales))


class _Loop:
    def __init__(self, status):
        self.status = status
        self._job_walks_unsupported = {}

    async def _await_corps_answer(self, row_id, seconds):
        return {
            "status": self.status,
            "detail": "" if self.status == "delivered" else "item not carried",
        }

    async def _corps_row_again(self, step, row, row_id, detail, walk):
        return False


for _name in ("_job_row", "_note_job_walk_unsupported"):
    setattr(_Loop, _name, getattr(bridge.Bridge, _name))


class TheBridgeLogsEachSale(unittest.TestCase):
    def run_row(self, status):
        step = guildjobs._sell_step(bonk(), None, 600.0)
        row = next(r for r in step.rows if r.command == "guid:%d" % BELT.guid)
        loop = _Loop(status)
        original = bridge._insert_corps_row
        bridge._insert_corps_row = lambda holder, r: 7
        try:
            with self.assertLogs("wow-overseer", level="INFO") as logs:
                went = asyncio.run(loop._job_row(step, row, 600.0))
        finally:
            bridge._insert_corps_row = original
        return went, logs.output

    def test_a_delivered_sale_is_one_line_naming_member_item_and_price(self):
        went, lines = self.run_row("delivered")
        self.assertTrue(went)
        said = [line for line in lines if "guild jobs: sale:" in line]
        self.assertEqual(
            [
                "INFO:wow-overseer:guild jobs: sale: Bonk sold Wolf Belt x1 for 2s 30c "
                "(row 7)"
            ],
            said,
        )

    def test_a_refused_sale_is_not_said_as_sold(self):
        went, lines = self.run_row("error")
        self.assertFalse(went)
        self.assertFalse([line for line in lines if "guild jobs: sale:" in line])


if __name__ == "__main__":
    unittest.main()
