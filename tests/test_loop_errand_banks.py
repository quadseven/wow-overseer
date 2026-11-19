"""A profession-loop errand makes room at a banker, and a bind town with no
banker is not one (Refs #1261, Refs #1983).

Measured on the dev realm 2026-11-17. A family held at 0 to 2 free slots went to
town on the profession loop's errand, hearthed to its bind town (a camp with a
mailbox and vendors and no banker), and ran every step for 48 minutes: the
vendor bought nothing (every stack was kept), the bank step logged "no banker
within 8 yards" and queued 0 moves, the mail step could not take its letters for
want of room. The errand released with the bags exactly as full, and the loop
sent the family back. The bank-first choice (#2841) was gated to the campaign's
bag-room errand, and its bind-town shortcut assumed a banker stands there.
"""

import pathlib
import unittest

import townerrand as te

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
LOOP = te.LOOP_WHY + "Oz (0), Zug (0) below 8 free bag slots"
CAMP = {"map_id": 0, "x": -6673.0, "y": -2151.0, "z": 244.0, "bind": True}
HEAD = {"map_id": 0, "pos_x": -6673.0, "pos_y": -2151.0}
CITY = {"map_id": 0, "x": -6000.0, "y": -2000.0, "name": "City Banker"}
COUNTS = {"Zug": 0, "Oz": 0}


def bankers(*rows):
    return te.vendor_stops(list(rows), kind="banker")


class TheLoopErrandBanksFirst(unittest.TestCase):
    def test_a_loop_errand_with_nothing_to_sell_is_bank_first(self):
        self.assertTrue(te.bank_first(LOOP, COUNTS, 4))

    def test_a_loop_errand_with_something_to_sell_keeps_the_vendor(self):
        self.assertFalse(te.bank_first(LOOP, {"Zug": 2, "Oz": 0}, 4))

    def test_an_errand_for_gear_in_the_post_still_does_not_bank_first(self):
        self.assertFalse(te.bank_first("gear in the post", COUNTS, 4))

    def test_a_banker_routed_loop_errand_runs_the_bank_ahead_of_the_vendor(self):
        state = te.State(phase=te.STEPS, why=LOOP, route=te.ROUTE_BANKER)
        self.assertEqual(te.BANK_ROOM_STEP_ORDER, state.steps)
        self.assertEqual(te.BANK, state.current_step)

    def test_a_loop_errand_on_the_vendor_keeps_the_room_order(self):
        self.assertEqual(te.ROOM_STEP_ORDER, te.State(why=LOOP).steps)

    def test_a_loop_errand_aims_at_the_nearest_banker(self):
        kind, spot, _line = te.bank_route(
            LOOP, COUNTS, 4, CAMP, bankers(CITY), None, HEAD, hub_has_banker=False
        )
        self.assertEqual(te.ROUTE_BANKER, kind)
        self.assertEqual(CITY["x"], spot["x"])


class ABindTownWithNoBankerIsNotABankerStop(unittest.TestCase):
    def test_the_stone_that_reaches_a_banker_less_town_does_not_keep_the_hub(self):
        kind, spot, _line = te.bank_route(
            LOOP,
            COUNTS,
            4,
            CAMP,
            bankers(CITY),
            None,
            HEAD,
            hearth_reaches=True,
            hub_has_banker=False,
        )
        self.assertEqual(te.ROUTE_BANKER, kind)
        self.assertNotEqual(CAMP["x"], spot["x"])

    def test_with_no_other_banker_and_no_vault_the_vendor_stands(self):
        out = te.bank_route(
            LOOP,
            COUNTS,
            4,
            CAMP,
            [],
            None,
            HEAD,
            hearth_reaches=True,
            hub_has_banker=False,
        )
        self.assertEqual("", out[0])

    def test_a_bind_town_with_a_banker_keeps_its_hub(self):
        out = te.bank_route(
            LOOP,
            COUNTS,
            4,
            CAMP,
            bankers(CITY),
            None,
            HEAD,
            hearth_reaches=True,
            hub_has_banker=True,
        )
        self.assertEqual((te.ROUTE_BANKER, CAMP), out[:2])

    def test_the_default_still_trusts_the_bind_town(self):
        out = te.bank_route(
            LOOP, COUNTS, 4, CAMP, bankers(CITY), None, HEAD, hearth_reaches=True
        )
        self.assertEqual((te.ROUTE_BANKER, CAMP), out[:2])

    def test_a_banker_beside_the_hub_is_found(self):
        near = {"map_id": 0, "x": -6600.0, "y": -2100.0, "name": "Near Banker"}
        self.assertTrue(te.banker_at_hub(CAMP, bankers(near)))

    def test_a_banker_far_from_the_hub_or_on_another_map_is_not(self):
        self.assertFalse(te.banker_at_hub(CAMP, bankers(CITY)))
        self.assertFalse(
            te.banker_at_hub(CAMP, bankers(dict(CITY, map_id=1, x=-6660.0, y=-2150.0)))
        )
        self.assertFalse(te.banker_at_hub(CAMP, []))


class TheBridgeWiresIt(unittest.TestCase):
    START = BRIDGE[BRIDGE.index("async def _town_errand_start(") :]
    START = START[: START.index("async def _town_errand_regroup(")]

    def test_the_start_does_not_gate_the_bank_choice_to_the_campaign_errand(self):
        self.assertIn("townerrand.room_errand(why)", self.START)
        self.assertNotIn("why == townerrand.BAG_PRESSURE_WHY", self.START)

    def test_the_start_asks_whether_the_hub_has_a_banker(self):
        self.assertIn("townerrand.banker_at_hub(", self.START)
        self.assertIn("hub_has_banker=", self.START)


if __name__ == "__main__":
    unittest.main()
