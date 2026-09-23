"""A campaign withheld for bag space sells, buys a bag and keeps its aim (#225).

Measured on wow-dev 2026-09-23. The Horde family's Ragefire Chasm order was
withheld for bag space for 45 minutes, and no sell, buy, give or mail row was
written for any member in that time:

    economy: no vendor trip is worth taking - free slots {..., 'Zug': 2}
             against sellable {..., 'Zug': 1} at a trigger of 3
    town slot: bags refines an unknown pass's '3487' on Zug into '3487'
    town slot: clearance takes the traveller Zug from bags: '3487' has held
             the family's one travel column for 946s, past its 300s lease
    bags: Zug is aimed at creature 3481 (Barg, faction 29, 17 yards) ...
             (aim taken=False)

Three defects, each pinned here against fakes:

  * The economy gate asks only whether SELLING lifts somebody past the line.
    For the leader, at 2 free slots with 1 sellable item, it does not. The
    pass returned before writing any sale, including when the Jev sell
    interlude called it.
  * Refining an orphaned aim kept the orphan's clock but moved it to the 300s
    lease, so the bag trip's lease had run out before it took the aim.
  * Fairness gave the traveller to clearance 17 yards short of the bag
    vendor. While the campaign is withheld, only the bag trip owns the aim.
"""

import ast
import asyncio
import pathlib
import types
import unittest

import bag_pressure
import item_plan
import jev_activity
import lockbox
import towntrip
import townslot

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

HORDE = townslot.Cohort(
    key="Zug", leader="Zug", names=("Oz", "Uzza", "Zork", "Zrog", "Zug")
)
# The free slots and sellable counts logged at 04:31:05.
LIVE_FREE = {"Oz": 23, "Uzza": 10, "Zork": 6, "Zrog": 6, "Zug": 2}
LIVE_SELLABLE = {"Oz": 4, "Uzza": 3, "Zork": 5, "Zrog": 7, "Zug": 1}


def economy(aim):
    return aim in ("vendor", "repair", "auctioneer") or (
        aim.startswith("at:") or aim.isdigit()
    )


def retaskable(aim):
    """`bridge._retaskable_from` for the aims this file writes."""
    if aim.isdigit():
        return ("", aim, "vendor")
    return ("", aim)


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


def _load(names, namespace):
    module = ast.Module(body=[_function(n) for n in names], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), namespace)  # noqa: S102
    return namespace


class _Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = debug = info


def _thread(fn, *a, **k):
    async def run():
        return fn(*a, **k)

    return run()


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def monotonic(self):
        return self.now


# --- the pure halves ---------------------------------------------------------


class TheGateCountsAWithheldCampaign(unittest.TestCase):
    def test_the_live_numbers_are_no_trip_on_sales_alone(self):
        """The defect's input: 2 + 1 is not past a trigger of 3."""
        self.assertFalse(
            bag_pressure.family_town_run_needed(LIVE_FREE, sellable=LIVE_SELLABLE)
        )
        self.assertTrue(jev_activity.withheld(True, LIVE_FREE))

    def test_a_withheld_campaign_sells_at_the_counter(self):
        self.assertEqual(
            bag_pressure.VENDOR_PASS_COUNTER,
            bag_pressure.vendor_pass_mode(False, True, False),
        )

    def test_a_trip_worth_taking_is_still_a_trip(self):
        for withheld in (False, True):
            self.assertEqual(
                bag_pressure.VENDOR_PASS_TRIP,
                bag_pressure.vendor_pass_mode(True, withheld, False),
            )

    def test_no_campaign_waiting_stays_home_as_before(self):
        self.assertEqual(
            bag_pressure.VENDOR_PASS_NONE,
            bag_pressure.vendor_pass_mode(False, False, False),
        )

    def test_never_inside_a_run(self):
        self.assertEqual(
            bag_pressure.VENDOR_PASS_NONE,
            bag_pressure.vendor_pass_mode(False, True, True),
        )


class AnOrphansClockIsNotInherited(unittest.TestCase):
    def test_the_live_sequence_keeps_the_bag_trip(self):
        """'3487' seen as an orphan at 0, refined by bags at 730, and asked
        for by clearance at 946. Clearance used to preempt at 946."""
        slot = townslot.Slot(releasable=economy)
        slot.want(
            claimant="clearance",
            character="Zug",
            aim="at:1:-443.7,-2649.1,95.8",
            leader="Zug",
            column="3487",
            retaskable=("", "at:1:-443.7,-2649.1,95.8"),
            now=0.0,
        )
        bags = slot.want(
            claimant="bags",
            character="Zug",
            aim="3487",
            leader="Zug",
            column="3487",
            retaskable=("", "3487", "vendor"),
            now=730.0,
        )
        self.assertEqual(townslot.SLOT_TAKE, bags.verdict)
        slot.settle(bags, True, 730.0)
        self.assertEqual(730.0, slot.holder.since)
        clearance = slot.want(
            claimant="clearance",
            character="Zug",
            aim="at:1:-443.7,-2649.1,95.8",
            leader="Zug",
            column="3487",
            retaskable=("", "at:1:-443.7,-2649.1,95.8"),
            now=946.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, clearance.verdict)

    def test_a_named_holders_clock_is_still_inherited(self):
        """The laundering guard between two owners is unchanged."""
        slot = townslot.Slot(releasable=economy)
        first = slot.want(
            claimant="economy",
            character="Zug",
            aim="vendor",
            leader="Zug",
            column="",
            retaskable=("", "vendor"),
            now=0.0,
        )
        slot.settle(first, True, 0.0)
        refined = slot.want(
            claimant="bags",
            character="Zug",
            aim="3481",
            leader="Zug",
            column="vendor",
            retaskable=("", "3481", "vendor"),
            now=200.0,
        )
        self.assertEqual(0.0, refined.inherit_since)


class OneOwnerWhileReserved(unittest.TestCase):
    def slot(self):
        slot = townslot.Slot(releasable=economy)
        taken = slot.want(
            claimant="bags",
            character="Zug",
            aim="3481",
            leader="Zug",
            column="",
            retaskable=("", "3481", "vendor"),
            now=0.0,
        )
        slot.settle(taken, True, 0.0)
        slot.reserve("bags", 0.0, "the campaign is withheld")
        return slot

    def ask(self, slot, claimant, now):
        return slot.want(
            claimant=claimant,
            character="Zug",
            aim="at:1:1,2,3",
            leader="Zug",
            column="3481",
            retaskable=("", "at:1:1,2,3"),
            now=now,
        )

    def test_another_pass_waits_past_the_lease(self):
        d = self.ask(self.slot(), "clearance", 600.0)
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)
        self.assertIn("bags owns the traveller Zug", d.reason)

    def test_an_idle_request_waits_too(self):
        d = self.slot().want_idle(
            claimant="craft_rhythm",
            character="Zug",
            leader="Zug",
            column="3481",
            now=600.0,
        )
        self.assertEqual(townslot.SLOT_WAIT, d.verdict)

    def test_the_owner_still_holds(self):
        d = self.slot().want(
            claimant="bags",
            character="Zug",
            aim="3481",
            leader="Zug",
            column="3481",
            retaskable=("", "3481", "vendor"),
            now=600.0,
        )
        self.assertEqual(townslot.SLOT_HOLD, d.verdict)

    def test_asking_again_does_not_renew_it(self):
        slot = self.slot()
        slot.reserve("bags", 1000.0, "again")
        self.assertEqual(0.0, slot.reservation.since)

    def test_the_hold_is_bounded(self):
        slot = self.slot()
        self.assertFalse(slot.reserved_by("bags", townslot.RESERVE_SECONDS))
        d = self.ask(slot, "clearance", townslot.RESERVE_SECONDS + 1)
        self.assertEqual(townslot.SLOT_PREEMPT, d.verdict)

    def test_unreserve_frees_the_turn(self):
        slot = self.slot()
        slot.unreserve("clearance")
        self.assertIsNotNone(slot.reservation)
        slot.unreserve("bags")
        self.assertEqual(
            townslot.SLOT_PREEMPT, self.ask(slot, "clearance", 600.0).verdict
        )


# --- the bridge, with a fake world -------------------------------------------

BARG_ROWS = [
    dict(
        entry=3481,
        name="Barg",
        faction=29,
        map_id=1,
        yards=17.0,
        item=4496,
        item_name="Small Brown Pouch",
        slots=6,
        price=500,
    )
]


class FakeWorld:
    """The Horde family at 04:31: an orphan '3487' on Zug, Barg 17 yards off."""

    def __init__(self, *, queued=True, column="3487"):
        self.queued = queued
        self.column = {"Zug": column}
        self.writes = []
        self.releases = []
        self.sells = []
        self.jobs = []

    def current(self, name):
        return self.column.get(name, "")

    def write(self, errand):
        self.writes.append((errand.character, errand.travel_npc))
        allowed = retaskable(errand.travel_npc)
        if self.column.get(errand.character, "") not in allowed:
            return False
        self.column[errand.character] = errand.travel_npc
        return True

    def release(self, name, aim):
        self.releases.append((name, aim))
        if self.column.get(name) != aim:
            return False
        self.column[name] = ""
        return True

    def standing(self, names):
        return [
            dict(
                name=n,
                map_id=1,
                pos_x=-440.0,
                pos_y=-2640.0,
                in_combat=0,
                job="quest",
                home_map=1,
                home_x=-440.0,
                home_y=-2640.0,
            )
            for n in names
        ]


def _bridge_self(world, clock, log):
    ns = _load(
        ["_claim_town_slot", "_aim_at_bag_vendor", "_cohort_town_slot"],
        {
            "asyncio": types.SimpleNamespace(to_thread=_thread),
            "time": clock,
            "log": log,
            "townslot": townslot,
            "bag_pressure": bag_pressure,
            "jev_activity": jev_activity,
            "professions": types.SimpleNamespace(
                Errand=lambda character, travel_npc: types.SimpleNamespace(
                    character=character, travel_npc=travel_npc
                )
            ),
            "BAGS_CLAIMANT": "bags",
            "TOWN_SLOT_LEASE_SECONDS": townslot.LEASE_SECONDS,
            "GATHER_CLAIMANT": "gather",
            "FLIGHT_CLAIMANT": "flight",
            "TOWN_SLOT_GATHER_LEASE_SECONDS": townslot.GATHER_LEASE_SECONDS,
            "TOWN_SLOT_FLIGHT_LEASE_SECONDS": townslot.GATHER_LEASE_SECONDS,
            "_is_economy_aim": economy,
            "_retaskable_from": retaskable,
            "_cohort_leader": lambda key: "Zug",
            "_head_now": lambda: "Grug",
            "_current_travel_npc": world.current,
            "_write_trade_errand": world.write,
            "_release_trade_errand": world.release,
            "_fetch_bag_trip_facts": world.standing,
            "_fetch_bag_vendors": lambda here: BARG_ROWS,
            "_campaign_waiting": lambda names: world.queued,
            "_fetch_free_slots": lambda names: dict(LIVE_FREE),
        },
    )
    me = types.SimpleNamespace(_town_slot=townslot.Slot(), _cohort_town_slots={})

    async def mid_run(names):
        return False

    me._mid_run = mid_run
    for name in ("_claim_town_slot", "_aim_at_bag_vendor", "_cohort_town_slot"):
        fn = ns[name]
        setattr(me, name, lambda *a, _fn=fn, **k: _fn(me, *a, **k))
    return me


def _needy():
    return tuple(
        bag_pressure.BagBuyer(
            name=n,
            level=18,
            money=10913,
            open_positions=4,
            free_slots=LIVE_FREE[n],
        )
        for n in HORDE.names
    )


class TheBagTripKeepsTheTraveller(unittest.TestCase):
    def run_live_sequence(self, world):
        clock, log = Clock(), _Log()
        me = _bridge_self(world, clock, log)
        slot = me._cohort_town_slot(HORDE)
        # 04:15:17 - clearance first sees the orphan '3487' on Zug.
        asyncio.run(
            me._claim_town_slot(
                "clearance", "Zug", "at:1:-443.7,-2649.1,95.8", cohort="Zug"
            )
        )
        # 04:27:29 - the bag trip aims Zug at Barg.
        clock.now = 730.0
        asyncio.run(me._aim_at_bag_vendor(_needy(), list(HORDE.names), HORDE))
        # 04:31:04 - clearance asks again.
        clock.now = 946.0
        took = asyncio.run(
            me._claim_town_slot(
                "clearance", "Zug", "at:1:-443.7,-2649.1,95.8", cohort="Zug"
            )
        )
        return took, slot, log.lines

    def test_a_withheld_campaign_keeps_the_leader_on_the_bag_vendor(self):
        world = FakeWorld(queued=True)
        took, slot, lines = self.run_live_sequence(world)
        self.assertEqual("3481", world.column["Zug"], lines)
        self.assertFalse(took, lines)
        self.assertTrue(slot.reserved_by("bags", 946.0))

    def test_without_a_campaign_the_ordinary_turn_is_unchanged(self):
        """No reservation and no urgency: the orphan's long lease stands, so
        the bag trip waits exactly as it did before."""
        world = FakeWorld(queued=False)
        took, slot, lines = self.run_live_sequence(world)
        self.assertIsNone(slot.reservation)
        self.assertEqual("3487", world.column["Zug"], lines)

    def test_the_hold_ends_when_the_campaign_is_no_longer_withheld(self):
        world = FakeWorld(queued=True)
        _, slot, _ = self.run_live_sequence(world)
        world.queued = False
        clock, log = Clock(1000.0), _Log()
        me = _bridge_self(world, clock, log)
        me._cohort_town_slots["Zug"] = slot
        asyncio.run(me._aim_at_bag_vendor(_needy(), list(HORDE.names), HORDE))
        self.assertIsNone(slot.reservation)


class _FakeEconomySelf:
    """Every pass `_vendor_once` calls, as a no-op, plus the town slot."""

    def __init__(self, world):
        self.world = world
        self.claims = []
        self.slot = townslot.Slot(releasable=economy)

    def _cohort_town_slot(self, cohort=None):
        return self.slot

    async def _settle_vendor_errand(self, names, leader):
        return bag_pressure.VENDOR_ERRAND_AIM

    async def _claim_town_slot(self, claimant, character, aim, **kw):
        self.claims.append((claimant, aim))
        return True

    async def _mid_run(self, names):
        return False

    async def _lockbox_plan(self, names, free_slots):
        return types.SimpleNamespace(sell=())

    async def _clearance_plan(self, names, leader, auction_open=True):
        return ()

    async def _jev_items_plan(self, *a):
        return None

    async def _noop(self, *a, **k):
        return None

    _release_stranded_vendor_errands = _noop
    _release_stranded_ground_errands = _noop
    _hand_recipes = _noop
    _route_lockboxes = _noop
    _route_clearance = _noop
    _hand_gear = _noop
    _equip_upgrades = _noop


def _vendor_rows():
    """One grey each, the counts logged at 04:31:05 for the leader."""
    return [
        dict(
            holder="Zug",
            item_guid=9001,
            count=1,
            quality=0,
            sell_price=12,
            quest_item=False,
            reagent=False,
            profession_needed=False,
            name="Broken Fang",
        )
    ]


def _run_vendor_once(queued, at_vendor=True):
    log = _Log()
    world = types.SimpleNamespace(sells=[])
    free = {"Zug": 2}
    ns = _load(
        ["_vendor_once", "_sellable_per_holder"],
        {
            "asyncio": types.SimpleNamespace(to_thread=_thread),
            "time": Clock(),
            "log": log,
            "townslot": townslot,
            "bag_pressure": bag_pressure,
            "jev_activity": jev_activity,
            "item_plan": item_plan,
            "lockbox": lockbox,
            "travel": types.SimpleNamespace(is_ground_aim=lambda a: False),
            "disposition": types.SimpleNamespace(
                Family=lambda **k: None, EXECUTABLE_TODAY=()
            ),
            "OWNER_KEEPS": (),
            "SELL_ROUTES": (),
            "SELL_MEMORY_HOURS": 24,
            "_fetch_free_slots": lambda names: dict(free),
            "_fetch_vendor_items": lambda names: _vendor_rows(),
            "_fetch_surplus_bags": lambda names: [],
            "_fetch_equipped_bag_slots": lambda names: {},
            "_clearance_sales": lambda plan: (),
            "_current_travel_npc": lambda name: "",
            "_release_trade_errand": lambda *a: False,
            "_fetch_surplus_gear": lambda names: [],
            "_fetch_family_equipped": lambda names: [],
            "_campaign_waiting": lambda names: queued,
            "_insert_job": lambda *a: 1,
            "_sell_attempts": lambda hours: {},
            "_fetch_town": lambda name: towntrip.Town(vendor=at_vendor),
            "_insert_sell": lambda c: world.sells.append(c) or 1,
        },
    )
    me = _FakeEconomySelf(world)
    cohort = townslot.Cohort(key="Zug", leader="Zug", names=("Zug",))
    asyncio.run(ns["_vendor_once"](me, cohort))
    return world.sells, me.claims, log.lines


class TheEconomySellsForAWithheldCampaign(unittest.TestCase):
    def test_the_leader_at_a_vendor_sells_its_junk(self):
        sells, claims, lines = _run_vendor_once(queued=True)
        self.assertEqual([9001], [c.item_guid for c in sells], lines)

    def test_and_takes_no_aim_of_its_own(self):
        _, claims, lines = _run_vendor_once(queued=True)
        self.assertEqual([], claims, lines)

    def test_away_from_a_vendor_nothing_is_written(self):
        sells, claims, _ = _run_vendor_once(queued=True, at_vendor=False)
        self.assertEqual([], sells)
        self.assertEqual([], claims)

    def test_with_no_campaign_waiting_it_stays_home_as_before(self):
        sells, claims, lines = _run_vendor_once(queued=False)
        self.assertEqual([], sells)
        self.assertEqual([], claims)
        self.assertTrue(
            any("no vendor trip is worth taking" in ln for ln in lines), lines
        )


if __name__ == "__main__":
    unittest.main()
