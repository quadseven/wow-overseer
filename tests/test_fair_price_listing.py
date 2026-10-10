"""A stack clearance lists at the fair price is listed at the fair price.

Measured on the dev realm 2026-10-10 (read-only): the auction house held 0
auctions, and no auction row had been written since 2026-10-05. The bank
forecast (#728) lists Cave's vault surplus "at 5s 46c each" for Linen Cloth,
priced from the house's own history, and clearance routes a carried stack past
the guild's target to AUCTION at "the live or fair price"
(`clearance._past_target_route`).

Then the listing dropped it. `_clearance_listings` carried no price, and
`_auction_sell_house` priced every candidate from the live listings alone, so
`auction.plan_sales` refused each one as `market_price <= 0`. On a house with
no listing of the entry (today: every entry), a stack routed to the auction
house was never listed, never sold and never vendored: it stayed in the bags.
The pass still aimed the leader at an auctioneer for it on bag pressure, and
the log said "took the travel column on bag pressure for a list walk and wrote
nothing yet". The vault withdrawal (#750) takes up to eight vault stacks a
visit into the guild master's bags for exactly this listing.

Pinned here: an AUCTION route carries the per-unit price it was judged at, the
listing candidate carries it, and a house with no live listing of the entry
prices the candidate at it. A live listing still wins.
"""

import pathlib
import re
import sys
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import auction  # noqa: E402
import clearance  # noqa: E402
import guildshare  # noqa: E402

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
LINEN = 2589
FAIR = 546
OVER = "the guild holds 1415 Linen Cloth against a target of 797"


def linen(guid=9001, holder="Grug", count=20):
    return clearance.Stack(
        holder=holder,
        guid=guid,
        entry=LINEN,
        name="Linen Cloth",
        item_class=7,
        count=count,
        quality=1,
        sell_price=13,
        subclass=5,
        material=True,
    )


GRUG = clearance.Person("Grug", {guildshare.SKILL_LINES["first aid"]: 12}, True, True)


def routed(market=None):
    (route,) = clearance.plan(
        [linen()],
        [GRUG],
        market=market or {},
        auction_open=True,
        over_target={LINEN: OVER},
        fair={LINEN: FAIR},
        short={},
    )
    return route


class TheRouteCarriesItsPrice(unittest.TestCase):
    def test_a_past_target_stack_on_an_empty_house_is_listed_at_the_fair_price(self):
        route = routed()
        self.assertEqual(clearance.AUCTION, route.route)
        self.assertEqual(FAIR, route.price)

    def test_a_live_listing_prices_it_instead(self):
        route = routed({LINEN: 700})
        self.assertEqual(clearance.AUCTION, route.route)
        self.assertEqual(700, route.price)

    def test_a_route_that_is_not_a_listing_has_no_price(self):
        (route,) = clearance.plan(
            [linen()],
            [GRUG],
            auction_open=False,
            over_target={LINEN: OVER},
            fair={LINEN: FAIR},
        )
        self.assertNotEqual(clearance.AUCTION, route.route)
        self.assertEqual(0, route.price)


def candidate(**extra):
    row = {
        "holder": "Grug",
        "item_guid": 9001,
        "entry": LINEN,
        "label": "Linen Cloth",
        "quality": 1,
        "binding": "none",
        "quest_item": False,
        "sell_price": 13,
        "count": 20,
    }
    row.update(extra)
    return row


class TheHousePricesTheCandidate(unittest.TestCase):
    def test_no_live_listing_lists_at_the_routes_price(self):
        (priced,) = auction.price_candidates([candidate(fair_price=FAIR)], {})
        self.assertEqual(FAIR, priced["market_price"])
        (sale,) = auction.plan_sales([priced])
        self.assertEqual(FAIR * 20, sale.buyout)

    def test_a_live_listing_wins(self):
        (priced,) = auction.price_candidates([candidate(fair_price=FAIR)], {LINEN: 480})
        self.assertEqual(480, priced["market_price"])

    def test_no_price_at_all_is_still_not_listed(self):
        (priced,) = auction.price_candidates([candidate()], {})
        self.assertEqual(0, priced["market_price"])
        self.assertEqual((), auction.plan_sales([priced]))


class TheBridgeWiring(unittest.TestCase):
    def setUp(self):
        self.src = BRIDGE.read_text(encoding="utf-8")

    def block(self, signature):
        start = self.src.index(signature)
        indent = len(signature) - len(signature.lstrip())
        rest = self.src[start:]
        end = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
        return rest[: end.start() + 1] if end else rest

    def test_the_listing_candidate_carries_the_routes_price(self):
        self.assertIn('"fair_price": r.price', self.block("def _clearance_listings("))

    def test_each_house_prices_through_the_one_rule(self):
        body = self.block("    async def _auction_sell_house(")
        self.assertIn("auction.price_candidates(house_candidates, market)", body)
        self.assertNotIn('candidate["market_price"] = market.get(', body)


if __name__ == "__main__":
    unittest.main()
