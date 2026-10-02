"""The gear gate lets a campaign go after the ceiling (#146, #147).

Measured on wow-dev 2026-09-27: both families' campaigns read
`queue: ...: withheld: gear-up first` every pass for over ten hours, while
every auctioneer walk failed and the Alliance family died on the way to one.
The hold (`_gear_campaign_hold`) released at the 45-minute ceiling, but it
cleared its own clock when it did, and the queue's re-send went through
`_gear_gate`, which had no ceiling at all. Pinned here, running both bridge
functions for real against fakes:

  * the gate withholds a funded, gear-short family before the ceiling;
  * the gate lets the run go once the family has been short past it;
  * the hold does not restart the clock when the ceiling releases it, so the
    family is not handed back to town on the next pass;
  * the clock clears once the gear does.
"""

import ast
import pathlib
import unittest

import bag_pressure
import gearup
import jobs

BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)
NAMES = ["Grug", "Bork", "Og", "Grog", "Ugga"]
NAKED = {"equipped": ["mainhand", "chest"], "purse": 630310}
DRESSED = {
    "equipped": ["mainhand"] + ["s%d" % i for i in range(16)],
    "purse": 630310,
}
CEILING = bag_pressure.CAMPAIGN_RESUME_CEILING_SECONDS


def _function(name):
    for node in ast.walk(ast.parse(BRIDGE)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
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


class GearGateCeilingTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.log = Log()
        self.facts = {n: dict(NAKED) for n in NAMES}
        self.jobs = {n: "dungeon:scarlet-library" for n in NAMES}
        self.inserted = []
        ns = {
            "time": self.clock,
            "log": self.log,
            "bag_pressure": bag_pressure,
            "gearup": gearup,
            "jobs": jobs,
            "TOWN_FIRST_SOURCE": "overseer:town-first",
            "GEARUP_GATE_EMPTY_SLOTS": 6,
            "GEARUP_GATE_MIN_PURSE": 20000,
            "_GEAR_HOLD_SINCE": {},
            "_fetch_gearup_facts": lambda names: {n: self.facts[n] for n in names},
            "_jobs_of": lambda names: {n: self.jobs[n] for n in names},
            "_queue_stall_floor": lambda names: 0.0,
            "_insert_job": self._insert_job,
        }
        module = ast.Module(
            body=[_function("_gear_gate"), _function("_gear_campaign_hold")],
            type_ignores=[],
        )
        exec(compile(module, "bridge.py", "exec"), ns)  # noqa: S102 - bridge.py's own source
        self.ns = ns

    def _insert_job(self, name, mode, source):
        self.inserted.append((name, mode, source))
        self.jobs[name] = mode

    def gate(self):
        return self.ns["_gear_gate"](NAMES, "scarlet-library")

    def hold(self, in_run=False):
        return self.ns["_gear_campaign_hold"](NAMES, "scarlet-library", in_run)

    def test_gate_withholds_before_the_ceiling(self):
        self.assertIn("gear-up first", self.gate())
        self.clock.now += CEILING - 1
        self.assertIn("gear-up first", self.gate())

    def test_gate_holds_empty_mainhand_below_the_empty_slot_threshold(self):
        self.facts = {n: dict(DRESSED) for n in NAMES}
        self.facts["Og"] = {
            "equipped": ["s%d" % i for i in range(10)],
            "purse": 630310,
        }
        self.ns["GEARUP_GATE_EMPTY_SLOTS"] = 8

        reason = self.gate()

        self.assertEqual(7, 17 - len(self.facts["Og"]["equipped"]))
        self.assertIn("Og has no main-hand weapon", reason)
        self.assertTrue(self.hold())

    def test_gate_lets_the_run_go_after_the_ceiling(self):
        self.gate()
        self.clock.now += CEILING
        self.assertIsNone(self.gate())
        self.assertTrue(
            any("no longer held for gear" in line for line in self.log.lines)
        )

    def test_early_level_family_can_gear_through_its_dungeon_band(self):
        self.facts = {
            name: {
                "level": 21,
                "equipped": ["mainhand"] + ["slot%d" % i for i in range(9)],
                "purse": 630310,
            }
            for name in NAMES
        }

        self.assertIsNone(self.gate())
        self.assertFalse(self.hold())
        self.assertEqual(self.inserted, [])

    def test_early_level_gate_still_holds_a_member_missing_nine_slots(self):
        self.facts = {
            name: {
                "level": 21,
                "equipped": ["mainhand"] + ["slot%d" % i for i in range(7)],
                "purse": 630310,
            }
            for name in NAMES
        }

        self.assertIn("gear-up first", self.gate())
        self.assertTrue(self.hold())

    def test_hold_then_gate_share_one_clock(self):
        self.assertTrue(self.hold())
        self.assertEqual(len(self.inserted), len(NAMES))
        self.clock.now += CEILING
        self.assertFalse(self.hold())
        # The queue's re-send lands in the gate on the next pass: it must go.
        self.assertIsNone(self.gate())
        # And with the job back on dungeon, the hold must not take it again.
        for n in NAMES:
            self.jobs[n] = "dungeon:scarlet-library"
        before = len(self.inserted)
        self.assertFalse(self.hold())
        self.assertEqual(len(self.inserted), before)

    def test_hold_never_touches_a_family_inside_a_run(self):
        self.assertFalse(self.hold(in_run=True))
        self.assertEqual(self.inserted, [])
        self.assertEqual(self.ns["_GEAR_HOLD_SINCE"], {})

    def test_bought_gear_in_the_mail_holds_a_broke_family(self):
        """The dev realm, 2026-09-27: the buyers' purses were spent and their
        purchases sat in the mailbox, so the gate read them as too poor to
        hold for and sent them to the door in eight of seventeen slots."""
        self.facts = {n: dict(NAKED, purse=0) for n in NAMES}
        self.assertIsNone(self.gate())
        self.ns["_mail_gear_holders"] = lambda names: {"Bork": 5}
        self.assertIn("Bork", self.gate())
        self.assertTrue(self.hold())

    def test_clock_clears_when_the_gear_does(self):
        self.gate()
        self.clock.now += CEILING
        self.facts = {n: dict(DRESSED) for n in NAMES}
        self.assertIsNone(self.gate())
        self.assertEqual(self.ns["_GEAR_HOLD_SINCE"], {})
        # Short again later: a fresh wait, not an old expired clock.
        self.facts = {n: dict(NAKED) for n in NAMES}
        self.assertIn("gear-up first", self.gate())


if __name__ == "__main__":
    unittest.main()
