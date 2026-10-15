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

import asyncio
import pathlib
import types
import unittest

from test_campaign_queue import FakeWorld, _load, _Log, _q  # sets up the pymysql stub

import campaignplan  # noqa: E402
import campaignqueue  # noqa: E402
import crossing  # noqa: E402
import dungeonpace  # noqa: E402
import dungeonstall as stall  # noqa: E402
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
        self.rows = []
        if flat.startswith("SELECT id, map_id, portal_keyword"):
            self.rows = [dict(r) for r in self.store.runs]
        elif "FROM overseer_dungeon_run_event" in flat:
            self.rows = [dict(e) for e in self.store.events if e["run_id"] in params]
        elif "SET status = 'cancelled'" in flat:
            self.store.world.cancel(params[0])
        elif flat.startswith("INSERT INTO overseer_dungeon_pace"):
            self.store.records.append(params)
            self.lastrowid = len(self.store.records)
        elif flat.startswith("UPDATE overseer_dungeon_pace SET closed_at"):
            self.store.closed.append(params)

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
        self.commits = 0
        self.world = self

    def cancel(self, qid):
        for r in self.queue:
            if r["id"] == qid and r["status"] in campaignqueue.PENDING:
                r["status"] = "cancelled"


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
            "_stall_reads",
            "_stall_write",
            "_stuck_doors",
            "_planner_rows",
        ],
        {
            "asyncio": asyncio,
            "campaignqueue": campaignqueue,
            "campaignplan": campaignplan,
            "dungeonpace": dungeonpace,
            "dungeonstall": stall,
            "jobs": jobs,
            "log": log,
            "pymysql": __import__("pymysql"),
            "_connect": lambda: StoreConn(world),
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
            "_pass_completed": lambda name: True,
        },
    )

    async def nothing(*a):
        return None

    async def no_plan(pending, fams):
        return False

    me = types.SimpleNamespace(
        _activity_holds=lambda key=None: "",
        _campaign_owns_travel=nothing,
        _leave_town_when_done=nothing,
        _plan_campaigns=no_plan,
    )
    for name in ("_campaign_queue_family_once", "_queue_holds", "_stall_breaker"):
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


BRIDGE = (pathlib.Path(__file__).resolve().parents[1] / "bridge.py").read_text(
    encoding="utf-8"
)


class TheBridgeOrder(unittest.TestCase):
    def test_the_breaker_runs_before_the_ladder_and_the_gear_hold(self):
        holds = BRIDGE[BRIDGE.index("    async def _queue_holds(") :]
        self.assertLess(holds.index("_stall_breaker"), holds.index("_dungeon_pace"))

    def test_the_breaker_does_not_wait_for_the_family_to_be_outside(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        body = body[: body.index("\n    async def ", 10)]
        self.assertNotIn("_mid_run", body)

    def test_the_job_leaves_the_door_before_the_entry_is_cancelled(self):
        body = BRIDGE[BRIDGE.index("    async def _stall_breaker(") :]
        self.assertLess(body.index("_apply_queue_move"), body.index("_stall_write"))

    def test_the_ladder_never_steps_to_a_stuck_door(self):
        facts = BRIDGE[BRIDGE.index("    async def _pace_facts(") :]
        facts = facts[: facts.index("\n    async def ", 10)]
        self.assertIn('avoid={head_kw} | reads["stuck"]', facts)
        self.assertIn('avoid={door} | reads["stuck"]', facts)


if __name__ == "__main__":
    unittest.main()
