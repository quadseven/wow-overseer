"""A town pass for a member at the bag floor frees a slot or says exactly why not.

Measured 2026-10-14: all five members of a family were held 2.4 hours on
"Grog at the bag floor and no town pass has made room, so the family quests
until there is room", and one member's last step read "the town trip ended
walking to the vendor on a town errand". A Bonkers family was held the same
way for five hours on 2026-10-11.

THE CAUSE. Two clocks raced. The hold at the floor releases after
bag_pressure.BAG_HOLD_STUCK_SECONDS with no gain, and the town errand ends
once the campaign has waited townerrand.HOLD_CEILING_SECONDS unless bag
pressure still needs the counter, a reading `_bag_errand_needed` turns off
the moment the hold releases. The errand's counters that make room came after
the walk, the gather, the fund and a mail step of up to fifteen minutes, so a
bag-room errand reached its vendor about forty minutes in, and the release at
forty-five ended it on the walk there. With the hold released no bag-room
errand ran again, and nothing said what the floor member carried.

Pinned here:

  * A bag-room errand sells and banks first, and the hold is not released
    under a town errand still running, so the errand reaches its vendor and
    bank before the hold is judged.
  * Once the pass ends with no slot gained the hold is released, and the
    reason names what the member at the floor carries and how the vendor step
    ended.
  * A hold that stands 30 minutes with no gain logs that reason, once.
"""

import ast
import contextlib
import pathlib
import unittest

import bag_pressure
import jobs
import townerrand

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

NAMES = ["Bork", "Grog", "Grug", "Og", "Ugga"]
KEY = tuple(sorted(NAMES))
# Grog at the floor; the rest with room.
MEASURED = {"Bork": 15, "Grog": 0, "Grug": 19, "Og": 10, "Ugga": 6}
HUB = {"map_id": 1, "x": 0.0, "y": 0.0}
TOWN_FIRST = "overseer:town-first"
TOWN_ERRAND = "overseer:town-errand"
# The walk to the hub and the gather take their whole windows.
ARRIVES = townerrand.GO_SECONDS - 60.0
GATHERS = ARRIVES + townerrand.GATHER_SECONDS


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


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def time(self):
        return self.now


class Log:
    def __init__(self):
        self.lines = []

    def info(self, msg, *a, **k):
        self.lines.append(msg % a if a else msg)

    warning = exception = info


class World:
    def __init__(self, free):
        self.free = dict(free)
        self.jobs = {n: jobs.TOWN_RUN for n in NAMES}
        self.sources = {n: TOWN_FIRST for n in NAMES}

    def insert_job(self, name, mode, source):
        self.jobs[name] = mode
        self.sources[name] = source


# The bridge functions the hold and the errand share. On main the last four
# do not exist; the reproduction below runs without them.
CORE = (
    "_withheld",
    "_hand_to_town",
    "_keep_in_town",
    "_town_first",
    "_insert_family_jobs",
    "_bag_hold_stuck",
    "_quest_while_stuck",
    "_bag_errand_needed",
    "_drive_dungeon",
    "_town_errand_active",
)
REASONS = ("_note_bag_floor", "_note_town_pass", "_bag_hold_why", "_say_bag_hold")


def _bridge(world, clock, log, reasons=True):
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
        "townerrand": townerrand,
        "time": clock,
        "log": log,
        "OWNER_KEEPS": (),
        "TOWN_FIRST_SOURCE": TOWN_FIRST,
        "TOWN_ERRAND_SOURCE": TOWN_ERRAND,
        "_TOWN_FIRST_SINCE": {},
        "_BAG_HOLD": {},
        "_BAG_HOLD_STUCK": {},
        "_BAG_FLOOR_WHY": {},
        "_TOWN_PASS_NOTE": {},
        "_BAG_HOLD_SAID": {},
        "_TOWN_ERRANDS": {},
        "_fetch_enabled_names": lambda: list(NAMES),
        "_fetch_free_slots": lambda names: {n: world.free[n] for n in names},
        "_jobs_of": lambda names: {n: world.jobs[n] for n in names},
        "_last_job_source": lambda name: world.sources[name],
        # The queue has waited past every ceiling.
        "_queue_stall_floor": lambda names: 3 * 3600.0,
        "_insert_job": world.insert_job,
        "_campaign_waiting": lambda names: True,
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "_memo_upsert": lambda *args: None,
        "_memo_delete": lambda *args: None,
        "pymysql": None,
    }
    names = CORE + (REASONS if reasons else ())
    exec(  # noqa: S102 - bridge.py's own source
        compile(
            ast.Module(body=_functions(*names), type_ignores=[]),
            "bridge.py",
            "exec",
        ),
        ns,
    )
    return ns


def kept(**kw):
    """One of Grog's carried rows as `_fetch_vendor_items` names it: a
    crafting good a vendor is never offered."""
    base = dict(
        holder="Grog",
        entry=2589,
        item_guid=100,
        count=3,
        name="Linen Cloth",
        quality=1,
        sell_price=10,
        quest_item=False,
        reagent=False,
        profession_needed=True,
    )
    base.update(kw)
    return base


GROG_ROWS = [
    kept(item_guid=100 + i) for i in range(12)
] + [
    kept(item_guid=200, name="Tome of Valor", quest_item=True, profession_needed=False),
    kept(item_guid=201, name="Fire Oil", reagent=True, profession_needed=False),
]


class Errand:
    """A bag-room town errand driven a minute at a time beside the hold, the
    way `_town_errand_once` and the queue's `_drive_dungeon` drive them.

    The family walks for the walk's whole window and gathers for the gather's;
    no step reports itself done, so every step runs its whole window. Nothing
    sells for Grog: he carries nothing a vendor will buy.
    """

    def __init__(self, reasons=True):
        self.world = World(MEASURED)
        self.clock = Clock()
        self.log = Log()
        self.ns = _bridge(self.world, self.clock, self.log, reasons=reasons)
        self.reasons = reasons
        self.state = townerrand.State()
        self.lines = []
        self.steps = []
        self.withheld = []
        self.start = self.clock.now

    def minute(self):
        self.clock.now += 60.0
        now = self.clock.now
        free = self.world.free
        withheld = []
        self.ns["_drive_dungeon"](
            "zulfarrak", 50, list(NAMES), "overseer:queue", withheld=withheld
        )
        self.withheld = withheld
        needed = self.ns["_bag_errand_needed"](NAMES, free, True)
        state = self.state
        if not state.active and not state.ended:
            why = townerrand.should_start(
                state,
                now=now,
                in_run=False,
                mail_gear={},
                facts={},
                stalled=3 * 3600.0,
                bag_pressure_needed=needed,
            )
            if why:
                state = townerrand.start(now, HUB, why)
                self.start = now
        if state.current_step and state.current_step not in self.steps:
            self.steps.append(state.current_step)
        new, line = townerrand.advance(
            state,
            now,
            leader_at_hub=now - self.start >= ARRIVES,
            gathered=now - self.start >= GATHERS,
            step_done=False,
            stalled=3 * 3600.0,
            bag_pressure_needed=needed,
        )
        if line:
            self.lines.append(line)
        if self.reasons and (new.phase != state.phase or new.step != state.step):
            self.ns["_note_town_pass"](KEY, state, new, line, {})
        self.state = new
        self.ns["_TOWN_ERRANDS"][KEY] = new
        return new

    def run(self, minutes):
        for _ in range(minutes):
            self.minute()

    def until_done(self, limit=120):
        for _ in range(limit):
            if self.minute().phase == townerrand.DONE:
                return
        raise AssertionError("the errand never ended: %s" % self.lines)


class TheTownPassReachesTheVendor(unittest.TestCase):
    """The reproduction: on main the hold's release ends the errand on its
    walk to the vendor, and it never banks."""

    def setUp(self):
        # Only functions main already has, so this fails there on behaviour.
        self.errand = Errand(reasons=False)
        self.errand.until_done()

    def test_the_errand_is_not_ended_by_the_holds_own_release(self):
        ended = self.errand.lines[-1]
        self.assertNotIn("the campaign has waited", ended)

    def test_the_vendor_step_runs_its_whole_window(self):
        self.assertTrue(
            any(line.startswith("vendor ") for line in self.errand.lines),
            self.errand.lines,
        )

    def test_the_bank_step_runs(self):
        self.assertIn(townerrand.BANK, self.errand.steps, self.errand.lines)


class TheHoldIsJudgedAfterThePass(unittest.TestCase):
    def setUp(self):
        self.errand = Errand()
        self.errand.ns["_note_bag_floor"](
            NAMES, MEASURED, GROG_ROWS, {n: 0 for n in NAMES}
        )

    def test_the_hold_stands_while_the_errand_runs(self):
        self.errand.run(int(bag_pressure.BAG_HOLD_STUCK_SECONDS // 60) + 5)
        self.assertTrue(self.errand.state.active)
        self.assertEqual({jobs.TOWN_RUN}, set(self.errand.world.jobs.values()))

    def test_the_hold_is_released_on_the_first_reading_after_the_pass(self):
        self.errand.until_done()
        self.errand.minute()
        self.assertEqual({jobs.DEFAULT}, set(self.errand.world.jobs.values()))
        self.assertIn("Grog at the bag floor", self.errand.withheld[0])

    def test_the_released_hold_names_the_items_and_the_vendor_step(self):
        self.errand.until_done()
        self.errand.minute()
        why = self.errand.withheld[0]
        self.assertIn("Grog carries nothing a vendor will buy", why)
        self.assertIn("Linen Cloth (profession stock)", why)
        self.assertIn("1 a quest item", why)
        self.assertIn(
            "vendor step ended before the leader stood at a vendor", why
        )

    def test_the_release_is_logged_with_the_reason(self):
        self.errand.until_done()
        self.errand.minute()
        released = [
            line for line in self.errand.log.lines
            if "no town pass has made room" in line
        ]
        self.assertTrue(released)
        self.assertIn("Grog carries nothing a vendor will buy", released[-1])

    def test_a_slot_freed_by_the_pass_holds_the_family_for_its_run(self):
        # The vendor step sells for Grog and he gains a slot: the hold's clock
        # restarts, so the family is not sent questing when the pass ends.
        self.errand.run(30)
        self.errand.world.free["Grog"] = 2
        self.errand.until_done()
        self.errand.minute()
        self.assertEqual({jobs.TOWN_RUN}, set(self.errand.world.jobs.values()))


class AHoldSaysWhyWithinThirtyMinutes(unittest.TestCase):
    def setUp(self):
        self.errand = Errand()
        self.errand.ns["_note_bag_floor"](
            NAMES, MEASURED, GROG_ROWS, {n: 0 for n in NAMES}
        )

    def _said(self):
        return [line for line in self.errand.log.lines if line.startswith("bag hold:")]

    def test_nothing_is_said_inside_thirty_minutes(self):
        self.errand.run(int(bag_pressure.BAG_HOLD_REASON_SECONDS // 60) - 2)
        self.assertEqual([], self._said())
        self.assertNotIn("Grog carries", self.errand.withheld[0])

    def test_at_thirty_minutes_the_reason_is_logged_once(self):
        self.errand.run(int(bag_pressure.BAG_HOLD_REASON_SECONDS // 60) + 10)
        said = self._said()
        self.assertEqual(1, len(said), said)
        self.assertIn("Grog", said[0])
        self.assertIn("Grog carries nothing a vendor will buy", said[0])
        self.assertIn("the town errand is under way", said[0])

    def test_at_thirty_minutes_the_withheld_reason_carries_it(self):
        self.errand.run(int(bag_pressure.BAG_HOLD_REASON_SECONDS // 60) + 1)
        self.assertIn("near full", self.errand.withheld[0])
        self.assertIn("Grog carries nothing a vendor will buy", self.errand.withheld[0])

    def test_the_thirty_minutes_is_inside_the_release_window(self):
        self.assertLessEqual(30 * 60, bag_pressure.BAG_HOLD_REASON_SECONDS)
        self.assertLess(
            bag_pressure.BAG_HOLD_REASON_SECONDS, bag_pressure.BAG_HOLD_STUCK_SECONDS
        )


class TheVendorStepSaysHowItEnded(unittest.TestCase):
    def setUp(self):
        self.ns = _bridge(World(MEASURED), Clock(), Log())
        self.note = self.ns["_TOWN_PASS_NOTE"]
        order = townerrand.ROOM_STEP_ORDER
        self.at_vendor = townerrand.State(
            phase=townerrand.STEPS,
            step=order.index(townerrand.VENDOR),
            why=townerrand.BAG_PRESSURE_WHY,
        )
        self.next = townerrand.State(
            phase=townerrand.STEPS,
            step=order.index(townerrand.VENDOR) + 1,
            why=townerrand.BAG_PRESSURE_WHY,
        )

    def test_a_vendor_step_that_stood_at_a_vendor(self):
        self.ns["_note_town_pass"](
            KEY, self.at_vendor, self.next, "vendor done; next: bank",
            {townerrand.VENDOR: 1.0},
        )
        self.assertEqual("the town errand's vendor step ran the sell pass at a vendor", self.note[KEY])

    def test_a_vendor_step_that_never_stood_at_a_vendor(self):
        self.ns["_note_town_pass"](
            KEY, self.at_vendor, self.next, "vendor ran out of time; next: bank", {}
        )
        self.assertIn("before the leader stood at a vendor", self.note[KEY])
        self.assertIn("vendor ran out of time", self.note[KEY])

    def test_an_errand_ended_on_the_walk(self):
        walking = townerrand.State(phase=townerrand.GO, why=townerrand.BAG_PRESSURE_WHY)
        done, line = townerrand.end(walking, 1.0, "the walk to the capital did not land")
        self.ns["_note_town_pass"](KEY, walking, done, line, {})
        self.assertIn("ended before its vendor step", self.note[KEY])
        self.assertIn("did not land", self.note[KEY])

    def test_a_later_step_changes_nothing(self):
        self.ns["_note_town_pass"](
            KEY, self.next, self.next, "bank done; next: tidy", {}
        )
        self.assertNotIn(KEY, self.note)


class ABagRoomErrandMakesRoomFirst(unittest.TestCase):
    def test_selling_and_banking_come_first(self):
        order = townerrand.steps_for(townerrand.BAG_PRESSURE_WHY)
        self.assertEqual((townerrand.VENDOR, townerrand.BANK), order[:2])

    def test_the_mail_comes_last(self):
        order = townerrand.steps_for(townerrand.BAG_PRESSURE_WHY)
        self.assertEqual(townerrand.MAIL, order[-1])

    def test_every_step_still_runs(self):
        self.assertEqual(
            sorted(townerrand.STEP_ORDER), sorted(townerrand.ROOM_STEP_ORDER)
        )

    def test_any_other_errand_keeps_its_order(self):
        self.assertEqual(townerrand.STEP_ORDER, townerrand.steps_for("gear"))
        self.assertEqual(townerrand.STEP_ORDER, townerrand.State().steps)

    def test_the_room_vendor_step_reaches_the_vendor_inside_thirty_minutes(self):
        # The walk and the gather at their whole windows, then the vendor.
        reached = townerrand.GO_SECONDS + townerrand.GATHER_SECONDS
        self.assertLessEqual(reached, bag_pressure.BAG_HOLD_REASON_SECONDS)


def _read(held, start, minutes, running):
    """Read MEASURED once a minute for `minutes` minutes after `start`."""
    for minute in range(1, minutes + 1):
        held = bag_pressure.bag_hold_progress(
            held, MEASURED, start + 60.0 * minute, running=running
        )
    return held


class TheHoldWaitsForARunningPass(unittest.TestCase):
    MINUTES = int(bag_pressure.BAG_HOLD_STUCK_SECONDS // 60)

    def test_a_running_pass_is_not_released_past_the_window(self):
        held = bag_pressure.bag_hold_progress(None, MEASURED, 0.0)
        held = _read(held, 0.0, self.MINUTES + 20, running=True)
        self.assertFalse(held.released)

    def test_the_first_reading_after_the_pass_releases_it(self):
        held = bag_pressure.bag_hold_progress(None, MEASURED, 0.0)
        held = _read(held, 0.0, self.MINUTES + 5, running=True)
        held = _read(held, 60.0 * (self.MINUTES + 5), 1, running=False)
        self.assertTrue(held.released)

    def test_a_released_hold_stays_released_under_a_pass(self):
        held = bag_pressure.bag_hold_progress(None, MEASURED, 0.0)
        held = _read(held, 0.0, self.MINUTES, running=False)
        self.assertTrue(held.released)
        held = _read(held, 60.0 * self.MINUTES, 5, running=True)
        self.assertTrue(held.released)


ROWS = [
    kept(item_guid=1, profession_needed=False),  # sells
    kept(item_guid=2),
    kept(item_guid=3, quest_item=True, profession_needed=False),
    kept(item_guid=4, reagent=True, profession_needed=False),
    kept(item_guid=5, quality=2, profession_needed=False),
    kept(item_guid=6, sell_price=0, profession_needed=False),
    kept(item_guid=7, entry=bag_pressure.GUILD_TABARD_ENTRY, profession_needed=False),
    kept(item_guid=8, name="Dervish Buckler", profession_needed=False),
    kept(item_guid=0, profession_needed=False),
    kept(item_guid=9, count=0, profession_needed=False),
    {k: v for k, v in kept(item_guid=10, profession_needed=False).items()
     if k != "reagent"},
    {k: v for k, v in kept(item_guid=11).items() if k != "sell_price"},
    kept(item_guid=12, entry="x", profession_needed=False),
]
KEEPS = ("dervish buckler",)


class TheReasonIsTheSaleDecision(unittest.TestCase):
    def test_a_row_sells_exactly_when_it_has_no_refusal(self):
        sold = {c.item_guid for c in bag_pressure.vendor_candidates(ROWS, KEEPS)}
        unrefused = {
            int(row["item_guid"])
            for row in ROWS
            if not bag_pressure.vendor_refusal(row, KEEPS)
        }
        self.assertEqual({1}, sold)
        self.assertEqual(sold, unrefused)

    def test_each_refusal_names_its_reason(self):
        why = {
            int(row["item_guid"]): bag_pressure.vendor_refusal(row, KEEPS)
            for row in ROWS
        }
        self.assertEqual(bag_pressure.KEPT_PROFESSION, why[2])
        self.assertEqual(bag_pressure.KEPT_QUEST, why[3])
        self.assertEqual(bag_pressure.KEPT_REAGENT, why[4])
        self.assertEqual(bag_pressure.KEPT_QUALITY, why[5])
        self.assertEqual(bag_pressure.KEPT_NO_PRICE, why[6])
        self.assertEqual(bag_pressure.KEPT_TABARD, why[7])
        self.assertEqual(bag_pressure.KEPT_BY_OWNER, why[8])
        for guid in (0, 9, 10, 11, 12):
            self.assertEqual(bag_pressure.KEPT_UNREAD, why[guid], guid)


class TheFloorReason(unittest.TestCase):
    def test_a_member_with_sales_is_told_how_many(self):
        self.assertEqual(
            "Grog carries 4 stack(s) a vendor will buy",
            bag_pressure.floor_reason("Grog", 4, GROG_ROWS),
        )

    def test_a_member_with_none_is_told_what_it_carries(self):
        why = bag_pressure.floor_reason("Grog", 0, GROG_ROWS)
        self.assertEqual(
            "Grog carries nothing a vendor will buy: 14 stack(s) kept "
            "(12 profession stock, 1 a quest item, 1 a reagent), e.g. "
            "Linen Cloth (profession stock), Linen Cloth (profession stock), "
            "Linen Cloth (profession stock)",
            why,
        )

    def test_another_members_rows_are_not_counted(self):
        rows = GROG_ROWS + [kept(holder="Og", item_guid=900, name="Og's Axe")]
        self.assertNotIn("Og's Axe", bag_pressure.floor_reason("Grog", 0, rows))

    def test_a_member_with_no_rows_read(self):
        self.assertEqual(
            "Grog carries nothing a vendor will buy, and no carried item was read",
            bag_pressure.floor_reason("Grog", 0, []),
        )


class TheVendorPassRecordsTheFloor(unittest.TestCase):
    def setUp(self):
        self.ns = _bridge(World(MEASURED), Clock(), Log())

    def test_only_members_at_the_floor_get_a_reason(self):
        self.ns["_note_bag_floor"](NAMES, MEASURED, GROG_ROWS, {n: 0 for n in NAMES})
        self.assertEqual({"Grog"}, set(self.ns["_BAG_FLOOR_WHY"]))

    def test_a_member_who_gets_room_is_forgotten(self):
        self.ns["_note_bag_floor"](NAMES, MEASURED, GROG_ROWS, {})
        self.ns["_note_bag_floor"](NAMES, dict(MEASURED, Grog=8), GROG_ROWS, {})
        self.assertEqual({}, self.ns["_BAG_FLOOR_WHY"])

    def test_the_vendor_pass_records_it(self):
        body = ast.get_source_segment(BRIDGE, _functions("_vendor_once")[0])
        record = body.index('globals().get("_note_bag_floor")')
        self.assertLess(body.index("sellable_counts[sale.holder]"), record)
        # Above every early return of the pass.
        self.assertLess(record, body.index("if mode == bag_pressure.VENDOR_MODE_NONE"))


if __name__ == "__main__":
    unittest.main()
