"""A bag-room errand lists at an auctioneer when no vendor would take the goods (#1261).

A family whose carried stacks are all ones the policy keeps, and whose recipes
nobody can learn are decided AUCTION, was sent to a vendor that bought nothing
and the bag floor held for hours. The errand now aims at a reachable auctioneer
on the leader's map, passing over ground the family died on. The names and
numbers are invented.
"""

import pathlib
import unittest

import townerrand as te

WHY = te.BAG_PRESSURE_WHY
HERE = {"map_id": 0, "pos_x": 1300.0, "pos_y": -2400.0}
NEAR = {
    "map_id": 0,
    "x": 900.0,
    "y": -2800.0,
    "z": 60.0,
    "place": "the auctioneer near",
}
FAR = {"map_id": 0, "x": 2300.0, "y": -1400.0, "z": 60.0, "place": "the auctioneer far"}
OTHER_MAP = {"map_id": 1, "x": 1250.0, "y": -2450.0, "z": 60.0, "place": "elsewhere"}


class AuctionFirst(unittest.TestCase):
    def test_nothing_to_sell_and_recipes_to_list(self):
        self.assertTrue(te.auction_first(WHY, {"Oz": 0, "Zug": 0}, 25))

    def test_a_handful_is_too_few_to_free_the_floor(self):
        self.assertTrue(te.auction_first(WHY, {"Oz": 2, "Zug": 0}, 25))
        self.assertFalse(te.auction_first(WHY, {"Oz": 9, "Zug": 0}, 25))

    def test_too_few_listings_keep_the_vendor(self):
        self.assertFalse(te.auction_first(WHY, {"Oz": 0}, te.AUCTION_FIRST_MIN - 1))

    def test_an_unread_member_keeps_the_vendor(self):
        self.assertFalse(te.auction_first(WHY, {"Oz": 0, "Zug": None}, 25))
        self.assertFalse(te.auction_first(WHY, {}, 25))

    def test_only_a_bag_room_errand(self):
        self.assertFalse(te.auction_first("gear for the family", {"Oz": 0}, 25))


class AuctionRoute(unittest.TestCase):
    def route(self, stops, deaths=(), walled=None, released=(), now=0.0):
        return te.auction_route(
            WHY,
            {"Oz": 0},
            25,
            stops,
            HERE,
            released=released,
            now=now,
            deaths=deaths,
            walled=walled,
        )

    def test_the_nearest_auctioneer_on_the_leaders_map(self):
        route, spot, _line = self.route([FAR, NEAR])
        self.assertEqual(route, te.ROUTE_AUCTION)
        self.assertEqual(spot["place"], "the auctioneer near")

    def test_another_map_is_no_auctioneer(self):
        route, spot, _line = self.route([OTHER_MAP])
        self.assertEqual((route, spot), ("", {}))

    def test_ground_the_family_died_on_is_passed_over(self):
        deaths = [{"map_id": 0, "x": 900.0, "y": -2800.0}] * 3
        route, spot, _line = self.route([NEAR, FAR], deaths=deaths)
        self.assertEqual(spot.get("place"), "the auctioneer far")

    def test_a_walk_the_town_slot_would_refuse_is_passed_over(self):
        route, spot, _line = self.route([NEAR], walled=lambda s: True)
        self.assertEqual((route, spot), ("", {}))

    def test_not_asked_when_the_vendor_would_buy(self):
        route, spot, _line = te.auction_route(WHY, {"Oz": 12}, 25, [NEAR], HERE)
        self.assertEqual((route, spot), ("", {}))

    def test_no_leader_position_keeps_the_vendor(self):
        route, spot, _line = te.auction_route(WHY, {"Oz": 0}, 25, [NEAR], None)
        self.assertEqual((route, spot), ("", {}))


class VendorWaitChangesRoute(unittest.TestCase):
    """A vendor wait that cannot end moves to another route (#1261).

    A family whose members hold nothing a vendor will buy waits on a vendor
    counter for sales that never queue. The route changes to an auctioneer,
    and when none is reachable the vendor aim stands with a reason said.
    """

    def test_a_vendor_that_will_buy_nothing_gives_way_to_an_auctioneer(self):
        route, spot, line = te.auction_route(
            WHY, {"Oz": 0, "Zug": 0, "Uzza": 0}, 12, [NEAR], HERE
        )
        self.assertEqual(route, te.ROUTE_AUCTION)
        self.assertTrue(line)

    def test_with_no_reachable_counter_the_reason_is_said(self):
        route, spot, line = te.auction_route(WHY, {"Oz": 0}, 12, [OTHER_MAP], HERE)
        self.assertEqual(route, "")
        self.assertIn("no auctioneer is reachable", line)

    def test_a_vendor_that_will_buy_enough_keeps_the_vendor_route(self):
        route, _spot, _line = te.auction_route(WHY, {"Oz": 9}, 12, [NEAR], HERE)
        self.assertEqual(route, "")


class Steps(unittest.TestCase):
    def test_the_auction_step_comes_first_on_its_route(self):
        steps = te.steps_for(WHY, te.ROUTE_AUCTION)
        self.assertEqual(steps[0], te.AUCTION)
        self.assertIn(te.AUCTION, te.STEP_SECONDS)
        self.assertEqual(set(steps), set(te.ROOM_STEP_ORDER) | {te.AUCTION})

    def test_other_routes_are_unchanged(self):
        self.assertEqual(te.steps_for(WHY), te.ROOM_STEP_ORDER)
        self.assertEqual(te.steps_for(WHY, te.ROUTE_BANKER), te.BANK_ROOM_STEP_ORDER)


class Wiring(unittest.TestCase):
    def test_the_errand_chooses_and_runs_the_route(self):
        bridge = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("townerrand.auction_route(", bridge)
        self.assertIn("townerrand.auction_first(", bridge)
        self.assertIn("step == townerrand.AUCTION", bridge)
        self.assertIn("_auction_stops_for_errand", bridge)
        self.assertIn("unplaced = [n for n in names if n not in positions]", bridge)


if __name__ == "__main__":
    unittest.main()
