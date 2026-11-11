"""The trade turn in the bridge's campaign queue pass (#2262, #2261).

After a queued run ends, the queue yields the family's job for one turn and
then takes it back. Fake rows and fake adapters; no database.
"""

import asyncio
import types
import unittest

import campaignqueue  # noqa: E402
import classic  # noqa: E402
import craft_rhythm  # noqa: E402
import jobs  # noqa: E402
import townerrand  # noqa: E402
import tradeturn  # noqa: E402
from test_campaign_queue import FakeWorld, _Log, _load, _q, _queue_pass  # noqa: E402

SECONDS = 1200
TOWN_SECONDS = 600
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
        self.seen = {}
        self.start_values = {}
        self.errand = False
        self.released = []
        self.errands = {}
        self.no_town = {}
        self.marks = {}

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
                "TRADE_TURN_TOWN_SECONDS": TOWN_SECONDS,
                "_TRADE_TURN_SEEN": self.seen,
                "_TRADE_TURN_START": self.start_values,
                "craft_rhythm": craft_rhythm,
                "townerrand": townerrand,
                "_TOWN_ERRANDS": self.errands,
                "_TOWN_ERRAND_MARKS": self.marks,
                "_TRADE_TURN_NO_TOWN": self.no_town,
                "_town_errand_active": lambda names: self.errand,
                "_cohort_of": lambda name: "Zug",
                "bonds": types.SimpleNamespace(head_of_family=lambda: "Zug"),
            },
        )

        async def mid_run(names):
            return world.mid_run

        async def release(names, leader, slot, label):
            world.released.append((list(names), leader, slot, label))

        me = types.SimpleNamespace(
            _mid_run=mid_run,
            _town_errand_release=release,
            _town_slot="own slot",
            _cohort_town_slot=lambda key: "slot of " + key,
        )

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

    def names(self):
        """The errand's key for the Zug family."""
        return tuple(sorted(r["name"] for r in self.family("Zug")))


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


class TheTurnCountsTradeTimeInTheBridge(unittest.TestCase):
    def test_a_town_errand_holding_the_family_is_released_at_the_allowance(self):
        w = started_world()
        w.run_pass()  # the turn starts
        w.zug()["job"] = jobs.TOWN_RUN
        w.errand = True
        w.errands[w.names()] = townerrand.State(ended=7.0, phase=townerrand.GO)
        w.marks[w.names()] = {"vendor": 1.0}
        w.clock.now += TOWN_SECONDS - 10
        w.run_pass()
        self.assertEqual([], w.released, "released before the allowance was spent")
        w.clock.now += 10
        lines = w.run_pass()
        self.assertEqual(1, len(w.released), "the release path ran once")
        self.assertEqual("Zug", w.released[0][1])
        self.assertEqual(jobs.DEFAULT, w.zug()["job"], "the default job was written")
        said = [ln for ln in lines if "releases" in ln]
        self.assertEqual(1, len(said), lines)
        self.assertIn("Zug", said[0])
        self.assertIn(str(TOWN_SECONDS), said[0])
        # A later pass does not release again.
        w.clock.now += 30
        w.run_pass()
        self.assertEqual(1, len(w.released))
        # The errand is over in memory, with its marks dropped.
        self.assertFalse(w.errands[w.names()].active)
        self.assertEqual(7.0, w.errands[w.names()].ended)
        self.assertNotIn(w.names(), w.marks)

    def test_a_release_with_no_errand_in_memory_still_writes_the_default(self):
        # After a restart the errand is forgotten but the job is still town run.
        w = started_world()
        w.run_pass()
        w.zug()["job"] = jobs.TOWN_RUN
        w.errand = False
        w.turns["Zug"] = tradeturn.Turn(RUN_END, NOW, False, off=TOWN_SECONDS - 10)
        w.clock.now += 20
        w.run_pass()
        w.clock.now += 20
        w.run_pass()
        self.assertEqual(jobs.DEFAULT, w.zug()["job"])
        self.assertTrue(w.turns["Zug"].released)
        self.assertEqual({}, w.errands)

    def test_a_released_family_is_barred_from_a_new_errand_until_the_turn_ends(self):
        w = started_world()
        w.run_pass()
        w.zug()["job"] = jobs.TOWN_RUN
        w.errand = True
        w.clock.now += TOWN_SECONDS
        w.run_pass()  # releases
        self.assertIn(w.names(), w.no_town)
        # A held pass keeps it barred; a restart rebuilds it from the row.
        w.no_town.clear()
        w.zug()["job"] = jobs.DEFAULT
        w.errand = False
        w.clock.now += 30
        w.run_pass()
        self.assertIn(w.names(), w.no_town)
        # The turn ends: the bar is lifted.
        w.turns["Zug"] = tradeturn.Turn(
            RUN_END, NOW, False, counted=SECONDS - 5, off=TOWN_SECONDS, released=True
        )
        w.clock.now += 30
        w.run_pass()
        self.assertNotIn(w.names(), w.no_town)

    def test_a_turn_that_has_not_released_bars_nothing(self):
        w = started_world()
        w.run_pass()
        w.clock.now += 30
        w.run_pass()
        self.assertEqual({}, w.no_town)

    def test_a_dungeon_job_on_the_leader_mid_turn_is_sent_back_to_the_default(self):
        w = started_world()
        w.run_pass()
        w.zug()["job"] = "dungeon:ragefire"
        before = len(w.jobs)
        w.clock.now += 30
        w.run_pass()
        self.assertEqual(jobs.DEFAULT, w.zug()["job"])
        self.assertTrue(
            [j for j in w.jobs[before:] if j[1] == jobs.DEFAULT], w.jobs[before:]
        )

    def test_time_in_a_town_errand_inside_the_allowance_is_not_counted(self):
        w = started_world()
        w.run_pass()
        w.zug()["job"] = jobs.TOWN_RUN
        w.errand = True
        w.clock.now += TOWN_SECONDS - 100
        w.run_pass()
        self.assertEqual({"Zug"}, w.held, "the turn counted a town errand")
        self.assertEqual(0, w.turns["Zug"].counted)

    def test_the_end_line_states_the_seconds_and_each_trade_moved(self):
        w = started_world()
        w.run_pass()
        w.clock.now += 600
        w.run_pass()
        w.trades = {"Zug": {"Alchemy": 52}}
        w.clock.now += 600
        lines = w.run_pass()
        ends = [ln for ln in lines if "trade turn" in ln and "ends" in ln]
        self.assertEqual(1, len(ends), lines)
        self.assertIn("1200 seconds counted", ends[0])
        self.assertIn("0 seconds off a trade job", ends[0])
        self.assertIn("Zug Alchemy 40->52", ends[0])

    def test_after_a_restart_the_end_line_says_the_start_values_are_unknown(self):
        w = started_world()
        w.run_pass()
        w.seen.clear()
        w.start_values.clear()
        w.turns["Zug"] = tradeturn.Turn(
            RUN_END, NOW, False, counted=SECONDS - 10, off=30.0
        )
        w.clock.now += 20
        w.run_pass()  # first pass after the restart: no earlier pass to measure
        w.clock.now += 20
        lines = w.run_pass()
        ends = [ln for ln in lines if "trade turn" in ln and "ends" in ln]
        self.assertEqual(1, len(ends), lines)
        self.assertIn("start values are unknown", ends[0])
        self.assertIn("30 seconds off a trade job", ends[0])


class ASavedTurnKeepsItsCounts(unittest.TestCase):
    """The store through a fake connection that keeps one row per family."""

    def store(self):
        rows = {}

        class Cursor:
            def execute(self, sql, params=()):
                self.sql = sql
                if sql.startswith("INSERT"):
                    head = sql.split("(", 1)[1].split(")", 1)[0]
                    cols = [c.strip() for c in head.split(",")]
                    row = dict(zip(cols, params, strict=True))
                    rows[row["family"]] = row

            def fetchall(self):
                head = self.sql.split("SELECT ", 1)[1].split(" FROM")[0]
                cols = [c.strip() for c in head.split(",")]
                return [{c: row[c] for c in cols} for row in rows.values()]

            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return rows, Cursor

    def test_counted_time_and_allowance_used_read_back(self):
        rows, connect = self.store()
        ns = _load(
            ["_fetch_trade_turns", "_save_trade_turn"],
            {
                "campaignqueue": campaignqueue,
                "tradeturn": tradeturn,
                "_connect": connect,
                "pymysql": types.SimpleNamespace(
                    err=types.SimpleNamespace(MySQLError=OSError)
                ),
            },
        )
        saved = tradeturn.Turn(
            RUN_END, NOW, False, counted=312.5, off=90.0, released=True
        )
        ns["_save_trade_turn"]("Zug", saved)
        self.assertEqual({"Zug": saved}, ns["_fetch_trade_turns"]())


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
