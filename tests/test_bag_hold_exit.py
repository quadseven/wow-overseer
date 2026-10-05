"""A family held in town for bag room always has a way out.

Measured on the dev realm 2026-10-05. Both family campaigns sat on job
`town run` for over three hours, and Grug's family earned 800 to 4,700
experience each in that time while Zug's earned none. Every cycle the
economy pass logged the family waiting in town with free slots
{Bork 15, Grog 0, Grug 19, Og 10, Ugga 6} and sellable {Bork 1, Grog 0,
Grug 1, Og 0, Ugga 3}. Grog's 57 items were all protected from a vendor
(crafting goods, soulbound gear, quest items, things with no price), and the
bank and guild bank passes, the two that could have made room, waited while
"town errand owns the traveller Grug". The town errand itself was waiting for
room. A cycle, with no exit: the module opens no run while a member has three
or fewer free slots, and the bridge held the family in town until one did.

Pinned here:

  * The bank makes room. While a campaign waits, a member short of the
    resume floor puts its trade goods and gems in its own bank up to that
    floor, never food, quest items, gear or the hearthstone, and nothing is
    withdrawn below it.
  * The town errand's bank step is the bank and the guild bank's turn.
  * The hold is judged on evidence. Once no held member has gained a slot in
    bag_pressure.BAG_HOLD_STUCK_SECONDS, the family goes back to questing
    (the campaign stays queued), stays out until nobody is at the floor, and
    the bag-room town errand stops pulling it back.
"""

import ast
import asyncio
import contextlib
import pathlib
import types
import unittest

import bag_pressure
import bank
import jobs
import townerrand

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

NAMES = ["Bork", "Grog", "Grug", "Og", "Ugga"]
# The economy pass's reading, every cycle of the hold.
MEASURED = {"Bork": 15, "Grog": 0, "Grug": 19, "Og": 10, "Ugga": 6}
WINDOW = bag_pressure.BAG_HOLD_STUCK_SECONDS
TOWN_FIRST = "overseer:town-first"
TOWN_ERRAND = "overseer:town-errand"


def _functions(*names):
    found = {
        node.name: node
        for node in ast.walk(ast.parse(BRIDGE))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    }
    missing = set(names) - set(found)
    if missing:
        raise AssertionError("not found in bridge.py: %s" % sorted(missing))
    return [found[n] for n in names]


def _held(previous, free, now):
    return bag_pressure.bag_hold_progress(previous, free, now)


def _minutes(progress, free, start, minutes):
    """Read `free` once a minute for `minutes` minutes from `start`."""
    for minute in range(1, minutes + 1):
        progress = _held(progress, free, start + 60.0 * minute)
    return progress


class TheHoldIsJudgedOnEvidence(unittest.TestCase):
    def test_nobody_at_the_floor_is_no_hold(self):
        self.assertIsNone(_held(None, {"Grog": 4, "Ugga": 6}, 0.0))

    def test_the_measured_family_is_held_on_grog(self):
        progress = _held(None, MEASURED, 0.0)
        self.assertEqual((("Grog", 0),), progress.best)
        self.assertEqual((), bag_pressure.bag_hold_stuck(progress))

    def test_a_window_with_no_gain_releases_the_hold(self):
        progress = _minutes(_held(None, MEASURED, 0.0), MEASURED, 0.0, 45)
        self.assertEqual(("Grog",), bag_pressure.bag_hold_stuck(progress))

    def test_short_of_the_window_it_is_still_held(self):
        progress = _minutes(_held(None, MEASURED, 0.0), MEASURED, 0.0, 44)
        self.assertEqual((), bag_pressure.bag_hold_stuck(progress))

    def test_a_gain_restarts_the_clock(self):
        progress = _minutes(_held(None, MEASURED, 0.0), MEASURED, 0.0, 40)
        gained = dict(MEASURED, Grog=2)
        progress = _minutes(progress, gained, 2400.0, 30)
        self.assertEqual((), bag_pressure.bag_hold_stuck(progress))
        self.assertEqual(2460.0, progress.since)

    def test_a_slot_won_and_lost_again_is_not_a_gain_twice(self):
        progress = _held(None, MEASURED, 0.0)
        progress = _held(progress, dict(MEASURED, Grog=1), 60.0)
        for minute in range(2, 48):
            free = dict(MEASURED, Grog=minute % 2)
            progress = _held(progress, free, 60.0 * minute)
        self.assertEqual(("Grog",), bag_pressure.bag_hold_stuck(progress))

    def test_a_released_hold_stays_released_until_nobody_is_at_the_floor(self):
        progress = _minutes(_held(None, MEASURED, 0.0), MEASURED, 0.0, 45)
        # Grog eats a conjured loaf: one slot back, still at the floor.
        progress = _held(progress, dict(MEASURED, Grog=1), 2760.0)
        self.assertEqual(("Grog",), bag_pressure.bag_hold_stuck(progress))
        self.assertIsNone(_held(progress, dict(MEASURED, Grog=8), 2820.0))

    def test_a_gap_in_the_readings_starts_a_new_hold(self):
        progress = _minutes(_held(None, MEASURED, 0.0), MEASURED, 0.0, 45)
        later = _held(progress, MEASURED, 2700.0 + 3600.0)
        self.assertEqual((), bag_pressure.bag_hold_stuck(later))

    def test_an_unknown_reading_holds_nobody(self):
        self.assertIsNone(_held(None, {"Grog": None, "Ugga": -1}, 0.0))

    def test_the_window_is_the_resume_ceiling(self):
        self.assertEqual(
            bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS,
            bag_pressure.BAG_HOLD_STUCK_SECONDS,
        )


def row(**kw):
    """One joined character_inventory row, as the bridge's SQL names it."""
    base = dict(
        holder="Grog",
        level=40,
        item_guid=1,
        count=1,
        name="Linen Cloth",
        quality=1,
        sell_price=10,
        required_level=0,
        bonding=0,
        item_class=7,
        container_slots=0,
        bag=0,
        slot=23,
    )
    base.update(kw)
    return base


# Grog works tailoring, so his cloth is his own stock and the keeper rule
# leaves it in the bags.
TAILOR = {"Grog": {"tailoring": 150}}


def _grog_full(extra=()):
    """Grog's 16-slot backpack, full: 12 small stacks of his own cloth (36,
    under the stock cap, so the keeper rule stores none), a loaf of conjured
    bread, a quest item, a worn-out sword and his hearthstone."""
    rows = [
        row(item_guid=100 + i, name="Linen Cloth", count=3, slot=23 + i)
        for i in range(12)
    ]
    rows += [
        row(item_guid=200, name="Conjured Bread", item_class=0, sell_price=0, slot=35),
        row(item_guid=201, name="Tome of Valor", item_class=12, sell_price=0, slot=36),
        row(item_guid=202, name="Rusty Sword", item_class=2, bonding=1, slot=37),
        row(
            item_guid=203,
            name="Hearthstone",
            item_class=15,
            sell_price=0,
            bonding=1,
            slot=38,
        ),
    ]
    return rows + list(extra)


def _plan(rows, room_floor):
    storage = bank.storage_from(TAILOR)
    return bank.plan(
        bank.members_from_rows(rows, ["Grog"]),
        bank.family_from_skills(TAILOR),
        storage=storage,
        room_floor=room_floor,
    )


class TheBankMakesRoom(unittest.TestCase):
    def test_grog_full_of_his_own_stock_is_measured_at_zero(self):
        members = bank.members_from_rows(_grog_full(), ["Grog"])
        self.assertEqual(0, members[0].bag_free)

    def test_without_a_campaign_his_own_stock_stays_in_the_bags(self):
        self.assertEqual((), _plan(_grog_full(), 0).moves)

    def test_a_waiting_campaign_banks_his_stock_up_to_the_floor(self):
        moves = _plan(_grog_full(), bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS).moves
        self.assertEqual(8, len(moves))
        self.assertTrue(all(m.verb == bank.DEPOSIT for m in moves))
        self.assertTrue(all(m.to == bank.PERSONAL for m in moves))
        # One slot each, in the bank's stable stack order.
        self.assertEqual([100 + i for i in range(8)], [m.guid for m in moves])
        self.assertIn("free slot", moves[0].why)

    def test_food_quest_items_gear_and_the_hearthstone_never_go_down(self):
        moves = _plan(_grog_full(), 16).moves
        self.assertFalse({200, 201, 202, 203} & {m.guid for m in moves})

    def test_a_member_at_the_floor_banks_nothing_for_room(self):
        rows = _grog_full()[4:]  # four stacks fewer: 4 free
        moves = _plan(rows, 4).moves
        self.assertEqual((), moves)

    def test_nothing_comes_back_out_below_the_floor(self):
        # 8 free in the bags, the room the hold asked for, and three cloth
        # banked for room on an earlier visit.
        water = [
            row(
                item_guid=400 + i,
                name="Conjured Water",
                item_class=0,
                sell_price=0,
                slot=23 + i,
            )
            for i in range(4)
        ]
        rows = (
            water
            + _grog_full()[12:]
            + [row(item_guid=300, name="Linen Cloth", count=3, slot=39)]
        )
        self.assertEqual(8, bank.members_from_rows(rows, ["Grog"])[0].bag_free)
        self.assertEqual((), _plan(rows, 8).moves)
        # With no campaign waiting the same stock comes back as before.
        self.assertEqual(
            [(bank.WITHDRAW, 300)], [(m.verb, m.guid) for m in _plan(rows, 0).moves]
        )


class TheBridgeAsksForRoom(unittest.TestCase):
    def test_the_bank_plan_keeps_run_room_only_while_a_campaign_waits(self):
        body = ast.get_source_segment(BRIDGE, _functions("_plan_bank")[0])
        self.assertIn(
            "bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS\n"
            "                  if _campaign_waiting(names) else 0",
            body,
        )
        self.assertIn("room_floor=room_floor", body)


class TheErrandsBankStepIsBothBanks(unittest.TestCase):
    def test_the_bank_step_runs_the_bank_and_the_guild_vault(self):
        calls = []

        class Family:
            async def _town_errand_aim(self, leader, aim, cohort):
                calls.append(("aim", aim))

            async def _bank_passing_once(self, cohort):
                calls.append("bank")

            async def _guild_bank_passing_once(self, cohort):
                calls.append("guild bank")

        ns = {
            "asyncio": asyncio,
            "townerrand": townerrand,
            "_TOWN_ERRAND_MARKS": {},
            "TOWN_ERRAND_SETTLE_SECONDS": 60.0,
            "_fetch_town": lambda leader: types.SimpleNamespace(banker=True),
        }
        exec(  # noqa: S102 - bridge.py's own source
            compile(
                ast.Module(body=_functions("_town_errand_step"), type_ignores=[]),
                "bridge.py",
                "exec",
            ),
            ns,
        )
        state = townerrand.State(
            phase=townerrand.STEPS,
            step=townerrand.STEP_ORDER.index(townerrand.BANK),
        )
        asyncio.run(
            ns["_town_errand_step"](
                Family(), state, NAMES, "Grug", {"Grug": {}}, None, 100.0
            )
        )
        self.assertEqual([("aim", "banker"), "bank", "guild bank"], calls)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


class World:
    def __init__(self, free, job):
        self.free = dict(free)
        self.jobs = {n: job for n in NAMES}
        self.sources = {n: TOWN_FIRST for n in NAMES}
        self.inserted = []

    def insert_job(self, name, mode, source):
        self.inserted.append((name, mode, source))
        self.jobs[name] = mode
        self.sources[name] = source


def _drive(world, clock, log):
    class Cursor:
        rowcount = 1

        def execute(self, sql, args):
            pass

    class Conn:
        def cursor(self):
            return contextlib.nullcontext(Cursor())

    ns = {
        "jobs": jobs,
        "bag_pressure": bag_pressure,
        "time": clock,
        "log": log,
        "TOWN_FIRST_SOURCE": TOWN_FIRST,
        "TOWN_ERRAND_SOURCE": TOWN_ERRAND,
        "_TOWN_FIRST_SINCE": {},
        "_BAG_HOLD": {},
        "_fetch_enabled_names": lambda: list(NAMES),
        "_fetch_free_slots": lambda names: {n: world.free[n] for n in names},
        "_jobs_of": lambda names: {n: world.jobs[n] for n in names},
        "_last_job_source": lambda name: world.sources[name],
        # The queue has waited past every ceiling: three hours.
        "_queue_stall_floor": lambda names: 3 * 3600.0,
        "_insert_job": world.insert_job,
        "_campaign_waiting": lambda names: True,
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "pymysql": None,
    }
    exec(  # noqa: S102 - bridge.py's own source
        compile(
            ast.Module(
                body=_functions(
                    "_withheld",
                    "_hand_to_town",
                    "_keep_in_town",
                    "_town_first",
                    "_insert_family_jobs",
                    "_bag_hold_stuck",
                    "_quest_while_stuck",
                    "_bag_errand_needed",
                    "_drive_dungeon",
                ),
                type_ignores=[],
            ),
            "bridge.py",
            "exec",
        ),
        ns,
    )

    def drive():
        withheld = []
        written = ns["_drive_dungeon"](
            "zulfarrak", 50, list(NAMES), "overseer:queue", withheld=withheld
        )
        return written, withheld

    return drive, ns


class TheHoldEnds(unittest.TestCase):
    def setUp(self):
        self.world = World(MEASURED, jobs.TOWN_RUN)
        self.clock = Clock()
        self.log = Log()
        self.drive, self.ns = _drive(self.world, self.clock, self.log)

    def _minutes(self, minutes):
        out = None
        for _ in range(minutes):
            self.clock.now += 60.0
            out = self.drive()
        return out

    def test_inside_the_window_the_family_waits_in_town(self):
        written, withheld = self._minutes(30)
        self.assertEqual((0, 0), written)
        self.assertIn("near full", withheld[0])
        self.assertEqual({jobs.TOWN_RUN}, set(self.world.jobs.values()))

    def test_no_room_made_in_the_window_sends_the_family_questing(self):
        written, withheld = self._minutes(46)
        self.assertEqual((0, 0), written)
        self.assertIn("Grog at the bag floor", withheld[0])
        self.assertEqual({jobs.DEFAULT}, set(self.world.jobs.values()))
        self.assertTrue(
            any("no town pass has made room" in line for line in self.log.lines)
        )

    def test_the_family_is_not_walked_back_to_town_while_released(self):
        self._minutes(46)
        self.world.free["Grog"] = 1
        self._minutes(30)
        self.assertEqual({jobs.DEFAULT}, set(self.world.jobs.values()))

    def test_room_for_a_run_sends_the_campaign_in(self):
        self._minutes(46)
        self.world.free.update(Grog=9, Ugga=9)
        written, _withheld = self._minutes(1)
        self.assertEqual(len(NAMES), written[0])
        self.assertEqual({"dungeon:zulfarrak"}, set(self.world.jobs.values()))

    def test_an_operators_own_town_run_stands(self):
        self.world.sources["Og"] = "operator"
        self._minutes(46)
        self.assertEqual(jobs.TOWN_RUN, self.world.jobs["Og"])
        self.assertEqual(jobs.DEFAULT, self.world.jobs["Grog"])

    def test_a_town_run_the_errand_left_standing_goes_questing_too(self):
        # The errand ends and hands the family back with its own town run
        # still standing; the hold's exit moves that row like its own.
        self.world.sources.update({n: TOWN_ERRAND for n in NAMES})
        self._minutes(46)
        self.assertEqual({jobs.DEFAULT}, set(self.world.jobs.values()))

    def test_the_bag_room_errand_stops_once_the_hold_is_released(self):
        needed = self.ns["_bag_errand_needed"]
        self.assertTrue(needed(NAMES, MEASURED, True))
        self._minutes(46)
        self.assertFalse(needed(NAMES, MEASURED, True))
        self.assertFalse(needed(NAMES, MEASURED, False))


if __name__ == "__main__":
    unittest.main()
