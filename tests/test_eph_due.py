"""`eph due` lists open waiting issues whose Proof line names a runnable decree."""

import base64
import pathlib
import tempfile
import unittest
from types import SimpleNamespace

from ephemeral import due

REPO = "example/repo"


class FakeGh:
    def __init__(self, issues, decrees):
        self.issues = issues
        self.decrees = decrees

    def api(self, path, method="GET", body=None, missing_ok=False, paginate=False):
        if "/issues?" in path:
            return self.issues
        did = path.split("/decrees/")[1].split(".yaml")[0]
        text = self.decrees.get(did)
        if text is None:
            return None
        return {
            "encoding": "base64",
            "content": base64.b64encode(text.encode()).decode(),
        }


def decree(did, issue):
    return f'decree: v1\nid: {did}\nproves: [{{repo: {REPO}, issue: {issue}, criterion: "x"}}]\n'


def issue(n, body):
    return {"number": n, "body": body}


class DueTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = SimpleNamespace(results_dir=tmp.name, decree_repo=REPO)

    def run_due(self, issues, decrees):
        return due.due(FakeGh(issues, decrees), self.cfg)

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

    def test_the_due_command_prints_each_due_issue(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        from ephemeral import __main__ as cli

        gh = FakeGh([issue(7, "Proof: decree a")], {"a": decree("a", 7)})
        buf = io.StringIO()
        with (
            mock.patch.object(cli, "_runner", lambda a: (self.cfg, None, gh)),
            redirect_stdout(buf),
        ):
            code = cli.main(["due"])
        self.assertEqual(code, 0)
        self.assertEqual(buf.getvalue(), f"{REPO}#7 a\n")


if __name__ == "__main__":
    unittest.main()
