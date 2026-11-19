"""A walk that restarts while a finished run leaves is not the door refusing the leader.

Measured on the dev realm: a family cleared Dire Maul East twice (every encounter
credited, `outcome = complete`), and each time the walk out through the exit
trigger failed and restarted four times before the exit hearth sent everyone
home. The stall breaker counted those exit-leg restarts as "the leader's walk to
the door ended and restarted 4 times in 60 minutes without arriving", stood the
run down, and left the door, so a family with two clean clears was held out of
its own queue. Restarts that began between a completed run's start and its end
are the way out, and are not counted.
"""

import unittest

import nowstatus

WALK = "the dungeon run took over: walking to Dire Maul for the dungeon run"
NOW = 1_000_000
HOUR = 3600


def walk(first_at, last_at=None, occurrences=1):
    return {
        "kind": "intent",
        "doing": WALK,
        "occurrences": occurrences,
        "first_at": first_at,
        "last_at": last_at or first_at,
    }


class ExitLegRestarts(unittest.TestCase):
    def test_without_windows_it_counts_as_before(self):
        steps = [walk(NOW - 600, occurrences=4)]
        self.assertEqual(4, nowstatus.restart_count(steps, NOW, 0, HOUR))

    def test_restarts_inside_a_completed_runs_window_are_not_counted(self):
        steps = [walk(NOW - 600, NOW - 100, occurrences=4)]
        done = [(NOW - 2400, NOW - 50)]
        self.assertEqual(
            0, nowstatus.restart_count(steps, NOW, 0, HOUR, completed=done)
        )

    def test_restarts_after_the_run_ended_still_count(self):
        steps = [walk(NOW - 300, NOW - 100, occurrences=4)]
        done = [(NOW - 2400, NOW - 400)]
        self.assertEqual(
            4, nowstatus.restart_count(steps, NOW, 0, HOUR, completed=done)
        )

    def test_restarts_before_the_run_began_still_count(self):
        steps = [walk(NOW - 3000, NOW - 2900, occurrences=3)]
        done = [(NOW - 2400, NOW - 400)]
        self.assertEqual(
            3, nowstatus.restart_count(steps, NOW, 0, HOUR, completed=done)
        )

    def test_only_the_steps_inside_are_dropped(self):
        steps = [
            walk(NOW - 3000, NOW - 2900, occurrences=3),
            walk(NOW - 600, NOW - 100, occurrences=4),
        ]
        done = [(NOW - 2400, NOW - 50)]
        self.assertEqual(
            3, nowstatus.restart_count(steps, NOW, 0, HOUR, completed=done)
        )


class BridgeReadsTheCompletedRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib

        text = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        a = text.index("def _door_wedge_evidence(")
        cls.body = text[a : text.index("\ndef _door_wedge_ages(", a)]
        cls.text = text

    def test_it_reads_the_leaders_completed_runs(self):
        self.assertIn("outcome = 'complete'", self.text)
        self.assertIn("completed=", self.body)


if __name__ == "__main__":
    unittest.main()
