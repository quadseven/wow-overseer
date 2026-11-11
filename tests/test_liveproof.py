"""Live proof probe runner tests (wow-overseer#2125).

The judgements that matter: a probe file may only ever be one read-only
SELECT, a verdict file has one fixed shape, a ticket closes only when it is
proven in BOTH of the last two runs, and nothing runs gh without --apply.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from liveproof import report, run

PROBES = Path(__file__).resolve().parent.parent / "liveproof" / "probes"


class FakeConn:
    """A connection whose rows are chosen by the ticket the SELECT names."""

    def __init__(self, rows_by_ticket=None):
        self.rows_by_ticket = rows_by_ticket or {}
        self.log = []

    def cursor(self):
        conn = self

        class Cursor:
            rows = []

            def execute(self, sql):
                conn.log.append(sql)
                self.rows = []
                for ticket, rows in conn.rows_by_ticket.items():
                    if f"'{ticket}'" in sql:
                        self.rows = rows

            def fetchall(self):
                return self.rows

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Cursor()


def probe(ticket="1", repo="quadseven/wow-overseer", sql=None):
    return run.Probe(
        ticket=ticket,
        repo=repo,
        sql=sql or f"SELECT '{ticket}' AS ticket, 'proven' AS verdict, 'x' AS evidence",
        path=f"{ticket}.sql",
    )


class SelectOnlyGuard(unittest.TestCase):
    def refused(self, sql):
        with self.assertRaises(run.UnsafeStatement):
            run.check_select_only(sql)

    def test_a_missing_parser_fails_closed_before_a_probe_reaches_the_database(self):
        conn = FakeConn({"1": [("1", "proven", "fixture")]})
        with mock.patch.dict(sys.modules, {"sqlglot": None}):
            with self.assertRaises(run.UnsafeStatement):
                run.check_select_only("SELECT 1")
            result = run.run_probe(conn, probe("1"))
        self.assertEqual(run.ERROR, result["verdict"])
        self.assertIn("sqlglot", result["evidence"])
        self.assertEqual([], conn.log)

    def test_quoted_forbidden_functions_are_refused_too(self):
        for function in ("LOAD_FILE", "GET_LOCK", "SYS_EXEC"):
            with self.subTest(function=function):
                self.refused(f"SELECT `{function}`('fixture')")

    def test_a_plain_select_passes_with_or_without_a_semicolon(self):
        run.check_select_only("SELECT 1")
        run.check_select_only("SELECT 1;")
        run.check_select_only("-- note; with a semicolon\nSELECT 1")

    def test_with_clause_and_subqueries_pass(self):
        run.check_select_only("WITH a AS (SELECT 1 AS n) SELECT n FROM a")
        run.check_select_only("SELECT (SELECT COUNT(*) FROM t) AS n")

    def test_writes_are_refused(self):
        for sql in (
            "DELETE FROM t",
            "UPDATE t SET a = 1",
            "INSERT INTO t VALUES (1)",
            "DROP TABLE t",
            "TRUNCATE TABLE t",
            "SET @a = 1",
            "CALL p()",
        ):
            self.refused(sql)

    def test_two_statements_are_refused_even_when_both_select(self):
        self.refused("SELECT 1; SELECT 2")
        self.refused("SELECT 1; DROP TABLE t")

    def test_a_write_hidden_after_a_comment_is_still_refused(self):
        self.refused("SELECT 1 -- ok\n; DELETE FROM t")

    def test_select_into_and_locking_reads_are_refused(self):
        self.refused("SELECT a INTO @v FROM t")
        self.refused("SELECT 1 INTO OUTFILE '/x'")
        self.refused("SELECT * FROM t FOR UPDATE")
        self.refused("SELECT * FROM t LOCK IN SHARE MODE")

    def test_functions_with_side_effects_are_refused(self):
        for fn in (
            "SLEEP(5)",
            "BENCHMARK(100, 1)",
            "LOAD_FILE('/etc/hosts')",
            "GET_LOCK('a', 1)",
        ):
            self.refused(f"SELECT {fn}")
            self.refused(f"SELECT (SELECT {fn})")

    def test_empty_and_unparseable_text_is_refused(self):
        self.refused("")
        self.refused("   -- only a comment\n")
        self.refused("SELEC 1 FROM")

    def test_a_union_is_refused(self):
        self.refused("SELECT 1 UNION SELECT 2")

    def test_every_seeded_probe_passes_the_guard(self):
        files = sorted(PROBES.glob("*/*.sql"))
        self.assertGreater(len(files), 20)
        for path in files:
            run.check_select_only(run.load_probe(path).sql)


class ProbeFiles(unittest.TestCase):
    def write(self, text, name="7.sql"):
        p = Path(tempfile.mkdtemp()) / name
        p.write_text(text)
        return p

    def test_header_gives_ticket_and_repo(self):
        p = self.write(
            "-- ticket: 7\n-- repo: quadseven/mod-overseer\n-- why\nSELECT '7' AS ticket;"
        )
        got = run.load_probe(p)
        self.assertEqual((got.ticket, got.repo), ("7", "quadseven/mod-overseer"))
        self.assertIn("SELECT '7'", got.sql)

    def test_missing_header_or_wrong_name_is_a_load_error(self):
        with self.assertRaises(run.ProbeFileError):
            run.load_probe(self.write("SELECT 1;"))
        with self.assertRaises(run.ProbeFileError):
            run.load_probe(
                self.write("-- ticket: 8\n-- repo: quadseven/wow-overseer\nSELECT 1;")
            )

    def test_unknown_repo_is_a_load_error(self):
        with self.assertRaises(run.ProbeFileError):
            run.load_probe(self.write("-- ticket: 7\n-- repo: someone/else\nSELECT 1;"))

    def test_seeded_probes_have_unique_repo_ticket_pairs_and_ascii(self):
        seen = set()
        for path in sorted(PROBES.glob("*/*.sql")):
            path.read_text().encode("ascii")
            p = run.load_probe(path)
            self.assertNotIn((p.repo, p.ticket), seen)
            seen.add((p.repo, p.ticket))

    def test_closed_tickets_are_not_in_the_registry(self):
        tickets = {run.load_probe(p).ticket for p in PROBES.glob("*/*.sql")}
        for closed in ("2021", "2038", "1965", "1422", "1444", "1424", "1440"):
            self.assertNotIn(closed, tickets)


class RunProbes(unittest.TestCase):
    def test_one_row_becomes_a_result(self):
        conn = FakeConn({"1": [("1", "proven", "n=3")]})
        self.assertEqual(
            run.run_probe(conn, probe("1")),
            {
                "ticket": "1",
                "repo": "quadseven/wow-overseer",
                "verdict": "proven",
                "evidence": "n=3",
            },
        )

    def test_bad_rows_become_an_error_verdict(self):
        cases = {
            "no rows": [],
            "two rows": [("1", "proven", "a"), ("1", "proven", "b")],
            "bad verdict": [("1", "maybe", "a")],
            "wrong ticket": [("2", "proven", "a")],
            "wrong width": [("1", "proven")],
        }
        for name, rows in cases.items():
            res = run.run_probe(FakeConn({"1": rows}), probe("1"))
            self.assertEqual(res["verdict"], "error", name)
            self.assertTrue(res["evidence"], name)

    def test_a_refused_statement_never_reaches_the_database(self):
        conn = FakeConn()
        res = run.run_probe(conn, probe("1", sql="DELETE FROM t"))
        self.assertEqual(res["verdict"], "error")
        self.assertEqual(conn.log, [])

    def test_a_database_error_is_recorded_not_raised(self):
        class Boom(FakeConn):
            def cursor(self):
                raise RuntimeError("connection lost")

        res = run.run_probe(Boom(), probe("1"))
        self.assertEqual(res["verdict"], "error")
        self.assertIn("connection lost", res["evidence"])

    def test_evidence_is_ascii_and_bounded(self):
        conn = FakeConn({"1": [("1", "proven", "caf\u00e9 " + "x" * 5000)]})
        ev = run.run_probe(conn, probe("1"))["evidence"]
        ev.encode("ascii")
        self.assertLessEqual(len(ev), run.MAX_EVIDENCE)


class VerdictFile(unittest.TestCase):
    def test_shape(self):
        conn = FakeConn({"1": [("1", "proven", "a")], "2": [("2", "no_evidence", "b")]})
        doc = run.run_all([probe("1"), probe("2")], conn, now="2026-11-09T12:00:00Z")
        self.assertEqual(set(doc), {"schema", "run_at", "results"})
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["run_at"], "2026-11-09T12:00:00Z")
        self.assertEqual([r["ticket"] for r in doc["results"]], ["1", "2"])
        for r in doc["results"]:
            self.assertEqual(set(r), {"ticket", "repo", "verdict", "evidence"})
        json.dumps(doc)

    def test_main_writes_a_file_and_exits_zero_when_the_database_is_down(self):
        out_dir = Path(tempfile.mkdtemp())
        pdir = Path(tempfile.mkdtemp())
        (pdir / "wow-overseer").mkdir()
        (pdir / "wow-overseer" / "1.sql").write_text(
            "-- ticket: 1\n-- repo: quadseven/wow-overseer\n"
            "SELECT '1' AS ticket, 'proven' AS verdict, 'x' AS evidence;"
        )
        env = {"LIVEPROOF_DB_HOST": "h", "LIVEPROOF_DB_USER": "u"}
        with mock.patch.object(run, "connect", side_effect=OSError("no route")):
            code = run.main(["--probes", str(pdir), "--out", str(out_dir)], env=env)
        self.assertEqual(code, 0)
        files = list(out_dir.glob("verdicts-*.json"))
        self.assertEqual(len(files), 1)
        doc = json.loads(files[0].read_text())
        self.assertEqual(doc["results"][0]["verdict"], "error")
        self.assertIn("no route", doc["results"][0]["evidence"])

    def test_connection_settings_come_from_the_environment(self):
        with self.assertRaises(SystemExit):
            run.settings_from_env({})
        s = run.settings_from_env({"LIVEPROOF_DB_HOST": "h", "LIVEPROOF_DB_USER": "u"})
        self.assertEqual((s["host"], s["user"]), ("h", "u"))


def verdicts(run_at, **by_ticket):
    """A verdict doc; a ticket key starting with m is a mod-overseer ticket."""
    return {
        "schema": 1,
        "run_at": run_at,
        "results": [
            {
                "ticket": t.lstrip("m"),
                "repo": "quadseven/mod-overseer"
                if t.startswith("m")
                else "quadseven/wow-overseer",
                "verdict": v,
                "evidence": f"e-{t}-{run_at}",
            }
            for t, v in by_ticket.items()
        ],
    }


class TwoRunRule(unittest.TestCase):
    def test_only_tickets_proven_in_both_runs_qualify(self):
        prev = verdicts(
            "a", **{"1": "proven", "2": "proven", "3": "disproven", "4": "proven"}
        )
        last = verdicts(
            "b", **{"1": "proven", "2": "no_evidence", "3": "proven", "5": "proven"}
        )
        got = report.proven_in_both(prev, last)
        self.assertEqual(
            [(g["repo"], g["ticket"]) for g in got], [("quadseven/wow-overseer", "1")]
        )

    def test_same_ticket_number_in_two_repos_is_two_tickets(self):
        prev = verdicts("a", **{"1": "proven", "m1": "no_evidence"})
        last = verdicts("b", **{"1": "proven", "m1": "proven"})
        got = report.proven_in_both(prev, last)
        self.assertEqual([g["repo"] for g in got], ["quadseven/wow-overseer"])

    def test_error_is_never_a_proof(self):
        prev = verdicts("a", **{"1": "error"})
        last = verdicts("b", **{"1": "error"})
        self.assertEqual(report.proven_in_both(prev, last), [])

    def test_latest_two_picks_the_newest_files_in_name_order(self):
        d = Path(tempfile.mkdtemp())
        for name in (
            "verdicts-20261109T010000Z.json",
            "verdicts-20261109T030000Z.json",
            "verdicts-20261109T020000Z.json",
        ):
            (d / name).write_text("{}")
        (d / "notes.txt").write_text("")
        got = [p.name for p in report.latest_two(d)]
        self.assertEqual(
            got, ["verdicts-20261109T020000Z.json", "verdicts-20261109T030000Z.json"]
        )

    def test_one_file_is_not_enough(self):
        d = Path(tempfile.mkdtemp())
        (d / "verdicts-20261109T010000Z.json").write_text("{}")
        self.assertIsNone(report.latest_two(d))


class DryRun(unittest.TestCase):
    def setup_dir(self, prev, last):
        d = Path(tempfile.mkdtemp())
        (d / "verdicts-20261109T010000Z.json").write_text(json.dumps(prev))
        (d / "verdicts-20261109T020000Z.json").write_text(json.dumps(last))
        return d

    def test_dry_run_prints_commands_and_runs_nothing(self):
        d = self.setup_dir(
            verdicts("a", **{"1": "proven"}), verdicts("b", **{"1": "proven"})
        )
        out = io.StringIO()
        with mock.patch("subprocess.run") as sub, redirect_stdout(out):
            code = report.main(["--dir", str(d)])
        sub.assert_not_called()
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("gh issue comment 1 -R quadseven/wow-overseer", text)
        self.assertIn("gh issue close 1 -R quadseven/wow-overseer", text)
        self.assertLess(text.index("gh issue comment"), text.index("gh issue close"))
        self.assertIn("dry run", text.lower())
        text.encode("ascii")

    def test_comment_names_both_runs_and_the_evidence(self):
        item = report.proven_in_both(
            verdicts("run-a", **{"1": "proven"}), verdicts("run-b", **{"1": "proven"})
        )[0]
        body = report.comment_body(item)
        self.assertIn("run-a", body)
        self.assertIn("run-b", body)
        self.assertIn("e-1-run-b", body)

    def test_evidence_cannot_mention_anyone(self):
        item = {
            "ticket": "1",
            "repo": "quadseven/wow-overseer",
            "evidence": "see @someone and \u00e9",
            "prev_run": "a",
            "last_run": "b",
            "prev_evidence": "p",
        }
        body = report.comment_body(item)
        self.assertNotIn("@", body)
        body.encode("ascii")

    def test_nothing_to_close_says_so(self):
        d = self.setup_dir(
            verdicts("a", **{"1": "proven"}), verdicts("b", **{"1": "no_evidence"})
        )
        out = io.StringIO()
        with redirect_stdout(out):
            report.main(["--dir", str(d)])
        self.assertIn("no ticket", out.getvalue().lower())
        self.assertNotIn("gh issue close", out.getvalue())

    def test_apply_runs_comment_then_close_and_skips_a_closed_issue(self):
        d = self.setup_dir(
            verdicts("a", **{"1": "proven", "2": "proven"}),
            verdicts("b", **{"1": "proven", "2": "proven"}),
        )
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            r = mock.Mock(returncode=0)
            r.stdout = "CLOSED\n" if cmd[2] == "view" and cmd[3] == "2" else "OPEN\n"
            return r

        with (
            mock.patch("subprocess.run", side_effect=fake_run),
            redirect_stdout(io.StringIO()),
        ):
            code = report.main(["--dir", str(d), "--apply"])
        self.assertEqual(code, 0)
        self.assertEqual([c[2] for c in calls], ["view", "comment", "close", "view"])
        self.assertFalse(
            any(c[3] == "2" for c in calls if c[2] in ("comment", "close"))
        )

    def test_apply_does_not_close_when_the_comment_fails(self):
        d = self.setup_dir(
            verdicts("a", **{"1": "proven"}), verdicts("b", **{"1": "proven"})
        )
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            r = mock.Mock(returncode=1 if cmd[2] == "comment" else 0)
            r.stdout = "OPEN\n"
            return r

        with (
            mock.patch("subprocess.run", side_effect=fake_run),
            redirect_stdout(io.StringIO()),
        ):
            report.main(["--dir", str(d), "--apply"])
        self.assertNotIn("close", [c[2] for c in calls])


if __name__ == "__main__":
    unittest.main()
