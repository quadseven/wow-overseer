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
import json
import pathlib
import time
import types
import unittest
from unittest.mock import patch

import claims
from _stub_modules import PYMYSQL
from test_campaign_queue import FakeWorld, _load, _Log, _q
from test_errand_recall_loop import bag_pressure_pass, vendor_pass_release

import bag_pressure  # noqa: E402
import campaignplan  # noqa: E402
import campaignqueue  # noqa: E402
import council  # noqa: E402
import crossing  # noqa: E402
import dungeonpace  # noqa: E402
import dungeonstall as stall  # noqa: E402
import errandgate  # noqa: E402
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


CLEARED = (
    "dungeon clear stopped: All bosses cleared!; it refused 'dc skip' 1 inside "
    "map 229 with nothing left it could reach"
)


class AFinishedClearIsNotAStall(unittest.TestCase):
    """The Lower Spire shares map 229 with the Upper Spire, so a run there never
    reads 'complete': the module clears every boss it can reach, says "All
    bosses cleared!" and the ledger closes the row 'stalled'. Two such runs
    barred the one door that drops the fire protection recipe (the Firebrand
    Invokers), for two days, after the family had cleared it twice."""

    LBRS = dict(map_id=229, portal="lower-blackrock-spire")

    def test_a_clear_the_module_finished_did_not_stall(self):
        events = [boss(7, 0, 491), stalled(7, CLEARED)]
        self.assertIsNone(stall.stall_of(ledger_row(7, **self.LBRS), events))

    def test_two_finished_clears_do_not_bar_the_door(self):
        runs = [ledger_row(1, **self.LBRS), ledger_row(2, **self.LBRS)]
        events = [boss(1, 0, 491), stalled(1, CLEARED)]
        events += [boss(2, 0, 491), stalled(2, CLEARED)]
        self.assertEqual({}, stuck(runs, events))

    def test_a_finished_clear_with_no_encounter_is_still_a_stall(self):
        got = stall.stall_of(ledger_row(7, **self.LBRS), [stalled(7, CLEARED)])
        self.assertIsNotNone(got)

    def test_a_ledger_row_closed_stalled_by_a_clear_counts_as_a_completed_run(self):
        rows = [
            {
                "leader_name": "Zug",
                "map_id": 229,
                "portal_keyword": "lower-blackrock-spire",
                "outcome": "stalled",
                "ended_reason": CLEARED,
            },
            {
                "leader_name": "Zug",
                "map_id": 229,
                "portal_keyword": "lower-blackrock-spire",
                "outcome": "stalled",
                "ended_reason": "the run stopped progressing",
            },
        ]
        done, failed = campaignplan.ledger(rows, ["Zug"])
        self.assertEqual({"lower-blackrock-spire": 1}, done)
        self.assertEqual({"lower-blackrock-spire": 1}, failed)


REFUSED_109 = (
    "dungeon clear stopped: it refused 'dc skip' 1 inside map 109 with "
    "nothing left it could reach"
)


class AReachableClearWithAnOptionalBossLeftIsNotAStall(unittest.TestCase):
    """Map 109 credits eight encounters (bits 0, 1, 2, 3, 5, 6, 7, 8; there
    is no bit 4), and bit 7 is an optional encounter a party may be unable
    to start at all. A run that credits every other encounter (mask 367)
    and ends on the module's refusal, because nothing left could be
    reached, finished everything it could reach: it did not stall, and
    two such runs must not bar the door (#2740)."""

    ST = dict(map_id=109, portal="sunken-temple")

    def test_a_run_missing_only_the_optional_encounter_did_not_stall(self):
        events = [boss(7, 0, 367), stalled(7, REFUSED_109)]
        self.assertIsNone(stall.stall_of(ledger_row(7, **self.ST), events))

    def test_two_reachable_clears_do_not_bar_the_door(self):
        runs = [ledger_row(1, **self.ST), ledger_row(2, **self.ST)]
        events = [boss(1, 0, 367), stalled(1, REFUSED_109)]
        events += [boss(2, 0, 367), stalled(2, REFUSED_109)]
        self.assertEqual({}, stuck(runs, events))

    def test_a_run_missing_a_required_encounter_still_stalls(self):
        """Mask 303 is mask 367 without bit 6, a required encounter: the
        same refusal text does not finish that run."""
        events = [boss(7, 0, 303), stalled(7, REFUSED_109)]
        got = stall.stall_of(ledger_row(7, **self.ST), events)
        self.assertIsNotNone(got)
        self.assertEqual(303, got.mask)

    def test_the_reachable_mask_alone_does_not_finish_a_run(self):
        """A run that credited every reachable encounter but stopped for
        another reason (no movement) still stalled: the refusal text is
        part of the shape, not decoration."""
        events = [boss(7, 0, 367), stalled(7, NO_MOVEMENT)]
        self.assertIsNotNone(stall.stall_of(ledger_row(7, **self.ST), events))


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

    def test_the_reason_says_what_the_family_was_doing(self):
        got = stall.silent_run(
            "gnomeregan", 2 * 60 * 60, "jobs now town run; last written by errand"
        )
        self.assertIn("jobs now town run; last written by errand", got.why)

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
        if flat.startswith(
            "SELECT COUNT(*) AS n FROM overseer_dungeon_pace WHERE family = %s"
        ):
            # _order_holds: holds of the order with no run formed since.
            return [{"n": getattr(store, "order_holds", 0)}]
        if flat.startswith(
            "SELECT id, created_at, TIMESTAMPDIFF(SECOND, NOW(), created_at"
        ):
            # _order_parked: the newest ORDER_DECISION row for this family and
            # door, with the backoff seconds left (store.park_left, default a
            # full backoff) and when it was written (store.park_at).
            want = tuple(params[2:5])
            left = store.park_left
            if left is None:
                left = int(stall.ORDER_BACKOFF.total_seconds())
            return [
                {
                    "id": n,
                    "created_at": store.park_at,
                    "left_s": left,
                    "ordered_after": int(params[1] in store.ordered_after),
                    "target": r[3],
                }
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
        self.park_left = None
        self.park_at = None
        self.order_holds = 0
        self.ordered_after = set()
        self.hold_said = {}
        self.stood_down = {}
        self.hold_lines = []
        self.silent_seconds = None
        self.wedge = None
        self.dungeonquest_held = set()
        self.positions = {}
        self.regroup_spent = {}
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
            "_mc_requeue",
            "_apply_queue_move",
            "_prune_bag_hold_stuck",
            "_queue_holds",
            "_stall_breaker",
            "_stall_step_past",
            "_stall_reads",
            "_stall_held",
            "_order_parked",
            "_order_holds",
            "_order_hold",
            "_order_step_past",
            "_regroup_wait",
            "_stall_write",
            "_silent_stall",
            "_job_story",
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
            "_OFF_DUNGEON_JOB_AT": {},
            "_door_wedge": lambda head, names, leader: world.wedge,
            "_jobs_of": lambda names: {n: world.member_job(n) for n in names},
            "_last_job_source": lambda name: "town-errand",
            "_STALL_STOOD_DOWN": world.stood_down,
            "_say_queue_hold": lambda key, hold, why="": world.hold_lines.append(
                (hold, why)
            ),
            "_fetch_positions": lambda names: dict(world.positions),
            "_REGROUP_SPENT": world.regroup_spent,
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
        _claims=claims.Claims(),
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
        "_order_step_past",
        "_order_hold",
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

    def test_the_silent_stand_down_records_what_the_family_was_doing(self):
        w = self.silent_family()

        _pass(w)

        reason = w.records[0][7]
        self.assertIn("jobs now dungeon:gnomeregan", reason)
        self.assertIn("last written by town-errand", reason)
        # Kept where the queue's hold is said, not only in the pace row.
        self.assertEqual(reason[:255], w.stood_down[w.queue[0]["family"]][:255])
        # And the queue's hold line says it.
        self.assertIn(
            ("stall breaker", w.stood_down[w.queue[0]["family"]]), w.hold_lines
        )

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
        # Held, never cancelled (#2216): the order stays pending and its own
        # hold is written.
        self.assertEqual("active", w.queue[1]["status"])
        self.assertEqual(2, len(w.records))
        self.assertEqual(stall.ORDER_DECISION, w.records[1][1])

    def test_an_older_overseer_entry_stays_held(self):
        row = dict(_q(9, "shadowfang", 30, "queued", 1), source="overseer:planner")
        w = self.left_2h_ago([row, _q(10, "deadmines", 10, "queued", 2)])
        w.ordered_after = {9}
        _pass(w)
        self.assertEqual(
            ["cancelled", "queued", "active"], [r["status"] for r in w.queue]
        )
        self.assertEqual({"dungeon:deadmines"}, self.zug_jobs(w))

    def test_an_older_operator_order_is_held_not_barred_for_the_window(self):
        """#2216: the old leave's 48 hour hold never applies to an operator's
        order; it is held for the short backoff, never cancelled."""
        row = dict(_q(9, "shadowfang", 30, "queued", 1), source="web:overseer")
        w = self.left_2h_ago([row, _q(10, "deadmines", 10, "queued", 2)])
        _pass(w)
        self.assertEqual("queued", w.queue[1]["status"])
        self.assertEqual(stall.ORDER_DECISION, w.records[-1][1])

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


class AMemberInsideAnInstanceIsNeverGivenAnErrand(unittest.TestCase):
    """#2280: run 1853482 (Blackrock Depths): the vendor aim taken at the door
    stayed on the tank, the clear stopped, and the module walked the tank out
    of the dungeon to a vendor; it died on the way and the run was left
    without its tank. A member on an instance map is not aimed out, and an
    economy aim it already carries is handed back."""

    NAMES = ("Grug", "Bork", "Grog")
    POSITIONS = {
        "Grug": {"map_id": 230, "pos_x": 0.0, "pos_y": 0.0},
        "Bork": {"map_id": 230, "pos_x": 2000.0, "pos_y": 0.0},
        "Grog": {"map_id": 230, "pos_x": 1400.0, "pos_y": 0.0},
    }
    SLOTS = {"Grug": 13, "Bork": 2, "Grog": 0}

    def aims(self, inside):
        return bag_pressure.stranded_vendor_aims(
            self.NAMES,
            "Grug",
            self.POSITIONS,
            self.SLOTS,
            pressure=True,
            in_run=False,
            inside=inside,
        )

    def test_a_member_inside_the_instance_is_not_aimed_at_a_vendor(self):
        """Fails before the change: both cut-off members were aimed."""
        self.assertEqual(("Bork", "Grog"), self.aims(frozenset()))
        self.assertEqual(("Grog",), self.aims(frozenset({"Bork"})))
        self.assertEqual((), self.aims(frozenset({"Bork", "Grog"})))

    def test_inside_is_read_from_the_fresh_map_of_each_member(self):
        maps = {"Grug": 230, "Bork": 0, "Grog": 409}
        got = bag_pressure.members_inside_instance(self.NAMES, maps, {230, 409})
        self.assertEqual(frozenset({"Grug", "Grog"}), got)
        self.assertEqual(
            frozenset(),
            bag_pressure.members_inside_instance(self.NAMES, None, {230}),
        )

    def test_the_bridge_reads_who_is_inside_before_aiming(self):
        """The pass is run with the bridge's own helpers beside it (#2323);
        it was pinned as text, which a renamed helper passed."""
        self.assertEqual((2, ["Bork", "Grog"]), bag_pressure_pass())
        self.assertEqual((1, ["Grog"]), bag_pressure_pass(maps={"Bork": 230}))
        self.assertEqual((0, []), bag_pressure_pass(maps={"Bork": 230, "Grog": 230}))

    def release(self, aims, maps):
        released = []
        fakes = {
            "bag_pressure": bag_pressure,
            "dungeonpath": types.SimpleNamespace(PORTAL_MAPS={"brd": 230}),
            "raidrun": types.SimpleNamespace(MAPS={}),
            "log": types.SimpleNamespace(info=lambda *a, **k: None),
            "_fetch_live_maps": lambda names: {n: maps[n] for n in names if n in maps},
            "_current_travel_npc": lambda name: aims.get(name, ""),
            "_is_economy_aim": lambda aim: aim in ("vendor", "banker"),
            "_release_trade_errand": lambda name, aim: (
                released.append((name, aim)) or aims.pop(name, None) or True
            ),
        }
        ns = _load(
            [
                "_members_inside_instance",
                "_release_instance_economy_aims",
            ],
            fakes,
        )
        return ns["_release_instance_economy_aims"], released

    def test_a_vendor_aim_carried_inside_the_instance_is_handed_back(self):
        """Fails before the change: the aim stood and the module walked the
        tank out once the clear stopped."""
        aims = {"Grug": "vendor", "Bork": "vendor"}
        drop, released = self.release(aims, {"Grug": 230, "Bork": 0})
        self.assertEqual(["Grug"], drop(["Grug", "Bork"]))
        self.assertEqual([("Grug", "vendor")], released)

    def test_an_aim_the_economy_did_not_write_is_left_inside(self):
        aims = {"Grug": "trainer:985"}
        drop, released = self.release(aims, {"Grug": 230})
        self.assertEqual([], drop(["Grug"]))
        self.assertEqual([], released)

    def test_the_vendor_pass_hands_back_aims_inside_during_a_run(self):
        """The whole vendor pass is run (#2323), during a run and with no
        run row at all; it was pinned as text."""
        self.assertEqual([("Zug", "vendor")], vendor_pass_release(in_run=True))
        self.assertEqual([("Zug", "vendor")], vendor_pass_release(in_run=False))
        self.assertEqual([], vendor_pass_release(in_run=True, inside=False))


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

    def test_a_slow_walk_restarted_four_times_over_an_hour_leaves_the_door(self):
        """#2151: the walk restarted every few minutes, interleaved with a
        quest drive and a town errand, so the quarter-hour fold never held
        ten and the run stayed open for forty minutes."""
        got = stall.door_unreachable("shadowfang", (1, stall.DOOR_RESTART_BOUND))
        self.assertIsNotNone(got)
        self.assertIn("restarted %d times" % stall.DOOR_RESTART_BOUND, got.why)

    def test_three_restarts_over_the_hour_do_not_leave(self):
        self.assertIsNone(
            stall.door_unreachable("shadowfang", (1, stall.DOOR_RESTART_BOUND - 1))
        )

    def test_the_bridge_folds_the_walk_over_the_wider_window_too(self):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("window=dungeonstall.DOOR_RESTART_WINDOW", src)

    def test_a_bare_count_still_reads_as_the_quarter_hour_fold(self):
        self.assertIsNone(stall.door_unreachable("shadowfang", 3))

    def test_the_restart_slope_leaves_the_door_at_three_quick_restarts(self):
        """The pre-wedge slope (#2636, second slice): three restarts of the
        leader's walk inside the quarter-hour fold, below the breaker's
        bound, already leave the door with the breaker's own stand-down,
        instead of reissuing the same walk until the bound trips."""
        got = stall.door_restart_slope("shadowfang", stall.SLOPE_RESTART_BOUND)
        self.assertIsNotNone(got)
        self.assertEqual("shadowfang", got.door)
        self.assertIn("restarted 3 times", got.why)

    def test_the_restart_slope_is_silent_below_three_quick_restarts(self):
        self.assertIsNone(
            stall.door_restart_slope("shadowfang", stall.SLOPE_RESTART_BOUND - 1)
        )

    def test_the_restart_slope_reads_only_the_quarter_hour_count(self):
        """Restarts spread over the hour are the breaker's wider fold, not
        the slope: a pair whose quarter-hour count is low stays silent here
        however the hour count reads below the breaker's own bound."""
        self.assertIsNone(stall.door_restart_slope("shadowfang", (1, 3)))
        got = stall.door_restart_slope("shadowfang", (3, 3))
        self.assertIsNotNone(got)
        self.assertIn("restarted 3 times", got.why)

    def test_the_restart_slope_does_not_duplicate_the_breaker(self):
        """At the breaker's own bound the breaker speaks, not the slope:
        the slope verdict is for the climb below it."""
        self.assertIsNone(stall.door_restart_slope("shadowfang", stall.RESTART_BOUND))
        self.assertIsNone(
            stall.door_restart_slope("shadowfang", stall.RESTART_BOUND + 5)
        )

    def test_a_slope_verdict_needs_a_real_door_and_a_count(self):
        self.assertIsNone(stall.door_restart_slope("nowhere", 3))
        self.assertIsNone(stall.door_restart_slope("shadowfang", None))

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
    boss_age = None

    def judge(
        self,
        evidence,
        clock,
        jobs_of=None,
        *,
        memo_store=None,
        positions=None,
        run_id=12345,
    ):
        self.asked = []
        self.holds = {}
        self.memos = {} if memo_store is None else memo_store

        def memo_read(kind):
            return {
                subject: value
                for (stored_kind, subject), value in self.memos.items()
                if stored_kind == kind
            }

        def memo_upsert(kind, subject, value, since, expires):
            self.memos[kind, subject] = (value, since)

        def memo_delete(kind, subject):
            self.memos.pop((kind, subject), None)

        ns = _load(
            [
                "_door_wedge",
                "_door_wedge_ages",
                "_door_wedge_member_recovered",
                "_door_hold_subject",
                "_door_hold_memo_put",
                "_door_hold_memo_delete",
                "_restore_door_hold_memos",
                "_door_held_verdict",
            ],
            {
                "campaignqueue": campaignqueue,
                "dungeonstall": stall,
                "raidrun": raidrun,
                "jobs": jobs,
                "time": types.SimpleNamespace(
                    monotonic=lambda: clock[0], time=lambda: clock[0]
                ),
                "json": json,
                "DOOR_HOLD_RECOVER_YARDS": 1500,
                "_jobs_of": jobs_of
                or (lambda names: {n: "dungeon:maraudon-orange" for n in names}),
                "_door_wedge_evidence": lambda leader, head_id: (
                    self.asked.append((leader, head_id))
                    or (evidence() if callable(evidence) else evidence)
                ),
                "_DOOR_HOLD_SINCE": self.holds,
                "_DOOR_HOLD_MEMO_READ_AT": None,
                "DOOR_HOLD_MEMO_KIND": "door_wedge_hold",
                "DOOR_HOLD_MEMO_SECONDS": 7 * 24 * 3600,
                "DOOR_HOLD_MEMO_REFRESH_SECONDS": 60,
                "_memo_read": memo_read,
                "_memo_upsert": memo_upsert,
                "_memo_delete": memo_delete,
                "_MEMO_WRITER": types.SimpleNamespace(
                    submit=lambda fn, *args: fn(*args)
                ),
                "_memo_job": lambda fn, *args: fn(*args),
                "_fetch_positions": lambda names: positions or {},
                "_door_open_run_id": lambda leader, keyword: run_id,
                "_door_run_boss_age": lambda run_id: self.boss_age,
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

    def test_slope_restarts_are_a_verdict_on_the_first_pass(self):
        """The bridge asks the slope verdict too (#2636): a leader's walk
        at three quarter-hour restarts leaves the door on this pass, not
        after the breaker's bound trips."""
        judge = self.judge(((3, 0), ()), [1000.0])
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("restarted 3 times", got.why)
        self.assertIn("before the wedge forms", got.why)

    def test_two_quick_restarts_are_no_verdict(self):
        judge = self.judge(((2, 0), ()), [1000.0])
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))

    def test_restarts_at_the_breaker_bound_speak_with_the_breaker(self):
        judge = self.judge(((stall.RESTART_BOUND, 0), ()), [1000.0])
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("restarted %d times" % stall.RESTART_BOUND, got.why)
        self.assertNotIn("before the wedge forms", got.why)

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

    def test_an_impossible_catch_up_hold_is_bounded_and_regroups(self):
        clock = [1000.0]
        state = "held where it stands, too far to walk back"
        judge = self.judge((0, (self.member("Tork", state),)), clock)
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Tork"], "Zug"))
        clock[0] += stall.HOLD_SECONDS - 1
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Tork"], "Zug"))
        clock[0] += 1
        got = judge(dict(self.HEAD), ["Zug", "Tork"], "Zug")
        self.assertIsNotNone(got)
        self.assertTrue(got.regroup)
        self.assertIn("Tork", got.why)
        self.assertIn("too far to walk back", got.why)

    def test_a_dead_member_becomes_a_verdict_past_the_shorter_bound(self):
        clock = [1000.0]
        judge = self.judge((0, (self.member("Uzza", "dead"),)), clock)
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.DEAD_SECONDS
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("dead", got.why)

    def test_a_hold_that_recovers_within_walk_range_starts_a_new_clock(self):
        clock = [1000.0]
        box = [(0, (self.member("Uzza", "on an errand of its own"),))]
        positions = {}
        ns = _load(
            [
                "_door_wedge",
                "_door_wedge_ages",
                "_door_wedge_member_recovered",
                "_door_hold_subject",
                "_door_hold_memo_put",
                "_door_hold_memo_delete",
                "_restore_door_hold_memos",
                "_door_held_verdict",
            ],
            {
                "campaignqueue": campaignqueue,
                "dungeonstall": stall,
                "raidrun": raidrun,
                "jobs": jobs,
                "time": types.SimpleNamespace(
                    monotonic=lambda: clock[0], time=lambda: clock[0]
                ),
                "json": json,
                "DOOR_HOLD_RECOVER_YARDS": 1500,
                "_jobs_of": lambda names: {n: "dungeon:maraudon-orange" for n in names},
                "_door_wedge_evidence": lambda leader, head_id: box[0],
                "_DOOR_HOLD_SINCE": {},
                "_DOOR_HOLD_MEMO_READ_AT": None,
                "DOOR_HOLD_MEMO_KIND": "door_wedge_hold",
                "DOOR_HOLD_MEMO_SECONDS": 7 * 24 * 3600,
                "DOOR_HOLD_MEMO_REFRESH_SECONDS": 60,
                "_memo_read": lambda kind: {},
                "_memo_upsert": lambda *args: None,
                "_memo_delete": lambda *args: None,
                "_MEMO_WRITER": types.SimpleNamespace(
                    submit=lambda fn, *args: fn(*args)
                ),
                "_memo_job": lambda fn, *args: fn(*args),
                "_fetch_positions": lambda names: positions,
                "_door_open_run_id": lambda leader, keyword: 12345,
                "_door_run_boss_age": lambda run_id: self.boss_age,
            },
        )
        judge = ns["_door_wedge"]
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.HOLD_SECONDS - 1
        box[0] = (0, (self.member("Uzza", "following"),))
        positions.update(
            {
                "Zug": {
                    "map_id": 1,
                    "instance_id": 0,
                    "pos_x": 0,
                    "pos_y": 0,
                    "pos_z": 0,
                },
                "Uzza": {
                    "map_id": 1,
                    "instance_id": 0,
                    "pos_x": 1400,
                    "pos_y": 0,
                    "pos_z": 0,
                },
            }
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        box[0] = (0, (self.member("Uzza", "on an errand of its own"),))
        clock[0] += 2
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))

    def test_a_state_flap_keeps_the_clock_while_the_member_is_still_far(self):
        clock = [1000.0]
        box = [(0, (self.member("Tork", stall.CATCH_UP_UNREACHABLE_STATE),))]
        positions = {
            "Zug": {"map_id": 1, "instance_id": 0, "pos_x": 0, "pos_y": 0, "pos_z": 0},
            "Tork": {
                "map_id": 1,
                "instance_id": 0,
                "pos_x": 2500,
                "pos_y": 0,
                "pos_z": 0,
            },
        }
        judge = self.judge(
            lambda: box[0],
            clock,
            memo_store={},
            positions=positions,
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Tork"], "Zug"))
        clock[0] += stall.HOLD_SECONDS - 1
        box[0] = (0, (self.member("Tork", "following"),))
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Tork"], "Zug"))
        box[0] = (0, (self.member("Tork", stall.CATCH_UP_UNREACHABLE_STATE),))
        clock[0] += 1
        got = judge(dict(self.HEAD), ["Zug", "Tork"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("Tork", got.why)

    def test_a_new_head_for_the_same_run_keeps_the_clock(self):
        """A hold timed under one queue entry persists for the next entry
        if it is the same run: the run is the attempt being judged."""
        clock = [1000.0]
        judge = self.judge(
            (0, (self.member("Uzza", "on an errand of its own"),)), clock
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.HOLD_SECONDS + 1
        # Same run (run_id=12345 from mock): the clock persists and the wedge fires.
        got = judge(dict(self.HEAD, id=8), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("Uzza", got.why)
        self.assertIn("errand of its own", got.why)

    # --- #2181: a run that credits a boss is not wedged ---------------------

    def test_a_hold_past_its_bound_is_no_verdict_while_the_run_credits_bosses(self):
        """Run 1850975 (Zug, Blackrock Depths): Oz was on an errand for over
        30 minutes while the other four cleared nine encounters, the newest
        13 minutes before the verdict, and the verdict walked the party out."""
        clock = [1000.0]
        judge = self.judge(
            (0, (self.member("Uzza", "on an errand of its own"),)), clock
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        clock[0] += stall.HOLD_SECONDS + 60
        self.boss_age = 13 * 60
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))

    def test_the_clock_restarts_at_the_newest_credit_and_a_silent_run_is_still_left(
        self,
    ):
        clock = [1000.0]
        judge = self.judge(
            (0, (self.member("Uzza", "on an errand of its own"),)), clock
        )
        judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        clock[0] += stall.HOLD_SECONDS + 60
        self.boss_age = stall.HOLD_SECONDS - 1
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        self.boss_age = stall.HOLD_SECONDS
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("Uzza", got.why)

    def test_a_dead_member_is_no_verdict_while_the_run_credits_bosses(self):
        clock = [1000.0]
        judge = self.judge((0, (self.member("Uzza", "dead"),)), clock)
        judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        clock[0] += stall.DEAD_SECONDS + 60
        self.boss_age = 5 * 60
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))

    def test_hold_clocks_are_cleared_on_a_pass_that_does_not_judge_the_family(self):
        clock = [1000.0]
        judge = self.judge(
            (0, (self.member("Uzza", "on an errand of its own"),)), clock, run_id=None
        )
        judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertTrue(self.holds)
        judge(dict(self.HEAD, status="queued"), ["Zug", "Uzza"], "Zug")
        self.assertEqual({}, self.holds)

    def test_a_stale_clock_is_not_counted_as_one_hold_after_the_job_returns(self):
        clock = [1000.0]
        job = ["dungeon:maraudon-orange"]
        evidence = [(0, (self.member("Uzza", "on an errand of its own"),))]
        judge = self.judge(
            evidence[0],
            clock,
            jobs_of=lambda names: {n: job[0] for n in names},
        )
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        # The family is off the dungeon job for longer than the bound.
        job[0] = "quest"
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug"))
        self.assertTrue(self.holds)
        clock[0] += stall.HOLD_SECONDS - 1
        job[0] = "dungeon:maraudon-orange"
        clock[0] += 1
        got = judge(dict(self.HEAD), ["Zug", "Uzza"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("Uzza", got.why)

    def test_a_bridge_restart_restores_the_hold_clock(self):
        clock, memos = [1000.0], {}
        evidence = (0, (self.member("Tork", stall.CATCH_UP_UNREACHABLE_STATE),))
        first = self.judge(evidence, clock, memo_store=memos)
        self.assertIsNone(first(dict(self.HEAD), ["Zug", "Tork"], "Zug"))
        clock[0] += stall.HOLD_SECONDS - 1

        restarted = self.judge(evidence, clock, memo_store=memos)
        self.assertIsNone(restarted(dict(self.HEAD), ["Zug", "Tork"], "Zug"))
        clock[0] += 1
        got = restarted(dict(self.HEAD), ["Zug", "Tork"], "Zug")
        self.assertIsNotNone(got)
        self.assertTrue(got.regroup)

    def test_a_legacy_memo_ages_a_queue_but_never_an_unproven_open_run(self):
        clock = [1000.0 + stall.HOLD_SECONDS]
        evidence = (0, (self.member("Tork", stall.CATCH_UP_UNREACHABLE_STATE),))
        for run_id in (None, 12345):
            with self.subTest(run_id=run_id):
                memos = {
                    ("door_wedge_hold", '["Zug","Tork"]'): ({"head_id": 7}, 1000.0)
                }
                judge = self.judge(evidence, clock, memo_store=memos, run_id=run_id)
                verdict = judge(dict(self.HEAD), ["Zug", "Tork"], "Zug")
                if run_id is None:
                    self.assertIsNotNone(verdict)
                else:
                    self.assertIsNone(verdict)

    def test_the_boss_read_is_the_open_runs_own_boss_rows(self):
        def sql(name):
            return next(
                ast.literal_eval(node.value)
                for node in ast.parse(BRIDGE).body
                if isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == name for t in node.targets)
            )

        run, boss = sql("_DOOR_RUN_SQL"), sql("_DOOR_BOSS_SQL")
        self.assertIn("ended_at IS NULL", run)
        self.assertIn("overseer_dungeon_run_event", boss)
        self.assertIn("kind = 'boss'", boss)
        self.assertIn("run_id = %s", boss)
        self.assertNotIn("JOIN", run + boss)

    def test_no_verdict_without_a_started_dungeon_head(self):
        judge = self.judge((38, ()), [1000.0])
        self.assertIsNone(
            judge(dict(self.HEAD, status="queued"), ["Zug", "Uzza"], "Zug")
        )


# --- an operator's order is held, never cancelled (#2216) ----------------------
#
# An operator's order was cancelled by a run that never got in, which read as
# the second stall running after an earlier real stall (#2216).


class AnOperatorOrderIsHeldNotCancelled(unittest.TestCase):
    BRD = campaignplan.BY_KEYWORD["blackrock-depths"].map_id
    OPERATOR = "web:overseer"

    def stuck(self):
        runs = [
            {
                "id": 101,
                "map_id": self.BRD,
                "portal_keyword": "blackrock-depths",
                "outcome": "stalled",
            },
            {
                "id": 102,
                "map_id": self.BRD,
                "portal_keyword": "blackrock-depths",
                "outcome": "stalled",
            },
        ]
        return stall.stuck_doors(runs, [boss(101, 255, 511), stalled(102, "x")])

    def order(self, qid, keyword="blackrock-depths", source=None, status="active"):
        return dict(
            queue_row(qid, keyword, status),
            source=source or self.OPERATOR,
        )

    def test_the_operators_rows_are_held_and_the_overseers_are_dropped(self):
        rows = [
            self.order(501),
            queue_row(163, "blackrock-depths", "queued", 1),
            queue_row(164, "uldaman", "queued", 2),
        ]
        got = stall.leave(rows, self.stuck())
        self.assertEqual((501,), got.park)
        self.assertEqual((163,), got.drop)
        self.assertEqual(stall.ORDER_DECISION, got.decision)

    def test_an_order_held_over_and_over_with_no_run_formed_is_given_up(self):
        rows = [self.order(501), queue_row(164, "uldaman", "queued", 1)]
        held = stall.leave(rows, self.stuck(), stall.ORDER_HOLD_LIMIT - 1)
        self.assertEqual((501,), held.park)
        got = stall.leave(rows, self.stuck(), stall.ORDER_HOLD_LIMIT)
        self.assertEqual((), got.park)
        self.assertEqual((501,), got.drop)
        self.assertEqual(stall.DECISION, got.decision)
        self.assertIn("given up", got.why)
        self.assertIn("Uldaman runs next", got.why)

    def test_the_hold_count_reads_only_holds_since_the_order_and_the_last_run(self):
        sql = stall.HOLDS_SQL.format(holes=stall.holes(2))
        self.assertEqual(
            sql.count("%s"), len(stall.holds_args("Fam", "d", 5, ["A", "B"]))
        )
        self.assertIn("overseer_dungeon_queue WHERE id", sql)
        self.assertIn("MAX(started_at)", sql)

    def test_a_lone_operator_order_is_not_dropped(self):
        got = stall.leave([self.order(501)], self.stuck())
        self.assertEqual((), got.drop)
        self.assertEqual((501,), got.park)

    def test_the_overseers_own_entry_is_still_left(self):
        got = stall.leave([queue_row(7, "blackrock-depths")], self.stuck())
        self.assertEqual((7,), got.drop)
        self.assertEqual((), got.park)
        self.assertEqual(stall.DECISION, got.decision)

    def test_the_sentence_says_held_not_left_and_when_it_runs_again(self):
        got = stall.leave([self.order(501)], self.stuck())
        minutes = int(stall.ORDER_BACKOFF.total_seconds() // 60)
        self.assertIn("the order is held, not left", got.why)
        self.assertIn("runs again in %d minutes" % minutes, got.why)
        self.assertNotIn("; left,", got.why)

    def test_the_backoff_is_far_shorter_than_the_door_window(self):
        self.assertLess(stall.ORDER_BACKOFF, timedelta(hours=stall.WINDOW_HOURS))

    def test_a_hold_older_than_the_order_does_not_rest_it(self):
        row = {"id": 5, "left_s": 600, "ordered_after": 1}
        self.assertIsNone(stall.order_hold(self.order(501), row))
        row["ordered_after"] = 0
        self.assertEqual(600, stall.order_hold(self.order(501), row)["left_s"])
        self.assertIsNone(stall.order_hold(queue_row(7, "blackrock-depths"), row))

    def test_the_stalls_that_earned_a_hold_are_not_read_again(self):
        runs = [
            {"id": 1, "started_at": 10},
            {"id": 2, "started_at": 50},
            {"id": 3, "started_at": 120},
        ]
        head = {"source": self.OPERATOR, "created_at": 5}
        got = stall.since_order(runs, head, parked_at=100)
        self.assertEqual([3], [r["id"] for r in got])
        own = {"source": "overseer:planner", "created_at": 5}
        self.assertEqual(3, len(stall.since_order(runs, own, parked_at=100)))

    def world(self):
        w = StallWorld(
            [dict(_q(501, "blackrock-depths", 20, "active", 0), source=self.OPERATOR)],
            [
                ledger_row(101, map_id=self.BRD, portal="blackrock-depths"),
                ledger_row(102, map_id=self.BRD, portal="blackrock-depths"),
            ],
            [boss(101, 255, 511), stalled(102, "x")],
        )
        for r in w.family("Zug"):
            r["job"] = "dungeon:blackrock-depths"
        return w

    def cancels(self, w):
        return [c for c in w.calls if "SET status = 'cancelled'" in c[0]]

    def test_an_order_held_again_and_again_with_no_run_is_given_up(self):
        w = self.world()
        w.order_holds = stall.ORDER_HOLD_LIMIT
        _pass(w)
        self.assertEqual("cancelled", w.queue[0]["status"])
        self.assertEqual(1, len(self.cancels(w)))
        self.assertEqual(stall.DECISION, w.records[0][1])
        self.assertEqual({jobs.DEFAULT}, {r["job"] for r in w.family("Zug")}, w.jobs)

    def test_a_stalled_operator_order_stays_pending_and_the_family_quests(self):
        w = self.world()
        lines = _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual([], self.cancels(w))
        self.assertEqual(
            {jobs.DEFAULT}, {r["job"] for r in w.family("Zug")}, (lines, w.jobs)
        )
        self.assertEqual(1, len(w.records))
        self.assertEqual(stall.ORDER_DECISION, w.records[0][1])
        self.assertTrue([ln for ln in lines if "the order is held, not left" in ln])

    def test_the_family_steps_past_the_held_order_during_the_backoff(self):
        w = self.world()
        _pass(w)
        w.queue.append(_q(170, "uldaman", 10, "queued", 1))
        w.park_left = 600
        lines = _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual("active", w.queue[1]["status"])
        self.assertEqual({"dungeon:uldaman"}, {r["job"] for r in w.family("Zug")})
        self.assertEqual([], self.cancels(w))
        self.assertEqual(1, len(w.records))
        said = [ln for ln in lines if "is held, not cancelled" in ln]
        self.assertEqual(1, len(said), lines)
        self.assertIn("runs again in about 10 minute", said[0])

    def test_alone_in_the_queue_the_held_order_waits_and_says_so_once(self):
        w = self.world()
        _pass(w)
        w.park_left = 600
        said = []
        for _ in range(3):
            said += [ln for ln in _pass(w) if "is held, not cancelled" in ln]
        self.assertEqual(1, len(said), said)
        self.assertIn("nothing else is queued", said[0])
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual({jobs.DEFAULT}, {r["job"] for r in w.family("Zug")})

    def test_after_the_backoff_the_same_order_runs_with_no_new_order(self):
        w = self.world()
        _pass(w)
        # The stalls that earned the hold are before the hold: the read the
        # database does for the breaker returns only runs after it.
        w.runs, w.events = [], []
        w.park_left = 0
        w.park_at = datetime(2026, 11, 10, 12, 37, 59)
        lines = _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual([], self.cancels(w))
        self.assertEqual(1, len(w.records), lines)
        self.assertEqual(
            {"dungeon:blackrock-depths"}, {r["job"] for r in w.family("Zug")}, lines
        )

    def test_a_repeated_stall_after_the_hold_holds_it_again_not_cancels_it(self):
        w = self.world()
        _pass(w)
        w.park_left = 0
        w.park_at = datetime(2026, 11, 10, 12, 37, 59)
        for r in w.runs:
            r["started_at"] = datetime(2026, 11, 10, 13, 0, 0)
        _pass(w)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual([], self.cancels(w))
        self.assertEqual(2, len(w.records))
        self.assertEqual(stall.ORDER_DECISION, w.records[1][1])

    def test_the_hold_is_read_before_the_stalls_and_is_never_a_leave_row(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        body = body[: body.index("\n    def ", 10)]
        self.assertLess(body.index("_order_hold"), body.index("_stall_reads"))
        self.assertIn("if not leave.park:", body)
        write = BRIDGE[BRIDGE.index("def _stall_write(") :]
        write = write[: write.index("\n\n\n", 10)]
        self.assertIn("leave.decision", write)


def standing(map_id=0, x=0.0, y=0.0, instance=0):
    """One member's snapshot row, as the bridge's position read returns it."""
    return {"map_id": map_id, "instance_id": instance, "pos_x": x, "pos_y": y}


class NoRestartUntilThePartyStandsTogether(unittest.TestCase):
    """#2280: an operator's order whose run was stood down for an unassembled
    party is not restarted when its backoff ends unless every member stands
    with the leader. The backoff is a clock; the party standing together is
    the fact the clock was waiting for."""

    OPERATOR = "web:overseer"
    NAMES = ("Zug", "Oz", "Bork")
    HOLD = {"id": 9, "left_s": 0, "target": stall.REGROUP}

    def together(self):
        return {
            "Zug": standing(0, 100.0, 100.0),
            "Oz": standing(0, 110.0, 105.0),
            "Bork": standing(0, 95.0, 90.0),
        }

    def judge(self, positions, hold=None, running=False):
        return stall.restart_after_hold(
            self.HOLD if hold is None else hold,
            running,
            "Zug",
            self.NAMES,
            positions,
        )

    def held_member(self):
        return stall.party_held("blackrock-depths", "Oz", stall.ERRAND_STATE, 1800)

    def test_a_stand_down_for_a_held_member_is_a_regroup_stand_down(self):
        self.assertTrue(self.held_member().regroup)
        still = stall.party_held("blackrock-depths", "Oz", "held still", 1800)
        self.assertTrue(still.regroup)

    def test_two_stalls_and_a_silent_run_are_not(self):
        self.assertFalse(stall.silent_run("blackrock-depths", 3 * 3600).regroup)
        twice = AnOperatorOrderIsHeldNotCancelled().stuck()
        self.assertFalse(twice["blackrock-depths"].regroup)

    def test_the_held_order_carries_the_regroup_mark_and_says_so(self):
        order = dict(queue_row(501, "blackrock-depths"), source=self.OPERATOR)
        got = stall.leave([order], {"blackrock-depths": self.held_member()})
        self.assertEqual((501,), got.park)
        self.assertEqual(stall.REGROUP, got.target)
        self.assertIn("once every member stands together", got.why)
        self.assertIn("the order is held, not left", got.why)

    def test_a_two_stall_hold_and_a_left_door_carry_no_mark(self):
        twice = AnOperatorOrderIsHeldNotCancelled().stuck()
        order = dict(queue_row(501, "blackrock-depths"), source=self.OPERATOR)
        self.assertEqual("", stall.leave([order], twice).target)
        own = [queue_row(7, "blackrock-depths")]
        left = stall.leave(own, {"blackrock-depths": self.held_member()})
        self.assertEqual((7,), left.drop)
        self.assertEqual("", left.target)

    def test_a_member_on_another_map_holds_the_restart_and_is_named(self):
        positions = self.together()
        positions["Oz"] = standing(1, 110.0, 105.0)
        got = self.judge(positions)
        self.assertFalse(got.allowed)
        self.assertEqual(stall.APART, got.reason)
        self.assertEqual((("Oz", "on another map"),), got.apart)
        self.assertIn("Oz is on another map", got.said())
        self.assertIn("stands together", got.said())

    def test_a_member_far_from_the_leader_holds_it_with_the_yards(self):
        positions = self.together()
        positions["Bork"] = standing(0, 100.0, 100.0 + 1639.0)
        got = self.judge(positions)
        self.assertFalse(got.allowed)
        self.assertEqual((("Bork", "1639 yards from Zug"),), got.apart)

    def test_a_member_in_another_copy_of_the_map_is_apart(self):
        positions = self.together()
        positions["Oz"] = standing(0, 110.0, 105.0, instance=7)
        self.assertEqual((("Oz", "on another map"),), self.judge(positions).apart)

    def test_a_member_nobody_can_see_holds_it(self):
        positions = self.together()
        del positions["Oz"]
        got = self.judge(positions)
        self.assertFalse(got.allowed)
        self.assertEqual((("Oz", "not seen in the world"),), got.apart)

    def test_an_unseen_leader_holds_it_too(self):
        positions = self.together()
        del positions["Zug"]
        got = self.judge(positions)
        self.assertFalse(got.allowed)
        self.assertEqual("Zug", got.apart[0][0])

    def test_the_edge_of_the_range_is_together(self):
        positions = self.together()
        positions["Oz"] = standing(0, 100.0 + stall.REGROUP_YARDS, 100.0)
        self.assertTrue(self.judge(positions).allowed)
        positions["Oz"] = standing(0, 100.0 + stall.REGROUP_YARDS + 1, 100.0)
        self.assertFalse(self.judge(positions).allowed)

    def test_every_member_beside_the_leader_lets_the_order_run(self):
        got = self.judge(self.together())
        self.assertTrue(got.allowed)
        self.assertEqual(stall.TOGETHER, got.reason)
        self.assertEqual((), got.apart)

    def test_the_backoff_still_holds_a_party_that_stands_together(self):
        got = self.judge(self.together(), hold=dict(self.HOLD, left_s=600))
        self.assertFalse(got.allowed)
        self.assertEqual(stall.BACKOFF, got.reason)

    def test_a_hold_with_no_regroup_mark_runs_on_the_clock_alone(self):
        apart = {"Zug": standing(0), "Oz": standing(1), "Bork": standing(1)}
        got = self.judge(apart, hold={"id": 9, "left_s": 0, "target": ""})
        self.assertTrue(got.allowed)
        self.assertEqual(stall.NOT_REGROUP, got.reason)
        self.assertTrue(self.judge(apart, hold={}).allowed)

    def test_an_order_already_running_again_is_not_held_mid_run(self):
        apart = {"Zug": standing(230), "Oz": standing(0), "Bork": standing(230)}
        got = self.judge(apart, running=True)
        self.assertTrue(got.allowed)
        self.assertEqual(stall.RUNNING, got.reason)

    def test_a_realm_that_shows_nobody_does_not_hold_the_order_for_ever(self):
        got = self.judge({})
        self.assertTrue(got.allowed)
        self.assertEqual(stall.UNREAD, got.reason)

    def test_an_unreadable_position_is_apart_not_a_crash(self):
        positions = self.together()
        positions["Oz"] = {"map_id": 0, "instance_id": 0, "pos_x": None}
        got = self.judge(positions)
        self.assertEqual((("Oz", "not seen in the world"),), got.apart)

    # --- the bridge's queue pass ---

    def world(self):
        w = StallWorld(
            [dict(_q(501, "blackrock-depths", 20, "active", 0), source=self.OPERATOR)],
            [],
            [],
        )
        for r in w.family("Zug"):
            r["job"] = "dungeon:blackrock-depths"
        names = [r["name"] for r in w.family("Zug")]
        self.straggler = next(n for n in names if n != "Zug")
        w.wedge = stall.party_held(
            "blackrock-depths", self.straggler, stall.ERRAND_STATE, 1800, "vendor"
        )
        w.positions = {n: standing(0, 100.0, 100.0) for n in names}
        return w

    def stood_down(self):
        """The world one pass after the stand-down, its backoff over."""
        w = self.world()
        _pass(w)
        w.wedge = None
        w.park_left = 0
        w.park_at = datetime(2026, 11, 12, 2, 42, 0)
        return w

    def jobs_of(self, w):
        return {r["job"] for r in w.family("Zug")}

    def test_the_stand_down_writes_the_regroup_mark_on_the_hold(self):
        w = self.world()
        _pass(w)
        self.assertEqual(1, len(w.records))
        self.assertEqual(stall.ORDER_DECISION, w.records[0][1])
        self.assertEqual(stall.REGROUP, w.records[0][3])
        self.assertEqual({jobs.DEFAULT}, self.jobs_of(w))

    def test_the_order_is_not_restarted_while_a_member_is_away(self):
        w = self.stood_down()
        w.positions[self.straggler] = standing(1, 5.0, 5.0)
        lines = _pass(w)
        self.assertEqual({jobs.DEFAULT}, self.jobs_of(w), lines)
        self.assertEqual("active", w.queue[0]["status"])
        self.assertEqual(1, len(w.records))
        said = [ln for ln in lines if "stands together" in ln]
        self.assertEqual(1, len(said), lines)
        self.assertIn("%s is on another map" % self.straggler, said[0])

    def test_the_wait_is_said_once_not_every_pass(self):
        w = self.stood_down()
        w.positions[self.straggler] = standing(1, 5.0, 5.0)
        said = []
        for _ in range(3):
            said += [ln for ln in _pass(w) if "stands together" in ln]
        self.assertEqual(1, len(said), said)
        self.assertEqual({jobs.DEFAULT}, self.jobs_of(w))

    def test_another_entry_runs_while_the_order_waits_for_the_party(self):
        w = self.stood_down()
        w.positions[self.straggler] = standing(1, 5.0, 5.0)
        w.queue.append(_q(170, "uldaman", 10, "queued", 1))
        _pass(w)
        self.assertEqual({"dungeon:uldaman"}, self.jobs_of(w))
        self.assertEqual("active", w.queue[0]["status"])

    def test_the_order_runs_again_once_every_member_stands_together(self):
        w = self.stood_down()
        w.positions[self.straggler] = standing(1, 5.0, 5.0)
        _pass(w)
        self.assertEqual({jobs.DEFAULT}, self.jobs_of(w))
        w.positions[self.straggler] = standing(0, 104.0, 98.0)
        lines = _pass(w)
        self.assertEqual({"dungeon:blackrock-depths"}, self.jobs_of(w), lines)
        self.assertEqual(1, len(w.records))

    def test_the_restarted_run_is_not_held_when_a_member_dies_far_away(self):
        w = self.stood_down()
        _pass(w)
        self.assertEqual({"dungeon:blackrock-depths"}, self.jobs_of(w))
        w.positions[self.straggler] = standing(1, 5.0, 5.0)
        lines = _pass(w)
        self.assertEqual({"dungeon:blackrock-depths"}, self.jobs_of(w), lines)
        self.assertEqual([], [ln for ln in lines if "stands together" in ln])

    def test_the_hold_gates_one_restart_not_every_later_pause_of_the_order(self):
        w = self.stood_down()
        _pass(w)
        self.assertEqual({"dungeon:blackrock-depths"}, self.jobs_of(w))
        # A town trip between runs takes the job away and scatters the party.
        for r in w.family("Zug"):
            r["job"] = jobs.DEFAULT
        w.positions[self.straggler] = standing(1, 5.0, 5.0)
        lines = _pass(w)
        self.assertEqual({"dungeon:blackrock-depths"}, self.jobs_of(w), lines)
        self.assertEqual([], [ln for ln in lines if "stands together" in ln])

    def test_the_call_site_is_thin_and_reads_after_the_backoff(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        body = body[: body.index("\n    def ", 10)]
        self.assertLess(body.index("if resting:"), body.index("_regroup_wait"))
        self.assertLess(body.index("_regroup_wait"), body.index("_stall_reads"))
        write = BRIDGE[BRIDGE.index("def _stall_write(") :]
        write = write[: write.index("\n\n\n", 10)]
        self.assertIn("leave.target", write)


class TheErrandARunWaitsOn(unittest.TestCase):
    """#2280: a member on an errand of its own while the family waits at the
    door is handed the errand back well inside the stand-down bound, and the
    stall line names the errand."""

    HEAD = {"id": 7, "keyword": "maraudon-orange", "status": "active"}

    def member(self, name, state):
        return jev_family_intent.Member(name, state, "0")

    def judge(self, clock, aims, released, *, with_recall=True):
        """_door_wedge with a family whose one straggler (Oz) is on an errand."""
        holds = {}
        recalled = {}

        def current(name):
            return aims.get(name, "")

        def release(name, aim):
            released.append((name, aim))
            aims.pop(name, None)
            return True

        fakes = {
            "campaignqueue": campaignqueue,
            "dungeonstall": stall,
            "jobs": jobs,
            "raidrun": raidrun,
            "log": types.SimpleNamespace(info=lambda *a, **k: None),
            "time": types.SimpleNamespace(monotonic=lambda: clock[0]),
            "_jobs_of": lambda names: {n: "dungeon:maraudon-orange" for n in names},
            "_door_wedge_evidence": lambda leader, head_id: (
                0,
                (self.member("Oz", "on an errand of its own"),)
                if "Oz" in aims
                else (self.member("Oz", "following"),),
            ),
            "_DOOR_HOLD_SINCE": holds,
            "_ERRAND_RECALLED": recalled,
            "_ERRAND_SERVED": {},
            "errandgate": errandgate,
            "_door_run_boss_age": lambda run_id: None,
            "_door_open_run_id": lambda leader, keyword: 12345,
            "_current_travel_npc": current,
            "_is_economy_aim": lambda aim: aim in ("vendor", "banker"),
            "_release_trade_errand": release,
        }
        names = [
            "_door_wedge",
            "_door_wedge_ages",
            "_door_wedge_member_recovered",
            "_door_held_verdict",
        ]
        if with_recall:
            names.append("_recall_door_errands")
        self.recalled = recalled
        return _load(names, fakes)["_door_wedge"]

    def test_an_errand_is_handed_back_inside_the_stand_down_bound(self):
        """Fails before the change: the member stayed on the errand until the
        30 minute stand-down."""
        clock, released, aims = [1000.0], [], {"Oz": "vendor"}
        judge = self.judge(clock, aims, released)
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        self.assertEqual([], released)
        clock[0] += stall.RECALL_SECONDS
        self.assertIsNone(judge(dict(self.HEAD), ["Zug", "Oz"], "Zug"))
        self.assertEqual([("Oz", "vendor")], released)
        self.assertIn("Oz", self.recalled)
        self.assertLess(stall.RECALL_SECONDS, stall.HOLD_SECONDS)

    def test_a_short_errand_is_left_alone(self):
        clock, released, aims = [1000.0], [], {"Oz": "vendor"}
        judge = self.judge(clock, aims, released)
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        clock[0] += stall.RECALL_SECONDS - 1
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        self.assertEqual([], released)

    def test_an_aim_the_economy_did_not_write_is_not_taken_back(self):
        clock, released, aims = [1000.0], [], {"Oz": "trainer:985"}
        judge = self.judge(clock, aims, released)
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        clock[0] += stall.RECALL_SECONDS + 1
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        self.assertEqual([], released)

    def test_a_recall_that_cannot_take_leaves_the_stand_down_as_the_backstop(self):
        clock, released, aims = [1000.0], [], {"Oz": "trainer:985"}
        judge = self.judge(clock, aims, released)
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        clock[0] += stall.HOLD_SECONDS
        got = judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        self.assertIsNotNone(got)
        self.assertIn("Oz", got.why)

    def test_the_stall_line_names_the_errand_that_held_the_run(self):
        clock, released, aims = [1000.0], [], {"Oz": "trainer:985"}
        judge = self.judge(clock, aims, released)
        judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        clock[0] += stall.HOLD_SECONDS
        got = judge(dict(self.HEAD), ["Zug", "Oz"], "Zug")
        self.assertIn("an errand called 'trainer:985'", got.why)

    def test_the_line_names_a_vendor_walk_in_words(self):
        got = stall.party_held(
            "shadowfang",
            "Oz",
            "on an errand of its own",
            stall.HOLD_SECONDS,
            "vendor",
        )
        self.assertIn(
            "Oz has been on an errand of its own (a walk to a vendor)", got.why
        )

    def test_a_line_with_no_known_errand_reads_as_it_did(self):
        got = stall.party_held(
            "shadowfang", "Oz", "on an errand of its own", stall.HOLD_SECONDS
        )
        self.assertIn("Oz has been on an errand of its own for over 30", got.why)
        held = stall.party_held(
            "shadowfang", "Oz", "held still", stall.HOLD_SECONDS, "vendor"
        )
        self.assertNotIn("(", held.why)

    def test_errand_words_cover_every_economy_aim(self):
        for aim in (
            "vendor",
            "banker",
            "guild banker",
            "repair",
            "auctioneer",
            "at:0:1.0,2.0,3.0",
            "5594",
        ):
            self.assertTrue(stall.errand_words(aim), aim)
        self.assertEqual("", stall.errand_words(""))

    def test_only_the_errand_state_is_recalled_and_only_past_the_bound(self):
        ages = {
            "Oz": ("on an errand of its own", stall.RECALL_SECONDS),
            "Uzza": ("on an errand of its own", stall.RECALL_SECONDS - 1),
            "Zork": ("dead", 99999.0),
            "Zrog": ("held still", 99999.0),
        }
        self.assertEqual(("Oz",), stall.errand_recalls(ages))

    def test_a_recalled_member_is_not_sent_straight_back_out(self):
        self.assertTrue(stall.recall_cooling(100.0, 100.0 + 60))
        self.assertFalse(
            stall.recall_cooling(100.0, 100.0 + stall.RECALL_COOLDOWN_SECONDS)
        )
        self.assertFalse(stall.recall_cooling(None, 100.0))

    def test_the_bag_pressure_aim_skips_a_member_in_its_cooldown(self):
        """The pass is run with a recalled member (#2323); it was pinned as
        text."""
        self.assertEqual(
            (1, ["Bork"]), bag_pressure_pass(recalled={"Grog": 940.0}, now=1000.0)
        )
        over = 940.0 + stall.RECALL_COOLDOWN_SECONDS
        self.assertEqual(
            (2, ["Bork", "Grog"]), bag_pressure_pass(recalled={"Grog": 940.0}, now=over)
        )


class ARegroupWaitIsBounded(unittest.TestCase):
    """A hold waiting for a party nothing is gathering must not wait for ever."""

    NAMES = ("Zug", "Oz", "Bork")

    def apart(self):
        return {
            "Zug": standing(0, 100.0, 100.0),
            "Oz": standing(0, 145.0, 100.0),
            "Bork": standing(0, 100.0, 175.0),
        }

    def judge(self, left_s):
        hold = {"id": 9, "left_s": left_s, "target": stall.REGROUP}
        return stall.restart_after_hold(hold, False, "Zug", self.NAMES, self.apart())

    def test_a_party_spread_past_the_range_holds_inside_the_ceiling(self):
        got = self.judge(-(stall.REGROUP_CEILING_SECONDS - 1))
        self.assertFalse(got.allowed)
        self.assertEqual(stall.APART, got.reason)

    def test_the_same_party_runs_once_the_ceiling_is_spent(self):
        got = self.judge(-stall.REGROUP_CEILING_SECONDS)
        self.assertTrue(got.allowed)
        self.assertEqual(stall.CEILING, got.reason)

    def test_a_backoff_still_running_holds_whatever_the_ceiling(self):
        self.assertEqual(stall.BACKOFF, self.judge(60).reason)
