"""Incidental holds never keep a queued campaign run out past a durable ceiling.

Measured on wow-dev 2026-09-29: Zug's family (Ragefire Chasm 0 of 50, active
for four days) was held out of its door by three things at once. The dungeon
quest pass walked the leader to a turn-in giver 2600 yards off and held the
queue for the walk; the gear hold kept the family in town on a clock that lives
in the bridge's memory, so every restart began the 45 minutes again; and the
bag-room hold measured its ceiling the same way. Pinned here:

  * a far dungeon quest giver does not hold the queue, and the walk is not taken;
  * a near one still does;
  * the quest pass stands down past the queue's own stall ceiling;
  * the gear gate, the gear hold and the town-first wait all read the queue's
    stall as read from the store, so a restart does not restart the wait.
"""

import ast
import asyncio
import pathlib
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import bag_pressure  # noqa: E402
import campaignqueue  # noqa: E402
import dungeonquests  # noqa: E402
import gearup  # noqa: E402
import jobs  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "bridge.py").read_text(encoding="utf-8")
CEILING = bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS
NAMES = ["Zug", "Oz", "Uzza", "Zork", "Zrog"]


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()


def _facts(leader_at, spawn=(1, 1000.0, 1000.0, 0.0)):
    quest = dungeonquests.Quest(100, 1581, 10, 0, 0, 3665, 3665)
    member = dungeonquests.Member(
        "Zug",
        level=18,
        race=2,
        map_id=leader_at[0],
        x=leader_at[1],
        y=leader_at[2],
        z=0.0,
    )
    return dungeonquests.Facts(
        dungeon="ragefire",
        leader="Zug",
        quests=(quest,),
        members=(member,),
        statuses={"Zug": {100: dungeonquests.STATUS_COMPLETE}},
        spawn=spawn,
        due=True,
    )


class FarGiverTest(unittest.TestCase):
    def test_a_giver_thousands_of_yards_off_does_not_hold_the_queue(self):
        step = dungeonquests.step(_facts((1, 1000.0 - 2600.0, 1000.0)))
        self.assertFalse(step.hold_planner)
        self.assertIsNone(step.aim)
        self.assertEqual(step.rows, ())
        self.assertIn("does not wait", step.line)

    def test_a_giver_on_another_map_does_not_hold_the_queue(self):
        step = dungeonquests.step(_facts((0, 1000.0, 1000.0)))
        self.assertFalse(step.hold_planner)
        self.assertIsNone(step.aim)

    def test_the_far_giver_hands_back_an_aim_left_on_it(self):
        step = dungeonquests.step(_facts((1, -1600.0, 1000.0)))
        self.assertTrue(step.release)
        self.assertEqual(step.giver, 3665)

    def test_a_near_giver_still_holds_and_is_walked_to(self):
        step = dungeonquests.step(_facts((1, 1000.0 - 300.0, 1000.0)))
        self.assertTrue(step.hold_planner)
        self.assertEqual(step.aim, 3665)


class _Pass:
    def __init__(self):
        self.claims = []

    async def _mid_run(self, names):
        return False

    async def _claim_town_slot(self, claimant, leader, aim, cohort=None):
        self.claims.append(aim)
        return True


class QuestPassCeilingTest(unittest.TestCase):
    def run_pass(self, stall):
        fam = {"leader": {"name": "Zug"}, "names": list(NAMES)}
        rows = [{"status": campaignqueue.ACTIVE, "keyword": "ragefire"}]
        walk = dungeonquests.Step(
            dungeonquests.GO,
            "walk the family to dungeon quest giver 3665 to turn in",
            hold_planner=True,
            aim=3665,
            giver=3665,
        )
        stage = _Pass()
        with (
            mock.patch.object(
                bridge, "_fetch_free_slots", lambda n: {x: 30 for x in n}
            ),
            mock.patch.object(bridge, "_dungeonquest_facts", lambda *a: None),
            mock.patch.object(bridge, "_queue_stall_floor", lambda names: stall),
            mock.patch.object(bridge.dungeonquests, "step", lambda facts: walk),
            mock.patch.object(bridge.log, "info"),
        ):
            held = asyncio.run(
                bridge.Bridge._dungeonquest_for_family(stage, "Zug", fam, rows, "Zug")
            )
        return held, stage.claims

    def test_a_fresh_queue_is_held_for_the_walk(self):
        held, claims = self.run_pass(60.0)
        self.assertTrue(held)
        self.assertEqual(claims, ["3665"])

    def test_a_stalled_queue_is_not_held_and_the_walk_is_not_taken(self):
        held, claims = self.run_pass(CEILING + 1)
        self.assertFalse(held)
        self.assertEqual(claims, [])


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ):
            return node
    raise AssertionError("%s not found in bridge.py" % name)


class Clock:
    now = 1000.0

    def monotonic(self):
        return self.now


class Log:
    def info(self, *a, **k):
        pass

    warning = exception = info


class StallFloorTest(unittest.TestCase):
    """The gear gate, the gear hold and the town-first wait after a restart."""

    def setUp(self):
        self.clock = Clock()
        self.jobs = {n: "town run" for n in NAMES}
        self.stall = {}
        self.ns = {
            "time": self.clock,
            "log": Log(),
            "bag_pressure": bag_pressure,
            "gearup": gearup,
            "jobs": jobs,
            "TOWN_FIRST_SOURCE": "overseer:town-first",
            "GEARUP_GATE_EMPTY_SLOTS": 6,
            "GEARUP_GATE_MIN_PURSE": 20000,
            "_GEAR_HOLD_SINCE": {},
            "_TOWN_FIRST_SINCE": {},
            "_QUEUE_STALL": self.stall,
            "_fetch_gearup_facts": lambda names: {
                n: {"equipped": ["mainhand"], "purse": 30000} for n in names
            },
            "_jobs_of": lambda names: {n: self.jobs[n] for n in names},
            "_insert_job": lambda *a: None,
            "_keep_in_town": lambda names: None,
        }
        module = ast.Module(
            body=[
                _function(n)
                for n in (
                    "_queue_stall_floor",
                    "_note_queue_stall",
                    "_gear_gate",
                    "_gear_campaign_hold",
                    "_town_first",
                )
            ],
            type_ignores=[],
        )
        exec(compile(module, "bridge.py", "exec"), self.ns)  # noqa: S102

    def restart_after(self, seconds):
        """A restarted bridge: empty in-process clocks, the store's stall read."""
        self.ns["_GEAR_HOLD_SINCE"].clear()
        self.ns["_TOWN_FIRST_SINCE"].clear()
        self.ns["_note_queue_stall"](NAMES, seconds)

    def test_the_gear_gate_lets_a_long_stalled_queue_go_after_a_restart(self):
        self.restart_after(CEILING + 5)
        self.assertIsNone(self.ns["_gear_gate"](NAMES, "ragefire"))

    def test_the_gear_gate_still_holds_a_young_queue(self):
        self.restart_after(30)
        self.assertIn("gear-up first", self.ns["_gear_gate"](NAMES, "ragefire"))

    def test_the_gear_hold_releases_a_long_stalled_queue_after_a_restart(self):
        self.restart_after(CEILING + 5)
        self.assertFalse(self.ns["_gear_campaign_hold"](NAMES, "ragefire", False))

    def test_the_stall_keeps_counting_between_reads(self):
        self.restart_after(CEILING - 10)
        self.assertIn("gear-up first", self.ns["_gear_gate"](NAMES, "ragefire"))
        self.clock.now += 11
        self.assertIsNone(self.ns["_gear_gate"](NAMES, "ragefire"))

    def test_the_town_first_wait_ends_on_the_stall_after_a_restart(self):
        self.restart_after(CEILING + 5)
        free = {n: 4 for n in NAMES}
        self.assertEqual(self.ns["_town_first"]("dungeon:ragefire", NAMES, free), "")

    def test_the_town_first_wait_holds_a_young_queue(self):
        self.restart_after(30)
        free = {n: 4 for n in NAMES}
        self.assertIn(
            "town first", self.ns["_town_first"]("dungeon:ragefire", NAMES, free)
        )


if __name__ == "__main__":
    unittest.main()
