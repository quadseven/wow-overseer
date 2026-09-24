"""Town first, then the dungeon (#265).

Measured on wow-dev 2026-09-23. Grug's family had Zul'Farrak active with
free slots Grug 9, Bork 3, Og 11, Grog 6, Ugga 2. The campaign was withheld
at a floor of three free slots and let go again at four, and the withhold
wrote nothing: a campaign already on the family kept its job while the town
passes were meant to own the head. One sale is enough to open a run that the
first loot then evacuates.

Pinned here, running bridge._drive_dungeon for real against fakes:

  * An armed campaign at the floor is handed to town: its job is taken off
    every member with the town-first source.
  * A campaign that is not armed waits until every member has
    CAMPAIGN_RESUME_FREE_SLOTS free, and says who is short.
  * The band has a ceiling, so a member nobody can lift does not hold the
    campaign in town for ever.
  * An armed campaign between the floor and the resume floor is not held.
"""

import ast
import contextlib
import pathlib
import unittest

import bag_pressure
import jobs

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)

NAMES = ["Grug", "Bork", "Og", "Grog", "Ugga"]
ZF = "dungeon:zulfarrak"
# Free slots at 23:30 on the day.
MEASURED = {"Grug": 9, "Bork": 3, "Og": 11, "Grog": 6, "Ugga": 2}


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


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
    """The roster's jobs and bags, and every write the drive makes."""

    def __init__(self, free, job, waiting=True):
        self.free = dict(free)
        self.jobs = {n: job for n in NAMES}
        self.inserted = []
        # Whether a queued campaign waits on the family (_campaign_waiting).
        self.waiting = waiting

    def insert_job(self, name, mode, source):
        self.inserted.append((name, mode, source))
        self.jobs[name] = mode


def _drive(world, clock, log, since):
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
        "TOWN_FIRST_SOURCE": "overseer:town-first",
        "_TOWN_FIRST_SINCE": since,
        "_fetch_enabled_names": lambda: list(NAMES),
        "_fetch_free_slots": lambda names: {n: world.free[n] for n in names},
        "_jobs_of": lambda names: {n: world.jobs[n] for n in names},
        "_insert_job": world.insert_job,
        "_campaign_waiting": lambda names: world.waiting,
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "pymysql": None,
    }
    module = ast.Module(
        body=[
            _function(n)
            for n in (
                "_withheld",
                "_hand_to_town",
                "_keep_in_town",
                "_town_first",
                "_insert_family_jobs",
                "_drive_dungeon",
            )
        ],
        type_ignores=[],
    )
    exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source

    def drive(withheld):
        return ns["_drive_dungeon"](
            "zulfarrak", 50, list(NAMES), "overseer:queue", withheld=withheld
        )

    return drive


class TheResumeFloor(unittest.TestCase):
    def test_who_is_short(self):
        self.assertEqual(
            ("Bork", "Grog", "Ugga"), bag_pressure.campaign_resume_short(MEASURED)
        )

    def test_nobody_short_when_everyone_has_room(self):
        self.assertEqual((), bag_pressure.campaign_resume_short({"Grug": 8, "Og": 30}))

    def test_an_unknown_reading_holds_nothing(self):
        self.assertEqual(
            (), bag_pressure.campaign_resume_short({"Grug": None, "Og": -1})
        )

    def test_the_ceiling_lets_it_go(self):
        self.assertEqual(
            (),
            bag_pressure.campaign_resume_short(
                MEASURED, held_seconds=bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS
            ),
        )

    def test_the_band_is_above_the_floor(self):
        self.assertGreater(
            bag_pressure.CAMPAIGN_RESUME_FREE_SLOTS,
            bag_pressure.TOWN_RUN_FREE_SLOTS + 1,
        )


class TownFirstThenTheDungeon(unittest.TestCase):
    def setUp(self):
        self.clock, self.log, self.since = Clock(), Log(), {}

    def drive(self, world):
        withheld = []
        result = _drive(world, self.clock, self.log, self.since)(withheld)
        return result, withheld

    def test_an_armed_campaign_at_the_floor_is_handed_to_town(self):
        world = World(MEASURED, ZF)
        result, withheld = self.drive(world)
        self.assertEqual((0, 0), result)
        self.assertIn("bags are near full", withheld[0])
        self.assertEqual(
            [(n, jobs.TOWN_RUN, "overseer:town-first") for n in NAMES], world.inserted
        )
        self.assertTrue(
            [
                ln
                for ln in self.log.lines
                if ln.startswith("town first: dungeon:zulfarrak")
            ],
            self.log.lines,
        )

    def test_a_campaign_already_in_town_is_not_handed_twice(self):
        world = World(MEASURED, jobs.TOWN_RUN)
        self.drive(world)
        self.assertEqual([], world.inserted)

    def test_one_sale_past_the_floor_does_not_send_it_back_in(self):
        world = World(MEASURED, ZF)
        self.drive(world)
        world.inserted.clear()
        # Town upkeep lifted Bork and Ugga past the floor, not to the band.
        world.free.update({"Bork": 4, "Ugga": 5})
        result, withheld = self.drive(world)
        self.assertEqual((0, 0), result)
        self.assertEqual([], world.inserted, "a run was sent in at four free slots")
        self.assertIn("town first: Bork, Grog, Ugga below 8 free slots", withheld[0])

    def test_room_for_a_run_sends_it_back_in(self):
        world = World(MEASURED, ZF)
        self.drive(world)
        world.inserted.clear()
        world.free = {n: 12 for n in NAMES}
        result, withheld = self.drive(world)
        self.assertEqual((5, 5), result)
        self.assertEqual([], withheld)
        self.assertEqual({ZF}, {mode for _, mode, _ in world.inserted})
        self.assertEqual({}, self.since)

    def test_the_ceiling_sends_it_back_in_at_the_floor(self):
        world = World(MEASURED, ZF)
        self.drive(world)
        world.inserted.clear()
        world.free.update({"Bork": 5, "Ugga": 5})
        self.assertEqual((0, 0), self.drive(world)[0])
        self.clock.now += bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS
        result, _ = self.drive(world)
        self.assertEqual((5, 5), result)

    def test_a_fresh_start_waits_for_room_too(self):
        world = World({n: 5 for n in NAMES}, jobs.TOWN_RUN)
        result, withheld = self.drive(world)
        self.assertEqual((0, 0), result)
        self.assertEqual([], world.inserted)
        self.assertIn("town first", withheld[0])

    def test_an_armed_campaign_between_the_floor_and_the_band_is_not_held(self):
        world = World({n: 5 for n in NAMES}, ZF)
        result, withheld = self.drive(world)
        self.assertEqual((5, 5), result)
        self.assertEqual([], withheld)


class TheWaitIsSpentInTown(unittest.TestCase):
    """mod-overseer#659. A campaign waiting in town used to leave the family on
    the default `quest` job, and on wow-dev 2026-09-24 the questing rules flew
    the Alliance leader 13,000 yards from his members and sent four Horde
    members off to three zones while their campaigns waited on a vendor."""

    def setUp(self):
        self.clock, self.log, self.since = Clock(), Log(), {}

    def drive(self, world):
        withheld = []
        result = _drive(world, self.clock, self.log, self.since)(withheld)
        return result, withheld

    def test_the_hand_off_writes_town_run_not_quest(self):
        world = World(MEASURED, ZF)
        self.drive(world)
        self.assertEqual({jobs.TOWN_RUN}, {mode for _, mode, _ in world.inserted})
        self.assertNotIn(jobs.DEFAULT, {mode for _, mode, _ in world.inserted})

    def test_a_wait_that_began_on_quest_moves_to_town(self):
        """The measured state: the hold began before this change, on quest."""
        world = World(MEASURED, jobs.DEFAULT)
        result, withheld = self.drive(world)
        self.assertEqual((0, 0), result)
        self.assertEqual(1, len(withheld))
        self.assertEqual(
            [(n, jobs.TOWN_RUN, "overseer:town-first") for n in NAMES], world.inserted
        )
        self.assertTrue(
            [ln for ln in self.log.lines if "wait in town for the campaign" in ln],
            self.log.lines,
        )

    def test_a_fresh_start_short_of_room_waits_in_town(self):
        world = World({n: 5 for n in NAMES}, jobs.DEFAULT)
        self.drive(world)
        self.assertEqual({jobs.TOWN_RUN}, {mode for _, mode, _ in world.inserted})

    def test_only_the_default_job_is_moved(self):
        world = World(MEASURED, jobs.DEFAULT)
        world.jobs.update({"Og": "craft", "Grog": "fish", "Ugga": ""})
        self.drive(world)
        self.assertEqual(
            [("Grug", jobs.TOWN_RUN), ("Bork", jobs.TOWN_RUN), ("Ugga", jobs.TOWN_RUN)],
            [(n, mode) for n, mode, _ in world.inserted],
        )

    def test_no_queued_campaign_no_town_run(self):
        """A council goal withheld with no queue row keeps the old behavior,
        so the release below cannot undo it every cycle."""
        world = World(MEASURED, jobs.DEFAULT, waiting=False)
        self.drive(world)
        self.assertEqual([], world.inserted)


def _leave(world, last_source):
    """bridge._leave_town, run for real against `world`."""
    log = Log()
    ns = {
        "jobs": jobs,
        "log": log,
        "TOWN_FIRST_SOURCE": "overseer:town-first",
        "_campaign_waiting": lambda names: world.waiting,
        "_jobs_of": lambda names: {n: world.jobs[n] for n in names},
        "_last_job_source": lambda name: last_source,
        "_insert_job": world.insert_job,
    }
    module = ast.Module(body=[_function("_leave_town")], type_ignores=[])
    exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
    return ns["_leave_town"](list(NAMES), "Grug"), log


class TheFamilyLeavesTownWhenNothingWaits(unittest.TestCase):
    def test_a_finished_campaign_sends_the_family_back_to_quest(self):
        world = World(MEASURED, jobs.TOWN_RUN, waiting=False)
        written, log = _leave(world, "overseer:town-first")
        self.assertEqual(5, written)
        self.assertEqual({jobs.DEFAULT}, set(world.jobs.values()))
        self.assertTrue([ln for ln in log.lines if "no campaign waits" in ln])

    def test_a_waiting_campaign_keeps_it_in_town(self):
        world = World(MEASURED, jobs.TOWN_RUN, waiting=True)
        self.assertEqual(0, _leave(world, "overseer:town-first")[0])
        self.assertEqual([], world.inserted)

    def test_an_operators_town_run_stands(self):
        world = World(MEASURED, jobs.TOWN_RUN, waiting=False)
        self.assertEqual(0, _leave(world, "discord:operator")[0])
        self.assertEqual([], world.inserted)

    def test_only_the_town_run_rows_go_back(self):
        world = World(MEASURED, jobs.TOWN_RUN, waiting=False)
        world.jobs["Og"] = "craft"
        _leave(world, "overseer:town-first")
        self.assertEqual("craft", world.jobs["Og"])
        self.assertNotIn("Og", [n for n, _, _ in world.inserted])

    def test_the_queue_pass_asks_for_the_release(self):
        body = ast.get_source_segment(BRIDGE, _function("_campaign_queue_once"))
        self.assertIn("await self._leave_town_when_done(fams)", body)
        self.assertLess(
            body.index("_campaign_owns_travel("), body.index("_leave_town_when_done(")
        )
        self.assertLess(
            body.index("_leave_town_when_done("), body.index("if not pending:")
        )


if __name__ == "__main__":
    unittest.main()
