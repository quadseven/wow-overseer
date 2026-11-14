"""A sustained wait for a vendor leads to a real sale trip."""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import jev_activity
import jev_family_intent
import jobs
import vendor_stall


BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text()


def _vendor_sellers_held_for_leader(namespace_extra=None):
    tree = ast.parse(BRIDGE)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_vendor_sellers_held_for_leader"
    )
    namespace = {
        "jev_family_intent": jev_family_intent,
        "vendor_stall": vendor_stall,
        "_fetch_family_intents": lambda: {
            "Leader": {"members_state": "HeldSeller|held too far to walk|3500"}
        },
    }
    namespace.update(namespace_extra or {})
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace["_vendor_sellers_held_for_leader"]


def _vendor_seller_fetch_blocks_trip(namespace_extra=None):
    tree = ast.parse(BRIDGE)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_vendor_seller_fetch_blocks_trip"
    )
    namespace = {
        "bag_pressure": bag_pressure,
        "vendor_stall": vendor_stall,
        "time": types.SimpleNamespace(monotonic=lambda: 0.0),
        "log": types.SimpleNamespace(info=lambda *args: None),
        "_HELD_FETCH_SINCE": {},
        "_vendor_sellers_held_for_leader": lambda *args: {
            "HeldSeller": jev_family_intent.Member(
                "HeldSeller", "held too far to walk", "3500"
            )
        },
    }
    namespace.update(namespace_extra or {})
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace["_vendor_seller_fetch_blocks_trip"]


def _vendor_pass_mode(namespace_extra=None):
    """The bridge's vendor pass mode, loaded on its own."""
    tree = ast.parse(BRIDGE)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_vendor_pass_mode"
    )
    namespace = {
        "asyncio": asyncio,
        "bag_pressure": bag_pressure,
        "jev_activity": jev_activity,
        "_town_first_hold": lambda names: False,
        "_campaign_waiting": lambda names: False,
        "_fetch_vendor_wait_seconds": lambda names: 30 * 60,
        "_standing_jobs": lambda: {},
        "jobs": jobs,
        "log": types.SimpleNamespace(info=lambda *args: None),
    }
    namespace.update(namespace_extra or {})
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), "bridge.py", "exec"),
        namespace,
    )
    return namespace


class VendorWaitTrip(unittest.TestCase):
    def test_only_a_sellable_member_held_for_the_leader_blocks_a_vendor_trip(self):
        held = _vendor_sellers_held_for_leader()
        self.assertTrue(held(["Leader", "HeldSeller"], "Leader", {"HeldSeller": 2}))
        self.assertFalse(held(["Leader", "HeldSeller"], "Leader", {"HeldSeller": 0}))

    def test_fetch_priority_blocks_only_a_trip_that_could_otherwise_run(self):
        blocks = _vendor_seller_fetch_blocks_trip()
        args = (["Leader", "HeldSeller"], "Leader", {}, {"HeldSeller": 2})
        self.assertTrue(blocks(*args, False))
        self.assertFalse(blocks(*args, True))
        self.assertFalse(blocks(*args[:3], {}, False))

    def test_carried_goods_get_a_trip_before_the_two_hour_stuck_finding(self):
        self.assertTrue(
            bag_pressure.vendor_wait_trip(
                wait_seconds=30 * 60,
                sellable_counts={"Leader": 2},
                in_run=False,
            )
        )

    def test_no_wait_trip_while_a_farm_order_holds_the_family(self):
        """A farming family's own town phase owns its vendor trips; a stuck
        seller (one held in a dungeon, say) must not take the leader's column
        and split the family off its node."""
        self.assertFalse(
            bag_pressure.vendor_wait_trip(30 * 60, {"Leader": 2}, False, farming=True)
        )
        self.assertTrue(
            bag_pressure.vendor_wait_trip(30 * 60, {"Leader": 2}, False, farming=False)
        )

    def test_the_pass_takes_no_wait_trip_for_a_farming_family(self):
        namespace = _vendor_pass_mode(
            {
                "_standing_jobs": lambda: {
                    "Leader": "farm:mining",
                    "Seller": "farm:mining",
                }
            }
        )
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None,
                ["Leader", "Seller"],
                {"Leader": 20, "Seller": 20},
                {"Seller": 2},
                False,
            )
        )
        self.assertEqual(mode, bag_pressure.VENDOR_MODE_COUNTER)

    def test_the_pass_passes_the_farming_flag(self):
        self.assertIn(
            "bag_pressure.vendor_wait_trip(waited, sellable_counts, in_run,",
            BRIDGE,
        )

    def test_no_trip_without_a_sustained_wait_or_goods(self):
        self.assertFalse(bag_pressure.vendor_wait_trip(29 * 60, {"Leader": 2}, False))
        self.assertFalse(bag_pressure.vendor_wait_trip(30 * 60, {"Leader": 0}, False))
        self.assertFalse(bag_pressure.vendor_wait_trip(30 * 60, {"Leader": 2}, True))

    def test_vendor_wait_times_out_into_a_trip_on_a_town_errand(self):
        # Once the wait exceeds 30 minutes, an ordinary town errand claims a
        # sale trip. Dungeon travel remains under the run coordinator.
        namespace = _vendor_pass_mode(
            {"_fetch_vendor_wait_seconds": lambda names: 30 * 60}
        )
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Leader"], {"Leader": 12}, {"Leader": 2}, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)

    def test_vendor_pass_claims_a_trip_for_an_old_range_wait(self):
        namespace = _vendor_pass_mode()
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Leader"], {"Leader": 12}, {"Leader": 2}, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)

    def test_a_held_seller_does_not_retake_the_trip_after_the_counter_yields(self):
        # After the leader yields its counter aim, the old no-vendor row is
        # still fresh. Retaking that trip while a seller remains held for the
        # leader recreates the same unreachable counter visit every pass.
        namespace = _vendor_pass_mode(
            {"_fetch_vendor_wait_seconds": lambda names: 8 * 60 * 60}
        )
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None,
                ["Leader", "HeldSeller"],
                {"Leader": 0, "HeldSeller": 0},
                {"Leader": 2, "HeldSeller": 3},
                False,
                held_seller_for_leader=True,
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_COUNTER, mode)


class TheTripMakesTheFamilyRoom(unittest.TestCase):
    """#1204: the family at the floor whose sale is shared between its members.

    The dev realm on 2026-10-19: Grog, Og and Ugga each carried stacks a
    vendor would buy, and Bork held the family at the floor with 68 stacks no
    vendor will buy (34 uncommon or better, 24 profession stock, 5 a quest
    item, 5 with no vendor price). No single member's sale cleared the
    trigger of 3 free slots, so the pass took no trip, wrote no sale rows and
    logged "no vendor within reach" for the three of them on every pass - and
    the health endpoint read them as stuck for 2.2 hours.
    """

    NAMES = ["Bork", "Grog", "Ugga", "Og"]
    FREE = {"Bork": 0, "Grog": 0, "Ugga": 0, "Og": 10}
    SELLABLE = {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2}

    def test_the_trip_goes_when_the_family_frees_room_between_its_members(self):
        # No sustained wait either: the family has not been waiting for a
        # vendor, its sale is simply spread over three members. The trip goes
        # for the sale itself (#1204): one walk to a counter sells every
        # holder's stacks, and Grog's two and Ugga's one add up to the
        # trigger's width of three free slots at the floor, so the goods move
        # and the room is made even though no single member's sale lifts its
        # seller past the trigger.
        namespace = _vendor_pass_mode({"_fetch_vendor_wait_seconds": lambda names: 0})
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, self.NAMES, self.FREE, self.SELLABLE, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)

    def test_the_bag_room_hold_does_not_wait_on_that_trip(self):
        # #1309's case, unchanged: no single member's sale lifts its seller
        # past the trigger (Grog 0 + 2 = 2, Ugga 0 + 1 = 1), so the trip
        # frees the floor for nobody and the hold must not wait on it. The
        # trip still goes (#1204): the family's goods are what the walk is
        # for, and the two questions are separate.
        self.assertFalse(bag_pressure.vendor_trip_makes_room(self.FREE, self.SELLABLE))

    def test_no_trip_when_the_family_carries_nothing_a_vendor_would_buy(self):
        # Bork alone at the floor, with 68 kept stacks: the trip cannot help
        # anybody, and infra#4190's answer still stands.
        namespace = _vendor_pass_mode({"_fetch_vendor_wait_seconds": lambda names: 0})
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Bork"], {"Bork": 0}, {"Bork": 0}, False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_COUNTER, mode)


class TheSharedSaleCount(unittest.TestCase):
    """#1204: one walk to a counter sells every holder's stacks.

    The count the vendor pass asks before it takes the shared sale: the slots
    the walk frees for the members at the floor, counted together and not one
    member at a time.
    """

    def test_the_floor_s_stacks_are_counted_together(self):
        # Bork carries 68 stacks no vendor will buy, so he frees nothing;
        # Grog and Ugga, at the floor, carry two and one. Og's two are sold
        # too, but Og has ten free slots: a slot freed in his bags is not one
        # in anybody's at the floor (#1243).
        self.assertEqual(
            3,
            bag_pressure.family_shared_sale_slots(
                {"Bork": 0, "Grog": 0, "Ugga": 0, "Og": 10},
                {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2},
            ),
        )

    def test_stacks_of_members_with_room_free_nothing_at_the_floor(self):
        self.assertEqual(
            0,
            bag_pressure.family_shared_sale_slots(
                {"Bork": 0, "Grog": 12, "Ugga": 9, "Og": 10},
                {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2},
            ),
        )

    def test_a_family_with_room_frees_nothing(self):
        self.assertEqual(
            0,
            bag_pressure.family_shared_sale_slots({"Bork": 11}, {"Bork": 40}),
        )

    def test_an_unreadable_count_frees_nothing(self):
        self.assertEqual(
            0, bag_pressure.family_shared_sale_slots({"Og": 0}, {"Og": None})
        )
        self.assertEqual(0, bag_pressure.family_shared_sale_slots({"Og": 0}, {}))
        self.assertEqual(
            0, bag_pressure.family_shared_sale_slots({"Og": 0}, {"Og": -5})
        )

    def test_an_unknown_family_frees_nothing(self):
        self.assertEqual(0, bag_pressure.family_shared_sale_slots({}, {"Og": 4}))
        self.assertEqual(
            0, bag_pressure.family_shared_sale_slots({"Og": -1}, {"Og": 4})
        )
        self.assertEqual(
            0, bag_pressure.family_shared_sale_slots({"Og": None}, {"Og": 4})
        )


class NoTripForAFloorItCannotLift(unittest.TestCase):
    """#1243: the family-room trip of #1204 counts only the floor's stacks.

    Bork sits at the floor on stacks no vendor will buy, and the members with
    room have looted five vendor stacks between them. Selling those frees
    slots in bags that were not full; the trip that took the leader's walk
    for it left Bork where he was, re-armed on the next pass, and kept the
    family in the bag-room hold.
    """

    def test_the_trip_does_not_go_for_stacks_of_members_with_room(self):
        namespace = _vendor_pass_mode({"_fetch_vendor_wait_seconds": lambda names: 0})
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None,
                ["Bork", "Grog", "Ugga", "Og"],
                {"Bork": 0, "Grog": 12, "Ugga": 9, "Og": 10},
                {"Bork": 0, "Grog": 2, "Ugga": 1, "Og": 2},
                False,
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_COUNTER, mode)

    def test_the_pass_records_the_counts_its_trip_decision_used(self):
        # The dungeon quest hold reads these to ask whether the trip it waits
        # on would make room; a pass that did not record them would leave it
        # waiting as before.
        recorded = {}
        namespace = _vendor_pass_mode(
            {
                "_fetch_vendor_wait_seconds": lambda names: 0,
                "_note_vendor_sellable": lambda names, sellable: recorded.update(
                    sellable
                ),
            }
        )
        asyncio.run(
            namespace["_vendor_pass_mode"](
                None, ["Bork", "Og"], {"Bork": 0, "Og": 10}, {"Bork": 0, "Og": 2}, False
            )
        )
        self.assertEqual({"Bork": 0, "Og": 2}, recorded)


class TheHeldFollowerGuardHasABound(unittest.TestCase):
    """#1983: a follower that can never be fetched no longer blocks the trip.

    The dev realm on 2026-11-07: Zork stood in Tanaris about 3100 yards from
    the four other members of his family in Un'Goro Crater, held for the
    leader to fetch, and every fetch was refused because his combat flag never
    cleared. The guard of #1948 kept the family in counter mode for hours
    ("no vendor trip while a sellable family member is held for the leader to
    fetch", 41 lines from 17:00 to 20:21 UTC) and Oz, standing with the
    leader with 21 sale candidates, sold nothing.
    """

    NAMES = ["Zug", "Oz", "Uzza", "Zrog", "Zork"]
    FREE = {"Zug": 12, "Oz": 5, "Uzza": 10, "Zrog": 11, "Zork": 4}
    SELLABLE = {"Zug": 0, "Oz": 21, "Uzza": 4, "Zrog": 0, "Zork": 10}
    BOUND = vendor_stall.HELD_FETCH_BOUND_SECONDS

    def _guard(self, lines):
        held = {
            "Zork": jev_family_intent.Member("Zork", "held too far to walk", "3100")
        }
        return _vendor_seller_fetch_blocks_trip(
            {
                "_vendor_sellers_held_for_leader": lambda *args: held,
                "log": types.SimpleNamespace(
                    info=lambda fmt, *args: lines.append(fmt % args)
                ),
            }
        )

    def test_the_guard_holds_inside_the_bound_and_lets_the_trip_go_after(self):
        lines, since = [], {}
        guard = self._guard(lines)
        args = (self.NAMES, "Zug", self.FREE, self.SELLABLE, False)
        self.assertTrue(guard(*args, since=since, now=100.0))
        self.assertTrue(guard(*args, since=since, now=100.0 + self.BOUND - 1))
        released = guard(*args, since=since, now=100.0 + self.BOUND)
        self.assertFalse(released)
        self.assertEqual(("Zork",), released.left_behind)

    def test_the_follower_left_behind_is_named_once_per_hold(self):
        lines, since = [], {}
        guard = self._guard(lines)
        args = (self.NAMES, "Zug", self.FREE, self.SELLABLE, False)
        guard(*args, since=since, now=0.0)
        guard(*args, since=since, now=self.BOUND)
        guard(*args, since=since, now=self.BOUND + 300)
        guard(*args, since=since, now=self.BOUND + 600)
        self.assertEqual(1, len(lines))
        self.assertIn("Zork", lines[0])
        self.assertIn("held too far to walk", lines[0])
        self.assertIn("3100", lines[0])
        self.assertIn("leaves Zork behind", lines[0])

    def test_a_new_hold_starts_a_fresh_clock(self):
        since = {}
        first = vendor_stall.held_fetch_bound("Zug", ["Zork"], since, 0.0)
        self.assertTrue(first)
        late = vendor_stall.held_fetch_bound("Zug", ["Zork"], since, self.BOUND)
        self.assertEqual(("Zork",), late.newly_left)
        # Zork is fetched: nobody is held, and the clock is dropped.
        vendor_stall.held_fetch_bound("Zug", [], since, self.BOUND + 60)
        self.assertEqual({}, since)
        again = vendor_stall.held_fetch_bound("Zug", ["Zork"], since, self.BOUND + 120)
        self.assertTrue(again)
        self.assertEqual((), again.left_behind)

    def test_one_follower_still_inside_its_bound_keeps_the_guard(self):
        since = {}
        vendor_stall.held_fetch_bound("Zug", ["Zork"], since, 0.0)
        both = vendor_stall.held_fetch_bound("Zug", ["Zork", "Uzza"], since, self.BOUND)
        self.assertTrue(both)
        self.assertEqual(("Zork",), both.left_behind)

    def test_the_trip_goes_for_the_members_who_stand_with_the_leader(self):
        names, free, sellable = vendor_stall.without_left_behind(
            self.NAMES, self.FREE, self.SELLABLE, ("Zork",)
        )
        self.assertNotIn("Zork", names)
        self.assertNotIn("Zork", free)
        self.assertNotIn("Zork", sellable)
        # Oz and Uzza logged "no vendor within reach" on every pass for
        # hours: the sustained wait that takes a trip once the guard lets go.
        namespace = _vendor_pass_mode(
            {"_fetch_vendor_wait_seconds": lambda n: 3 * 60 * 60}
        )
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, names, free, sellable, False, held_seller_for_leader=False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_TRIP, mode)

    def test_no_trip_rearms_on_stacks_only_the_absent_member_carries(self):
        # After the leader's walk Oz and Uzza have sold out; Zork's ten
        # stacks alone are no reason for the leader to walk again.
        sold = dict(self.SELLABLE, Oz=0, Uzza=0)
        free = dict(self.FREE, Oz=26, Uzza=14)
        names, free, sold = vendor_stall.without_left_behind(
            self.NAMES, free, sold, ("Zork",)
        )
        namespace = _vendor_pass_mode(
            {"_fetch_vendor_wait_seconds": lambda n: 8 * 60 * 60}
        )
        mode = asyncio.run(
            namespace["_vendor_pass_mode"](
                None, names, free, sold, False, held_seller_for_leader=False
            )
        )
        self.assertEqual(bag_pressure.VENDOR_MODE_COUNTER, mode)

    def test_the_economy_pass_judges_the_trip_without_the_left_behind(self):
        # The wiring in _vendor_once: the pass mode is asked about the family
        # without the members the guard left behind.
        body = BRIDGE[BRIDGE.index("async def _vendor_once(") :]
        body = body[: body.index("\n    async def ", 10)]
        self.assertIn("vendor_stall.without_left_behind(", body)
        self.assertIn("trip_names, trip_free, trip_sellable, in_run", body)
