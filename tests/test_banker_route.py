"""The item plan's BANKER route: send a stack to the guild's bankers by mail.

A stack no keep, bank, vault, give or listing route can hold used to fall to a
vendor sale (or stay put with no room). With a banker that has room, a stack
worth keeping goes to the banker instead, and junk still goes to the vendor.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import itemplan  # noqa: E402
from itemplan import BANKER, SELL_VENDOR, Context  # noqa: E402
from test_itemplan import decide, member, one, stack  # noqa: E402

PALADIN = 2


def surplus(**kw):
    # A trade good no crafter in reach uses, worth 40 silver the stack.
    base = dict(
        entry=8956, name="Flask of Mojo", item_class=7, subclass=11, sell=200, count=20
    )
    base.update(kw)
    return stack(**base)


def holder(**kw):
    # A paladin with no bank room (28 slots less the 2 kept) and no vault.
    return member(cls=PALADIN, bank_slots=2, **kw)


class BankerTakesWhatNothingElseCan(unittest.TestCase):
    def test_a_worth_keeping_stack_goes_to_the_banker(self):
        s = surplus()
        d = one([s], [holder()], s, Context(banker_free={"Fam": 4}))
        self.assertEqual(BANKER, d.route)
        self.assertIn("banker", d.reason)

    def test_without_a_banker_the_plan_is_what_it_was(self):
        s = surplus()
        for ctx in (
            Context(),
            Context(banker_free={}),
            Context(banker_free={"Fam": 0}),
        ):
            d = one([s], [holder()], s, ctx)
            self.assertNotEqual(BANKER, d.route)
            self.assertNotIn(BANKER, d.options)

    def test_another_family_banker_room_does_not_count(self):
        s = surplus()
        d = one([s], [holder()], s, Context(banker_free={"Other": 9}))
        self.assertNotEqual(BANKER, d.route)

    def test_junk_still_goes_to_the_vendor(self):
        grey = surplus(entry=1, name="Tattered Cloth", quality=0, sell=3, count=5)
        d = one([grey], [holder()], grey, Context(banker_free={"Fam": 4}))
        self.assertEqual(SELL_VENDOR, d.route)
        self.assertNotIn(BANKER, d.options)

    def test_a_soulbound_stack_is_never_mailed(self):
        s = surplus(soulbound=True, bind=1)
        by_key, _ = decide([s], [holder()], Context(banker_free={"Fam": 4}))
        self.assertNotIn(BANKER, by_key[s.key].options)

    def test_the_bankers_room_is_shared_out_one_slot_a_stack(self):
        stacks = [surplus(entry=8956 + i, name="Flask %d" % i) for i in range(3)]
        by_key, _ = decide(stacks, [holder()], Context(banker_free={"Fam": 2}))
        routes = [by_key[s.key].route for s in stacks]
        self.assertEqual(2, routes.count(BANKER))

    def test_a_banked_stack_is_left_in_the_bank(self):
        s = surplus(loc="bank")
        by_key, _ = decide([s], [holder()], Context(banker_free={"Fam": 4}))
        self.assertNotIn(BANKER, by_key[s.key].options)

    def test_banker_is_a_route_and_not_irreversible(self):
        self.assertIn(BANKER, itemplan.ROUTES)
        self.assertNotIn(BANKER, itemplan.IRREVERSIBLE)


if __name__ == "__main__":
    unittest.main()
