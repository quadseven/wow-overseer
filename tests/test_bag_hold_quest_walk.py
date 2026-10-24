"""A released bag hold keeps the quest walk it handed over (#872).

#1178 made the hold at the bag floor time out into questing: after
bag_pressure.BAG_HOLD_STUCK_SECONDS with no slot gained, the campaign gate
says "... so the family quests until there is room" and the level pass walks
the leader to its leveling hub. Measured on the dev realm 2026-10-18, from the
18:21Z bridge ship on, that line came every minute for over four hours and the
family never got there:

    19:07:03 town slot: level takes the traveller Grug from economy ...
    19:10:51 economy: released stale leader ground aim
             at:1:139.2,1325.8,193.5 under bag pressure; vendor
             maintenance gets the town slot next
    ...
    22:32:38 town slot: level takes the traveller Grug for
             'at:1:139.2,1325.8,193.5'; the column was free
    22:37:43 economy: released stale leader ground aim
             at:1:139.2,1325.8,193.5 under bag pressure; ...

The walk to Nijel's Point is a ground aim, and the economy pass releases a
leader's ground aim whenever the bags are under pressure. The bags were the
reason the hold was released (Bork carries nothing a vendor will buy), so they
kept tearing down the walk that was meant to be the way out. Five of the six
walks the level pass won were released this way within six minutes.

Pinned here: once the hold is released, bag pressure no longer releases the
leader's ground aim; while the hold still stands it does, as before.
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
import vendor_stall

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

# The level pass's walk to Nijel's Point, as the log names it.
QUEST_WALK = "at:1:139.2,1325.8,193.5"
FAMILY = ("Bork", "Grog", "Grug", "Og", "Ugga")
# Free slots logged with the hold on 2026-10-18.
FREE = {"Bork": 1, "Grog": 3, "Grug": 13, "Og": 11, "Ugga": 3}


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


class _Clock:
    def monotonic(self):
        return 0.0


def _ground(aim):
    return str(aim).startswith("at:")


class _FakeEconomySelf:
    """Every pass `_vendor_once` calls, as a no-op, plus the town slot."""

    def __init__(self):
        self.slot = townslot.Slot()

    def _cohort_town_slot(self, cohort=None):
        return self.slot

    async def _settle_vendor_errand_and_should_yield(self, names, leader):
        return bag_pressure.VENDOR_ERRAND_AIM

    async def _claim_town_slot(self, claimant, character, aim, **kw):
        return False

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

    def _jev_keep_shadow(self, *a, **k):
        return None

    _release_stranded_vendor_errands = _noop
    _release_stranded_ground_errands = _noop
    _hand_recipes = _noop
    _route_lockboxes = _noop
    _route_clearance = _noop
    _jev_keep_give = _noop
    _hand_gear = _noop
    _equip_upgrades = _noop
    _destroy_released = _noop


def _vendor_rows():
    """The one stack Grog carries that a vendor will buy."""
    return [
        dict(
            holder="Grog",
            item_guid=15444324,
            count=1,
            quality=0,
            sell_price=12,
            quest_item=False,
            reagent=False,
            profession_needed=False,
            name="Broken Fang",
        )
    ]


def _run_vendor_once(stuck):
    """One economy pass with the leader on the quest walk; the aims it
    released."""
    released = []

    def release(name, aim):
        released.append((name, aim))
        return True

    ns = _load(
        [
            "_vendor_once",
            "_vendor_pass_mode",
            "_sellable_per_holder",
            "_without_bank_keeps",
            "_take_vendor_aim",
            "_count_sales",
            "_queue_vendor_sales",
            "_report_vendor_claim",
            "_bag_hold_released",
        ],
        {
            "_BAG_HOLD_STUCK": dict(stuck),
            "_bank_policy": lambda names, fresh=False: {},
            "_bank_spare": lambda names, fresh=False: frozenset(),
            "_log_capped": lambda prefix, notes: None,
            "_log_changed": lambda prefix, notes, key=(), capped=True: None,
            "asyncio": types.SimpleNamespace(to_thread=_thread),
            "time": _Clock(),
            "log": _Log(),
            "townslot": townslot,
            "bag_pressure": bag_pressure,
            "vendor_stall": vendor_stall,
            "jev_activity": jev_activity,
            "item_plan": item_plan,
            "lockbox": lockbox,
            "travel": types.SimpleNamespace(is_ground_aim=_ground),
            "disposition": types.SimpleNamespace(
                Family=lambda **k: None, EXECUTABLE_TODAY=()
            ),
            "OWNER_KEEPS": (),
            "SELL_ROUTES": (),
            "SELL_MEMORY_HOURS": 24,
            "_fetch_free_slots": lambda names: dict(FREE),
            "_present_members": lambda names, leader="": list(names),
            "_fetch_vendor_wait_seconds": lambda names: 0,
            "_fetch_vendor_items": lambda names: _vendor_rows(),
            "_fetch_surplus_bags": lambda names: [],
            "_fetch_equipped_bag_slots": lambda names: {},
            "_clearance_sales": lambda plan: (),
            "_current_travel_npc": lambda name: QUEST_WALK if name == "Grug" else "",
            "_release_trade_errand": release,
            "_fetch_surplus_gear": lambda names: [],
            "_fetch_equip_candidate_gear": lambda names: [],
            "_fetch_family_equipped": lambda names: [],
            "_campaign_waiting": lambda names: True,
            "_town_errand_active": lambda names: False,
            "_town_first_hold": lambda names: False,
            "_insert_job": lambda *a: 1,
            "_sell_attempts": lambda hours: {},
            "_fetch_town": lambda name: towntrip.Town(vendor=False),
            "_insert_sell": lambda c: 1,
            "_nearest_vendor_yards": lambda name: None,
        },
    )
    me = _FakeEconomySelf()
    me._vendor_pass_mode = lambda *a: ns["_vendor_pass_mode"](me, *a)
    me._take_vendor_aim = lambda *a: ns["_take_vendor_aim"](me, *a)
    cohort = townslot.Cohort(key="Grug", leader="Grug", names=FAMILY)
    asyncio.run(ns["_vendor_once"](me, cohort))
    return released


class AReleasedHoldKeepsTheQuestWalk(unittest.TestCase):
    def test_the_live_bags_are_bag_pressure(self):
        """The precondition: these bags make the release urgent at all."""
        self.assertTrue(bag_pressure.family_town_run_needed(FREE, sellable={"Grog": 1}))

    def test_a_released_hold_does_not_release_the_quest_walk(self):
        stuck = {name: ("Bork", "Grog", "Ugga") for name in FAMILY}
        self.assertEqual([], _run_vendor_once(stuck))

    def test_a_hold_still_standing_releases_the_stale_ground_aim(self):
        """Unchanged while the hold has not timed out: a town pass may still
        make room, so the urgent release stands."""
        self.assertEqual([("Grug", QUEST_WALK)], _run_vendor_once({}))


class ThePureRule(unittest.TestCase):
    def test_a_released_hold_is_no_reason_to_interrupt_a_ground_aim(self):
        self.assertFalse(
            townslot.urgent_ground_release(
                aim=QUEST_WALK,
                pressure=True,
                in_run=False,
                hold_released=True,
                ground=_ground,
            )
        )

    def test_the_hold_defaults_to_standing(self):
        self.assertTrue(
            townslot.urgent_ground_release(
                aim=QUEST_WALK, pressure=True, in_run=False, ground=_ground
            )
        )


class TheReleasedReading(unittest.TestCase):
    def _released(self, stuck, names):
        ns = _load(["_bag_hold_released"], {"_BAG_HOLD_STUCK": stuck})
        return ns["_bag_hold_released"](names)

    def test_any_member_with_a_released_hold_counts(self):
        self.assertTrue(self._released({"Grug": ("Bork",)}, FAMILY))

    def test_no_released_hold_is_not_released(self):
        self.assertFalse(self._released({"Zug": ("Oz",)}, FAMILY))
        self.assertFalse(self._released({}, FAMILY))


if __name__ == "__main__":
    unittest.main()
