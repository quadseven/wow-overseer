"""A bag-room errand whose room comes from the bank aims at a banker (#1261).

Measured on the dev realm 2026-11-17. A family's bags held stacks the item
plan routes to the bank (26 of them), a vendor would buy none, and the bag-room
town errand kept aiming at vendors: the bank pass logged "no banker within 8
yards" and "queued 0/26 move(s)", and nothing drained.
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
NEAR = {"map_id": 0, "x": -6600.0, "y": -2100.0, "name": "Near Banker"}
FAR = {"map_id": 0, "x": -7800.0, "y": -2200.0, "name": "Far Banker"}
VAULT = {"map_id": 0, "x": -6500.0, "y": -2000.0, "z": 5.0, "d2": 1.0}
FAMILY = ("Zug", "Grug")


def bankers(*rows):
    return te.vendor_stops(list(rows), kind="banker")


def route(sellable=0, routed=26, rows=(NEAR,), vault=None, **kw):
    counts = {name: sellable for name in FAMILY}
    return te.bank_route(
        WHY, counts, routed, CAPITAL, bankers(*rows), vault, HEAD, **kw
    )


class WhenTheErrandBanks(unittest.TestCase):
    def test_no_sellables_and_26_bank_routed_stacks_aims_at_a_banker(self):
        kind, spot, line = route()
        self.assertEqual(te.ROUTE_BANKER, kind)
        self.assertEqual((0, -6600.0, -2100.0), (spot["map_id"], spot["x"], spot["y"]))
        self.assertIn("banker", spot["place"])
        self.assertTrue(line)

    def test_the_nearest_banker_is_chosen(self):
        _kind, spot, _line = route(rows=(FAR, NEAR))
        self.assertEqual(-6600.0, spot["x"])

    def test_a_banker_past_the_town_service_limit_is_not_aimed_at(self):
        # 2119 yards off: the module never walks a character that far to a
        # counter, so the same hub would be re-issued for ever.
        far = {"map_id": 0, "x": -6705.0 + 2119.0, "y": -2195.0, "name": "Far"}
        kind, spot, line = route(rows=(far,))
        self.assertEqual(("", {}), (kind, spot))
        self.assertIn("town-service limit", line)

    def test_a_vault_past_the_limit_is_not_aimed_at_either(self):
        far = {"map_id": 0, "x": -4000.0, "y": -2195.0, "z": 5.0, "d2": 1.0}
        self.assertEqual("", route(rows=(), vault=far)[0])

    def test_sellables_keep_the_vendor(self):
        self.assertEqual(("", {}, ""), route(sellable=1))

    def test_nothing_bank_routed_keeps_the_vendor(self):
        self.assertEqual(("", {}, ""), route(routed=0))

    def test_an_unread_member_keeps_the_vendor(self):
        counts = {"Zug": 0, "Grug": None}
        out = te.bank_route(WHY, counts, 26, CAPITAL, bankers(NEAR), None, HEAD)
        self.assertEqual("", out[0])

    def test_only_the_bag_room_errand_banks(self):
        out = te.bank_route(
            "gear in the post", {"Zug": 0}, 26, CAPITAL, bankers(NEAR), None, HEAD
        )
        self.assertEqual("", out[0])

    def test_a_bind_town_the_stone_reaches_keeps_its_hub(self):
        home = {"map_id": 1, "x": -1035.0, "y": -3676.0, "bind": True}
        out = te.bank_route(
            WHY,
            {"Zug": 0},
            26,
            home,
            bankers(NEAR),
            None,
            HEAD,
            hearth_reaches=True,
        )
        self.assertEqual((te.ROUTE_BANKER, home), out[:2])


class WhenTheBankerIsRefused(unittest.TestCase):
    DEATHS = [{"map_id": 0, "x": -6650.0, "y": -2150.0}] * 3

    def test_a_banker_over_deadly_ground_with_no_vault_falls_back_to_the_vendor(self):
        kind, spot, line = route(deaths=self.DEATHS)
        # No vault known: the vendor stands, and the line says why.
        self.assertEqual("", kind)
        self.assertEqual({}, spot)
        self.assertIn("vendor", line)

    def test_a_refused_banker_falls_back_to_the_guild_vault(self):
        walled_banker = lambda s: s.get("x") == NEAR["x"]  # noqa: E731
        kind, spot, line = route(vault=VAULT, walled=walled_banker)
        self.assertEqual(te.ROUTE_VAULT, kind)
        self.assertEqual(VAULT["x"], spot["x"])
        self.assertIn("guild vault", line)

    def test_a_released_banker_is_not_repeated(self):
        released = te.remember_released([], NEAR, 100.0)
        kind, spot, _line = route(rows=(NEAR, FAR), released=released, now=200.0)
        self.assertEqual(te.ROUTE_BANKER, kind)
        self.assertEqual(-7800.0, spot["x"])

    def test_the_vault_is_refused_by_the_same_guard(self):
        kind, _spot, line = route(vault=VAULT, walled=lambda _s: True)
        self.assertEqual("", kind)
        self.assertIn("vendor", line)

    def test_a_banker_on_another_map_is_not_a_walk(self):
        kind, _spot, _line = route(rows=(dict(NEAR, map_id=1),))
        self.assertEqual("", kind)


class TheErrandBanksFirst(unittest.TestCase):
    def test_the_steps_put_the_bank_ahead_of_the_vendor(self):
        state = te.start(0.0, CAPITAL, WHY)
        self.assertEqual(te.ROOM_STEP_ORDER, state.steps)
        banked = te.State(phase=te.STEPS, why=WHY, route=te.ROUTE_BANKER)
        self.assertEqual(te.BANK_ROOM_STEP_ORDER, banked.steps)
        self.assertEqual(te.BANK, banked.current_step)

    def test_the_bound_stands_for_a_banker_walk(self):
        old = te.State(phase=te.GO, why=WHY, route=te.ROUTE_BANKER, hub=NEAR)
        new, _line = te.advance(old, te.GO_SECONDS)
        self.assertEqual(te.DONE, new.phase)
        self.assertEqual(NEAR, te.unlanded_aim(old, new))


class TheBridgeWiresIt(unittest.TestCase):
    def test_the_start_asks_for_the_bank_route_and_records_it(self):
        start = BRIDGE[BRIDGE.index("async def _town_errand_start(") :]
        start = start[: start.index("async def _town_errand_regroup(")]
        self.assertIn("townerrand.bank_route(", start)
        self.assertIn("_bank_first_reads", start)
        self.assertIn("replace(", start)
        self.assertIn("route=", start)

    def test_the_reads_are_the_policy_filtered_count_and_the_plans_routes(self):
        body = BRIDGE[BRIDGE.index("def _bank_first_reads(") :]
        body = body[: body.index("\n\n\n")]
        self.assertIn("_VENDOR_SELLABLE", body)
        self.assertIn("_itemplan_bank_routes", body)

    def test_the_vault_route_is_served_at_the_vault(self):
        step = BRIDGE[BRIDGE.index("async def _town_errand_step(") :]
        step = step[: step.index("async def _town_errand_fund(")]
        self.assertIn("townerrand.ROUTE_VAULT", step)
        self.assertIn("_guild_bank_passing_once", step)


if __name__ == "__main__":
    unittest.main()
