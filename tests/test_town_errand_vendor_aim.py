"""A bag-room errand aims at a reachable vendor, and a walk that never landed
is not repeated (wow-overseer#2065).

The dev realm, 2026-11-08: a family held for bag room stood on map 0 with its
capital 4,874 yards away. The walk was released at GO_SECONDS ("did not land")
and the same capital was chosen again, so no vendor was ever reached.
"""

import pathlib
import unittest

import townerrand as te

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
WHY = te.BAG_PRESSURE_WHY
CAPITAL = {"map_id": 0, "x": -8877.0, "y": 652.0, "z": 96.0, "place": "the capital"}
HEAD = {"map_id": 0, "pos_x": -6705.0, "pos_y": -2195.0}
NEAR = {"map_id": 0, "x": -6600.0, "y": -2100.0, "name": "Near Vendor"}
NEXT = {"map_id": 0, "x": -6000.0, "y": -2100.0, "name": "Next Vendor"}
OTHER_MAP = {"map_id": 1, "x": -6700.0, "y": -2190.0, "name": "Elsewhere"}


class TheAimChoice(unittest.TestCase):
    def test_the_capital_is_far_in_the_reported_case(self):
        here = {"map_id": 0, "x": HEAD["pos_x"], "y": HEAD["pos_y"]}
        self.assertGreater(te._planar(CAPITAL, here), 2000)

    def test_a_vendor_in_reach_beats_a_far_capital(self):
        stops = te.vendor_stops([NEAR, NEXT])
        pick = te.choose_aim(CAPITAL, stops, HEAD, WHY)
        self.assertEqual((0, -6600.0, -2100.0), (pick["map_id"], pick["x"], pick["y"]))

    def test_a_near_capital_stays_the_aim(self):
        close = dict(CAPITAL, x=-6650.0, y=-2150.0)
        self.assertEqual(
            close, te.choose_aim(close, te.vendor_stops([NEAR]), HEAD, WHY)
        )

    def test_other_errands_keep_their_hub(self):
        stops = te.vendor_stops([NEAR])
        self.assertEqual(
            CAPITAL, te.choose_aim(CAPITAL, stops, HEAD, "gear in the post")
        )

    def test_a_vendor_on_another_map_is_not_a_walk(self):
        stops = te.vendor_stops([OTHER_MAP])
        self.assertEqual(CAPITAL, te.choose_aim(CAPITAL, stops, HEAD, WHY))

    def test_a_hub_on_another_map_stays_for_the_hearthstone(self):
        home = {"map_id": 1, "x": -1035.0, "y": -3676.0, "bind": True}
        self.assertEqual(home, te.choose_aim(home, te.vendor_stops([NEAR]), HEAD, WHY))

    def test_the_other_sides_vendors_are_never_aimed(self):
        hostile = dict(NEAR, enemy_group=4)
        stops = te.vendor_stops([hostile, NEXT], side=4)
        self.assertEqual([-6000.0], [s["x"] for s in stops])

    def test_vendors_of_one_square_are_one_stop(self):
        twin = dict(NEAR, x=NEAR["x"] + 10)
        self.assertEqual(1, len(te.vendor_stops([NEAR, twin])))


class TheReleasedAimIsNotRepeated(unittest.TestCase):
    def _released_walk(self, hub):
        old = te.start(0.0, hub, WHY)
        new, _line = te.advance(old, te.GO_SECONDS)
        return old, new

    def test_a_walk_that_did_not_land_is_remembered(self):
        old, new = self._released_walk(CAPITAL)
        self.assertEqual(CAPITAL, te.unlanded_aim(old, new))

    def test_other_endings_are_not_remembered(self):
        old = te.start(0.0, CAPITAL, WHY)
        new, _ = te.advance(old, 5.0, in_run=True)
        self.assertEqual({}, te.unlanded_aim(old, new))

    def test_the_next_pass_picks_the_next_nearest(self):
        # Even a capital within a walk is not repeated once it did not land.
        close = dict(CAPITAL, x=-6300.0, y=-2100.0)
        old, new = self._released_walk(close)
        released = te.remember_released([], te.unlanded_aim(old, new), 1200.0)
        stops = te.vendor_stops([NEAR, NEXT])
        pick = te.choose_aim(close, stops, HEAD, WHY, released, 9000.0)
        self.assertEqual(-6600.0, pick["x"])
        # And a released vendor is skipped for the one after it.
        released = te.remember_released(released, pick, 9000.0)
        again = te.choose_aim(close, stops, HEAD, WHY, released, 9100.0)
        self.assertEqual(-6000.0, again["x"])

    def test_the_memory_is_bounded(self):
        released = te.remember_released([], CAPITAL, 0.0)
        later = te.AIM_MEMORY_SECONDS + 1
        self.assertEqual([], te.remember_released(released, {}, later))
        close = dict(CAPITAL, x=-6650.0, y=-2150.0)
        released = te.remember_released([], close, 0.0)
        self.assertEqual(close, te.choose_aim(close, [], HEAD, WHY, released, later))

    def test_with_nothing_fresh_left_the_hub_stands(self):
        released = te.remember_released([], CAPITAL, 0.0)
        self.assertEqual(CAPITAL, te.choose_aim(CAPITAL, [], HEAD, WHY, released, 10.0))


class TheAimAvoidsGroundTheFamilyDiedOn(unittest.TestCase):
    """#2271: the nearest vendor was chosen by straight-line yards only, and
    the walk to it crossed ground the family had died on that day."""

    LETHAL = {"map_id": 0, "x": -5800.0, "y": -1300.0, "name": "Lethal Vendor"}
    SAFE = {"map_id": 0, "x": -8300.0, "y": -2200.0, "name": "Safe Vendor"}

    def deaths_between(self, count=3):
        # Deaths on the straight line from the head to LETHAL, in the last day.
        return [{"map_id": 0, "x": -6000.0, "y": -1500.0}] * count

    def test_without_deaths_the_nearest_vendor_is_aimed(self):
        stops = te.vendor_stops([self.LETHAL, self.SAFE])
        self.assertEqual(-5800.0, te.choose_aim(CAPITAL, stops, HEAD, WHY)["x"])

    def test_a_vendor_over_ground_the_family_died_on_is_not_aimed(self):
        stops = te.vendor_stops([self.LETHAL])
        pick = te.choose_aim(CAPITAL, stops, HEAD, WHY, deaths=self.deaths_between())
        self.assertEqual(CAPITAL, pick)

    def test_the_next_safe_vendor_is_aimed_instead(self):
        stops = te.vendor_stops([self.LETHAL, self.SAFE])
        pick = te.choose_aim(CAPITAL, stops, HEAD, WHY, deaths=self.deaths_between())
        self.assertEqual(-8300.0, pick["x"])

    def test_deaths_where_the_head_stands_count_against_every_stop(self):
        # The line starts at the head, so ground he stands on and dies on
        # makes every stop on the map lethal: the family hearths instead.
        at_head = [{"map_id": 0, "x": -6700.0, "y": -2190.0}] * 2
        stops = te.vendor_stops([self.LETHAL, self.SAFE])
        self.assertEqual(
            CAPITAL, te.choose_aim(CAPITAL, stops, HEAD, WHY, deaths=at_head)
        )

    def test_the_passed_over_stops_come_back_with_their_death_counts(self):
        stops = te.vendor_stops([self.LETHAL, self.SAFE])
        here = {"map_id": 0, "x": HEAD["pos_x"], "y": HEAD["pos_y"]}
        dropped = te.lethal_stops(stops, here, self.deaths_between(3))
        self.assertEqual([(-5800.0, 3)], [(s["x"], n) for s, n in dropped])
        self.assertEqual([], te.lethal_stops(stops, here, self.deaths_between(1)))

    def test_one_death_is_not_a_pattern(self):
        stops = te.vendor_stops([self.LETHAL])
        pick = te.choose_aim(CAPITAL, stops, HEAD, WHY, deaths=self.deaths_between(1))
        self.assertEqual(-5800.0, pick["x"])

    def test_deaths_far_from_the_walk_do_not_count(self):
        far = [{"map_id": 0, "x": -3000.0, "y": 500.0}] * 5
        stops = te.vendor_stops([self.LETHAL])
        pick = te.choose_aim(CAPITAL, stops, HEAD, WHY, deaths=far)
        self.assertEqual(-5800.0, pick["x"])

    def test_deaths_on_another_map_do_not_count(self):
        elsewhere = [{"map_id": 1, "x": -6000.0, "y": -1500.0}] * 5
        stops = te.vendor_stops([self.LETHAL])
        pick = te.choose_aim(CAPITAL, stops, HEAD, WHY, deaths=elsewhere)
        self.assertEqual(-5800.0, pick["x"])


class AHubTheHeadsStoneReaches(unittest.TestCase):
    """wow-overseer#2329: the dev realm, 2026-11-12. The head stood in Eastern
    Plaguelands, the family's stones were bound in the Badlands, and the
    nearest vendor beat the bind hub, so four members walked 9,000 yards."""

    BIND = {"map_id": 0, "x": -6673.9, "y": -2174.3, "z": 244.2, "bind": True,
            "place": "Zug's hearthstone point"}
    PLAGUELANDS = {"map_id": 0, "pos_x": 2151.7, "pos_y": -5264.5}
    CALEB = {"map_id": 0, "x": 2151.7, "y": -5264.5, "name": "Caretaker Alen"}

    def test_the_far_bind_hub_stays_when_the_stone_will_be_cast(self):
        stops = te.vendor_stops([self.CALEB])
        pick = te.choose_aim(
            self.BIND, stops, self.PLAGUELANDS, WHY, hearth_reaches=True
        )
        self.assertEqual(self.BIND, pick)

    def test_the_vendor_still_wins_when_the_stone_will_not_be_cast(self):
        stops = te.vendor_stops([self.CALEB])
        pick = te.choose_aim(self.BIND, stops, self.PLAGUELANDS, WHY)
        self.assertEqual(2151.7, pick["x"])

    def test_a_walked_capital_is_not_made_a_hearth_hub(self):
        stops = te.vendor_stops([self.CALEB])
        pick = te.choose_aim(
            CAPITAL, stops, self.PLAGUELANDS, WHY, hearth_reaches=True
        )
        self.assertEqual(2151.7, pick["x"])

    def test_a_hub_released_unlanded_still_gives_way(self):
        released = te.remember_released([], self.BIND, 100.0)
        stops = te.vendor_stops([self.CALEB])
        pick = te.choose_aim(
            self.BIND, stops, self.PLAGUELANDS, WHY, released, 200.0,
            hearth_reaches=True,
        )
        self.assertEqual(2151.7, pick["x"])

    def test_the_bridge_reads_the_stone_before_it_chooses(self):
        self.assertIn("hearth_reaches=leader in casts", BRIDGE)
        self.assertLess(
            BRIDGE.index("casts = townerrand.to_hearth("),
            BRIDGE.index("hearth_reaches=leader in casts"),
        )


class TheBridgeUsesIt(unittest.TestCase):
    def test_the_start_reads_the_deaths_and_chooses_the_aim(self):
        self.assertIn("deaths=", BRIDGE)

    def test_the_start_chooses_the_aim_and_the_release_is_remembered(self):
        self.assertIn("townerrand.choose_aim(", BRIDGE)
        self.assertIn("townerrand.unlanded_aim(state, new)", BRIDGE)


if __name__ == "__main__":
    unittest.main()
