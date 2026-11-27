"""`eph due` lists open waiting issues whose Proof line names a runnable decree."""

import base64
import io
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from ephemeral import __main__ as cli
from ephemeral import due, ghx, submit

REPO = "example/repo"


class FakeGh:
    def __init__(self, issues, decrees):
        self.issues = issues
        self.decrees = decrees
        self.contents_reads = []
        self.current_issues = {}

    def issue(self, repo, n):
        if (repo, n) in self.current_issues:
            return self.current_issues[repo, n]
        rows = (
            self.issues.get(repo, []) if isinstance(self.issues, dict) else self.issues
        )
        for row in rows:
            if row["number"] == n:
                return row
        raise ghx.GhError("issue unavailable")

    def api(self, path, method="GET", body=None, missing_ok=False, paginate=False):
        if "/issues?" in path:
            if isinstance(self.issues, dict):
                repo = path.split("/issues?", 1)[0].removeprefix("repos/")
                return self.issues[repo]
            return self.issues
        self.contents_reads.append(path)
        did = path.split("/decrees/")[1].split(".yaml")[0]
        text = self.decrees.get(did)
        if text is None:
            return None
        return {
            "encoding": "base64",
            "content": base64.b64encode(text.encode()).decode(),
        }


def decree(did, *issues):
    proves = ", ".join(
        f'{{repo: {REPO}, issue: {number}, criterion: "x"}}' for number in issues
    )
    return f"decree: v1\nid: {did}\nproves: [{proves}]\n"


def issue(n, body, *labels):
    return {
        "number": n,
        "body": body,
        "state": "open",
        "labels": [{"name": label} for label in ("awaiting-live-check", *labels)],
    }


class DueTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = SimpleNamespace(results_dir=tmp.name, decree_repo=REPO)

    def run_due(self, issues, decrees):
        return due.due(FakeGh(issues, decrees), self.cfg)

    def run_submit(self, gh, *args, limit=1, response=None):
        buf = io.StringIO()
        with (
            mock.patch.object(cli, "_runner", return_value=(self.cfg, None, gh)),
            mock.patch.object(submit, "submit", side_effect=response) as submit_call,
            redirect_stdout(buf),
        ):
            code = cli.main(
                ["submit", "--due", str(limit), "--control-history", "past.json", *args]
            )
        return code, buf.getvalue(), submit_call.call_args_list

    def test_proof_line_present_is_due(self):
        got = self.run_due(
            [issue(5, "text\nProof: decree alpha\n")], {"alpha": decree("alpha", 5)}
        )
        self.assertEqual(got, [(REPO, 5, "alpha")])

    def test_no_proof_line_is_skipped(self):
        self.assertEqual(
            self.run_due([issue(5, "no line")], {"alpha": decree("alpha", 5)}), []
        )

    def test_decree_missing_is_skipped(self):
        self.assertEqual(self.run_due([issue(5, "Proof: decree alpha")], {}), [])

    def test_decree_proving_another_issue_is_skipped(self):
        self.assertEqual(
            self.run_due(
                [issue(5, "Proof: decree alpha")], {"alpha": decree("alpha", 6)}
            ),
            [],
        )

    def test_proof_is_skipped_if_the_file_defines_a_different_decree_id(self):
        self.assertEqual(
            self.run_due(
                [issue(5, "Proof: decree alpha")], {"alpha": decree("beta", 5)}
            ),
            [],
        )

    def test_already_submitted_is_skipped(self):
        d = pathlib.Path(self.cfg.results_dir) / "alpha"
        d.mkdir()
        (d / "batch-abc123.json").write_text("{}")
        self.assertEqual(
            self.run_due(
                [issue(5, "Proof: decree alpha")], {"alpha": decree("alpha", 5)}
            ),
            [],
        )

    def test_order_is_kept_and_pull_requests_skipped(self):
        issues = [
            issue(9, "Proof: decree b"),
            {"number": 7, "body": "Proof: decree a", "pull_request": {}},
            issue(3, "Proof: decree a"),
        ]
        decrees = {"a": decree("a", 3), "b": decree("b", 9)}
        self.assertEqual(
            self.run_due(issues, decrees), [(REPO, 9, "b"), (REPO, 3, "a")]
        )

    def test_proof_regex_needs_whole_line(self):
        self.assertEqual(due.proof_decree("see Proof: decree a and more"), "")
        self.assertEqual(due.proof_decree("x\n  Proof: decree a-b\n"), "a-b")

    def test_numeric_proves_form(self):
        self.assertTrue(due.proves_issue({"proves": 5}, REPO, 5))
        self.assertFalse(due.proves_issue({"proves": 5}, REPO, 6))

    def test_configured_repos_share_oldest_first_discovery_and_automation(self):
        other = "example/module"
        self.cfg.proof_repos = (REPO, other)
        gh = FakeGh(
            {
                REPO: [
                    {
                        **issue(8, "Proof: decree a"),
                        "created_at": "2026-11-22T00:00:00Z",
                    },
                    issue(9, "Proof: decree c"),
                ],
                other: [
                    {
                        **issue(3, "Proof: decree b"),
                        "created_at": "2026-11-21T00:00:00Z",
                    },
                    issue(4, "Proof: decree d"),
                    issue(5, "Proof: decree e"),
                ],
            },
            {
                "a": decree("a", 8),
                "b": decree("b", 3).replace(REPO, other),
                "c": decree("c", 9),
                "d": decree("d", 4).replace(REPO, other),
                "e": "decree: v1\nid: e\nproves: 5\n",
            },
        )
        self.assertEqual(
            due.due(gh, self.cfg),
            [(other, 3, "b"), (REPO, 8, "a"), (REPO, 9, "c"), (other, 4, "d")],
        )
        code, _, calls = self.run_submit(gh)
        self.assertEqual(code, 0)
        self.assertEqual([call.args[3] for call in calls], ["data/decrees/b.yaml"] * 2)
        self.assertTrue(
            all(
                path.startswith(f"repos/{REPO}/contents/") for path in gh.contents_reads
            )
        )

    def test_the_due_command_prints_each_due_issue(self):
        gh = FakeGh([issue(7, "Proof: decree a")], {"a": decree("a", 7)})
        buf = io.StringIO()
        with (
            mock.patch.object(cli, "_runner", lambda a: (self.cfg, None, gh)),
            redirect_stdout(buf),
        ):
            code = cli.main(["due"])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue(), f"{REPO}#7 a\n")

    def test_submit_due_uses_the_default_branch_proof_bytes(self):
        raw = decree("a", 7)
        gh = FakeGh([issue(7, "Proof: decree a")], {"a": raw})
        code, _, calls = self.run_submit(gh)
        self.assertEqual(code, 0)
        self.assertEqual(
            gh.contents_reads, [f"repos/{REPO}/contents/data/decrees/a.yaml"]
        )
        self.assertEqual(
            [call.kwargs["decree_bytes"] for call in calls],
            [raw.encode(), raw.encode()],
        )
        self.assertEqual([call.args[4]["dry_run"] for call in calls], [True, False])
        self.assertTrue(all(call.args[4]["control"] == "auto" for call in calls))

    def test_claimed_peer_holds_the_shared_decree_but_stays_visible_in_due(self):
        gh = FakeGh(
            [
                issue(7, "Proof: decree a"),
                issue(8, "Proof: decree b", "loom:running", "lane:spark"),
                issue(9, "Proof: decree a", "claim:other-agent"),
                issue(10, "Proof: decree c", "loom:merged", "lane:old"),
            ],
            {"a": decree("a", 7, 9), "b": decree("b", 8), "c": decree("c", 10)},
        )
        self.assertEqual([n for _, n, _ in due.due(gh, self.cfg)], [7, 8, 9, 10])
        code, output, calls = self.run_submit(gh)
        self.assertEqual(code, 0)
        self.assertIn(f"skip a: {REPO}#9 (claim:other-agent)", output)
        self.assertIn(f"skip b: {REPO}#8 (lane:spark)", output)
        self.assertEqual([call.args[3] for call in calls], ["data/decrees/c.yaml"] * 2)

    def test_secondary_without_a_proof_line_must_be_readable_and_unheld(self):
        other = "example/module"
        raw = decree("a", 7, 8).replace(
            f"repo: {REPO}, issue: 8", f"repo: {other}, issue: 8"
        )
        for scenario in ("held", "claimed-during-preflight", "unreadable"):
            with self.subTest(scenario=scenario):
                gh = FakeGh({REPO: [issue(7, "Proof: decree a")]}, {"a": raw})
                held = issue(8, "no Proof line", "claim:other-agent")
                if scenario == "held":
                    gh.current_issues[other, 8] = held
                elif scenario == "claimed-during-preflight":
                    gh.current_issues[other, 8] = issue(8, "no Proof line")

                def preflight(*args, gh=gh, held=held, **kwargs):
                    self.assertTrue(args[4]["dry_run"])
                    gh.current_issues[other, 8] = held

                self.assertEqual(due.due(gh, self.cfg), [(REPO, 7, "a")])
                code, output, calls = self.run_submit(gh, response=preflight)
                self.assertEqual(code, 0)
                if scenario == "unreadable":
                    self.assertIn(f"skip a: {other}#8: could not read", output)
                else:
                    self.assertIn(f"skip a: {other}#8 (claim:other-agent)", output)
                self.assertEqual(
                    len(calls), int(scenario == "claimed-during-preflight")
                )

    def test_first_distinct_decrees_preflight_once_and_a_skip_is_not_replaced(self):
        gh = FakeGh(
            [
                issue(7, "Proof: decree a"),
                issue(8, "Proof: decree a"),
                issue(9, "Proof: decree b"),
                issue(10, "Proof: decree c"),
            ],
            {"a": decree("a", 7, 8), "b": decree("b", 9), "c": decree("c", 10)},
        )
        code, output, calls = self.run_submit(
            gh, limit=2, response=[None, None, submit.SubmitError("old image is gone")]
        )
        self.assertEqual(code, 0)
        self.assertIn("skip b: old image is gone", output)
        self.assertEqual(
            gh.contents_reads.count(f"repos/{REPO}/contents/data/decrees/a.yaml"), 1
        )
        self.assertEqual(
            [
                (pathlib.Path(call.args[3]).stem, call.args[4]["dry_run"])
                for call in calls
            ],
            [("a", True), ("a", False), ("b", True)],
        )

    def test_real_submission_errors_stop_instead_of_being_reported_as_skips(self):
        gh = FakeGh(
            [issue(7, "Proof: decree a"), issue(9, "Proof: decree b")],
            {"a": decree("a", 7), "b": decree("b", 9)},
        )
        code, output, calls = self.run_submit(
            gh, limit=2, response=[None, submit.SubmitError("create failed")]
        )
        self.assertEqual(code, 2)
        self.assertEqual(output, "error: create failed\n")
        self.assertEqual([call.args[3] for call in calls], ["data/decrees/a.yaml"] * 2)

    def test_due_argument_errors_are_refused_before_loading_the_runner(self):
        for args, error in (
            (["--due", "0"], "positive count"),
            (["--due", "1"], "needs --control-history"),
            (
                ["--due", "1", "--control-history", "h", "--arm", "treatment"],
                "requires both",
            ),
            (
                ["--due", "1", "--control-history", "h", "--decree-pr", "12"],
                "cannot be combined with --decree-pr",
            ),
            (
                [
                    "--due",
                    "1",
                    "--control-history",
                    "h",
                    "--control-drop-keys",
                    "Overseer.X",
                ],
                "cannot be combined with --control-drop-keys",
            ),
        ):
            with (
                self.subTest(args=args),
                mock.patch.object(cli, "_runner") as runner,
                redirect_stdout(io.StringIO()) as buf,
            ):
                self.assertEqual(cli.main(["submit", *args]), 2)
                self.assertIn(error, buf.getvalue())
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
