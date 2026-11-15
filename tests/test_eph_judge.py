"""The judge: the act timeline, the observations, and the three verdicts.

INVALID means the scenario was never reached. It never counts as a pass and
never closes anything, so every way of not reaching it has a test here.
"""

import copy
import json
import pathlib
import tempfile
import unittest

from ephemeral import dbschema, guard, judge
from ephemeral.miniyaml import loads

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = dbschema.Schema.load()
GUZZLER = loads(
    (ROOT / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml").read_text(
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


def guzzler_world(clock, patrons=(), plugger_dies_at=60, left=True, loaded=True):
    w = FakeWorld(clock)
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

    def test_a_clean_log_passes(self):
        clock = Clock()
        r = run(self.decree(0), guzzler_world(clock), clock, log="all quiet\n")
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

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

    def test_a_missing_or_null_scalar_never_holds(self):
        self.assertFalse(judge.expectation_holds({"scalar": "= 0"}, [])[0])
        self.assertFalse(judge.expectation_holds({"scalar": "= 0"}, [(None,)])[0])


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


class ConfigMapStoreTest(unittest.TestCase):
    def store(self, http):
        return judge.ConfigMapStore(
            "https://api.example.invalid", "tok", "eph-ns", http
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
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(json.loads(body)["metadata"]["name"], "eph-result-run-1")

    def test_refuses_any_other_name_or_namespace(self):
        http = FakeHttp()
        s = self.store(http)
        with self.assertRaises(judge.JudgeError):
            s.write(self.cm("eph-harness"))
        other = self.cm()
        other["metadata"]["namespace"] = "wow-dev"
        with self.assertRaises(judge.JudgeError):
            s.write(other)
        with self.assertRaises(judge.JudgeError):
            s.write({**self.cm(), "kind": "Secret"})
        self.assertEqual(http.calls, [])

    def test_a_refused_write_raises(self):
        with self.assertRaises(judge.JudgeError):
            self.store(FakeHttp(status=403)).write(self.cm())


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
            path = ROOT / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"
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
            str(ROOT / "decrees" / "no-such-decree.yaml"),
            self.ENV,
            connect=lambda **kw: ScriptedConn(),
            store=Store(),
            out=lambda _line: None,
            clock=Clock(),
        )
        self.assertEqual((rc, stored[0]["data"]["verdict"]), (0, "INVALID"))

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
                str(ROOT / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"),
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
