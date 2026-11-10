"""A door the family stalls at twice running is left, not run a third time (#1041).

Zug's family ran Shadowfang Keep eleven times in a row on 2026-10-15 with no
clear. Every run credited the first four or six encounters, stalled there, and
ended; a new run of the same door began half a minute later. The fixtures below
are that record, rebuilt from the ticket's own quotes of the run timeline
(overseer_dungeon_run_event) for runs 590561 and 590562, with the module's
event wording (RunTimelineEvents in mod-overseer's overseer_decisions.cpp).

Pure tests against dungeonstall.py, then the bridge's queue pass driven
against a fake queue, roster and store.
"""

from datetime import datetime, timedelta
import ast
import asyncio
import pathlib
import time
import types
import unittest
from unittest.mock import patch

from _stub_modules import PYMYSQL
from test_campaign_queue import FakeWorld, _load, _Log, _q

import campaignplan  # noqa: E402
import campaignqueue  # noqa: E402
import council  # noqa: E402
import crossing  # noqa: E402
import dungeonpace  # noqa: E402
import dungeonstall as stall  # noqa: E402
import jev_family_intent  # noqa: E402
import jobs  # noqa: E402
import raidrun  # noqa: E402

SFK = 33
SWITCHED_OFF = (
    "the dungeon module refused 'dc skip' 3 inside map 33: it had switched "
    "itself off with nothing left it could reach"
)
NO_MOVEMENT = (
    "the run stopped progressing inside map 33: no boss credit and no movement "
    "for 20 minutes, and 3 'dc skip's did not restart it"
)


def ledger_row(run_id, outcome="stalled", map_id=SFK, portal="shadowfang"):
    return {
        "id": run_id,
        "map_id": map_id,
        "portal_keyword": portal,
        "outcome": outcome,
    }


def boss(run_id, before, after):
    gained = bin(after & ~before).count("1")
    return {
        "run_id": run_id,
        "kind": "boss",
        "detail": "%d encounter%s credited, %d in all (mask %d -> %d)"
        % (gained, "" if gained == 1 else "s", bin(after).count("1"), before, after),
    }


def stalled(run_id, reason):
    return {"run_id": run_id, "kind": "stalled", "detail": reason}


def skip(run_id, n):
    return {
        "run_id": run_id,
        "kind": "dc_skip",
        "detail": "'dc skip' %d issued: the run has not advanced" % n,
    }


def run_590562():
    """Run 590562's timeline as the ticket quotes it: five encounters, a sixth
    (mask 31 -> 63), three skips, then the module refusing the third because
    it had switched itself off."""
    rid = 590562
    return [
        {"run_id": rid, "kind": "phase", "detail": "IDLE -> RESET (shadowfang)"},
        boss(rid, 0, 7),
        boss(rid, 7, 31),
        boss(rid, 31, 63),
        skip(rid, 1),
        skip(rid, 2),
        skip(rid, 3),
        stalled(rid, SWITCHED_OFF),
        {"run_id": rid, "kind": "phase", "detail": "CLEARING -> EXIT"},
    ]


def run_590561():
    """The run before it: the same six encounters, then twenty minutes of
    nothing and three skips that did not restart it."""
    rid = 590561
    return [boss(rid, 0, 31), boss(rid, 31, 63), stalled(rid, NO_MOVEMENT)]


class TheTimelineSaysWhereARunStopped(unittest.TestCase):
    def test_the_mask_a_boss_row_ends_on(self):
        self.assertEqual(63, stall.mask_of(boss(1, 31, 63)["detail"]))
        self.assertIsNone(stall.mask_of("'dc skip' 1 issued: the run has not advanced"))

    def test_run_590562_stopped_after_its_sixth_encounter(self):
        got = stall.stall_of(ledger_row(590562), run_590562())
        self.assertEqual(63, got.mask)
        self.assertEqual(6, got.encounters)
        self.assertEqual(SWITCHED_OFF, got.reason)

    def test_the_module_switching_itself_off_is_named_as_the_cause(self):
        """The replay: the module switched itself off after encounter 6, and
        that is read as the door's dead end, said in words, not as a run that
        merely ran long."""
        got = stall.stall_of(ledger_row(590562), run_590562())
        self.assertTrue(got.switched_off)
        self.assertIn("switched itself off after encounter 6", got.said())
        other = stall.stall_of(ledger_row(590561), run_590561())
        self.assertFalse(other.switched_off)
        self.assertIn("after encounter 6", other.said())

    def test_a_cleared_run_did_not_stall(self):
        self.assertIsNone(stall.stall_of(ledger_row(9, "complete"), run_590561()))

    def test_a_wipe_did_not_stall(self):
        self.assertIsNone(stall.stall_of(ledger_row(9, "wipe"), []))

    def test_a_stall_before_any_boss_is_encounter_zero(self):
        got = stall.stall_of(ledger_row(9), [stalled(9, NO_MOVEMENT)])
        self.assertEqual(0, got.mask)
        self.assertIn("before its first encounter", got.said())

    def test_a_stalled_event_on_another_outcome_still_counts(self):
        """The hearth fallback can close the row under another word; the
        timeline's own 'stalled' row says what happened."""
        got = stall.stall_of(ledger_row(9, "left"), [stalled(9, NO_MOVEMENT)])
        self.assertIsNotNone(got)


def stuck(runs, events):
    return stall.stuck_doors(runs, events)


class TwoStallsRunning(unittest.TestCase):
    def test_two_stalls_at_the_same_encounter_leave_the_door(self):
        runs = [ledger_row(590561), ledger_row(590562)]
        got = stuck(runs, run_590561() + run_590562())
        self.assertEqual(["shadowfang"], sorted(got))
        why = got["shadowfang"].why
        self.assertIn("Shadowfang Keep", why)
        self.assertIn("590561", why)
        self.assertIn("590562", why)
        self.assertIn("switched itself off after encounter 6", why)

    def test_one_stall_is_not_enough(self):
        self.assertEqual({}, stuck([ledger_row(590562)], run_590562()))

    def test_a_clear_between_them_resets_the_record(self):
        runs = [ledger_row(1), ledger_row(2, "complete"), ledger_row(3)]
        events = [boss(1, 0, 63), stalled(1, NO_MOVEMENT)]
        events += [boss(3, 0, 63), stalled(3, NO_MOVEMENT)]
        self.assertEqual({}, stuck(runs, events))

    def test_a_run_that_never_got_in_does_not_break_the_pair(self):
        runs = [ledger_row(1), ledger_row(2, "staging_failed"), ledger_row(3)]
        events = [boss(1, 0, 63), stalled(1, NO_MOVEMENT)]
        events += [boss(3, 0, 63), stalled(3, SWITCHED_OFF)]
        self.assertEqual(["shadowfang"], sorted(stuck(runs, events)))

    def test_a_later_stall_further_in_is_progress(self):
        """Mask 15 then mask 63: the second run got two encounters further, so
        the door gets another run."""
        runs = [ledger_row(1), ledger_row(2)]
        events = [boss(1, 0, 15), stalled(1, NO_MOVEMENT)]
        events += [boss(2, 0, 63), stalled(2, SWITCHED_OFF)]
        self.assertEqual({}, stuck(runs, events))

    def test_a_later_stall_no_further_in_is_the_same_wall(self):
        """Mask 63 then mask 15: the family alternated between the two places
        all day, and a run that got no further than the last is no news."""
        runs = [ledger_row(1), ledger_row(2)]
        events = [boss(1, 0, 63), stalled(1, SWITCHED_OFF)]
        events += [boss(2, 0, 15), stalled(2, NO_MOVEMENT)]
        self.assertEqual(["shadowfang"], sorted(stuck(runs, events)))

    def test_each_door_is_judged_on_its_own_runs(self):
        runs = [
            ledger_row(1),
            ledger_row(2, "complete", 36, "deadmines"),
            ledger_row(3),
        ]
        events = [boss(1, 0, 63), stalled(1, NO_MOVEMENT)]
        events += [boss(3, 0, 63), stalled(3, NO_MOVEMENT)]
        self.assertEqual(["shadowfang"], sorted(stuck(runs, events)))

    def test_the_events_read_asks_only_for_the_last_two_fought_runs(self):
        runs = [ledger_row(n) for n in (1, 2, 3, 4)]
        runs.append(ledger_row(5, "staging_failed"))
        self.assertEqual([3, 4], stall.event_ids(runs))


class ActiveRunSilence(unittest.TestCase):
    def test_a_silent_family_gets_a_named_course_change_at_two_hours(self):
        got = stall.silent_run("gnomeregan", 2 * 60 * 60)
        self.assertEqual("gnomeregan", got.door)
        self.assertIn("no quest, level, gear, or boss progress event", got.why)
        self.assertIn("no stall reason recorded", got.why)

    def test_silence_does_not_trip_early_or_without_a_clock(self):
        self.assertIsNone(stall.silent_run("gnomeregan", 7199))
        self.assertIsNone(stall.silent_run("gnomeregan", None))

    def test_an_alternate_door_counts_toward_its_wing(self):
        door = next(iter(campaignplan.ALTERNATES))
        got = stall.silent_run(door, 2 * 60 * 60)
        self.assertEqual(campaignplan.wing_of(door), got.door)

    def test_a_keyword_with_no_run_is_not_a_silent_stall(self):
        self.assertIsNone(stall.silent_run("nowhere", 2 * 60 * 60))


def queue_row(qid, keyword, status="active", position=0):
    return {
        "id": qid,
        "keyword": keyword,
        "status": status,
        "position": position,
        "runs_wanted": 30,
        "source": campaignplan.SOURCE,
    }


class TheQueueLeavesTheDoor(unittest.TestCase):
    def setUp(self):
        self.stuck = stuck(
            [ledger_row(590561), ledger_row(590562)], run_590561() + run_590562()
        )

    def test_every_entry_for_the_door_is_dropped(self):
        rows = [
            queue_row(7, "shadowfang"),
            queue_row(8, "deadmines", "queued", 1),
            queue_row(9, "shadowfang", "queued", 2),
        ]
        got = stall.leave(rows, self.stuck)
        self.assertEqual("shadowfang", got.door)
        self.assertEqual((7, 9), got.drop)
        self.assertIn("Deadmines runs next", got.why)

    def test_with_nothing_after_it_the_family_quests(self):
        got = stall.leave([queue_row(7, "shadowfang")], self.stuck)
        self.assertIn("back to %s" % jobs.DEFAULT, got.why)

    def test_a_door_with_no_stall_is_left_alone(self):
        self.assertIsNone(stall.leave([queue_row(7, "deadmines")], self.stuck))

    def test_an_alternate_door_into_the_wing_counts(self):
        record = stuck(
            [
                ledger_row(1, map_id=90, portal="gnomeregan"),
                ledger_row(2, map_id=90, portal="gnomeregan-depot"),
            ],
            [stalled(1, NO_MOVEMENT), stalled(2, NO_MOVEMENT)],
        )
        got = stall.leave([queue_row(7, "gnomeregan-depot")], record)
        self.assertEqual("gnomeregan", got.door)


class ThePlannerDoesNotPickItAgain(unittest.TestCase):
    """With the queue emptied, the planner must not queue the same door."""

    HORDE = (
        {"name": "Zug", "level": 24, "race": 2, "map_id": 0, "lead": 1},
        {"name": "Oz", "level": 23, "race": 8, "map_id": 0, "lead": 0},
    )

    def facts(self, barred=None):
        return campaignplan.Facts(
            family="Zug",
            level_rows=self.HORDE,
            done={},
            failed={},
            stalled=barred,
        )

    def test_the_door_is_refused_with_the_reason(self):
        record = stuck(
            [ledger_row(590561), ledger_row(590562)], run_590561() + run_590562()
        )
        facts = self.facts(stall.barred(record))
        offered = {o.keyword for o in campaignplan.options(facts)}
        self.assertNotIn("shadowfang", offered)
        kind, why = campaignplan.refusal_kinds(facts)["shadowfang"]
        self.assertEqual(campaignplan.REFUSED_STALLED, kind)
        self.assertIn("stalled twice running", why)

    def test_unread_it_refuses_nothing(self):
        offered = {o.keyword for o in campaignplan.options(self.facts())}
        self.assertIn("shadowfang", offered)


# --- the bridge pass -----------------------------------------------------------


class StoreCursor:
    """The ledger, the timeline and the two tables the breaker writes."""

    def __init__(self, store):
        self.store = store
        self.rows = []
        self.lastrowid = 0

    def execute(self, sql, params=()):
        flat = " ".join(sql.split())
        self.store.calls.append((flat, params))
        if self.store.fail_on and self.store.fail_on in flat:
            raise RuntimeError("the store refused: %s" % flat[:40])
        self.rows = self._read(flat, params) if flat.startswith("SELECT") else []
        if not flat.startswith("SELECT"):
            self._write(flat, params)

    def _read(self, flat, params):
        store = self.store
        if flat.startswith("SELECT id, map_id, portal_keyword") or flat.startswith(
            "SELECT r.id, r.map_id, (SELECT e.portal"
        ):
            # The ledger by door: the column, or each run's timeline door.
            return [dict(r) for r in store.runs]
        if "FROM overseer_dungeon_run_event" in flat:
            return [dict(e) for e in store.events if e["run_id"] in params]
        if flat.startswith("SELECT id, TIMESTAMPDIFF(SECOND, NOW(), created_at"):
            # _stall_held: the latest stall_left row for this family and door,
            # and the seconds its hold has left (store.held_left, default the
            # whole window).
            want = tuple(params[2:5])
            left = store.held_left
            if left is None:
                left = stall.WINDOW_HOURS * 3600
            # ordered_after: the head row (params[1]) was created after the
            # leave, as the database reads it (store.ordered_after holds the
            # ids the test says were ordered later).
            later = int(params[1] in store.ordered_after)
            return [
                {"id": n, "left_s": left, "ordered_after": later}
                for n, r in reversed(list(enumerate(store.records, 1)))
                if tuple(r[:3]) == want
            ][:1]
        if flat.startswith("SELECT id, decision, door, target, queue_id"):
            # dungeonpace.OPEN_SQL: the family's open ladder row, if any.
            return [
                dict(r)
                for r in store.open_pace
                if r["family"] == params[0] and r["id"] not in store.shut
            ]
        return []

    def _write(self, flat, params):
        store = self.store
        if "SET status = 'cancelled'" in flat:
            store.world.cancel(params[0])
        elif flat.startswith("INSERT INTO overseer_dungeon_pace"):
            store.records.append(params)
            self.lastrowid = len(store.records)
        elif flat.startswith("UPDATE overseer_dungeon_pace SET closed_at"):
            store.closed.append(params)
            store.shut.add(params[1])

    def fetchall(self):
        return list(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StoreConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return StoreCursor(self.store)

    def begin(self):
        pass

    def commit(self):
        self.store.commits += 1

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StallWorld(FakeWorld):
    def __init__(self, queue, runs, events):
        super().__init__(queue)
        self.runs = runs
        self.events = events
        self.calls = []
        self.records = []
        self.closed = []
        self.shut = set()
        self.open_pace = []
        self.fail_on = ""
        self.commits = 0
        self.held_left = None
        self.ordered_after = set()
        self.hold_said = {}
        self.silent_seconds = None
        self.wedge = None
        self.dungeonquest_held = set()
        self.world = self

    def cancel(self, qid):
        for r in self.queue:
            if r["id"] == qid and r["status"] in campaignqueue.PENDING:
                r["status"] = "cancelled"

    def member_job(self, name):
        return next(
            (str(r.get("job") or "") for r in self.roster if r.get("name") == name),
            "",
        )


def _pass(world):
    """One queue pass with the stall breaker in front of the step."""
    log = _Log()
    ns = _load(
        [
            "_campaign_queue_family_once",
            "_campaign_queue_once",
            "_apply_queue_move",
            "_prune_bag_hold_stuck",
            "_queue_holds",
            "_stall_breaker",
            "_stall_step_past",
            "_stall_reads",
            "_stall_held",
            "_stall_write",
            "_silent_stall",
            "_stuck_doors",
            "_planner_rows",
        ],
        {
            "asyncio": asyncio,
            "campaignqueue": campaignqueue,
            "campaignplan": campaignplan,
            "council": council,
            "dungeonpace": dungeonpace,
            "dungeonstall": stall,
            "jobs": jobs,
            "log": log,
            "pymysql": PYMYSQL,
            "_connect": lambda: StoreConn(world),
            "_silent_seconds": lambda head_id, names: world.silent_seconds,
            "_door_wedge": lambda head, names, leader: world.wedge,
            "_jobs_of": lambda names: {n: world.member_job(n) for n in names},
            "_fetch_queue_rows": world.fetch_queue,
            "_fetch_queue_roster": world.fetch_roster,
            "_fetch_module_crossing": lambda: "",
            "crossing": crossing,
            "_mark_queue": world.mark,
            "_drive_dungeon": world.drive,
            "_drive_raid": world.drive_raid,
            "raidrun": raidrun,
            "_insert_job": world.insert_job,
            "_reset_campaign_done": world.reset,
            "_aim_family_quest": world.clear_family_quest,
            "_PACE_QUESTING": {},
            "_BAG_HOLD_STUCK": {},
            "_STALL_HOLD_SAID": world.hold_said,
            "time": time,
            "_pass_completed": lambda name: True,
        },
    )

    async def nothing(*a):
        return None

    async def no_plan(pending, fams):
        return False

    async def dungeonquest_pass(pending, fams):
        return world.dungeonquest_held

    me = types.SimpleNamespace(
        _activity_holds=lambda key=None: "",
        _campaign_owns_travel=nothing,
        _leave_town_when_done=nothing,
        _plan_campaigns=no_plan,
        _dungeonquest_pass=dungeonquest_pass,
    )
    for name in (
        "_campaign_queue_family_once",
        "_queue_holds",
        "_stall_breaker",
        "_stall_step_past",
    ):
        setattr(me, name, types.MethodType(ns[name], me))
    asyncio.run(ns["_campaign_queue_once"](me))
    return log.lines


class TheCampaignDoesNotStartAThirdRun(unittest.TestCase):
    """The acceptance criterion: two runs stalled at the same encounter, and
    the campaign does not start a third run of that dungeon, and says why."""

    def world(self, queue):
        w = StallWorld(
            queue,
            [ledger_row(590561), ledger_row(590562)],
            run_590561() + run_590562(),
        )
        for r in w.family("Zug"):
            r["job"] = "dungeon:shadowfang"
            r["dungeon_runs_done"] = 11
        return w

    def zug_jobs(self, w):
        return {r["job"] for r in w.family("Zug")}

    def test_the_door_is_left_and_the_family_quests(self):
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        lines = _pass(w)
        self.assertEqual("cancelled", w.queue[0]["status"])
        self.assertEqual({jobs.DEFAULT}, self.zug_jobs(w))
        self.assertTrue(
            [ln for ln in lines if "stalled twice running" in ln and "Zug" in ln],
            lines,
        )
        # Recorded: one pace row, closed at once, that names the door and why.
        self.assertEqual(1, len(w.records))
        family, decision, door = w.records[0][:3]
        self.assertEqual(
            ("Zug", stall.DECISION, "shadowfang"), (family, decision, door)
        )
        self.assertIn("switched itself off after encounter 6", w.records[0][7])
        self.assertEqual(1, len(w.closed))

        # The next pass does not send the family back in.
        _pass(w)
        self.assertNotIn("dungeon:shadowfang", self.zug_jobs(w))
        self.assertFalse([j for j in w.jobs if j[1] == "dungeon:shadowfang"])

    def silent_family(self, status="active"):
        w = StallWorld([_q(7, "gnomeregan", 27, status, 0)], [], [])
        for row in w.family("Zug"):
            row["job"] = "dungeon:gnomeregan"
        w.silent_seconds = 2 * 60 * 60
        return w

    def test_two_hours_without_a_progress_event_releases_the_family(self):
        w = self.silent_family()

        lines = _pass(w)

        self.assertEqual("cancelled", w.queue[0]["status"], lines)
        self.assertEqual({jobs.DEFAULT}, self.zug_jobs(w))
        self.assertIn("no stall reason recorded", w.records[0][7])
        self.assertTrue([line for line in lines if "no stall reason recorded" in line])

    def test_silent_head_is_checked_before_a_dungeon_quest_hold(self):
        w = self.silent_family()
        w.silent_seconds += 1
        w.dungeonquest_held = {w.queue[0]["family"]}

        lines = _pass(w)

        self.assertEqual("cancelled", w.queue[0]["status"], lines)
        self.assertEqual({jobs.DEFAULT}, self.zug_jobs(w))
        held_reads = [params for sql, params in w.calls if "decision = %s" in sql]
        self.assertEqual(
            [("Zug", stall.DECISION, "gnomeregan")], [p[2:5] for p in held_reads]
        )

    def test_silent_head_is_left_on_the_first_pass_at_the_bound(self):
        w = self.silent_family()
        w.silent_seconds = 2 * 60 * 60

        lines = _pass(w)

        self.assertEqual("cancelled", w.queue[0]["status"], lines)
        self.assertEqual(w.queue[0]["family"], w.records[0][0])
        self.assertEqual(w.queue[0]["id"], w.records[0][4])
        self.assertEqual({jobs.DEFAULT}, self.zug_jobs(w))

    def test_silence_needs_no_run_row_only_the_active_head(self):
        # No ledger row and no run timeline at all: the family never reached a
        # run, the shape a clock that starts from the run row cannot see.
        w = self.silent_family()
        self.assertEqual([], w.runs)
        _pass(w)
        self.assertEqual("cancelled", w.queue[0]["status"])

    def test_a_quiet_family_inside_two_hours_keeps_its_door(self):
        w = self.silent_family()
        w.silent_seconds = 2 * 60 * 60 - 1
        _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual([], w.records)

    def test_a_family_taken_off_the_dungeon_job_is_not_silent(self):
        # A hold that took the job away (town first, the bag hold) has recorded
        # its reason: the family is not sitting on a dungeon job.
        w = self.silent_family()
        for row in w.family("Zug"):
            row["job"] = "quest"
        _pass(w)
        self.assertEqual([], w.records)
        self.assertEqual("active", w.queue[0]["status"])

    def test_a_head_not_started_is_not_silent(self):
        w = self.silent_family("queued")
        _pass(w)
        self.assertEqual([], w.records)
        self.assertEqual("active", w.queue[0]["status"])

    def test_the_campaign_moves_on_to_its_next_dungeon(self):
        w = self.world(
            [_q(7, "shadowfang", 30, "active", 0), _q(8, "deadmines", 10, "queued", 1)]
        )
        _pass(w)
        self.assertEqual(["cancelled", "queued"], [r["status"] for r in w.queue])
        _pass(w)
        self.assertEqual(["cancelled", "active"], [r["status"] for r in w.queue])
        self.assertEqual({"dungeon:deadmines"}, self.zug_jobs(w))

    def test_a_door_that_stalled_once_runs_again(self):
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        w.runs = [ledger_row(590561, "complete"), ledger_row(590562)]
        _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual({"dungeon:shadowfang"}, self.zug_jobs(w))
        self.assertEqual([], w.records)

    def test_the_other_family_is_never_written(self):
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        _pass(w)
        others = {r["name"] for r in w.roster if r["family"] != "Zug"}
        self.assertFalse([j for j in w.jobs if j[0] in others])


class TheBreakerWritesInOrder(unittest.TestCase):
    """The pre-ship review's smaller findings on the breaker (#1062)."""

    world = TheCampaignDoesNotStartAThirdRun.world
    zug_jobs = TheCampaignDoesNotStartAThirdRun.zug_jobs

    def cancels(self, w):
        return [c for c in w.calls if "SET status = 'cancelled'" in c[0]]

    def test_a_failed_cancel_never_puts_the_family_on_quest(self):
        """The job moves only after the cancel and its pace row are durable:
        a write that fails leaves no quest job to flip back on the same pass."""
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        w.fail_on = "SET status = 'cancelled'"
        lines = _pass(w)
        self.assertEqual(0, w.commits)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertFalse([j for j in w.jobs if j[1] == jobs.DEFAULT], (w.jobs, lines))
        self.assertTrue([ln for ln in lines if "stall: the pass for" in ln], lines)

    def test_a_durable_cancel_puts_the_family_on_quest(self):
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        _pass(w)
        self.assertEqual(1, w.commits)
        self.assertEqual({jobs.DEFAULT}, self.zug_jobs(w))

    def test_a_requeued_stuck_door_is_cancelled_once_then_held(self):
        """The 48h window still reads the two stalls, so every later pass sees
        the door as stuck; the pace row it wrote holds it instead of cancelling
        the re-queued entry again."""
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        _pass(w)
        self.assertEqual(1, len(self.cancels(w)))
        w.queue.append(_q(9, "shadowfang", 30, "queued", 1))
        for _ in range(3):
            _pass(w)
        self.assertEqual("queued", w.queue[1]["status"])
        self.assertEqual(1, len(self.cancels(w)))
        self.assertEqual(1, len(w.records))
        self.assertFalse([j for j in w.jobs if j[1] == "dungeon:shadowfang"])

    def held_lines(self, lines):
        return [ln for ln in lines if ln.startswith("stall: ") and " held " in ln]

    def left_2h_ago(self, queue):
        """A world whose shadowfang leave was recorded 2 hours ago (#1078)."""
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        _pass(w)
        w.queue.extend(queue)
        w.held_left = (stall.WINDOW_HOURS - 2) * 3600
        return w

    def test_a_held_head_steps_the_next_entry(self):
        """#1078: a reseeded held door at the head no longer holds the whole
        queue; the next pending entry steps, and the held entry is left as it
        is (not cancelled a second time)."""
        w = self.left_2h_ago(
            [_q(9, "shadowfang", 30, "queued", 1), _q(10, "deadmines", 10, "queued", 2)]
        )
        lines = _pass(w)
        self.assertEqual(
            ["cancelled", "queued", "active"], [r["status"] for r in w.queue]
        )
        self.assertEqual({"dungeon:deadmines"}, self.zug_jobs(w))
        self.assertEqual(1, len(self.cancels(w)))
        self.assertEqual(1, len(w.records))
        self.assertTrue([ln for ln in lines if "starting" in ln], lines)

    def test_the_held_line_names_family_door_and_end_once_per_window(self):
        w = self.left_2h_ago(
            [_q(9, "shadowfang", 30, "queued", 1), _q(10, "deadmines", 10, "queued", 2)]
        )
        before = time.time()
        with patch("time.time", return_value=before):
            first = self.held_lines(_pass(w))
        self.assertEqual(1, len(first), first)
        self.assertIn("Zug", first[0])
        self.assertIn("shadowfang", first[0])
        ends = {
            time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(before + w.held_left + d))
            for d in (0, 60)
        }
        self.assertTrue([e for e in ends if e in first[0]], (ends, first))
        for _ in range(3):
            self.assertEqual([], self.held_lines(_pass(w)))
        # A new hold window (a later leave of the door) says it again.
        w.hold_said[("Zug", "shadowfang")] = -1
        self.assertEqual(1, len(self.held_lines(_pass(w))))

    def test_a_held_door_alone_in_the_queue_holds_it_and_says_so(self):
        """The pre-ship review's case: nothing left behind the held door, so
        the queue holds (no IndexError on an empty queue) and says why."""
        w = self.left_2h_ago([_q(9, "shadowfang", 30, "queued", 1)])
        lines = _pass(w)
        self.assertFalse([ln for ln in lines if "failed" in ln], lines)
        self.assertEqual("queued", w.queue[1]["status"])
        self.assertFalse([j for j in w.jobs if j[1] == "dungeon:shadowfang"])
        held = self.held_lines(lines)
        self.assertEqual(1, len(held), lines)
        self.assertIn("nothing else", held[0])

    def test_an_operator_order_given_after_the_leave_runs(self):
        """#2033: the operator re-ordered the left door after its leave; that
        order is not stepped past, it starts on its own record."""
        later = dict(_q(9, "shadowfang", 30, "queued", 1), source="web:overseer")
        w = self.left_2h_ago([later, _q(10, "deadmines", 10, "queued", 2)])
        w.ordered_after = {9}
        w.runs = []
        w.events = []
        lines = _pass(w)
        self.assertEqual(
            ["cancelled", "active", "queued"], [r["status"] for r in w.queue]
        )
        self.assertEqual({"dungeon:shadowfang"}, self.zug_jobs(w))
        self.assertEqual([], self.held_lines(lines), lines)

    def test_a_silent_operator_order_earns_its_own_leave(self):
        """The same order, silent for two hours on its own: a fresh leave is
        written for it rather than the old hold stepping past it."""
        later = dict(_q(9, "shadowfang", 30, "active", 1), source="web:overseer")
        w = self.left_2h_ago([later, _q(10, "deadmines", 10, "queued", 2)])
        w.ordered_after = {9}
        w.queue[0]["status"] = "cancelled"
        w.runs = []
        w.events = []
        w.silent_seconds = 2 * 3600 + 5
        for row in w.family("Zug"):
            row["job"] = "dungeon:shadowfang"
        _pass(w)
        self.assertEqual("cancelled", w.queue[1]["status"])
        self.assertEqual(2, len(w.records))

    def test_an_older_order_or_the_overseers_entry_stays_held(self):
        for source, ordered_after in (
            ("web:overseer", set()),
            ("overseer:planner", {9}),
        ):
            with self.subTest(source=source):
                row = dict(_q(9, "shadowfang", 30, "queued", 1), source=source)
                w = self.left_2h_ago([row, _q(10, "deadmines", 10, "queued", 2)])
                w.ordered_after = ordered_after
                _pass(w)
                self.assertEqual(
                    ["cancelled", "queued", "active"], [r["status"] for r in w.queue]
                )
                self.assertEqual({"dungeon:deadmines"}, self.zug_jobs(w))

    def test_a_cancelled_entry_closes_its_step_down_pace_row(self):
        w = self.world([_q(7, "shadowfang", 30, "active", 0)])
        w.open_pace = [
            {
                "id": 41,
                "family": "Zug",
                "decision": "step_down",
                "door": "shadowfang",
                "target": "deadmines",
                "queue_id": 7,
            },
        ]
        _pass(w)
        self.assertIn(("left", 41), w.closed)
        self.assertEqual(1, w.commits)


BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


class TheHoldReadKnowsTheOrder(unittest.TestCase):
    def test_the_hold_read_compares_the_heads_creation_with_the_leave(self):
        read = BRIDGE[BRIDGE.index("def _stall_held(") :]
        read = read[: read.index("\ndef ", 10)]
        self.assertIn("WHERE q.id = %s) > created_at, 0) AS ordered_after", read)
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        body = body[: body.index("\n    async def ", 10)]
        self.assertIn('_stall_held, key, leave.door, int(rows[0]["id"])', body)
        self.assertIn("dungeonstall.order_outlives(rows[0], held)", body)

    def test_order_outlives_is_the_operators_later_order_only(self):
        held = {"id": 1, "left_s": 100, "ordered_after": 1}
        self.assertTrue(stall.order_outlives({"source": "web:overseer"}, held))
        self.assertFalse(stall.order_outlives({"source": "overseer:planner"}, held))
        self.assertFalse(stall.order_outlives({"source": ""}, held))
        self.assertFalse(
            stall.order_outlives(
                {"source": "web:overseer"}, dict(held, ordered_after=0)
            )
        )
        self.assertFalse(stall.order_outlives({"source": "web:overseer"}, None))


class TheBridgeOrder(unittest.TestCase):
    def test_the_breaker_runs_before_the_ladder_and_the_gear_hold(self):
        holds = BRIDGE[BRIDGE.index("    async def _queue_holds(") :]
        self.assertLess(holds.index("_stall_breaker"), holds.index("_dungeon_pace"))

    def test_the_breaker_does_not_wait_for_the_family_to_be_outside(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        body = body[: body.index("\n    async def ", 10)]
        self.assertNotIn("_mid_run", body)

    def test_the_cancel_is_durable_before_the_job_moves(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        self.assertLess(body.index("_stall_write"), body.index("_apply_queue_move"))

    def silence_read(self):
        read = BRIDGE[BRIDGE.index("def _silent_seconds(") :]
        return read[: read.index("\ndef ", 10)]

    def test_silence_uses_progress_events_and_the_two_hour_rule(self):
        read = self.silence_read()
        self.assertIn("TIMESTAMPDIFF(SECOND", read)
        self.assertIn("'level_up'", read)
        self.assertIn("'item_equip'", read)
        self.assertIn("re.kind = 'boss'", read)
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        body = body[: body.index("\n    async def ", 10)]
        self.assertIn("_silent_stall", body)
        helper = BRIDGE[BRIDGE.index("def _silent_stall(") :]
        helper = helper[: helper.index("\ndef ", 10)]
        self.assertIn("_silent_seconds", helper)
        self.assertIn("dungeonstall.silent_run", helper)

    def test_a_boss_credit_written_again_is_not_progress(self):
        # wow-overseer#2147: a party sealed in a finished dungeon loops
        # EXIT -> IDLE -> CLEARING, and every pass writes the same boss row
        # ("N encounters credited, N in all") again. Counting the newest boss
        # row reset the clock on every pass for as long as the loop ran. Only
        # the first sighting of a credit on a run is progress.
        read = self.silence_read()
        boss = read[read.index("re.kind = 'boss'") :]
        self.assertIn("NOT EXISTS", boss)
        self.assertIn("p.run_id = re.run_id", boss)
        self.assertIn("p.detail = re.detail", boss)
        self.assertIn("p.id < re.id", boss)

    def test_a_quest_written_again_is_not_progress(self):
        # wow-overseer#2147: one overseer_event row per character and quest
        # moves last_seen on each repeat, so a bot accepting and completing
        # the same quest every hour held the clock near zero. The quest kinds
        # are timed by first_seen; the other kinds stay on last_seen.
        read = self.silence_read()
        self.assertNotIn("MAX(e.last_seen)", read)
        quest = read[read.index("CASE WHEN e.kind IN") :]
        quest = quest[: quest.index("FROM overseer_event e")]
        for kind in ("'quest_accept'", "'quest_complete'", "'quest_reward'"):
            self.assertIn(kind, quest)
        self.assertIn("THEN e.first_seen END) ELSE e.last_seen END", quest)

    def test_a_quest_row_in_a_later_hour_bucket_is_not_progress(self):
        # wow-overseer#2147 round 2: overseer_event keeps one row per
        # character, kind, subject AND hour bucket, so the same quest written
        # each hour is a NEW row with its own first_seen (#2165's first_seen
        # read still moved hourly). A quest row counts only when no earlier
        # row exists for the same character, kind and subject inside the
        # head's window; a first-time quest has none and counts.
        read = self.silence_read()
        quest = read[read.index("CASE WHEN e.kind IN") :]
        quest = quest[: quest.index("FROM overseer_event e")]
        self.assertIn("NOT EXISTS", quest)
        self.assertIn("FROM overseer_event p", quest)
        self.assertIn("p.character_name = e.character_name", quest)
        self.assertIn("p.kind = e.kind", quest)
        self.assertIn("p.subject_id = e.subject_id", quest)
        self.assertIn("p.id < e.id", quest)
        self.assertIn("p.first_seen >= COALESCE(q.started_at, q.created_at)", quest)
        # the #2165 first_seen read and the #2148 boss NOT EXISTS stay
        self.assertIn("THEN e.first_seen END) ELSE e.last_seen END", quest)
        boss = read[read.index("re.kind = 'boss'") :]
        self.assertIn("p.id < re.id", boss)

    def test_the_silence_clock_starts_at_the_head_not_at_a_run(self):
        # The stuck read's clock runs across runs. A clock restarted by each
        # run opening never reaches two hours on a campaign of short runs,
        # and an active-run filter or the portal_keyword column blinds it.
        read = self.silence_read()
        self.assertIn("COALESCE(q.started_at, q.created_at)", read)
        self.assertNotIn("r.state = 'active'", read)
        self.assertNotIn("GREATEST(r.started_at", read)
        self.assertNotIn("portal_keyword", read)

    def test_silent_run_event_read_keeps_the_name_index_usable(self):
        # wow-overseer#1513: overseer_event.character_name is
        # utf8mb4_unicode_ci and indexed (idx_character_last_seen). A COLLATE
        # on the column makes MySQL scan the table; collate the names instead.
        read = self.silence_read()
        self.assertIn(
            "e.character_name IN (%s COLLATE utf8mb4_unicode_ci{more_names})", read
        )
        self.assertIn('", %s COLLATE utf8mb4_unicode_ci" * (len(names) - 1)', read)
        self.assertNotIn("character_name COLLATE", read)

    def test_the_silent_run_threshold_is_two_hours(self):
        self.assertEqual(stall.NO_PROGRESS_AFTER.total_seconds(), 2 * 3600)

    def test_the_ladder_never_steps_to_a_stuck_door(self):
        facts = BRIDGE[BRIDGE.index("    async def _pace_facts(") :]
        facts = facts[: facts.index("\n    async def ", 10)]
        self.assertIn('avoid={head_kw} | reads["stuck"]', facts)
        self.assertIn('avoid={door} | reads["stuck"]', facts)


if __name__ == "__main__":
    unittest.main()


# 2026-11-08, wow-dev: an operator re-queued Grug's family on Blackrock Depths
# x20 at 07:47:12Z (queue row 149) and the bridge cancelled it 45 seconds later
# for two stalls (runs 1643433 and 1649476) that both began before the order
# and before the healer-mana fix. (#2058)
class AnOperatorsOrderIsJudgedOnRunsAfterIt(unittest.TestCase):
    BRD = campaignplan.BY_KEYWORD["blackrock-depths"].map_id
    GERSTAHN = "dungeon clear stopped: RepeatedTimeout at High Interrogator Gerstahn after 180s"

    def runs(self, *starts):
        return [
            {
                "id": 1643433 + i,
                "map_id": self.BRD,
                "portal_keyword": "blackrock-depths",
                "outcome": "stalled",
                "started_at": at,
            }
            for i, at in enumerate(starts)
        ]

    def events(self, runs):
        return [stalled(r["id"], self.GERSTAHN) for r in runs]

    def head(self, source, created):
        return {
            "id": 149,
            "keyword": "blackrock-depths",
            "source": source,
            "created_at": created,
        }

    def judged(self, source, created, *starts):
        runs = self.runs(*starts)
        runs = stall.since_order(runs, self.head(source, created))
        return stall.stuck_doors(runs, self.events(self.runs(*starts)))

    def test_stalls_before_an_operators_order_do_not_cancel_it(self):
        got = self.judged("web:overseer", 100, 10, 50)
        self.assertEqual({}, got)

    def test_stalls_after_an_operators_order_still_leave_the_door(self):
        got = self.judged("web:overseer", 100, 110, 150)
        self.assertEqual(["blackrock-depths"], sorted(got))

    def test_one_stall_before_and_one_after_is_not_two_running(self):
        self.assertEqual({}, self.judged("web:overseer", 100, 50, 150))

    def test_the_overseers_own_entry_is_judged_on_the_whole_window(self):
        got = self.judged("overseer:planner", 100, 10, 50)
        self.assertEqual(["blackrock-depths"], sorted(got))

    def test_the_sql_reads_when_each_run_began(self):
        self.assertIn("started_at", stall.RUNS_SQL)
        self.assertIn(
            "r.outcome, r.started_at, r.ended_at FROM", stall.RUNS_SQL_TIMELINE
        )
        self.assertIn("ended_at", stall.RUNS_SQL)

    def test_the_breaker_reads_with_the_head_it_judges(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        self.assertIn("_stall_reads, names, rows[0]", body.split("leave =")[0])


# 2026-11-08, wow-dev: Grug's x40 Blackrock Depths order (row 155) was
# cancelled at 19:51Z because run 1676285 stalled 65 seconds after it opened,
# five seconds after the run before it ended split_failed. (#2092)
class ARunThatNeverGotInIsNotAStall(unittest.TestCase):
    BRD = campaignplan.BY_KEYWORD["blackrock-depths"].map_id
    LORE = "dungeon clear stopped: RepeatedTimeout at Lord Incendius after 180s"

    def row(self, rid, outcome, seconds, started=1000):
        begun = datetime(2026, 11, 8, 19, 0) + timedelta(seconds=started + rid)
        return {
            "id": rid,
            "map_id": self.BRD,
            "portal_keyword": "blackrock-depths",
            "outcome": outcome,
            "started_at": begun,
            "ended_at": None if seconds is None else begun + timedelta(seconds=seconds),
        }

    def judged(self, later_seconds):
        runs = [
            self.row(1665107, "stalled", 5000),
            self.row(1671027, "split_failed", 5760),
            self.row(1676285, "stalled", later_seconds),
        ]
        events = [stalled(1665107, self.LORE), stalled(1676285, self.LORE)]
        return stall.stuck_doors(runs, events)

    def test_a_65_second_stall_does_not_make_two_running(self):
        self.assertEqual({}, self.judged(65))

    def test_a_stall_after_three_minutes_still_does(self):
        self.assertEqual(["blackrock-depths"], sorted(self.judged(180)))

    def test_a_stall_with_no_end_time_still_counts(self):
        self.assertEqual(["blackrock-depths"], sorted(self.judged(None)))

    def test_the_events_read_skips_the_non_entry(self):
        runs = [self.row(1, "stalled", 5000), self.row(2, "stalled", 65)]
        self.assertEqual([1], stall.event_ids(runs))


class TheWedgeAtTheDoor(unittest.TestCase):
    """#2151's three shapes, as pure verdicts. The two-stall rule judges runs
    that ENDED and the silence rule a family nothing happened to; a run that
    stays open with the party split across its door is neither, so it was
    never left. These judge the open run itself: the leader's walk, the
    members' holds, and a member dead at the door."""

    def test_a_walk_that_restarts_past_the_bound_leaves_the_door(self):
        got = stall.door_unreachable("maraudon-orange", 38)
        self.assertIsNotNone(got)
        self.assertEqual("maraudon-orange", got.door)
        self.assertIn("restarted 38 times", got.why)

    def test_a_walk_at_the_bound_leaves_and_one_under_it_does_not(self):
        self.assertIsNotNone(stall.door_unreachable("shadowfang", stall.RESTART_BOUND))
        self.assertIsNone(stall.door_unreachable("shadowfang", stall.RESTART_BOUND - 1))

    def test_an_unreachable_verdict_needs_a_real_door_and_a_count(self):
        self.assertIsNone(stall.door_unreachable("nowhere", 500))
        self.assertIsNone(stall.door_unreachable("shadowfang", None))

    def test_a_member_held_on_an_errand_past_the_bound_leaves_the_door(self):
        got = stall.party_held(
            "shadowfang", "Bork", "on an errand of its own", stall.HOLD_SECONDS
        )
        self.assertIsNotNone(got)
        self.assertEqual("shadowfang", got.door)
        self.assertIn("Bork", got.why)
        self.assertIn("errand", got.why)

    def test_a_member_held_briefly_is_left_alone(self):
        self.assertIsNone(
            stall.party_held(
                "shadowfang", "Bork", "on an errand of its own", stall.HOLD_SECONDS - 1
            )
        )

    def test_a_member_dead_at_the_door_past_the_bound_leaves_the_door(self):
        got = stall.member_dead("dire-maul-east-east", "Zrog", stall.DEAD_SECONDS)
        self.assertIsNotNone(got)
        self.assertEqual("dire-maul-east-east", got.door)
        self.assertIn("Zrog", got.why)
        self.assertIn("dead", got.why)

    def test_a_member_dead_briefly_is_left_alone(self):
        """A death the party is still recovering from is the module's work:
        the breaker speaks only once the run has plainly failed to recover
        the member itself."""
        self.assertIsNone(
            stall.member_dead("shadowfang", "Zrog", stall.DEAD_SECONDS - 1)
        )


class TheWedgeIsLeftLikeAStall(unittest.TestCase):
    """The breaker's leave for a wedge is the stall leave: the door's queue
    entries are cancelled, the reason is recorded in a pace row, and the
    family goes on the default job, which stands the run coordinator down
    and walks the party out (#2151)."""

    def wedged_world(self):
        w = StallWorld([_q(7, "maraudon-orange", 23, "active", 0)], [], [])
        for row in w.family("Zug"):
            row["job"] = "dungeon:maraudon-orange"
        w.wedge = stall.door_unreachable("maraudon-orange", 38)
        return w

    def test_the_family_is_stood_down_and_the_reason_names_the_restarts(self):
        w = self.wedged_world()
        lines = _pass(w)
        self.assertEqual("cancelled", w.queue[0]["status"])
        self.assertEqual({jobs.DEFAULT}, {r["job"] for r in w.family("Zug")})
        self.assertEqual(1, len(w.records))
        family, decision, door = w.records[0][:3]
        self.assertEqual(
            ("Zug", stall.DECISION, "maraudon-orange"), (family, decision, door)
        )
        self.assertIn("restarted 38 times", w.records[0][7])
        self.assertTrue([ln for ln in lines if "restarted 38 times" in ln], lines)

    def test_no_wedge_no_leave(self):
        w = self.wedged_world()
        w.wedge = None
        _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual([], w.records)


class TheWedgeLeaveIsNotSteppedPast(unittest.TestCase):
    """The held-door step-past (#1078) exists for a door left on ended runs
    and then re-queued: the re-queued entry is not cancelled a second time
    on stale evidence. A wedge verdict is not stale evidence. It is judged
    fresh each pass on the run open now (an active head, a walk restarting
    now, members held now), so stepping past it leaves that run open past
    every bound for as long as the earlier leave is in its window. Run
    1690476 sat open for 25 hours that way (#2191): the entry was never
    cancelled and the family never stood down, until the module's own
    hearth recovery ended the run."""

    def world(self):
        w = StallWorld([_q(7, "maraudon-orange", 23, "active", 0)], [], [])
        for row in w.family("Zug"):
            row["job"] = "dungeon:maraudon-orange"
        w.wedge = stall.door_unreachable("maraudon-orange", 33)
        return w

    def test_the_first_wedge_leave_cancels_and_records(self):
        w = self.world()
        _pass(w)
        self.assertEqual("cancelled", w.queue[0]["status"])
        self.assertEqual(1, len(w.records))
        self.assertEqual({jobs.DEFAULT}, {r["job"] for r in w.family("Zug")})

    def test_a_wedged_run_open_inside_the_hold_is_left_anyway(self):
        w = self.world()
        _pass(w)
        # The door is re-engaged under a new entry, its run is open, and it
        # wedges again while the first leave's hold is still in its window.
        w.queue.append(_q(9, "maraudon-orange", 23, "active", 1))
        for row in w.family("Zug"):
            row["job"] = "dungeon:maraudon-orange"
        w.held_left = (stall.WINDOW_HOURS - 2) * 3600
        _pass(w)
        self.assertEqual("cancelled", w.queue[1]["status"])
        self.assertEqual(2, len(w.records))
        self.assertIn("restarted 33 times", w.records[1][7])
        self.assertEqual({jobs.DEFAULT}, {r["job"] for r in w.family("Zug")})


class TheDoorWedgeReads(unittest.TestCase):
    """The bridge's wedge judge (_door_wedge), loaded the way the breaker
    harness loads its neighbours: the evidence read and the clock are fakes,
    the verdicts are dungeonstall's own."""

    HEAD = {"id": 7, "keyword": "maraudon-orange", "status": "active"}

    def judge(self, evidence, clock):
        self.asked = []
        ns = _load(
            ["_door_wedge", "_door_wedge_ages"],
            {
                "campaignqueue": campaignqueue,
                "dungeonstall": stall,
                "jobs": jobs,
                "time": types.SimpleNamespace(monotonic=lambda: clock[0]),
                "_jobs_of": lambda names: {n: "dungeon:maraudon-orange" for n in names},
                "_door_wedge_evidence": lambda leader, head_id: (
                    self.asked.append((leader, head_id)) or evidence
                ),
                "_DOOR_HOLD_SINCE": {},
            },
        )
        return ns["_door_wedge"]

    def member(self, name, state):
        return jev_family_intent.Member(name, state, "0")

    def test_restarts_past_the_bound_are_a_verdict_on_the_first_pass(self):
        judge = self.judge((38, ()), [1000.0])
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("restarted 38 times", got.why)

    def test_the_walk_is_counted_for_the_queue_entry_being_judged(self):
        judge = self.judge((0, ()), [1000.0])
        judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertEqual([("Zug", 7)], self.asked)

    def test_the_steps_read_bounds_the_walk_by_when_the_run_started(self):
        sql = next(
            ast.literal_eval(node.value)
            for node in ast.parse(BRIDGE).body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "_DOOR_STEPS_SQL" for t in node.targets)
        )
        self.assertIn("started_at", sql)
        self.assertEqual(2, sql.count("%s"))

    def test_an_errand_hold_becomes_a_verdict_only_past_its_bound(self):
        clock = [1000.0]
        judge = self.judge(
            (0, (self.member("Uzza", "on an errand of its own"),)), clock
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.HOLD_SECONDS
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("Uzza", got.why)

    def test_a_dead_member_becomes_a_verdict_past_the_shorter_bound(self):
        clock = [1000.0]
        judge = self.judge((0, (self.member("Uzza", "dead"),)), clock)
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.DEAD_SECONDS
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("dead", got.why)

    def test_a_hold_that_clears_and_returns_starts_a_new_clock(self):
        clock = [1000.0]
        box = [(0, (self.member("Uzza", "on an errand of its own"),))]
        ns = _load(
            ["_door_wedge", "_door_wedge_ages"],
            {
                "campaignqueue": campaignqueue,
                "dungeonstall": stall,
                "jobs": jobs,
                "time": types.SimpleNamespace(monotonic=lambda: clock[0]),
                "_jobs_of": lambda names: {n: "dungeon:maraudon-orange" for n in names},
                "_door_wedge_evidence": lambda leader, head_id: box[0],
                "_DOOR_HOLD_SINCE": {},
            },
        )
        judge = ns["_door_wedge"]
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.HOLD_SECONDS - 1
        box[0] = (0, (self.member("Uzza", "following"),))
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        box[0] = (0, (self.member("Uzza", "on an errand of its own"),))
        clock[0] += 2
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))

    def test_a_new_head_starts_new_clocks(self):
        """A hold timed under one queue entry must not hang the next entry
        for the same door: the entry is the attempt being judged."""
        clock = [1000.0]
        judge = self.judge(
            (0, (self.member("Uzza", "on an errand of its own"),)), clock
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.HOLD_SECONDS + 1
        self.assertIsNone(judge(dict(self.HEAD, id=8), ["Zug", "Uzza"], "Zug"))

    def test_no_verdict_without_a_started_dungeon_head(self):
        judge = self.judge((38, ()), [1000.0])
        self.assertIsNone(
            judge(dict(self.HEAD, status="queued"), ["Zug", "Uzza"], "Zug")
        )
