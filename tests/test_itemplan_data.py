"""The item plan's missing inputs (#1973): quest log, worn gear, auction prices.

Pure: fixture rows shaped like the real tables, no database.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import itemplan  # noqa: E402
import itemplan_data as data  # noqa: E402
from itemplan import Context, Member, Stack  # noqa: E402

RUNE, SHIELD, ORE, SWORD = 5001, 6002, 7003, 8004


def template(quest, **kw):
    row = {"quest": quest}
    row.update(kw)
    return row


def worn_row(slot, entry, ilvl, itype, member="Ana", **kw):
    row = dict(
        member=member,
        slot=slot,
        entry=entry,
        name="W%d" % entry,
        item_class=4,
        subclass=2,
        quality=2,
        item_level=ilvl,
        inventory_type=itype,
        req_level=10,
    )
    row.update(kw)
    return row


class QuestNeeds(unittest.TestCase):
    TEMPLATES = [
        template(10, item1=RUNE, item_count1=3, item2=0, item_count2=0),
        template(11, item1=RUNE, item_count1=2, drop1=9100, start_item=9200),
    ]

    def test_quest_needing_three_of_ten(self):
        needs = data.quest_needs([{"quest": 10, "status": 3}], self.TEMPLATES)
        self.assertEqual(needs, {RUNE: 3})

    def test_two_open_quests_add_and_source_items_count_one(self):
        rows = [{"quest": 10, "status": 3}, {"quest": 11, "status": 1}]
        self.assertEqual(
            data.quest_needs(rows, self.TEMPLATES), {RUNE: 5, 9100: 1, 9200: 1}
        )

    def test_status_zero_and_unknown_quest_need_nothing(self):
        rows = [{"quest": 10, "status": 0}, {"quest": 99, "status": 3}]
        self.assertEqual(data.quest_needs(rows, self.TEMPLATES), {})

    def test_malformed_rows_are_skipped(self):
        rows = [
            None,
            "x",
            {"quest": "abc", "status": 3},
            {"status": 3},
            {"quest": 10, "status": None},
            {"quest": 10, "status": 3},
        ]
        bad = [None, {"quest": "zz"}, template(10, item1="?", item_count1=3)]
        self.assertEqual(data.quest_needs(rows, bad), {})
        # An unreadable count still protects the item: counted as 1.
        odd = [template(10, item1=RUNE, item_count1="n")]
        self.assertEqual(data.quest_needs(rows, odd), {RUNE: 1})
        self.assertEqual(data.quest_needs(rows, bad + self.TEMPLATES), {RUNE: 3})

    def test_open_quest_items_by_member(self):
        rows = [
            {"member": "Ana", "quest": 10, "status": 3},
            {"member": "Bo", "quest": 99, "status": 3},
            {"quest": 10},
            None,
        ]
        got = data.open_quest_items(rows, self.TEMPLATES)
        self.assertEqual(got, {"Ana": frozenset({RUNE}), "Bo": frozenset()})


class Equipped(unittest.TestCase):
    def test_worn_by_slot_name(self):
        got = data.equipped([worn_row(0, 1, 20, 1), worn_row(15, SWORD, 30, 13)])
        self.assertEqual(got["Ana"]["head"]["entry"], 1)
        self.assertEqual(got["Ana"]["main hand"]["entry"], SWORD)
        self.assertEqual(data.worn_entries(got), {"Ana": frozenset({1, SWORD})})

    def test_malformed_and_out_of_range_rows_are_skipped(self):
        rows = [
            None,
            {"member": "Ana"},
            worn_row(19, 3, 1, 1),
            worn_row(-1, 3, 1, 1),
            worn_row(1, 3, 1, 1, item_level="x"),
            worn_row(1, 0, 1, 1),
        ]
        self.assertEqual(data.equipped(rows), {})

    def test_better_bag_piece_is_a_wear_verdict_and_worse_is_not(self):
        worn = data.equipped([worn_row(0, 1, 20, 1)])
        bag = [
            dict(
                member="Ana",
                entry=SHIELD,
                inventory_type=1,
                item_level=30,
                req_level=10,
                level=20,
            ),
            dict(
                member="Ana",
                entry=77,
                inventory_type=1,
                item_level=10,
                req_level=10,
                level=20,
            ),
            dict(
                member="Ana",
                entry=78,
                inventory_type=1,
                item_level=40,
                req_level=50,
                level=20,
            ),
            {"member": "Ana"},
        ]
        self.assertEqual(data.upgrade_verdicts(worn, bag), {("Ana", SHIELD): "wear"})

    def test_unread_worn_gear_gives_no_verdict(self):
        bag = [
            dict(
                member="Ana",
                entry=1,
                inventory_type=1,
                item_level=30,
                req_level=10,
                level=20,
            )
        ]
        self.assertEqual(data.upgrade_verdicts({}, bag), {})

    def test_worn_item_is_never_proposed_for_sale(self):
        worn = Stack(
            holder="Ana",
            loc=itemplan.WORN,
            entry=SWORD,
            name="Blade",
            item_class=2,
            subclass=7,
            quality=2,
            count=1,
            sell=5000,
            bind=0,
            req_level=10,
            item_level=30,
        )
        plan = itemplan.plan([worn], [Member("Ana", "f", 20, 1)], Context())
        (d,) = plan.decisions
        self.assertEqual(d.route, itemplan.KEEP_CARRY)
        self.assertFalse(d.irreversible)


class AuctionPrices(unittest.TestCase):
    def listing(self, entry, buyout, count=1, **kw):
        row = dict(auction_id=1, house=2, buyout=buyout, entry=entry, count=count)
        row.update(kw)
        return row

    def test_lowest_live_per_unit_with_sample_count(self):
        rows = [
            self.listing(ORE, 2820, 20),
            self.listing(ORE, 150, 1),
            self.listing(ORE, 143, 1),
        ]
        self.assertEqual(data.auction_prices(rows), {ORE: (141, 3)})

    def test_item_with_no_listings_is_absent(self):
        got = data.auction_prices([self.listing(ORE, 150)])
        self.assertNotIn(SWORD, got)

    def test_history_prices_an_entry_with_no_live_listing(self):
        hist = [
            dict(
                house=2,
                item_entry=SWORD,
                item_count=1,
                price_paid=900,
                buyout=1000,
                bid=0,
                outcome="sold",
            )
        ]
        got = data.auction_prices([self.listing(ORE, 150)], hist, house=2)
        self.assertEqual(got[SWORD], (900, 1))
        self.assertEqual(got[ORE], (150, 1))

    def test_malformed_rows_are_skipped(self):
        rows = [
            None,
            {"entry": ORE},
            self.listing(ORE, 0),
            self.listing(ORE, "x"),
            self.listing("e", 5),
            self.listing(ORE, 90, count=None),
        ]
        self.assertEqual(
            data.auction_prices(rows, [None, {"outcome": "sold"}]), {ORE: (90, 1)}
        )

    def test_no_source_is_absent_with_a_reason(self):
        self.assertEqual(data.auction_prices([], []), {})
        self.assertIn("no auction price source", data.absent_reason([], []))
        self.assertEqual(data.absent_reason([self.listing(ORE, 5)]), "")


class PlanUsesTheData(unittest.TestCase):
    def fixture(self):
        stacks = [
            Stack(
                holder="Ana",
                loc="carried_bag",
                entry=100 + i,
                name="Q%d" % i,
                item_class=12,
                subclass=0,
                quality=1,
                count=1,
                sell=50,
                bind=0,
                index=i,
            )
            for i in range(13)
        ]
        return stacks, [Member("Ana", "f", 54, 8, carried_slots=13)]

    def test_quest_needs_frees_slots_the_unread_log_cannot(self):
        stacks, members = self.fixture()
        member = members[0]
        absent = itemplan.plan(stacks, members, Context())
        rows = [{"member": "Ana", "quest": 1, "status": 3}]
        tpl = [template(1, item1=100, item_count1=1)]
        read = itemplan.plan(
            stacks,
            members,
            Context(open_quest_items=data.open_quest_items(rows, tpl)),
        )
        self.assertGreater(
            itemplan.free_after(read, member, stacks),
            itemplan.free_after(absent, member, stacks),
        )
        kept = [d for d in read.decisions if d.route == itemplan.KEEP_CARRY]
        self.assertEqual([d.entry for d in kept], [100])


if __name__ == "__main__":
    unittest.main()
