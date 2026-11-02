"""Material requests (#476): routed to a gatherer or the house, acted on once.

mod-overseer's DriveCraft writes one `material-request` overseer_event row
when it skips a craft for a reagent the crafter is short of: the character,
the recipe (`subject_id`), the reagent item (`item_guid`) and a detail of the
shape "short 4x Copper Bar (needs 6, has 2)". These tests hold the site's
half: each request goes to exactly one errand, gather or buy, and a request
already acted on is not acted on again.

The last class is a contract test over bridge.py's source, in the pattern
test_craft_rhythm.py uses: the pure decision is only half of the change.
"""

import pathlib
import unittest

import auction
import craft_rhythm as cr

BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"

PEACEBLOOM = 2447
LINEN_CLOTH = 2589
COPPER_BAR = 2840
HERB, METAL, CLOTH = (7, 9), (7, 7), (7, 5)


def _row(name="Ugga", recipe=2330, entry=PEACEBLOOM, detail=None, **extra):
    row = {
        "id": 11,
        "occurrences": 1,
        "character_name": name,
        "subject_id": recipe,
        "subject_name": "Minor Healing Potion",
        "item_guid": entry,
        "detail": detail or "short 1x Peacebloom (needs 1, has 0)",
    }
    row.update(extra)
    return row


def _request(**kw):
    request = cr.material_request(_row(**kw))
    assert request is not None
    return request


class TheEventIsRead(unittest.TestCase):
    def test_the_detail_gives_the_count_short_and_the_count_needed(self):
        request = _request(
            detail="short 4x Copper Bar (needs 6, has 2)", entry=COPPER_BAR
        )
        self.assertEqual(request.character, "Ugga")
        self.assertEqual(request.recipe, 2330)
        self.assertEqual(request.entry, COPPER_BAR)
        self.assertEqual(request.label, "Copper Bar")
        self.assertEqual((request.short, request.need), (4, 6))
        self.assertEqual((request.event_id, request.occurrence), (11, 1))

    def test_a_row_of_another_kind_or_shape_is_not_a_request(self):
        self.assertIsNone(cr.material_request(_row(detail="need 6x Copper Bar")))
        self.assertIsNone(cr.material_request(_row(entry=0)))
        self.assertIsNone(cr.material_request(_row(name="")))


class EachRequestGoesToOneErrand(unittest.TestCase):
    def test_a_herb_goes_to_the_member_who_holds_herbalism(self):
        how, who, _why = cr.route_request(
            _request(), HERB, {"Ugga": {"alchemy": 14}, "Bork": {"herbalism": 40}}
        )
        self.assertEqual((how, who), (cr.ROUTE_GATHER, "Bork"))

    def test_the_requester_is_asked_first_when_it_gathers_its_own(self):
        how, who, _why = cr.route_request(
            _request(),
            HERB,
            {"Ugga": {"herbalism": 132}, "Bork": {"herbalism": 140}},
        )
        self.assertEqual((how, who), (cr.ROUTE_GATHER, "Ugga"))

    def test_a_herb_nobody_gathers_goes_to_the_auction_house(self):
        how, who, why = cr.route_request(_request(), HERB, {"Ugga": {"alchemy": 14}})
        self.assertEqual((how, who), (cr.ROUTE_BUY, "Ugga"))
        self.assertIn("herbalism", why)

    def test_cloth_is_a_kill_drop_so_the_requester_roams_for_it(self):
        request = _request(
            entry=LINEN_CLOTH, detail="short 2x Linen Cloth (needs 2, has 0)"
        )
        how, who, _why = cr.route_request(request, CLOTH, {"Ugga": {}})
        self.assertEqual((how, who), (cr.ROUTE_GATHER, "Ugga"))

    def test_an_item_whose_kind_is_unknown_is_bought_not_guessed(self):
        how, _who, why = cr.route_request(_request(), None, {"Bork": {"herbalism": 40}})
        self.assertEqual(how, cr.ROUTE_BUY)
        self.assertIn("item_template", why)


class PendingRequestsAreActedOnOnce(unittest.TestCase):
    def setUp(self):
        self.pending = {}
        self.skills = {"Ugga": {"herbalism": 132}}
        self.kinds = {PEACEBLOOM: HERB}

    def _take(self, requests, held=None, now=100.0):
        return cr.take_requests(
            self.pending, requests, self.kinds, self.skills, held or {}, now
        )

    def test_a_new_request_is_routed_once_and_then_pending(self):
        routed = self._take([_request()])
        self.assertEqual([r.how for r in routed], [cr.ROUTE_GATHER])
        self.assertEqual(self._take([_request()], now=200.0), [])
        self.assertEqual(len(self.pending), 1)

    def test_two_recipes_short_of_one_reagent_are_one_errand(self):
        routed = self._take(
            [
                _request(),
                _request(
                    recipe=2331, id=12, detail="short 3x Peacebloom (needs 3, has 0)"
                ),
            ]
        )
        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0].request.need, 3)

    def test_a_request_the_bags_already_answer_is_not_routed(self):
        self.assertEqual(self._take([_request()], held={("Ugga", PEACEBLOOM): 1}), [])
        self.assertEqual(self.pending, {})

    def test_holding_enough_closes_it_and_the_same_row_is_not_routed_again(self):
        self._take([_request()])
        closed = cr.settle_requests(self.pending, {("Ugga", PEACEBLOOM): 1})
        self.assertEqual(len(closed), 1)
        self.assertEqual(cr.open_routes(self.pending), [])
        self.assertEqual(self._take([_request()], now=300.0), [])

    def test_short_again_after_it_closed_is_a_new_request(self):
        self._take([_request()])
        cr.settle_requests(self.pending, {("Ugga", PEACEBLOOM): 1})
        again = self._take([_request(occurrences=2)], now=300.0)
        self.assertEqual(len(again), 1)

    def test_a_gather_that_has_not_closed_goes_to_the_house_once(self):
        self._take([_request()], now=0.0)
        self.assertEqual(cr.escalate_requests(self.pending, cr.GATHER_SECONDS - 1), [])
        moved = cr.escalate_requests(self.pending, cr.GATHER_SECONDS + 1)
        self.assertEqual([r.how for r in moved], [cr.ROUTE_BUY])
        self.assertEqual(cr.escalate_requests(self.pending, cr.GATHER_SECONDS * 3), [])

    def test_an_old_route_is_forgotten_with_its_event(self):
        self._take([_request()], now=0.0)
        self.assertEqual(cr.expire_requests(self.pending, cr.READ_SECONDS - 1), [])
        self.assertEqual(len(cr.expire_requests(self.pending, cr.READ_SECONDS + 1)), 1)
        self.assertEqual(self.pending, {})

    def test_a_request_still_read_keeps_its_route_past_the_window(self):
        # Routed at 0 and still reported by the module a day later: the
        # route's age is past the window but its event's is not, so it is
        # kept and the same request is not routed a second time.
        self._take([_request()], now=0.0)
        later = cr.READ_SECONDS + 100.0
        self.assertEqual(self._take([_request(age=10)], now=later), [])
        self.assertEqual(cr.expire_requests(self.pending, later + 1), [])
        self.assertEqual(self._take([_request()], now=later + 2), [])
        self.assertEqual(len(self.pending), 1)

    def test_a_route_is_forgotten_once_its_event_leaves_the_window(self):
        self._take([_request(age=600)], now=1000.0)
        seen = 400.0
        self.assertEqual(
            cr.expire_requests(self.pending, seen + cr.READ_SECONDS - 1), []
        )
        self.assertEqual(
            len(cr.expire_requests(self.pending, seen + cr.READ_SECONDS)), 1
        )

    def test_an_unchanged_last_seen_does_not_rewrite_the_route(self):
        self._take([_request(age=600)], now=1000.4)
        before = dict(self.pending)
        self._take([_request(age=660)], now=1060.9)
        self.assertEqual(self.pending, before)

    def test_the_memo_round_trip_keeps_the_route_and_its_clock(self):
        self._take([_request(age=5)], now=50.0)
        route = next(iter(self.pending.values()))
        back = cr.route_from_memo(cr.route_memo(route, 1000.0), 1000.0)
        self.assertEqual(back, route)

    def test_a_memo_written_before_the_event_clock_still_reads(self):
        self._take([_request()], now=50.0)
        memo = cr.route_memo(next(iter(self.pending.values())), 1000.0)
        del memo["seen"], memo["base"]
        back = cr.route_from_memo(memo, 1000.0)
        self.assertEqual((back.seen, back.base, back.since), (None, 0, 50.0))


class AGathererElsewhereClosesItsRoute(unittest.TestCase):
    def setUp(self):
        self.pending = {}
        skills = {"Ugga": {"alchemy": 14}, "Bork": {"herbalism": 40}}
        request = _request(detail="short 3x Peacebloom (needs 3, has 0)")
        cr.take_requests(
            self.pending,
            [request],
            {PEACEBLOOM: HERB},
            skills,
            {("Bork", PEACEBLOOM): 5},
            0.0,
        )

    def test_the_gatherers_stock_at_routing_is_its_base(self):
        route = next(iter(self.pending.values()))
        self.assertEqual(
            (route.how, route.who, route.base), (cr.ROUTE_GATHER, "Bork", 5)
        )

    def test_what_the_gatherer_gathers_closes_the_route(self):
        self.assertEqual(
            cr.settle_requests(self.pending, {("Bork", PEACEBLOOM): 7}), []
        )
        closed = cr.settle_requests(self.pending, {("Bork", PEACEBLOOM): 8})
        self.assertEqual(len(closed), 1)
        # Closed, so it is never escalated into a purchase.
        self.assertEqual(cr.escalate_requests(self.pending, cr.GATHER_SECONDS * 2), [])

    def test_the_requesters_bags_and_the_gathered_stock_add_up(self):
        held = {("Ugga", PEACEBLOOM): 1, ("Bork", PEACEBLOOM): 7}
        self.assertEqual(len(cr.settle_requests(self.pending, held)), 1)


class GatherRoutesSendTheFamilyOut(unittest.TestCase):
    def test_a_gather_route_makes_its_gatherer_short(self):
        pending = {}
        cr.take_requests(
            pending,
            [_request()],
            {PEACEBLOOM: HERB},
            {"Ugga": {"herbalism": 9}},
            {},
            0.0,
        )
        stands = (
            cr.Stand(name="Ugga", craft_spell=2330, verdict=cr.STOCKED, casts=20),
        )
        out = cr.requested_stands(stands, cr.open_routes(pending))
        self.assertEqual(out[0].verdict, cr.SHORT)
        self.assertIn("material-request", out[0].why)
        self.assertEqual(cr.rhythm(out, cr.MODE_CRAFT).mode, cr.MODE_GATHER)

    def test_a_buy_route_leaves_the_stands_alone(self):
        pending = {}
        cr.take_requests(
            pending, [_request()], {PEACEBLOOM: HERB}, {"Ugga": {}}, {}, 0.0
        )
        stands = (
            cr.Stand(name="Ugga", craft_spell=2330, verdict=cr.STOCKED, casts=20),
        )
        self.assertEqual(cr.requested_stands(stands, cr.open_routes(pending)), stands)


class BuyRoutesBecomeAuctionNeeds(unittest.TestCase):
    def _buy(self):
        pending = {}
        cr.take_requests(
            pending, [_request()], {PEACEBLOOM: HERB}, {"Ugga": {}}, {}, 0.0
        )
        return cr.open_routes(pending, cr.ROUTE_BUY)

    def test_a_buy_route_is_one_need_counting_the_mail(self):
        needs = auction.requested_needs(
            self._buy(), {("Ugga", PEACEBLOOM): 3}, {("Ugga", PEACEBLOOM): 2}
        )
        self.assertEqual(len(needs), 1)
        self.assertEqual(needs[0].shopper, "Ugga")
        self.assertEqual(needs[0].short, auction.CASTS_PER_TRIP - 5)

    def test_need_is_per_cast_so_a_trip_buys_casts_per_trip_of_it(self):
        pending = {}
        request = _request(
            entry=COPPER_BAR, detail="short 4x Copper Bar (needs 6, has 2)"
        )
        cr.take_requests(pending, [request], {COPPER_BAR: (7, 7)}, {}, {}, 0.0)
        routes = cr.open_routes(pending, cr.ROUTE_BUY)
        needs = auction.requested_needs(routes, {("Ugga", COPPER_BAR): 2}, {})
        self.assertEqual(needs[0].short, 6 * auction.CASTS_PER_TRIP - 2)

    def test_a_reagent_the_standing_errand_already_buys_is_not_bought_twice(self):
        have = [auction.Need(shopper="Ugga", entry=PEACEBLOOM, short=4)]
        self.assertEqual(auction.requested_needs(self._buy(), {}, {}, have), [])


class TheBridgeRoutesTheRequests(unittest.TestCase):
    source = BRIDGE.read_text(encoding="utf-8")

    def _body(self, name):
        start = self.source.index("    async def %s(" % name)
        end = self.source.index("\n    async def ", start + 1)
        return self.source[start:end]

    def test_the_event_kind_is_read(self):
        self.assertTrue("kind = 'material-request'" in self.source)

    def test_the_rhythm_sends_the_family_out_for_a_gather_route(self):
        body = self._body("_craft_rhythm_once")
        self.assertIn("await self._material_routes(names)", body)
        self.assertIn("craft_rhythm.requested_stands(", body)

    def test_the_auction_pass_buys_for_a_buy_route(self):
        body = self._body("_auction_once")
        self.assertIn("await self._material_routes(names)", body)
        self.assertIn("craft_rhythm.ROUTE_BUY", body)
        self.assertIn("auction.requested_needs(", self._body("_auction_shortfall"))

    def test_the_event_age_is_read_for_the_route_clock(self):
        self.assertIn("TIMESTAMPDIFF(SECOND, last_seen, NOW()) AS age", self.source)

    def test_every_members_count_is_read_for_gather_settlement(self):
        body = self._body("_material_routes")
        self.assertIn("for name in names for entry in entries", body)
        self.assertIn("(r.who, r.request.entry)", body)

    def test_a_buyer_with_no_standing_errand_shops_with_its_own_purse(self):
        body = self._body("_auction_once")
        self.assertIn("_fetch_purses", body)
        self.assertNotIn("spells.get(name, (0, 0))", body)

    def test_pending_requests_survive_a_restart(self):
        self.assertTrue('"material_request"' in self.source)
        self.assertTrue('"_material_requests"' in self.source)


if __name__ == "__main__":
    unittest.main()
