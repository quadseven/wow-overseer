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

    def __init__(self, free, job):
        self.free = dict(free)
        self.jobs = {n: job for n in NAMES}
        self.inserted = []

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
        "_connect": lambda: contextlib.nullcontext(Conn()),
        "pymysql": None,
    }
    module = ast.Module(
        body=[
            _function(n)
            for n in (
                "_withheld",
                "_hand_to_town",
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
            [(n, jobs.DEFAULT, "overseer:town-first") for n in NAMES], world.inserted
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
        world = World(MEASURED, jobs.DEFAULT)
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
        world = World({n: 5 for n in NAMES}, jobs.DEFAULT)
        result, withheld = self.drive(world)
        self.assertEqual((0, 0), result)
        self.assertEqual([], world.inserted)
        self.assertIn("town first", withheld[0])

    def test_an_armed_campaign_between_the_floor_and_the_band_is_not_held(self):
        world = World({n: 5 for n in NAMES}, ZF)
        result, withheld = self.drive(world)
        self.assertEqual((5, 5), result)
        self.assertEqual([], withheld)


if __name__ == "__main__":
    unittest.main()
