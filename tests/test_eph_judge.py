"""The judge: the act timeline, the observations, and the three verdicts.

INVALID means the scenario was never reached. It never counts as a pass and
never closes anything, so every way of not reaching it has a test here.
"""

import copy
import json
import pathlib
import tempfile
import unittest
import uuid
from unittest import mock

from ephemeral import anchors, dbschema, guard, judge, lint
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = dbschema.Schema.load()
GUZZLER = loads(
    (ROOT / "data" / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml").read_text(
        encoding="utf-8"
    )
)
HANDOFF = {
    "variables": {"brd": 7, "cast": "1, 2", "cast0": 1, "Grug": 1, "Ugga": 2},
    "members": [
        {"cast_index": 0, "who": "family:grug", "guid": 1, "name": "Grug"},
        {"cast_index": 0, "who": "family:grug", "guid": 2, "name": "Ugga"},
    ],
}


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeWorld:
    """Answers SELECTs by a distinctive fragment; records every write."""

    def __init__(self, clock):
        self.clock = clock
        self.answers = []  # (fragment, fn(now) -> rows | Exception)
        self.selects = []
        self.commands = []
        self.raid_orders = []

    def answer(self, fragment, rows):
        fn = rows if callable(rows) else (lambda _now, r=rows: r)
        self.answers.append((fragment, fn))

    def select(self, sql):
        self.selects.append((self.clock.now, sql))
        for fragment, fn in self.answers:
            if fragment in sql:
                out = fn(self.clock.now)
                if isinstance(out, Exception):
                    raise out
                return out
        return []

    def db_now(self):
        return "2026-01-01 00:00:00"

    def insert_command(self, target, kind, text):
        self.commands.append((self.clock.now, target, kind, text))
        return len(self.commands)

    def enqueue_molten_core_order(self, family):
        self.raid_orders.append((self.clock.now, family))
        return len(self.raid_orders)


def guzzler_world(
    clock, patrons=(), plugger_dies_at=60, left=True, loaded=True, credited=True
):
    w = FakeWorld(clock)
    w.answer("log_encounter", [(1 if credited else 0,)])
    w.answer("overseer_dungeon_run", [(1 if loaded else 0,)])
    w.answer(
        "'Plugger Spazzring'",
        lambda now: [(1 if now >= plugger_dies_at else 0,)],
    )
    w.answer("map = 230", [] if left else [("Grug",)])
    w.answer("'Grim Patron'", [tuple(p) for p in patrons])
    w.answer("overseer_death", [])
    return w


def run(decree, world, clock, log="", handoff=HANDOFF, poll=10):
    return judge.Judge(
        decree,
        world,
        handoff,
        log_text=lambda: log,
        clock=clock.monotonic,
        sleep=clock.sleep,
        poll=poll,
        run_id="run-1",
        sha="a" * 64,
        arm="control",
    ).run()


def named(result, name):
    return next(a for a in result["assertions"] if a["name"] == name)


class VerdictTest(unittest.TestCase):
    def test_pass_when_every_precondition_and_check_holds(self):
        clock = Clock()
        world = guzzler_world(clock)
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertEqual(r["reasons"], [])
        for a in r["assertions"]:
            self.assertEqual(a["status"], "held", a["name"])

    def test_the_act_timeline_kills_plugger_then_walks_out(self):
        clock = Clock()
        world = guzzler_world(clock, plugger_dies_at=60)
        r = run(GUZZLER, world, clock)
        jobs = [(c[0], c[1], c[3]) for c in world.commands]
        # at 0s the whole family gets the dungeon job, one command per member
        self.assertEqual(jobs[0], (0.0, "Grug", "dungeon:blackrockdepths"))
        self.assertEqual(jobs[1], (0.0, "Ugga", "dungeon:blackrockdepths"))
        # the exit walk starts only after Plugger is observed dead
        quest = [j for j in jobs if j[2] == "quest"]
        self.assertEqual({j[1] for j in quest}, {"Grug", "Ugga"})
        self.assertGreaterEqual(quest[0][0], 60)
        self.assertTrue(all(c[2] == "job" for c in world.commands))
        self.assertEqual(
            [a["fired"] for a in r["acts"]], [True, True], "both steps fired"
        )

    def test_fail_when_a_patron_died_and_every_precondition_held(self):
        clock = Clock()
        world = guzzler_world(clock, patrons=[("Grim Patron", 5, 1234)])
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "FAIL")
        bad = named(r, "zero-patron-deaths")
        self.assertEqual(bad["status"], "violated")
        self.assertEqual(bad["sample"][0][0], "Grim Patron")
        self.assertEqual(named(r, "plugger-was-dead")["status"], "held")
        self.assertIn("zero-patron-deaths", " ".join(r["reasons"]))

    def test_invalid_when_the_act_precondition_never_happens(self):
        # Plugger never dies, so the exit walk never starts. The patron check
        # would "pass" (nothing died), and that must NOT be a PASS.
        clock = Clock()
        world = guzzler_world(clock, plugger_dies_at=10**9)
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "zero-patron-deaths")["status"], "held")
        self.assertEqual(named(r, "plugger-was-dead")["status"], "violated")
        self.assertFalse(r["acts"][1]["fired"])
        self.assertIn("plugger-was-dead", " ".join(r["reasons"]))
        self.assertEqual([c for c in world.commands if c[3] == "quest"], [])

    def test_invalid_beats_fail_when_a_precondition_failed(self):
        clock = Clock()
        world = guzzler_world(
            clock, patrons=[("Grim Patron", 5, 1)], loaded=False
        )  # a check failed AND the family never loaded in
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "family-loaded-inside")["status"], "violated")

    def test_invalid_when_the_family_never_left_the_instance(self):
        clock = Clock()
        world = guzzler_world(clock, left=False)
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "INVALID")

    def test_a_start_precondition_that_fails_stops_the_run_early(self):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "started-alive",
                "role": "precondition",
                "when": "start",
                "sql": "SELECT COUNT(*) FROM corpse WHERE guid = @cast0",
                "expect": {"scalar": "= 0"},
            }
        )
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("FROM corpse", [(1,)])
        r = run(d, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(world.commands, [], "no order is given in an unreached world")
        self.assertLess(clock.now, 1)

    def test_continuous_check_violation_is_a_fail(self):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "no-death-ever",
                "role": "check",
                "when": "continuous",
                "sql": "SELECT character_name FROM overseer_death WHERE created_at >= @t0",
                "expect": {"rows": 0},
            }
        )
        clock = Clock()
        world = guzzler_world(clock)
        world.answers.insert(
            0,
            (
                "character_name FROM",
                lambda now: [("Ugga",)] if 300 <= now < 310 else [],
            ),
        )
        r = run(d, world, clock)
        self.assertEqual(r["verdict"], "FAIL")
        row = named(r, "no-death-ever")
        self.assertEqual(row["status"], "violated")
        self.assertEqual(row["first_violation_s"], 300)

    def test_continuous_precondition_violation_is_invalid(self):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "stays-in-world",
                "role": "precondition",
                "when": "continuous",
                "sql": "SELECT COUNT(*) FROM characters WHERE guid IN (@cast) AND online = 1",
                "expect": {"scalar": ">= 1"},
            }
        )
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("online = 1", lambda now: [(2 if now < 200 else 0,)])
        r = run(d, world, clock)
        self.assertEqual(r["verdict"], "INVALID")


class StartWaitTest(unittest.TestCase):
    """A world's port opens before the family has logged in, so `start` waits for it."""

    def decree(self):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "cast-is-in-the-world",
                "role": "precondition",
                "when": "start",
                "sql": "SELECT COUNT(*) FROM corpse WHERE guid = @cast0",
                "expect": {"scalar": "= 1"},
            }
        )
        return d

    def run_waiting(self, world, clock, wait=600, poll=10):
        return judge.Judge(
            self.decree(),
            world,
            HANDOFF,
            log_text=lambda: "",
            clock=clock.monotonic,
            sleep=clock.sleep,
            poll=poll,
            run_id="run-1",
            sha="a" * 64,
            arm="control",
            start_wait=wait,
        ).run()

    def test_a_precondition_that_holds_a_minute_late_is_judged_not_invalid(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("FROM corpse", lambda now: [(1 if now >= 60 else 0,)])
        r = self.run_waiting(world, clock)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        self.assertGreaterEqual(r["start_wait_s"], 60)
        self.assertLess(r["start_wait_s"], 90)
        self.assertEqual(named(r, "cast-is-in-the-world")["status"], "held")

    def test_no_order_is_given_and_no_act_clock_runs_during_the_wait(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("FROM corpse", lambda now: [(1 if now >= 60 else 0,)])
        r = self.run_waiting(world, clock)
        self.assertTrue(world.commands)
        self.assertGreaterEqual(world.commands[0][0], 60, "first order after the wait")
        self.assertEqual(
            r["acts"][0]["fired_s"], 0, "the act clock starts when the wait ends"
        )

    def test_a_precondition_that_never_holds_ends_invalid_after_the_limit(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("FROM corpse", [(0,)])
        r = self.run_waiting(world, clock, wait=120)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertTrue(
            any("cast-is-in-the-world" in x for x in r["reasons"]), r["reasons"]
        )
        self.assertGreaterEqual(clock.now, 120)
        self.assertLess(clock.now, 140, "it waits the limit, not the whole window")
        self.assertEqual(world.commands, [])
        self.assertEqual(r["start_wait_s"], int(clock.now))

    def test_a_timed_out_precondition_is_retried_inside_the_wait(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer(
            "FROM corpse",
            lambda now: judge.QueryTimeout("slow") if now < 20 else [(1,)],
        )
        r = self.run_waiting(world, clock)
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_a_zero_wait_samples_once_as_before(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("FROM corpse", [(0,)])
        r = self.run_waiting(world, clock, wait=0)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertLess(clock.now, 1)

    def test_the_entry_reads_the_limit_from_the_environment(self):
        self.assertEqual(judge.start_wait_from_env({}), judge.START_WAIT_SECONDS)
        self.assertEqual(
            judge.start_wait_from_env({"EPH_START_WAIT_SECONDS": "90"}), 90
        )
        self.assertEqual(
            judge.start_wait_from_env({"EPH_START_WAIT_SECONDS": "junk"}),
            judge.START_WAIT_SECONDS,
        )
        self.assertEqual(
            judge.start_wait_from_env({"EPH_START_WAIT_SECONDS": "-5"}),
            judge.START_WAIT_SECONDS,
        )


class CastOnlineWaitTest(unittest.TestCase):
    def decree(self):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "cast-online",
                "role": "precondition",
                "when": "start",
                "online": "cast",
            }
        )
        return d

    def run_waiting(self, world, clock, wait=120):
        return judge.Judge(
            self.decree(),
            world,
            HANDOFF,
            log_text=lambda: "",
            clock=clock.monotonic,
            sleep=clock.sleep,
            poll=10,
            run_id="run-1",
            sha="a" * 64,
            arm="control",
            start_wait=wait,
        ).run()

    def test_acts_wait_until_every_cast_member_is_online(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer(
            "FROM characters", lambda now: [(1,)] if now < 60 else [(1,), (2,)]
        )
        result = self.run_waiting(world, clock)
        self.assertEqual(result["verdict"], "PASS", result["reasons"])
        self.assertGreaterEqual(result["start_wait_s"], 60)
        self.assertGreaterEqual(world.commands[0][0], 60)
        online = named(result, "cast-online")
        self.assertEqual(online["status"], "held")
        self.assertEqual(online["missing_members"], [])
        online_sql = next(sql for _, sql in world.selects if "FROM characters" in sql)
        self.assertIn("guid IN (1, 2)", online_sql)
        self.assertIn("online = 1", online_sql)

    def test_timeout_is_invalid_and_names_the_member_who_never_logged_in(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answer("FROM characters", [(1,)])
        result = self.run_waiting(world, clock, wait=120)
        self.assertEqual(result["verdict"], "INVALID")
        self.assertTrue(any("Ugga" in reason for reason in result["reasons"]))
        self.assertEqual(world.commands, [])
        self.assertGreaterEqual(result["start_wait_s"], 120)
        self.assertLess(result["start_wait_s"], 130)


class ScalarAndCreditTest(unittest.TestCase):
    def test_an_ambiguous_scalar_makes_the_run_invalid(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answers.insert(0, ("'Plugger Spazzring'", [(1,), (0,)]))
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "plugger-was-dead")["status"], "error")

    def test_a_run_with_no_encounter_credit_is_invalid_not_pass(self):
        clock = Clock()
        r = run(GUZZLER, guzzler_world(clock, credited=False), clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "encounter-credited")["status"], "violated")
        self.assertIn("encounter-credited", " ".join(r["reasons"]))

    def test_a_decree_with_an_instance_but_no_credit_observation_cannot_pass(self):
        d = copy.deepcopy(GUZZLER)
        d["observe"] = [o for o in d["observe"] if o["name"] != "encounter-credited"]
        clock = Clock()
        r = run(d, guzzler_world(clock), clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertIn("encounter credit", " ".join(r["reasons"]))

    def test_a_literal_string_spoof_of_the_table_name_is_refused(self):
        spoofs = (
            "SELECT COUNT('log_encounter') FROM characters WHERE guid IN (@cast)",
            "SELECT COUNT(*) FROM characters WHERE name <> 'log_encounter'",
            "SELECT COUNT(*) AS log_encounter FROM characters",
        )
        for sql in spoofs:
            d = copy.deepcopy(GUZZLER)
            for o in d["observe"]:
                if o["name"] == "encounter-credited":
                    o["sql"] = sql
            clock = Clock()
            r = run(d, guzzler_world(clock), clock)
            self.assertEqual(r["verdict"], "INVALID", sql)
            self.assertIn("encounter credit", " ".join(r["reasons"]), sql)

    def test_a_real_read_or_join_of_the_table_counts(self):
        reads = (
            "SELECT COUNT(*) FROM acore_characters.log_encounter WHERE map = 230 AND time >= @t0",
            "SELECT COUNT(*) FROM characters c JOIN log_encounter e ON e.map = c.map "
            "WHERE e.map = 230 AND e.time >= @t0",
            "SELECT COUNT(*) FROM `log_encounter` WHERE map = 230 AND time > @t0",
        )
        for sql in reads:
            d = copy.deepcopy(GUZZLER)
            for o in d["observe"]:
                if o["name"] == "encounter-credited":
                    o["sql"] = sql
            clock = Clock()
            r = run(d, guzzler_world(clock), clock)
            self.assertEqual(r["verdict"], "PASS", (sql, r["reasons"]))

    def credit_run(self, sql, expect, credited=True):
        d = copy.deepcopy(GUZZLER)
        for o in d["observe"]:
            if o["name"] == "encounter-credited":
                o["sql"], o["expect"] = sql, expect
        clock = Clock()
        return run(d, guzzler_world(clock, credited=credited), clock)

    BOUNDED = "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0"

    def test_an_expectation_that_holds_at_zero_is_not_credit(self):
        for expect in (
            {"scalar": ">= 0"},
            {"scalar": "<= 5"},
            {"scalar": "!= 7"},
            {"scalar": "= 0"},
            {"rows": ">= 0"},
            {"rows": "<= 1"},
        ):
            # no credits were earned, and the expectation holds anyway
            r = self.credit_run(self.BOUNDED, expect, credited=False)
            self.assertEqual(r["verdict"], "INVALID", expect)
            self.assertIn("positive", " ".join(r["reasons"]), expect)

    def test_a_positive_bounded_expectation_passes(self):
        for expect in ({"scalar": ">= 1"}, {"scalar": "> 0"}):
            r = self.credit_run(self.BOUNDED, expect)
            self.assertEqual(r["verdict"], "PASS", (expect, r["reasons"]))

    def test_rows_over_a_count_is_vacuous_and_refused(self):
        # COUNT(*) returns one row even at zero credits, so these always hold
        for expect in ({"rows": ">= 1"}, {"rows": "= 1"}):
            r = self.credit_run(self.BOUNDED, expect, credited=False)
            self.assertEqual(r["verdict"], "INVALID", expect)
            self.assertIn("positive", " ".join(r["reasons"]), expect)
        # and these can never hold over an aggregate, so the run is INVALID anyway
        for expect in ({"rows": 0}, {"rows": "<= 0"}):
            r = self.credit_run(self.BOUNDED, expect, credited=False)
            self.assertEqual(r["verdict"], "INVALID", expect)

    def test_a_row_list_query_with_rows_at_least_one_passes(self):
        sql = "SELECT creditEntry FROM log_encounter WHERE map = 230 AND time >= @t0"
        r = self.credit_run(sql, {"rows": ">= 1"})
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        for expect in ({"rows": ">= 0"}, {"rows": 0}, {"rows": "<= 3"}):
            r = self.credit_run(sql, expect)
            self.assertEqual(r["verdict"], "INVALID", expect)

    def test_a_query_not_bounded_to_this_run_is_not_credit(self):
        unbounded = (
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230",
            "SELECT COUNT(*) FROM log_encounter WHERE time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 409 AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= '2000-01-01'",
            "SELECT COUNT(*) FROM log_encounter WHERE map <> 230 AND time >= @t0",
        )
        for sql in unbounded:
            r = self.credit_run(sql, {"scalar": ">= 1"})
            self.assertEqual(r["verdict"], "INVALID", sql)
            self.assertIn("this run", " ".join(r["reasons"]), sql)

    def test_bounds_that_do_not_apply_to_every_row_are_refused(self):
        widened = (
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 OR time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE time >= @t0 OR map = 230",
            "SELECT COUNT(*) FROM log_encounter WHERE (map = 230 OR 1 = 1) AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0 OR difficulty = 0",
            "SELECT COUNT(*) FROM log_encounter WHERE NOT (map = 230 AND time >= @t0)",
            "SELECT COUNT(*) FROM log_encounter WHERE NOT map = 230 AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND NOT time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 XOR time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE (map = 230) AND (time >= @t0)",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time BETWEEN @t0 AND @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0 || 1",
            "SELECT COUNT(*) FROM log_encounter ",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0 AND guid IN (SELECT guid FROM characters)",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0 UNION ALL SELECT COUNT(*) FROM log_encounter WHERE map = 230",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0 UNION SELECT 9 FROM log_encounter",
        )
        for sql in widened:
            r = self.credit_run(sql, {"scalar": ">= 1"})
            self.assertEqual(r["verdict"], "INVALID", sql)
            self.assertIn("encounter credit", " ".join(r["reasons"]), sql)

    def test_a_self_join_or_mismatched_alias_is_not_one_bounded_read(self):
        bad = (
            "SELECT COUNT(*) FROM log_encounter e JOIN log_encounter n ON n.map = e.map WHERE e.map = 230 AND n.time >= @t0",
            "SELECT COUNT(*) FROM log_encounter JOIN log_encounter ON 1 = 1 WHERE map = 230 AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter e JOIN log_encounter n ON n.map = e.map WHERE e.map = 230 AND e.time >= @t0",
            "SELECT COUNT(*) FROM log_encounter e JOIN characters c ON c.guid = e.map WHERE c.map = 230 AND e.time >= @t0",
            "SELECT COUNT(*) FROM log_encounter e JOIN characters c ON c.guid = e.map WHERE e.map = 230 AND c.guid >= @t0",
            "SELECT COUNT(*) FROM log_encounter e JOIN characters c ON c.guid = e.map WHERE map = 230 AND e.time >= @t0",
            "SELECT COUNT(*) FROM log_encounter e WHERE x.map = 230 AND e.time >= @t0",
        )
        for sql in bad:
            r = self.credit_run(sql, {"scalar": ">= 1"})
            self.assertEqual(r["verdict"], "INVALID", sql)

    def test_both_bounds_on_the_one_alias_pass_qualified_or_unqualified(self):
        good = (
            "SELECT COUNT(*) FROM log_encounter e WHERE e.map = 230 AND e.time >= @t0",
            "SELECT COUNT(*) FROM log_encounter AS e WHERE e.time >= @t0 AND e.map = 230",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE log_encounter.map = 230 AND log_encounter.time >= @t0",
            "SELECT COUNT(*) FROM characters c JOIN log_encounter e ON e.map = c.map WHERE e.map = 230 AND e.time >= @t0",
        )
        for sql in good:
            r = self.credit_run(sql, {"scalar": ">= 1"})
            self.assertEqual(r["verdict"], "PASS", (sql, r["reasons"]))

    def test_a_plain_and_chain_with_both_bounds_passes(self):
        chains = (
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter WHERE time > @t0 AND map = 230",
            "SELECT COUNT(*) FROM log_encounter WHERE map = 230 AND difficulty = 0 AND time >= @t0",
            "SELECT COUNT(*) FROM log_encounter e WHERE e.map = 230 AND e.time >= @t0 ORDER BY e.time",
        )
        for sql in chains:
            r = self.credit_run(sql, {"scalar": ">= 1"})
            self.assertEqual(r["verdict"], "PASS", (sql, r["reasons"]))

    def test_a_bounded_positive_check_with_no_credit_is_invalid(self):
        r = self.credit_run(self.BOUNDED, {"scalar": ">= 1"}, credited=False)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "encounter-credited")["status"], "violated")

    def test_the_shipped_decree_credit_observation_meets_the_rule(self):
        r = self.credit_run(
            next(
                o["sql"]
                for o in GUZZLER["observe"]
                if o["name"] == "encounter-credited"
            ),
            next(
                o["expect"]
                for o in GUZZLER["observe"]
                if o["name"] == "encounter-credited"
            ),
        )
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_the_credit_must_come_from_the_core_log_not_a_run_flag(self):
        d = copy.deepcopy(GUZZLER)
        for o in d["observe"]:
            if o["name"] == "encounter-credited":
                o["sql"] = (
                    "SELECT COUNT(*) FROM overseer_dungeon_run WHERE outcome = 'done' "
                    "AND started_at >= @t0"
                )
        clock = Clock()
        r = run(d, guzzler_world(clock), clock)
        self.assertEqual(r["verdict"], "INVALID")

    def test_a_decree_with_no_instance_needs_no_credit(self):
        d = copy.deepcopy(GUZZLER)
        d["arrange"] = [a for a in d["arrange"] if "instance" not in a]
        d["observe"] = [o for o in d["observe"] if o["name"] != "encounter-credited"]
        clock = Clock()
        r = run(d, guzzler_world(clock), clock)
        self.assertNotIn("encounter credit", " ".join(r["reasons"]))


class TimeoutTest(unittest.TestCase):
    def test_a_check_that_times_out_is_invalid_not_pass_or_fail(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answers.insert(
            0, ("'Grim Patron'", lambda _now: judge.QueryTimeout("30s"))
        )
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        row = named(r, "zero-patron-deaths")
        self.assertEqual(row["status"], "timeout")
        self.assertIn("timed out", " ".join(r["reasons"]))

    def continuous_check(self, answers):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "no-death-ever",
                "role": "check",
                "when": "continuous",
                "sql": "SELECT character_name FROM overseer_death WHERE created_at >= @t0",
                "expect": {"rows": 0},
            }
        )
        clock = Clock()
        world = guzzler_world(clock)
        world.answers.insert(0, ("character_name FROM", lambda now: answers(now)))
        return run(d, world, clock)

    def test_a_timeout_is_sticky_and_a_later_violation_cannot_make_it_a_fail(self):
        def answers(now):
            if now == 100:
                return judge.QueryTimeout("30s")
            return [("Ugga",)] if now >= 300 else []

        r = self.continuous_check(answers)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "no-death-ever")["status"], "timeout")

    def test_a_timeout_after_a_violation_is_still_invalid(self):
        def answers(now):
            if now == 200:
                return judge.QueryTimeout("30s")
            return [("Ugga",)] if now >= 100 else []

        r = self.continuous_check(answers)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "no-death-ever")["status"], "timeout")

    def test_a_timeout_followed_by_clean_samples_stays_invalid(self):
        r = self.continuous_check(
            lambda now: judge.QueryTimeout("30s") if now == 100 else []
        )
        self.assertEqual(r["verdict"], "INVALID")

    def test_a_precondition_that_times_out_is_invalid(self):
        clock = Clock()
        world = guzzler_world(clock)
        world.answers.insert(
            0, ("overseer_dungeon_run", lambda _now: judge.QueryTimeout("30s"))
        )
        r = run(GUZZLER, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "family-loaded-inside")["status"], "timeout")

    def test_a_waited_for_observation_that_never_comes_runs_out_the_window(self):
        clock = Clock()
        world = guzzler_world(clock, plugger_dies_at=10**9)
        run(GUZZLER, world, clock)
        self.assertGreaterEqual(clock.now, 20 * 60)
        self.assertLess(clock.now, 20 * 60 + 11)


class RaidOrderActTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.world = guzzler_world(self.clock)
        self.decree = copy.deepcopy(GUZZLER)
        self.decree["world"]["bridge"] = "on"
        self.decree["cast"][0]["who"] = "Grug"
        self.decree["act"] = [{"at": "10s", "raid_order": {"family": "Grug"}}]
        self.handoff = copy.deepcopy(HANDOFF)
        self.handoff["members"][0]["who"] = "Grug"

    def lint_errors(self):
        return [
            str(finding)
            for finding in lint.lint_document(self.decree, anchors.Anchors({}), SCHEMA)
            if finding.level == "error" and finding.path.startswith("decree.act")
        ]

    def test_named_family_uses_campaign_queue_at_the_scheduled_time(self):
        self.assertEqual(self.lint_errors(), [])
        result = run(self.decree, self.world, self.clock, handoff=self.handoff)
        self.assertEqual(result["verdict"], "PASS", result["reasons"])
        self.assertEqual(self.world.raid_orders, [(10, "Grug")])
        self.assertEqual(self.world.commands, [])

    def test_raid_order_requires_a_bridge_and_one_named_cast_family(self):
        for bridge, family in (("off", "Grug"), ("on", "Ugga"), ("on", "family:grug")):
            with self.subTest(bridge=bridge, family=family):
                self.decree["world"]["bridge"] = bridge
                self.decree["act"][0]["raid_order"]["family"] = family
                self.assertTrue(self.lint_errors())

    def test_two_raid_orders_are_rejected(self):
        self.decree["act"] *= 2
        self.assertIn("one raid order", "\n".join(self.lint_errors()))

    def test_family_selected_only_by_group_never_gets_a_queue_order(self):
        result = run(self.decree, self.world, self.clock)
        self.assertEqual(result["verdict"], "INVALID")
        self.assertEqual(self.world.raid_orders, [])

    def test_command_kind_cannot_take_the_typed_queue_path(self):
        self.decree["act"] = [
            {
                "at": "0s",
                "command": {"who": "Grug", "kind": "raid_order", "text": "moltencore"},
            }
        ]
        result = run(self.decree, self.world, self.clock, handoff=self.handoff)
        self.assertEqual(result["verdict"], "INVALID")
        self.assertEqual(self.world.raid_orders, [])

    def test_rehearsal_distinguishes_refused_accepted_and_unconsumed_orders(self):
        decree_file = ROOT / "data/decrees/molten-core-order-refuses-unavailable.yaml"
        decree = loads(decree_file.read_text(encoding="utf-8"))
        self.handoff["members"][1].update(who="Ugga", cast_index=1)
        self.handoff["variables"]["cast1"] = 2
        scenarios = (
            (
                "PASS",
                "wow-overseer INFO queue: Grug's family: withheld: Molten Core refused: "
                "1 of 40 approved members unavailable: Ugga (level 49; needs 50)",
                0,
            ),
            (
                "FAIL",
                "wow-overseer INFO raid: Grug's family ordered into moltencore - "
                "2 seats written in 1 groups, 2 job row(s) of 2.",
                2,
            ),
            ("INVALID", "", 0),
        )
        for verdict, log, jobs_written in scenarios:
            with self.subTest(verdict=verdict):
                clock = Clock()
                world = FakeWorld(clock)
                world.answer("AND online = 1", [(1,), (2,)])
                world.answer("JOIN guild_member", [(2,)])
                world.answer("status IN ('queued', 'active')", [(0,)])
                world.answer("status IN ('pending', 'claimed', 'verifying')", [(0,)])
                world.answer(
                    "AND written_at >= ",
                    lambda _, w=world, jobs=jobs_written: [
                        (2 if w.raid_orders and jobs else 0,)
                    ],
                )
                world.answer(
                    "runs_wanted = 1", lambda _, w=world: [(len(w.raid_orders),)]
                )
                world.answer("c.source = 'overseer:queue'", [(jobs_written,)])
                world.answer("started_at IS NULL", [(int(jobs_written == 0),)])
                result = run(decree, world, clock, log=log, handoff=self.handoff)
                self.assertEqual(result["verdict"], verdict, result["reasons"])
                self.assertEqual(world.raid_orders, [(0, "Grug")])
                self.assertEqual(world.commands, [])


class SafetyTest(unittest.TestCase):
    def one_check(self, sql):
        d = copy.deepcopy(GUZZLER)
        d["observe"][-1]["sql"] = sql
        return d

    def test_an_observation_that_writes_is_refused_and_never_executed(self):
        for sql in (
            "DELETE FROM characters WHERE guid = 1",
            "SELECT 1; DROP TABLE characters",
            "SELECT 1 INTO OUTFILE 'x'",
        ):
            clock = Clock()
            world = guzzler_world(clock)
            r = run(self.one_check(sql), world, clock)
            self.assertEqual(r["verdict"], "INVALID", sql)
            self.assertEqual(
                [s for _, s in world.selects if "DELETE" in s or "DROP" in s], []
            )

    def test_an_unknown_variable_is_invalid(self):
        clock = Clock()
        world = guzzler_world(clock)
        r = run(
            self.one_check("SELECT name FROM characters WHERE guid = @nobody"),
            world,
            clock,
        )
        self.assertEqual(r["verdict"], "INVALID")
        self.assertIn("nobody", " ".join(r["reasons"]))

    def test_the_only_writes_are_job_commands(self):
        clock = Clock()
        world = guzzler_world(clock)
        run(GUZZLER, world, clock)
        self.assertTrue(world.commands)
        self.assertEqual({c[2] for c in world.commands}, {"job"})

    def test_a_gm_command_is_never_queued(self):
        d = copy.deepcopy(GUZZLER)
        d["act"] = [
            {"at": "0s", "command": {"who": "Grug", "kind": "gm", "text": ".die"}}
        ]
        clock = Clock()
        world = guzzler_world(clock)
        r = run(d, world, clock)
        self.assertEqual(world.commands, [])
        self.assertEqual(r["verdict"], "INVALID")

    def test_an_act_target_the_seed_did_not_resolve_is_invalid(self):
        d = copy.deepcopy(GUZZLER)
        d["act"] = [{"at": "0s", "roster": {"who": "family:zug", "job": "quest"}}]
        clock = Clock()
        world = guzzler_world(clock)
        r = run(d, world, clock)
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(world.commands, [])

    def test_a_missing_seed_handoff_is_invalid(self):
        clock = Clock()
        r = run(GUZZLER, guzzler_world(clock), clock, handoff=None)
        self.assertEqual(r["verdict"], "INVALID")


class LogAssertionTest(unittest.TestCase):
    def decree(self, count):
        d = copy.deepcopy(GUZZLER)
        d["observe"].append(
            {
                "name": "no-ghost-loop",
                "role": "check",
                "log": {"pattern": "ghost.*retry", "expect": {"count": count}},
            }
        )
        return d

    def test_a_log_pattern_is_counted_and_the_lines_are_evidence(self):
        log = "ok\nghost loop retry 1\nfine\nghost loop retry 2\n"
        clock = Clock()
        r = run(self.decree(0), guzzler_world(clock), clock, log=log)
        self.assertEqual(r["verdict"], "FAIL")
        row = named(r, "no-ghost-loop")
        self.assertEqual(row["observed"], "count=2")
        self.assertEqual(row["matched"], ["ghost loop retry 1", "ghost loop retry 2"])

    def test_an_unreadable_log_is_invalid_never_zero_matches(self):
        def broken():
            raise judge.JudgeError("worldserver log unreadable")

        clock = Clock()
        r = judge.Judge(
            self.decree(0),
            guzzler_world(clock),
            HANDOFF,
            log_text=broken,
            clock=clock.monotonic,
            sleep=clock.sleep,
        ).run()
        self.assertEqual(r["verdict"], "INVALID")
        self.assertEqual(named(r, "no-ghost-loop")["status"], "error")

    def test_a_missing_log_path_refuses(self):
        with self.assertRaises(judge.JudgeError):
            judge._read_log(None)
        with self.assertRaises(judge.JudgeError):
            judge._read_log("/no/such/world.log")

    def test_a_clean_log_passes(self):
        clock = Clock()
        r = run(self.decree(0), guzzler_world(clock), clock, log="all quiet\n")
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_an_unwitnessed_scenario_is_invalid_even_when_an_outcome_check_fails(self):
        d = self.bounded({"at_least": 1})
        observation = d["observe"][-1]
        observation.update(name="observed-encounter", role="precondition", when="end")
        observation["log"]["pattern"] = "the family entered the hall"
        for log, patrons, verdict in (
            ("", [("Grim Patron", 5, 1234)], "INVALID"),
            ("the family entered the hall", [("Grim Patron", 5, 1234)], "FAIL"),
            ("the family entered the hall", [], "PASS"),
        ):
            with self.subTest(log=log, verdict=verdict):
                clock = Clock()
                world = guzzler_world(clock, patrons=patrons)
                result = run(d, world, clock, log=log)
                self.assertEqual(result["verdict"], verdict, result["reasons"])
                if verdict == "INVALID":
                    self.assertIn(
                        "precondition observed-encounter", result["reasons"][0]
                    )

    def bounded(self, expect):
        d = self.decree(0)
        d["observe"][-1]["log"]["expect"] = expect
        return d

    def verdict(self, expect, log):
        clock = Clock()
        r = run(self.bounded(expect), guzzler_world(clock), clock, log=log)
        return r["verdict"], named(r, "no-ghost-loop")

    def test_a_required_line_that_is_absent_fails(self):
        # #2767: a log check could only forbid a line. at_least requires one.
        verdict, row = self.verdict({"at_least": 1}, "all quiet\n")
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(row["status"], "violated")
        self.assertEqual(row["observed"], "count=0")

    def test_a_required_line_present_often_enough_passes(self):
        log = "ghost loop retry 1\nfine\nghost loop retry 2\nghost retry 3\n"
        verdict, row = self.verdict({"at_least": 2}, log)
        self.assertEqual(verdict, "PASS")
        self.assertEqual(row["status"], "held")
        self.assertEqual(row["observed"], "count=3")
        verdict, _ = self.verdict({"at_least": 4}, log)
        self.assertEqual(verdict, "FAIL")

    def test_at_most_holds_up_to_the_bound_and_not_past_it(self):
        log = "ghost retry 1\nghost retry 2\n"
        self.assertEqual(self.verdict({"at_most": 2}, log)[0], "PASS")
        self.assertEqual(self.verdict({"at_most": 2}, "quiet\n")[0], "PASS")
        self.assertEqual(self.verdict({"at_most": 1}, log)[0], "FAIL")

    def test_exactly_is_the_exact_count_under_its_own_name(self):
        log = "ghost retry 1\nghost retry 2\n"
        self.assertEqual(self.verdict({"exactly": 2}, log)[0], "PASS")
        self.assertEqual(self.verdict({"exactly": 1}, log)[0], "FAIL")
        self.assertEqual(self.verdict({"exactly": 3}, log)[0], "FAIL")

    def test_at_least_and_at_most_together_are_a_range(self):
        log = "ghost retry 1\nghost retry 2\n"
        both = {"at_least": 1, "at_most": 2}
        self.assertEqual(self.verdict(both, log)[0], "PASS")
        self.assertEqual(self.verdict(both, "quiet\n")[0], "FAIL")
        self.assertEqual(self.verdict(both, log + "ghost retry 3\n")[0], "FAIL")

    def test_count_still_means_exactly(self):
        log = "ghost retry 1\n"
        self.assertEqual(self.verdict({"count": 1}, log)[0], "PASS")
        self.assertEqual(self.verdict({"count": 0}, log)[0], "FAIL")
        self.assertEqual(self.verdict({"count": 2}, log)[0], "FAIL")

    def test_a_bound_the_judge_cannot_read_is_invalid_never_a_pass(self):
        # The lint refuses these first; a judge handed one anyway must not
        # read an unknown bound as held.
        for expect in ({}, {"about": 1}, {"at_least": "one"}, {"at_least": -1}):
            verdict, row = self.verdict(expect, "ghost retry 1\n")
            self.assertEqual(verdict, "INVALID", expect)
            self.assertEqual(row["status"], "error", expect)

    def test_every_shipped_decree_keeps_its_exact_count_verdict(self):
        # #2767 regression: the rule before bounds was `matches == count`. Every
        # log check shipped on main must still hold and fail at the same counts.
        folder = pathlib.Path(__file__).resolve().parent.parent / "data" / "decrees"
        seen = 0
        for path in sorted(folder.glob("*.yaml")):
            if path.name == "anchors.yaml":
                continue
            decree = loads(path.read_text(encoding="utf-8"))
            for o in decree.get("observe") or []:
                if "log" not in o:
                    continue
                expect = o["log"]["expect"]
                if set(expect) != {"count"}:
                    continue
                seen += 1
                for n in range(expect["count"] + 4):
                    self.assertEqual(
                        judge.log_bound_holds(expect, n),
                        n == expect["count"],
                        f"{path.name} {o['name']} at {n} matches",
                    )
        self.assertGreater(seen, 0, "no shipped decree carries an exact log count")

    def test_matched_lines_are_capped_and_truncated(self):
        log = "\n".join("ghost retry " + "x" * 1000 for _ in range(100))
        clock = Clock()
        r = run(self.decree(0), guzzler_world(clock), clock, log=log)
        row = named(r, "no-ghost-loop")
        self.assertEqual(row["observed"], "count=100")
        self.assertEqual(len(row["matched"]), judge.MAX_MATCHED_LINES)
        self.assertLessEqual(len(row["matched"][0]), judge.MAX_CELL_CHARS)


class ExpectTest(unittest.TestCase):
    def test_rows_and_scalar_forms(self):
        ok = judge.expectation_holds
        self.assertTrue(ok({"rows": 0}, [])[0])
        self.assertFalse(ok({"rows": 0}, [(1,)])[0])
        self.assertTrue(ok({"rows": ">=1"}, [(1,)])[0])
        self.assertTrue(ok({"rows": "> 1"}, [(1,), (2,)])[0])
        self.assertTrue(ok({"scalar": ">= 1"}, [(3,)])[0])
        self.assertFalse(ok({"scalar": "= 1"}, [(2,)])[0])
        self.assertTrue(ok({"scalar": "> 0"}, [(0.5,)])[0])

    def test_a_null_scalar_never_holds(self):
        self.assertFalse(judge.expectation_holds({"scalar": "= 0"}, [(None,)])[0])

    def test_a_scalar_needs_exactly_one_row_and_one_column(self):
        # [(1,), (0,)] must not read as held because the first row happens to pass
        for rows in ([], [(1,), (0,)], [(1, 0)], [(1,), (1,)]):
            with self.assertRaises(judge.JudgeError, msg=str(rows)):
                judge.expectation_holds({"scalar": ">= 1"}, rows)


class EvidenceTest(unittest.TestCase):
    def test_the_evidence_names_the_decree_the_run_and_the_rendered_sql(self):
        clock = Clock()
        r = run(GUZZLER, guzzler_world(clock), clock)
        self.assertEqual(r["decree"], "brd-guzzler-exit-zero-patron-deaths")
        self.assertEqual(r["decree_sha256"], "a" * 64)
        self.assertEqual((r["run_id"], r["arm"]), ("run-1", "control"))
        row = named(r, "plugger-was-dead")
        self.assertIn("r.instanceId = 7", row["sql"])  # @brd filled in
        self.assertNotIn("@", row["sql"])
        self.assertEqual(row["role"], "precondition")
        self.assertEqual(row["expect"], {"scalar": "= 1"})
        self.assertEqual(row["observed"], "scalar=1")
        self.assertEqual(r["t0"], "2026-01-01 00:00:00")

    def test_samples_are_capped_and_cells_truncated(self):
        rows = [("Grim Patron" + "y" * 900, i, 1) for i in range(100)]
        clock = Clock()
        r = run(GUZZLER, guzzler_world(clock, patrons=rows), clock)
        row = named(r, "zero-patron-deaths")
        self.assertEqual(row["observed"], "rows=100")
        self.assertEqual(len(row["sample"]), judge.MAX_SAMPLE_ROWS)
        self.assertLessEqual(len(row["sample"][0][0]), judge.MAX_CELL_CHARS)

    def test_the_result_is_json_and_fits_the_configmap_cap(self):
        big = [("p" * 500, i, 1) for i in range(5000)]
        clock = Clock()
        r = run(GUZZLER, guzzler_world(clock, patrons=big), clock)
        body = judge.encode_result(r)
        self.assertLessEqual(len(body.encode("utf-8")), judge.RESULT_CAP_BYTES)
        self.assertEqual(json.loads(body)["verdict"], "FAIL")

    def test_an_oversize_result_keeps_the_verdict_and_says_it_was_cut(self):
        r = {
            "verdict": "FAIL",
            "reasons": ["r" * 1000] * 400,
            "assertions": [
                {
                    "name": f"a{i}",
                    "sample": [["x" * 300]] * 20,
                    "matched": ["m" * 300] * 20,
                }
                for i in range(200)
            ],
            "acts": [],
        }
        body = judge.encode_result(r)
        self.assertLessEqual(len(body.encode("utf-8")), judge.RESULT_CAP_BYTES)
        doc = json.loads(body)
        self.assertEqual(doc["verdict"], "FAIL")
        self.assertTrue(doc["truncated"])

    def test_the_configmap_carries_verdict_labels_and_the_json(self):
        clock = Clock()
        r = run(GUZZLER, guzzler_world(clock), clock)
        cm = judge.result_configmap(r, namespace="eph-ns")
        self.assertEqual(cm["metadata"]["name"], "eph-result-run-1")
        self.assertEqual(cm["metadata"]["namespace"], "eph-ns")
        self.assertEqual(cm["metadata"]["labels"]["eph/arm"], "control")
        self.assertEqual(
            cm["metadata"]["labels"]["eph/decree"],
            "brd-guzzler-exit-zero-patron-deaths",
        )
        self.assertEqual(cm["metadata"]["labels"]["eph/verdict"], "PASS")
        self.assertEqual(cm["data"]["verdict"], "PASS")
        self.assertEqual(json.loads(cm["data"]["result.json"])["verdict"], "PASS")

    def test_a_long_decree_id_still_makes_a_valid_label(self):
        r = {"verdict": "PASS", "decree": "d" * 90, "arm": "treatment", "run_id": "r"}
        label = judge.result_configmap(r, namespace="n")["metadata"]["labels"][
            "eph/decree"
        ]
        self.assertLessEqual(len(label), 63)
        self.assertRegex(label, r"^[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?$")


class FakeHttp:
    def __init__(self, status=201):
        self.status = status
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.status, b"{}"


def fresh_marker():
    """A unique throwaway string made at run time, so no fixed value sits in the file."""
    return uuid.uuid4().hex


class ConfigMapStoreTest(unittest.TestCase):
    def setUp(self):
        self.marker = fresh_marker()

    def store(self, http):
        return judge.ConfigMapStore(
            "https://api.example.invalid", self.marker, "eph-ns", http
        )

    def cm(self, name="eph-result-run-1"):
        return {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": "eph-ns"},
            "data": {"verdict": "PASS"},
        }

    def test_creates_the_result_in_its_own_namespace_only(self):
        http = FakeHttp()
        self.store(http).write(self.cm())
        method, url, headers, body = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            url, "https://api.example.invalid/api/v1/namespaces/eph-ns/configmaps"
        )
        # built from whatever the store was given, and nothing else
        self.assertEqual(headers["Authorization"], "Bearer " + self.marker)
        self.assertEqual(json.loads(body)["metadata"]["name"], "eph-result-run-1")

    def test_reads_the_rotated_projected_token_for_each_attempt(self):
        first, second = fresh_marker(), fresh_marker()
        http = mock.Mock(side_effect=[(503, b"{}"), (201, b"{}")])
        env = {
            "KUBERNETES_SERVICE_HOST": "api.example.invalid",
            "KUBERNETES_SERVICE_PORT": "443",
        }
        with tempfile.TemporaryDirectory() as directory:
            token = pathlib.Path(directory) / "token"
            token.write_text(self.marker, encoding="utf-8")
            with mock.patch.object(judge, "urllib_http", return_value=http):
                store = judge.ConfigMapStore.in_cluster("eph-ns", env, directory)
            token.write_text(first + "\n", encoding="utf-8")
            store.sleep = lambda _: token.write_text(second, encoding="utf-8")
            store.log = mock.Mock()
            store.write(self.cm())

        self.assertEqual(
            [call.args[2]["Authorization"] for call in http.call_args_list],
            [f"Bearer {first}", f"Bearer {second}"],
        )

    def test_refuses_any_other_name_or_namespace(self):
        http = FakeHttp()
        s = self.store(http)
        with self.assertRaises(judge.JudgeError):
            s.write(self.cm("eph-harness"))
        other = self.cm()
        other["metadata"]["namespace"] = "another-ns"
        with self.assertRaises(judge.JudgeError):
            s.write(other)
        with self.assertRaises(judge.JudgeError):
            s.write({**self.cm(), "kind": "Secret"})
        self.assertEqual(http.calls, [])

    def test_a_refused_write_raises(self):
        with self.assertRaises(judge.JudgeError):
            self.store(FakeHttp(status=403)).write(self.cm())

    def test_the_marker_never_reaches_an_error_or_the_body(self):
        http = FakeHttp(status=403)
        with self.assertRaises(judge.JudgeError) as cm:
            self.store(http).write(self.cm())
        self.assertNotIn(self.marker, str(cm.exception))
        self.assertNotIn(self.marker, http.calls[0][3].decode("utf-8"))
        self.assertNotIn(self.marker, repr(self.store(http).namespace))


class FlakyHttp:
    """Scripted answers: an exception is raised, an int is a status."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        step = self.script.pop(0) if self.script else 201
        if isinstance(step, Exception):
            raise step
        return step, b"{}"


class WriteRetryTest(unittest.TestCase):
    def store(self, http, **kw):
        self.slept = []
        self.lines = []
        return judge.ConfigMapStore(
            "https://api.example.invalid",
            "t",
            "eph-ns",
            http,
            sleep=self.slept.append,
            log=self.lines.append,
            **kw,
        )

    def cm(self):
        return {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "eph-result-run-1", "namespace": "eph-ns"},
            "data": {"verdict": "PASS"},
        }

    def test_two_connect_timeouts_then_success_writes_the_result(self):
        http = FlakyHttp(TimeoutError("timed out"), OSError("unreachable"), 201)
        self.store(http).write(self.cm())
        self.assertEqual(len(http.calls), 3)
        self.assertEqual(len(self.slept), 2)
        self.assertEqual(len(self.lines), 2, "each failed attempt is printed")
        self.assertIn("attempt 1", self.lines[0])

    def test_the_backoff_grows_and_is_capped(self):
        http = FlakyHttp(*[TimeoutError("t")] * 8, 201)
        self.store(http, retry_seconds=10_000).write(self.cm())
        self.assertEqual(self.slept, sorted(self.slept))
        self.assertLessEqual(max(self.slept), judge.WRITE_BACKOFF_CAP)
        self.assertGreater(self.slept[-1], self.slept[0])

    def test_a_server_error_or_throttle_is_retried(self):
        http = FlakyHttp(503, 429, 201)
        self.store(http).write(self.cm())
        self.assertEqual(len(http.calls), 3)

    def test_a_client_refusal_is_not_retried(self):
        http = FlakyHttp(403, 201)
        with self.assertRaises(judge.JudgeError):
            self.store(http).write(self.cm())
        self.assertEqual(len(http.calls), 1)

    def test_already_exists_after_a_lost_answer_counts_as_written(self):
        http = FlakyHttp(TimeoutError("t"), 409)
        self.store(http).write(self.cm())
        self.assertEqual(len(http.calls), 2)

    def test_a_first_attempt_conflict_is_still_an_error(self):
        with self.assertRaises(judge.JudgeError):
            self.store(FlakyHttp(409)).write(self.cm())

    def test_it_gives_up_after_the_limit_with_a_judge_error(self):
        http = FlakyHttp(*[TimeoutError("t")] * 1000)
        with self.assertRaises(judge.JudgeError) as cm:
            self.store(http, retry_seconds=60).write(self.cm())
        self.assertIn("attempts", str(cm.exception))
        self.assertLessEqual(sum(self.slept), 60)

    def test_a_failing_write_leaves_the_whole_result_in_the_log(self):
        out = []

        class Dead:
            def write(self, cm):
                raise judge.JudgeError("result not written after 5 attempts")

        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            handoff = d / "handoff.json"
            handoff.write_text(json.dumps(HANDOFF), encoding="utf-8")
            rc = judge.run(
                str(
                    ROOT
                    / "data"
                    / "decrees"
                    / "brd-guzzler-exit-zero-patron-deaths.yaml"
                ),
                {**RunEntryTest.ENV, "EPH_VARS_FILE": str(handoff)},
                connect=lambda **kw: ScriptedConn(),
                store=Dead(),
                log_path=str(d / "world.log"),
                out=out.append,
                clock=Clock(),
            )
        self.assertEqual(rc, 2)
        full = json.loads(out[-1])
        self.assertIn(full["verdict"], ("PASS", "FAIL", "INVALID"))
        self.assertEqual(full["run_id"], "run-9")


class InClusterTest(unittest.TestCase):
    def test_the_api_server_address_comes_from_the_pod_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "token").write_text(fresh_marker(), encoding="utf-8")
            store = judge.ConfigMapStore.in_cluster(
                "eph-ns",
                {
                    "KUBERNETES_SERVICE_HOST": "192.0.2.1",
                    "KUBERNETES_SERVICE_PORT": "443",
                },
                sa_dir=d,
            )
        self.assertEqual(store.base_url, "https://192.0.2.1:443")

    def test_an_ipv6_host_is_bracketed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "token").write_text(fresh_marker(), encoding="utf-8")
            store = judge.ConfigMapStore.in_cluster(
                "n",
                {
                    "KUBERNETES_SERVICE_HOST": "2001:db8::1",
                    "KUBERNETES_SERVICE_PORT": "443",
                },
                sa_dir=d,
            )
        self.assertEqual(store.base_url, "https://[2001:db8::1]:443")

    def test_a_missing_host_or_port_refuses(self):
        for env in (
            {},
            {"KUBERNETES_SERVICE_HOST": "192.0.2.1"},
            {"KUBERNETES_SERVICE_PORT": "443"},
            {"KUBERNETES_SERVICE_HOST": "", "KUBERNETES_SERVICE_PORT": "443"},
        ):
            with self.assertRaises(judge.JudgeError, msg=str(env)):
                judge.ConfigMapStore.in_cluster("n", env)

    def test_no_api_server_address_is_written_into_the_source(self):
        src = (ROOT / "ephemeral" / "judge.py").read_text(encoding="utf-8")
        self.assertNotIn("kubernetes.default", src)


class GuardedWorldDbTest(unittest.TestCase):
    def test_a_raw_connection_is_not_accepted(self):
        with self.assertRaises(guard.GuardError):
            judge.GuardedWorldDb(object(), SCHEMA)

    def test_commands_and_selects_go_through_the_guard(self):
        conn = ScriptedConn()
        g = guard.open_guarded(
            guard.GuardInputs("127.0.0.1", "ephemeral", "grants: enabled"),
            lambda **kw: conn,
            SCHEMA,
        )
        db = judge.GuardedWorldDb(g, SCHEMA)
        db.insert_command("Grug", "job", "quest")
        self.assertEqual(
            conn.writes, [(guard.COMMAND_SQL, ("Grug", "quest", "job", "eph-judge"))]
        )
        self.assertEqual(db.select("SELECT COUNT(*) FROM characters"), [(1,)])
        with self.assertRaises(judge.JudgeError):
            db.select("SELECT 1; DELETE FROM characters WHERE guid = 1")
        with self.assertRaises(guard.GuardError):
            db.insert_command("Grug", "gm", ".die")
        with self.assertRaises(guard.GuardError):
            db.insert_command("Grug", "job", "quest'); DROP TABLE x; --")
        self.assertEqual(len(conn.writes), 1)
        # The playerbots go command separates x;y with a semicolon; the guard must pass it.
        db.insert_command("Uzza", "bot", "go -6968.6;-2274.1")
        self.assertEqual(
            conn.writes[1][1], ("Uzza", "go -6968.6;-2274.1", "bot", "eph-judge")
        )

    def test_a_server_side_timeout_becomes_a_query_timeout(self):
        conn = ScriptedConn()
        conn.fail_select = (3024, "Query execution was interrupted")
        g = guard.open_guarded(
            guard.GuardInputs("127.0.0.1", "ephemeral", "grants: enabled"),
            lambda **kw: conn,
            SCHEMA,
        )
        with self.assertRaises(judge.QueryTimeout):
            judge.GuardedWorldDb(g, SCHEMA).select("SELECT COUNT(*) FROM characters")


try:  # the world image carries pymysql; the unit suite may not
    from pymysql.err import OperationalError
except ImportError:  # same shape: an Exception whose args are (code, message)

    class OperationalError(Exception):
        pass


class ScriptedConn:
    def __init__(self):
        self.writes = []
        self.fail_select = None
        self.last = None

    def cursor(self):
        return ScriptedCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class ScriptedCursor:
    lastrowid = 9

    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, sql, params=None):
        if sql == guard.MARKER_SQL:
            self.rows = [(1,)]
        elif sql == guard.COMMAND_SQL:
            self.conn.writes.append((sql, params))
        elif sql.startswith("SELECT"):
            if self.conn.fail_select:
                raise OperationalError(*self.conn.fail_select)
            self.rows = [(1,)]

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class SnapshotConn(ScriptedConn):
    """MySQL's default REPEATABLE READ: the first read freezes what later reads see
    until the transaction ends (commit or rollback)."""

    def __init__(self):
        super().__init__()
        self.live = 0
        self.frozen = None

    def cursor(self):
        return SnapshotCursor(self)

    def commit(self):
        self.frozen = None

    rollback = commit


class SnapshotCursor(ScriptedCursor):
    def execute(self, sql, params=None):
        if sql.startswith("SELECT COUNT") and "FROM characters" in sql:
            if self.conn.frozen is None:
                self.conn.frozen = self.conn.live
            self.rows = [(self.conn.frozen,)]
        else:
            super().execute(sql, params)


class ReadSnapshotTest(unittest.TestCase):
    """A judge that polls for the family to log in must see rows written after its first read."""

    def test_a_later_read_sees_rows_written_after_the_first(self):
        conn = SnapshotConn()
        g = guard.open_guarded(
            guard.GuardInputs("127.0.0.1", "ephemeral", "grants: enabled"),
            lambda **kw: conn,
            SCHEMA,
        )
        db = judge.GuardedWorldDb(g, SCHEMA)
        sql = "SELECT COUNT(*) FROM characters"
        self.assertEqual(db.select(sql), [(0,)])
        conn.live = 1  # the family logs in
        self.assertEqual(db.select(sql), [(1,)])


class RunEntryTest(unittest.TestCase):
    ENV = {
        "EPH_MYSQL_HOST": "127.0.0.1",
        "EPH_WORLD_LABEL": "ephemeral",
        "EPH_HARNESS_GRANTS": "grants: enabled",
        "EPH_RUN_ID": "run-9",
        "EPH_ARM": "treatment",
        "EPH_NAMESPACE": "eph-ns",
    }

    def run_entry(self, env, with_handoff=True):
        out = []
        calls = []
        stored = []

        class Store:
            def write(self, cm):
                stored.append(cm)

        def connect(**kw):
            calls.append(kw)
            return ScriptedConn()

        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            path = (
                ROOT / "data" / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"
            )
            handoff = d / "handoff.json"
            if with_handoff:
                handoff.write_text(json.dumps(HANDOFF), encoding="utf-8")
            rc = judge.run(
                str(path),
                {**env, "EPH_VARS_FILE": str(handoff)},
                connect=connect,
                store=Store(),
                log_path=str(d / "world.log"),
                out=out.append,
                clock=Clock(),
            )
        return rc, calls, stored, "\n".join(out)

    def test_a_foreign_host_writes_an_invalid_result_and_never_connects(self):
        rc, calls, stored, text = self.run_entry(
            {**self.ENV, "EPH_MYSQL_HOST": "mysql"}
        )
        self.assertEqual(calls, [])
        self.assertEqual(
            rc, 0, "a verdict is data; only a broken harness exits non-zero"
        )
        self.assertEqual(stored[0]["data"]["verdict"], "INVALID")
        self.assertIn("guard refused", text)

    def test_an_unreadable_decree_path_still_writes_an_invalid_result(self):
        stored = []

        class Store:
            def write(self, cm):
                stored.append(cm)

        rc = judge.run(
            str(ROOT / "data" / "decrees" / "no-such-decree.yaml"),
            self.ENV,
            connect=lambda **kw: ScriptedConn(),
            store=Store(),
            out=lambda _line: None,
            clock=Clock(),
        )
        self.assertEqual((rc, stored[0]["data"]["verdict"]), (0, "INVALID"))

    def test_missing_api_server_environment_is_invalid_and_exits_2(self):
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            handoff = pathlib.Path(tmp) / "h.json"
            handoff.write_text(json.dumps(HANDOFF), encoding="utf-8")
            rc = judge.run(
                str(
                    ROOT
                    / "data"
                    / "decrees"
                    / "brd-guzzler-exit-zero-patron-deaths.yaml"
                ),
                {**self.ENV, "EPH_VARS_FILE": str(handoff)},
                connect=lambda **kw: ScriptedConn(),
                out=out.append,
                clock=Clock(),
            )
        text = "\n".join(out)
        self.assertEqual(rc, 2)
        self.assertIn("INVALID", text)
        self.assertIn("KUBERNETES_SERVICE_HOST", text)

    def test_a_missing_handoff_writes_an_invalid_result(self):
        rc, _, stored, _ = self.run_entry(self.ENV, with_handoff=False)
        self.assertEqual((rc, stored[0]["data"]["verdict"]), (0, "INVALID"))

    def test_a_store_that_fails_is_a_broken_harness(self):
        class Broken:
            def write(self, cm):
                raise judge.JudgeError("no")

        out = []
        with tempfile.TemporaryDirectory() as tmp:
            rc = judge.run(
                str(
                    ROOT
                    / "data"
                    / "decrees"
                    / "brd-guzzler-exit-zero-patron-deaths.yaml"
                ),
                {**self.ENV, "EPH_MYSQL_HOST": "mysql"},
                connect=lambda **kw: ScriptedConn(),
                store=Broken(),
                log_path=str(pathlib.Path(tmp) / "x"),
                out=out.append,
                clock=Clock(),
            )
        self.assertEqual(rc, 2)


class CliAndSeedTest(unittest.TestCase):
    def test_the_judge_is_a_subcommand(self):
        from ephemeral.__main__ import main

        with self.assertRaises(SystemExit) as cm:
            main(["judge", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_the_seed_hands_its_variables_and_cast_to_the_judge(self):
        from ephemeral import seedrun
        from ephemeral.compiler import Member, SeedPlan

        plan = SeedPlan(
            variables={"brd": 7, "cast": "1"},
            members=[Member(0, "family:grug", 1, "Grug")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "h.json"
            seedrun.write_handoff(str(p), plan)
            doc = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(doc["variables"]["brd"], 7)
        self.assertEqual(
            doc["members"],
            [{"cast_index": 0, "who": "family:grug", "guid": 1, "name": "Grug"}],
        )


if __name__ == "__main__":
    unittest.main()
