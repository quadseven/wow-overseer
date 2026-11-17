"""A raid seat on a town stop lists the surplus the item plan routes to the
auction house (#2611, part 2).

The real economy only: the plan's own AUCTION route at its own price, never a
bound, quest or kept item, and never stock made up. The seams driven are
`seatbags.plan_for` and `relieve` (what is listed), `guildjobs.plan` (the walk
and the rows) and the bridge's own auctioneer read and seat pass.
"""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest import mock

import auction
import guildjobs
import seatbags
from test_guild_seat_bags import SEAT, extras_for, row, seat
from test_guildjobs import only_step, plan
from test_guildsocial_bridge import bridge

SWORD = 301
COUNTER = guildjobs.Spot(
    kind="creature", spawn=555, map_id=0, x=-9050.0, y=105.0, name="Auctioneer", near=4
)
FAR_COUNTER = guildjobs.Spot(
    kind="creature", spawn=556, map_id=0, x=-8000.0, y=105.0, name="Faraway"
)
ALLIANCE_FACTION = 12
HORDE_FACTION = 29
NEUTRAL_FACTION = 120


def rows():
    return [
        row(1, 100, "Broken Whistle", sell=40),
        row(2, 200, "Tattered Letter", item_class=12, sell=0, quest_item=True),
        row(5, SWORD, "Fine Sword", quality=2, sell=3000, item_class=2),
    ]


def extras(**over):
    base = replace(extras_for(rows()), market={100: (400, 3), SWORD: (50000, 2)})
    return replace(base, **over)


def plan_for(**kw):
    return seatbags.plan_for([SEAT], "Cave", rows(), {SEAT: 2}, extras(), **kw)


class WhatIsListed(unittest.TestCase):
    def test_nothing_is_listed_while_the_switch_is_off(self):
        with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "off"}):
            self.assertEqual(plan_for().auctions, {})

    def test_the_plans_auction_stack_is_listed_at_the_plans_price(self):
        with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "on"}):
            got = plan_for()
        (sale,) = got.auctions[SEAT]
        self.assertEqual(sale.candidate.entry, SWORD)
        self.assertEqual(sale.buyout, 50000)
        self.assertEqual(sale.bid, 40000)
        self.assertEqual(sale.hours, 12)

    def test_a_quest_stack_and_a_vendor_stack_are_never_listed(self):
        with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "on"}):
            got = plan_for()
        listed = {s.candidate.entry for s in got.auctions[SEAT]}
        self.assertNotIn(200, listed)
        self.assertNotIn(100, listed)

    def test_a_rare_is_never_listed(self):
        rare = [row(7, 400, "Rare Blade", quality=3, sell=9000, item_class=2)]
        ex = replace(extras_for(rare), market={400: (900000, 2)})
        with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "on"}):
            got = seatbags.plan_for([SEAT], "Cave", rare, {SEAT: 2}, ex)
        self.assertEqual(got.auctions, {})

    def test_no_market_and_no_vendor_quote_lists_nothing(self):
        ex = replace(extras_for(rows()), market={})
        with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "on"}):
            got = seatbags.plan_for([SEAT], "Cave", rows(), {SEAT: 2}, ex)
        self.assertEqual(got.auctions, {})


class TheCounter(unittest.TestCase):
    def test_a_counter_the_team_can_shop_at_is_the_nearest_chosen(self):
        m = seat(race=1)
        counters = [(FAR_COUNTER, ALLIANCE_FACTION), (COUNTER, ALLIANCE_FACTION)]
        self.assertEqual(seatbags.nearest_auctioneer(m, counters, 5000), COUNTER)

    def test_an_enemy_counter_is_not_chosen_but_a_neutral_one_is(self):
        m = seat(race=1)
        self.assertIsNone(
            seatbags.nearest_auctioneer(m, [(COUNTER, HORDE_FACTION)], 5000)
        )
        self.assertEqual(
            seatbags.nearest_auctioneer(m, [(COUNTER, NEUTRAL_FACTION)], 5000),
            COUNTER,
        )

    def test_a_counter_on_another_map_or_past_the_cap_is_not_chosen(self):
        m = seat(race=1)
        elsewhere = replace(COUNTER, map_id=1)
        self.assertIsNone(
            seatbags.nearest_auctioneer(m, [(elsewhere, ALLIANCE_FACTION)], 5000)
        )
        self.assertIsNone(
            seatbags.nearest_auctioneer(m, [(FAR_COUNTER, ALLIANCE_FACTION)], 100)
        )

    def test_attach_puts_the_listings_and_the_counter_on_the_seat(self):
        with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "on"}):
            got = plan_for()
        (out,) = seatbags.attach(
            [seat(race=1)], got, (), 5000, True, [(COUNTER, ALLIANCE_FACTION)]
        )
        self.assertEqual(len(out.plan_auctions), 1)
        self.assertEqual(out.auctioneer, COUNTER)


def listing_seat(**over):
    with mock.patch.dict(os.environ, {"ITEMPLAN_AUCTION": "on"}):
        got = plan_for()
    base = dict(race=1, free_slots=30, money=1_000_000)
    base.update(over)
    (out,) = seatbags.attach(
        [seat(**base)], got, (), 5000, True, [(COUNTER, ALLIANCE_FACTION)]
    )
    return out


def nothing_before(test):
    # The trainer and profession rungs come first for a seat that lacks a trade;
    # these tests are about the auction rung.
    answers = {
        "_profession_first": lambda *a, **k: (None, ""),
        "_train_step": lambda *a, **k: (None, ""),
        "_learn_step": lambda *a, **k: None,
    }
    for name, answer in answers.items():
        patch = mock.patch.object(guildjobs, name, answer)
        patch.start()
        test.addCleanup(patch.stop)


def recent_auction(age, **over):
    base = dict(
        name=SEAT,
        action=guildjobs.SEAT_AUCTION_ACTION,
        age_minutes=age,
        status="applied",
        command="list guid:5 bid:1 buyout:2 hours:12",
    )
    base.update(over)
    return guildjobs.Recent(**base)


class TheStep(unittest.TestCase):
    def setUp(self):
        nothing_before(self)

    def step(self, m, recent=()):
        return only_step(plan([m], recent=tuple(recent)), SEAT)

    def test_a_seat_away_from_the_counter_walks_there_then_lists(self):
        step = self.step(listing_seat())
        self.assertEqual(step.action, guildjobs.SEAT_AUCTION_ACTION)
        self.assertIn("walk-to-spawn creature:555", step.walk.command)
        self.assertEqual(len(step.rows), 1)
        self.assertEqual(step.rows[0].kind, auction.AUCTION_KIND)
        self.assertTrue(step.rows[0].command.startswith("list guid:5 "))

    def test_a_seat_at_the_counter_lists_without_a_walk(self):
        step = self.step(listing_seat(x=COUNTER.x + 2, y=COUNTER.y))
        self.assertIsNone(step.walk)

    def test_a_seat_that_cannot_cover_the_deposit_lists_nothing(self):
        step = self.step(listing_seat(money=1))
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_AUCTION_ACTION)

    def test_a_seat_in_a_fight_is_not_sent(self):
        step = self.step(listing_seat(in_combat=True))
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_AUCTION_ACTION)

    def test_a_seat_listed_lately_waits(self):
        step = self.step(listing_seat(), [recent_auction(5)])
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_AUCTION_ACTION)

    def test_a_seat_is_asked_again_after_the_cooldown(self):
        age = guildjobs.SEAT_AUCTION_COOLDOWN_MINUTES + 1
        step = self.step(listing_seat(), [recent_auction(age)])
        self.assertEqual(step.action, guildjobs.SEAT_AUCTION_ACTION)

    def test_an_out_of_reach_answer_is_retried_after_the_short_wait(self):
        age = guildjobs.LEVEL_TRANSIENT_RETRY_MINUTES + 1
        refused = recent_auction(
            age,
            status="error",
            reason=auction.OUT_OF_REACH,
            result=auction.OUT_OF_REACH,
        )
        step = self.step(listing_seat(), [refused])
        self.assertEqual(step.action, guildjobs.SEAT_AUCTION_ACTION)
        fresh = recent_auction(
            1, status="error", reason=auction.OUT_OF_REACH, result=auction.OUT_OF_REACH
        )
        again = self.step(listing_seat(), [fresh])
        self.assertNotEqual(getattr(again, "action", ""), guildjobs.SEAT_AUCTION_ACTION)

    def test_a_batch_is_capped(self):
        sales = tuple(listing_seat().plan_auctions) * (guildjobs.SEAT_AUCTION_BATCH + 3)
        step = self.step(replace(listing_seat(), plan_auctions=sales))
        self.assertEqual(len(step.rows), guildjobs.SEAT_AUCTION_BATCH)

    def test_a_seat_with_no_listings_gets_no_step(self):
        step = self.step(seat(free_slots=30))
        self.assertNotEqual(getattr(step, "action", ""), guildjobs.SEAT_AUCTION_ACTION)


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=()):
        self.log.append((sql, params))

    def fetchall(self):
        return [
            {
                "spawn": 555,
                "map_id": 0,
                "x": -9050.0,
                "y": 105.0,
                "name": "Auctioneer",
                "faction": ALLIANCE_FACTION,
            }
        ]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return FakeCursor(self.log)


class TheBridgePass(unittest.TestCase):
    def setUp(self):
        nothing_before(self)
        self.sql = []
        patch = mock.patch.object(bridge, "_connect", lambda: FakeConn(self.sql))
        patch.start()
        self.addCleanup(patch.stop)
        memo = mock.patch.object(bridge, "_SEAT_MEMO", seatbags.Memo())
        memo.start()
        self.addCleanup(memo.stop)

    def test_the_auctioneer_read_names_the_spawn_and_its_faction(self):
        ((spot, faction),) = bridge._fetch_seat_auctioneers([0])
        self.assertEqual((spot.spawn, spot.map_id, faction), (555, 0, ALLIANCE_FACTION))
        self.assertEqual(spot.near, int(guildjobs.AUCTION_NEAR))
        self.assertIn(bridge.NPC_FLAG_AUCTIONEER, self.sql[0][1])

    def test_no_maps_is_no_read(self):
        self.assertEqual(bridge._fetch_seat_auctioneers([]), ())
        self.assertEqual(self.sql, [])

    def test_the_seat_pass_attaches_the_listing_and_the_plan_sends_it(self):
        def read(names):
            return ("Cave", rows(), {SEAT: 2}, extras(), (), (), ())

        with (
            mock.patch.object(bridge, "_read_seat_bags", read),
            mock.patch.object(bridge, "_fetch_banker_spots", lambda maps: ()),
            mock.patch.dict(
                os.environ, {"ITEMPLAN_AUCTION": "on", "ITEMPLAN_SELL_VENDOR": "on"}
            ),
        ):
            (m,), _ = bridge._seat_bag_relief(
                [seat(race=1, free_slots=2, money=1_000_000)], 5000
            )
        self.assertEqual(len(m.plan_auctions), 1)
        self.assertEqual(m.auctioneer.spawn, 555)
        step = only_step(plan([replace(m, free_slots=30)]), SEAT)
        self.assertEqual(step.action, guildjobs.SEAT_AUCTION_ACTION)


if __name__ == "__main__":
    unittest.main()
