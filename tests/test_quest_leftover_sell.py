"""A member sells the quest leftovers no open quest asks for (#1592, #1813).

Read on the dev realm on 2026-11-08 (read-only SELECT on character_inventory,
item_instance and item_template): 120 of the 162 members of Cave and Bonkers
had one free bag slot or fewer, and their bags held 3,757 slots. 944 of them
were quest-class stacks. Only 551 were needed: 381 named by a quest in the
holder's log and 172 starting a quest the holder was never rewarded. The other
396 were leftovers, 222 of them with a vendor price (about 30g, in 82 members:
Security DELTA Data Access Card 38 times, Small Furry Paw 29, Grime-Encrusted
Object 25). The members' carried read never selected a quest-class stack and
the verdict kept the class outright, so the sale could not offer one. Selling
only those 222 stacks would take 57 of the 120 members above one free slot.

The rule now: a white or grey quest-class stack with a price that
bag_pressure.QUEST_NEEDED_SQL no longer protects sells. A stack whose row does
not say, a needed one, an uncommon one and one with no price stay.
"""

import dataclasses
import unittest

import guildjobs
import keep
import vendorsale
from test_guildsocial_bridge import bridge
from test_member_income import CRYSTAL, MOUNT, bonk

# Small Furry Paw as item_template has it: a white quest-class stack with a
# price, a drop for a quest the member no longer has.
PAW = guildjobs.Carried(
    guid=7101,
    entry=5134,
    name="Small Furry Paw",
    count=5,
    item_class=12,
    quality=1,
    sell_price=92,
    item_level=1,
    quest_needed=False,
)
NEEDED = dataclasses.replace(PAW, guid=7102, name="Needed Paw", quest_needed=True)
UNSAID = guildjobs.Carried(
    guid=7103, entry=5134, name="Unsaid Paw", item_class=12, quality=1, sell_price=92
)
UNPRICED = dataclasses.replace(PAW, guid=7104, name="Unpriced Note", sell_price=0)
BLUE_LEFTOVER = dataclasses.replace(PAW, guid=7105, name="Blue Leftover", quality=3)


def full(*carried):
    return bonk(
        name="Ekka", level=35, free_slots=0, bag_slots=16, carried=tuple(carried)
    )


def sold(member, kept=None):
    return {c.name for c in guildjobs.vendor_stacks(member, kept)}


class AQuestLeftoverNothingAsksForSells(unittest.TestCase):
    def test_the_verdict_sells_it(self):
        verdict = vendorsale.verdict(PAW, guildjobs.vendor_judge(full(PAW)))
        self.assertIs(vendorsale.SELL, verdict[0])
        self.assertIn("no open quest", verdict[1])

    def test_a_full_member_walks_to_sell_only_the_leftover(self):
        member = full(PAW, NEEDED, UNPRICED, BLUE_LEFTOVER, MOUNT)
        self.assertEqual({PAW.name}, sold(member))
        step = guildjobs._full_bags_first(member, None, (), 600.0)
        self.assertIsNotNone(step)
        self.assertEqual("sell", step.action)
        self.assertEqual({"guid:%d" % PAW.guid}, {r.command for r in step.rows})


class AQuestItemStillNeededStays(unittest.TestCase):
    def test_a_needed_stack_is_kept(self):
        verdict = vendorsale.verdict(NEEDED, guildjobs.vendor_judge(full(NEEDED)))
        self.assertEqual((vendorsale.KEEP, "a quest item"), verdict)

    def test_a_row_that_does_not_say_is_kept(self):
        self.assertTrue(UNSAID.quest_needed)
        self.assertEqual(set(), sold(full(UNSAID)))

    def test_the_existing_fixture_without_the_flag_is_kept(self):
        self.assertEqual(set(), sold(full(CRYSTAL)))

    def test_an_unpriced_or_uncommon_leftover_is_kept(self):
        self.assertEqual(set(), sold(full(UNPRICED, BLUE_LEFTOVER)))

    def test_a_reservation_still_holds_it(self):
        kept = keep.with_guids(keep.Reservations(), [("Ekka", PAW.guid)])
        self.assertEqual(set(), sold(full(PAW), kept=kept))


class TheBridgeReadsTheQuestNeed(unittest.TestCase):
    def test_the_carried_read_selects_priced_quest_stacks_and_the_need(self):
        sql = bridge._JOB_ITEMS_SQL
        self.assertIn("it.class = 12 AND it.Quality <= 1 AND it.SellPrice > 0", sql)
        self.assertIn("AS quest_needed", sql)
        self.assertIn("character_queststatus_rewarded", sql)

    def test_a_row_flagged_not_needed_is_carried_so(self):
        rows = [
            dict(owner=5, item_guid=1, entry=5134, quest_needed=0, **{"class": 12}),
            dict(owner=5, item_guid=2, entry=5134, quest_needed=1),
            dict(owner=5, item_guid=3, entry=5134),
        ]
        carried = guildjobs.carried_from_rows(rows)[5]
        self.assertEqual([False, True, True], [c.quest_needed for c in carried])


if __name__ == "__main__":
    unittest.main()
