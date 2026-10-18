"""A Jev interlude does not end a family's bag hold (#872).

Measured on the dev realm 2026-10-18. Grug's family was withheld from
Uldaman on "bags are near full, and a run started now would be evacuated
before it could progress" for over five hours. The hold at the floor has a
way out (bag_pressure.BAG_HOLD_STUCK_SECONDS with no slot gained sends the
family back to questing), but it never got there: Jev chose a sell interlude
for the family about every half hour, eight to twelve minutes each, and the
queue does not call the campaign gate while an interlude holds the order. The
gate is the only reader of the hold it judges, so every interlude of ten
minutes or more was a gap longer than bag_pressure.BAG_HOLD_GAP_SECONDS, and
the first reading after it started a new hold. The bridge log shows it: the
queue's readings stopped at 09:47:06 and resumed at 10:00:27, and stopped at
10:49:49 and resumed at 11:00:03; the hold logged its 30-minute warning
30 minutes after 11:00 and was released at 11:45, the first time in the log
it reached 45 minutes.

Pinned here: the queue reads the bags of a family it holds for an
interlude, under the gate's own key, so the hold keeps its clock through the
interlude and times out into questing with its reason.
"""

import ast
import unittest

import bag_pressure
import jobs
from test_bag_hold_exit import MEASURED, NAMES, Clock, Log, World, _drive, _functions
from test_campaign_queue import FakeWorld, _q, _queue_pass

WINDOW_MINUTES = int(bag_pressure.BAG_HOLD_STUCK_SECONDS // 60)
# The longest sell interlude the log shows, in minutes: longer than the gap.
INTERLUDE_MINUTES = 12


def _with_hold_read(ns):
    exec(  # noqa: S102 - bridge.py's own source
        compile(
            ast.Module(body=_functions("_bag_hold_read"), type_ignores=[]),
            "bridge.py",
            "exec",
        ),
        ns,
    )
    return ns


class TheHoldKeepsItsClockThroughAnInterlude(unittest.TestCase):
    def setUp(self):
        self.world = World(MEASURED, jobs.TOWN_RUN)
        self.clock = Clock()
        self.log = Log()
        self.drive, self.ns = _drive(self.world, self.clock, self.log)
        _with_hold_read(self.ns)

    def _gate(self, minutes):
        out = None
        for _ in range(minutes):
            self.clock.now += 60.0
            out = self.drive()
        return out

    def _interlude(self, minutes, read=True):
        for _ in range(minutes):
            self.clock.now += 60.0
            if read:
                self.ns["_bag_hold_read"](list(NAMES))

    def test_the_gap_is_longer_than_the_rule_allows(self):
        self.assertGreater(INTERLUDE_MINUTES * 60.0, bag_pressure.BAG_HOLD_GAP_SECONDS)

    def test_an_unread_interlude_restarts_the_hold(self):
        # The measured cause, without the queue's reading: the gap starts a
        # new hold, and the family is still in town past the window.
        self._gate(20)
        self._interlude(INTERLUDE_MINUTES, read=False)
        written, withheld = self._gate(WINDOW_MINUTES + 2 - 20 - INTERLUDE_MINUTES)
        self.assertEqual((0, 0), written)
        self.assertIn("near full", withheld[0])
        self.assertEqual({jobs.TOWN_RUN}, set(self.world.jobs.values()))

    def test_a_read_interlude_times_out_into_questing_with_a_reason(self):
        self._gate(20)
        self._interlude(INTERLUDE_MINUTES)
        written, withheld = self._gate(WINDOW_MINUTES + 2 - 20 - INTERLUDE_MINUTES)
        self.assertEqual((0, 0), written)
        self.assertIn(
            "Grog at the bag floor and no town pass has made room", withheld[0]
        )
        self.assertIn("the family quests until there is room", withheld[0])
        self.assertEqual({jobs.DEFAULT}, set(self.world.jobs.values()))

    def test_a_slot_sold_in_the_interlude_still_restarts_the_clock(self):
        self._gate(20)
        self.world.free["Grog"] = 2
        self._interlude(INTERLUDE_MINUTES)
        _written, withheld = self._gate(WINDOW_MINUTES + 2 - 20 - INTERLUDE_MINUTES)
        self.assertIn("near full", withheld[0])

    def test_back_to_back_interludes_do_not_hold_the_family_for_hours(self):
        # The measured cadence: an interlude about every half hour. The
        # family is questing within the window, not five hours later.
        for _ in range(3):
            self._gate(20)
            self._interlude(INTERLUDE_MINUTES)
        self.assertEqual({jobs.DEFAULT}, set(self.world.jobs.values()))
        self.assertTrue(
            any("no town pass has made room" in line for line in self.log.lines)
        )

    def test_the_read_uses_the_gates_key_without_a_member_sitting_out(self):
        self.ns["_standin_running"] = lambda names: [n for n in names if n != "Og"]
        self._gate(20)
        self._interlude(INTERLUDE_MINUTES)
        self._gate(WINDOW_MINUTES + 2 - 20 - INTERLUDE_MINUTES)
        running = [n for n in NAMES if n != "Og"]
        self.assertEqual({jobs.DEFAULT}, {self.world.jobs[n] for n in running})

    def test_no_hold_is_no_read(self):
        def no_read(names):
            raise AssertionError("read bags with no hold to keep")

        self.ns["_fetch_free_slots"] = no_read
        self.assertEqual((), self.ns["_bag_hold_read"](list(NAMES)))
        self.assertEqual({}, self.ns["_BAG_HOLD"])

    def test_a_failed_read_is_logged_and_keeps_the_hold(self):
        self._gate(5)
        before = dict(self.ns["_BAG_HOLD"])

        def broken(names):
            raise RuntimeError("database gone")

        self.ns["_fetch_free_slots"] = broken
        self.assertEqual((), self.ns["_bag_hold_read"](list(NAMES)))
        self.assertEqual(before, self.ns["_BAG_HOLD"])
        self.assertTrue(
            any("during an interlude failed" in line for line in self.log.lines)
        )


class TheQueueReadsDuringAnInterlude(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld([_q(1, "ragefire", 50, "queued", 0)])
        self.reads = []

    def _read(self, names):
        self.reads.append(sorted(names))
        return ()

    def test_an_interlude_reads_the_family_it_holds(self):
        lines = _queue_pass(
            self.world, holds={"Zug": "sell"}, extra={"_bag_hold_read": self._read}
        )
        self.assertTrue(any("interlude runs" in line for line in lines))
        self.assertEqual(
            [sorted(r["name"] for r in self.world.family("Zug"))], self.reads
        )

    def test_no_interlude_leaves_the_reading_to_the_gate(self):
        _queue_pass(self.world, extra={"_bag_hold_read": self._read})
        self.assertEqual([], self.reads)


if __name__ == "__main__":
    unittest.main()
