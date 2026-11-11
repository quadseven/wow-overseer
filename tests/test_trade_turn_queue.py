"""The trade turn in the bridge's campaign queue pass (#2262, #2261).

After a queued run ends, the queue yields the family's job for one turn and
then takes it back. Fake rows and fake adapters; no database.
"""

import asyncio
import types
import unittest

import campaignqueue  # noqa: E402
import classic  # noqa: E402
import tradeturn  # noqa: E402
from test_campaign_queue import FakeWorld, _Log, _load, _q, _queue_pass  # noqa: E402

SECONDS = 1200
RUN_END = 5000
NOW = 100000.0
LOW = {"Zug": {"Alchemy": 40}}
MAXED = {"Zug": {"Alchemy": classic.MAX_PROFESSION_SKILL}}


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def time(self):
        return self.now


class TurnWorld(FakeWorld):
    """The queue world plus the turn store, the run table and the skills."""

    def __init__(self):
        super().__init__([_q(1, "ragefire", 50, "queued", 0)])
        self.turns = {}
        self.last_end = None
        self.mid_run = False
        self.trades = LOW
        self.clock = Clock()
        self.saved = []
        self.log = _Log()
        self.held = set()

    def fetch_turns(self):
        return dict(self.turns)

    def save_turn(self, family, turn):
        self.turns[family] = turn
        self.saved.append((family, turn))

    def fetch_end(self, leader):
        return self.last_end

    def fetch_skills(self, names):
        return self.trades

    def hooks(self, seconds=SECONDS):
        world = self
        ns = _load(
            ["_trade_turn_pass", "_trade_turn_family"],
            {
                "asyncio": asyncio,
                "campaignqueue": campaignqueue,
                "tradeturn": tradeturn,
                "jobs": __import__("jobs"),
                "log": self.log,
                "time": self.clock,
                "TRADE_TURN_SECONDS": seconds,
                "_TRADE_TURN": self.held,
                "_fetch_trade_turns": self.fetch_turns,
                "_save_trade_turn": self.save_turn,
                "_fetch_last_run_end": self.fetch_end,
                "_fetch_trade_skills": self.fetch_skills,
                "_insert_job": self.insert_job,
            },
        )

        async def mid_run(names):
            return world.mid_run

        me = types.SimpleNamespace(_mid_run=mid_run)

        async def turn_pass(pending, fams):
            return await ns["_trade_turn_pass"](me, pending, fams)

        me._trade_turn_family = lambda *a: ns["_trade_turn_family"](me, *a)
        return {"_trade_turn_pass": turn_pass}

    def run_pass(self, seconds=SECONDS):
        lines = _queue_pass(
            self, extra={"_TRADE_TURN": self.held}, **self.hooks(seconds)
        )
        return lines + self.log.lines

    def zug(self):
        return self.row("Zug")


def started_world():
    """Entry running, a run just ended."""
    w = TurnWorld()
    w.run_pass()
    assert w.zug()["job"] == "dungeon:ragefire", w.zug()["job"]
    w.last_end = RUN_END
    return w


class TheQueueYieldsForATurn(unittest.TestCase):
    def test_the_job_is_not_the_queues_for_the_turn_and_comes_back(self):
        w = started_world()
        w.run_pass()
        self.assertEqual("quest", w.zug()["job"], "the turn handed the job off")
        self.assertIn("Zug", w.turns)
        # Mid turn: the queue neither re-asserts nor owns.
        w.clock.now += 600
        before = len(w.jobs)
        w.run_pass()
        self.assertEqual(before, len(w.jobs))
        self.assertEqual({"Zug"}, w.held)
        # Turn spent: the queue admits its entry again, same entry, same count.
        w.clock.now += 700
        w.zug()["dungeon_runs_done"] = 7
        w.run_pass()
        self.assertEqual("dungeon:ragefire", w.zug()["job"])
        self.assertEqual(7, w.zug()["dungeon_runs_done"], "the count was reset")
        self.assertEqual(set(), w.held)

    def test_no_second_turn_until_another_run_ends(self):
        w = started_world()
        w.run_pass()
        w.clock.now += SECONDS + 10
        w.run_pass()
        self.assertEqual("dungeon:ragefire", w.zug()["job"])
        starts = len(w.saved)
        w.clock.now += 5000
        w.run_pass()
        self.assertEqual("dungeon:ragefire", w.zug()["job"])
        self.assertEqual(starts, len(w.saved))
        w.last_end = RUN_END + 900
        w.run_pass()
        self.assertEqual("quest", w.zug()["job"])

    def test_a_restart_in_the_middle_resumes_the_same_turn(self):
        w = started_world()
        w.run_pass()
        started = w.turns["Zug"].started
        # A new process: nothing in memory, the store remains.
        w.held.clear()
        w.clock.now += 500
        w.run_pass()
        self.assertEqual(started, w.turns["Zug"].started)
        self.assertEqual({"Zug"}, w.held)
        self.assertEqual("quest", w.zug()["job"])

    def test_every_trade_at_the_cap_takes_no_turn_and_logs_why(self):
        w = started_world()
        w.trades = MAXED
        lines = w.run_pass()
        self.assertEqual("dungeon:ragefire", w.zug()["job"])
        skips = [ln for ln in lines if "trade turn" in ln and "skip" in ln]
        self.assertEqual(1, len(skips), lines)
        self.assertIn("cap", skips[0])
        self.assertIn("Zug", skips[0])
        # And the skip is said once per run.
        w.run_pass()
        self.assertEqual(1, len([ln for ln in w.log.lines if "skip" in ln]))

    def test_a_setting_of_zero_takes_no_turn_and_logs_why(self):
        w = started_world()
        lines = w.run_pass(seconds=0)
        self.assertEqual("dungeon:ragefire", w.zug()["job"])
        self.assertTrue([ln for ln in lines if "TRADE_TURN_SECONDS is 0" in ln])

    def test_a_run_in_progress_is_not_interrupted_and_entries_stand(self):
        w = started_world()
        w.mid_run = True
        w.run_pass()
        self.assertEqual("dungeon:ragefire", w.zug()["job"])
        self.assertEqual({}, w.turns)
        self.assertEqual(
            [("active", 50)], [(r["status"], r["runs_wanted"]) for r in w.queue]
        )

    def test_a_turn_changes_no_queue_entry(self):
        w = TurnWorld()
        w.queue = [
            _q(1, "ragefire", 50, "queued", 0),
            _q(2, "wailing", 50, "queued", 1),
        ]
        w.run_pass()
        w.last_end = RUN_END
        before = [(r["id"], r["keyword"], r["position"]) for r in w.queue]
        w.run_pass()
        w.clock.now += 3000
        w.run_pass()
        self.assertEqual(
            before, [(r["id"], r["keyword"], r["position"]) for r in w.queue]
        )

    def test_start_and_end_are_each_logged_once_with_the_family(self):
        w = started_world()
        w.run_pass()
        w.run_pass()
        w.clock.now += SECONDS + 1
        w.run_pass()
        w.run_pass()
        starts = [ln for ln in w.log.lines if "trade turn" in ln and "starts" in ln]
        ends = [ln for ln in w.log.lines if "trade turn" in ln and "ends" in ln]
        self.assertEqual(1, len(starts), w.log.lines)
        self.assertEqual(1, len(ends), w.log.lines)
        self.assertIn("Zug", starts[0])
        self.assertIn("Zug", ends[0])


class TheOtherPassesSeeNoQueueDuringATurn(unittest.TestCase):
    def owns(self, held, family="Zug", dungeon=False):
        ns = _load(
            ["_queue_owns_job"],
            {
                "campaignqueue": campaignqueue,
                "log": _Log(),
                "_cohort_of": lambda name: "Zug",
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Zug"),
                "_fetch_queue_rows": lambda: [_q(1, "ragefire", 50, "active", 0)],
                "_PACE_QUESTING": {},
                "_BAG_HOLD_STUCK": {},
                "_TRADE_TURN": held,
            },
        )
        return ns["_queue_owns_job"](family, dungeon)

    def test_the_queue_does_not_own_the_job_during_a_turn(self):
        self.assertFalse(self.owns({"Zug"}))

    def test_it_owns_the_job_again_when_the_turn_is_over(self):
        self.assertTrue(self.owns(set()))

    def test_the_dungeon_lease_still_sees_the_queue(self):
        self.assertTrue(self.owns({"Zug"}, dungeon=True))

    def test_another_family_is_untouched(self):
        self.assertTrue(self.owns({"Thrak"}))


class TheCampaignPassHidesTheFamilyFromTravelDuringATurn(unittest.TestCase):
    def test_learn_trips_and_town_errands_see_an_empty_queue(self):
        w = started_world()
        seen = []
        w.run_pass()  # starts the turn
        hooks = w.hooks()
        inner = hooks["_trade_turn_pass"]

        async def watching(pending, fams):
            kept = await inner(pending, fams)
            seen.append(sorted(kept))
            return kept

        _queue_pass(w, extra={"_TRADE_TURN": w.held}, _trade_turn_pass=watching)
        self.assertEqual([[]], seen)


if __name__ == "__main__":
    unittest.main()
