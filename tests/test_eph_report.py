"""The report command publishes batch evidence and never closes a ticket."""

import hashlib
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace

from eph_fakes import FakeGh
from ephemeral import ghx, report, runids

ENV = {"GH_TOKEN": "test-token", "GH_CONFIG_DIR": "test-config"}
REPO = "quadseven/wow-overseer"
ISSUE = 44
BATCH = "abc123"
DECREE = "demo-decree"
DECREE_TEXT = "decree: v1\nid: demo-decree\n"
SHA = hashlib.sha256(DECREE_TEXT.encode()).hexdigest()
BOX = "The family leaves without a defeat"
BODY = f"## Acceptance\n- [ ] {BOX}\n- [ ] an unrelated check\n"


def batch(pair_count=3, box=BOX, batch_id=BATCH, expected_pairs=None):
    runs = []
    for n in range(1, pair_count + 1):
        for arm in ("control", "treatment"):
            rid = runids.run_id(batch_id, arm, n)
            runs.append({"run_id": rid, "arm": arm, "n": n})
    return {
        "batch": batch_id,
        "decree_id": DECREE,
        "decree_sha256": SHA,
        "proves": ISSUE,
        "box": box,
        "runs_wanted": {
            "control": expected_pairs or pair_count,
            "treatment": expected_pairs or pair_count,
        },
        "runs": runs,
    }


def result(rec, control=None, treatment=None):
    control = control or ["FAIL"] * rec["runs_wanted"]["control"]
    treatment = treatment or ["PASS"] * rec["runs_wanted"]["treatment"]
    results, jobs = [], []
    for run in rec["runs"]:
        states = control if run["arm"] == "control" else treatment
        verdict = states[run["n"] - 1]
        result_doc = {
            "verdict": verdict,
            "decree_sha256": SHA,
            "run_id": run["run_id"],
            "arm": run["arm"],
            "reasons": [f"{run['arm']} assertion {run['n']} {verdict.lower()}"],
        }
        results.append(
            {
                "metadata": {
                    "name": runids.result_name(run["run_id"]),
                    "labels": {
                        "eph/decree": DECREE,
                        "eph/arm": run["arm"],
                        "eph/verdict": verdict,
                    },
                    "creationTimestamp": "2000-01-01T12:05:00Z",
                },
                "data": {"result.json": json.dumps(result_doc), "verdict": verdict},
            }
        )
        jobs.append(
            {
                "metadata": {
                    "name": runids.job_name(run["run_id"]),
                    "labels": {
                        runids.JOB_LABEL_BATCH: BATCH,
                        "eph/run": run["run_id"],
                    },
                },
                "status": {"startTime": f"2000-01-01T12:{run['n']:02d}:00Z"},
            }
        )
    return results, jobs


class FakeCluster:
    def __init__(self, result_maps, jobs):
        self.objects = {"configmaps": result_maps, "jobs": jobs}

    def list(self, kind, selector=""):
        rows = self.objects.get(kind, [])
        if selector.startswith("eph/batch="):
            wanted = selector.split("=", 1)[1]
            return [
                row
                for row in rows
                if row.get("metadata", {}).get("labels", {}).get("eph/batch") == wanted
            ]
        if selector == "eph/verdict":
            return [
                row
                for row in rows
                if "eph/verdict" in row.get("metadata", {}).get("labels", {})
            ]
        return rows


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = SimpleNamespace(results_dir=self.tmp.name, decree_repo=REPO)
        self.fg = FakeGh()
        self.gh = ghx.Gh(self.fg, env=ENV, author=FakeGh.author)
        self.logs = []
        self.rec = batch()
        self._save(self.rec)

    def _save(self, rec):
        folder = pathlib.Path(self.cfg.results_dir) / rec["decree_id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"batch-{rec['batch']}.json").write_text(
            json.dumps(rec), encoding="utf-8"
        )

    def _run(
        self, control=None, treatment=None, rec=None, body=None, dry_run=False, box=None
    ):
        rec = rec or self.rec
        if box is not None:
            rec = {**rec, "box": box}
        results, jobs = result(rec, control, treatment)
        if rec["runs"]:
            self._save(rec)
        issue_key = ("GET", f"repos/{REPO}/issues/{ISSUE}")
        body = (
            body
            if body is not None
            else self.fg.answers.get(issue_key, {}).get("body", BODY)
        )
        self.fg.answers[issue_key] = {
            "state": "open",
            "body": body,
            "labels": [],
        }
        cluster = FakeCluster(results, jobs)
        reporter = report.Reporter(
            self.cfg, cluster, self.gh, env=ENV, out=self.logs.append
        )
        return reporter.run(BATCH, dry_run=dry_run)

    def _writes(self):
        return [
            (call[0][call[0].index("-X") + 1], call[0][2], call[1])
            for call in self.fg.calls
            if "-X" in call[0]
        ]

    def _comment(self):
        return self.fg.comments[f"repos/{REPO}/issues/{ISSUE}/comments"][0]["body"]

    def test_full_standard_posts_evidence_and_ticks_only_the_named_box(self):
        preview = self._run()
        self.assertTrue(preview["standard_met"])
        writes = self._writes()
        edits = [x for x in writes if x[0] == "PATCH"]
        self.assertEqual(len(edits), 1)
        edited_body = json.loads(edits[0][2])["body"]
        self.assertIn(f"- [x] {BOX}", edited_body)
        self.assertIn("- [ ] an unrelated check", edited_body)
        comment = self._comment()
        self.assertIn(f"decree_id: {DECREE}", comment)
        self.assertIn(f"batch_ids: {BATCH}", comment)
        self.assertIn("2000-01-01T12:01:00Z", comment)
        self.assertIn("control assertion 1 fail", comment)
        self.assertIn("checkbox: ticked", comment)
        self.assertFalse(any('"state": "closed"' in (x[2] or "") for x in writes))

    def test_one_pair_only_posts_but_does_not_tick(self):
        rec = batch(pair_count=1)
        rec["runs_wanted"] = {"control": 3, "treatment": 3}
        self._save(rec)
        preview = self._run(rec=rec)
        self.assertFalse(preview["standard_met"])
        self.assertEqual(self._writes()[0][0], "POST")
        self.assertIn("standard: not met", self._comment())
        self.assertIn("MISSING", self._comment())
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))

    def test_treatment_failure_posts_but_does_not_tick(self):
        preview = self._run(treatment=["PASS", "FAIL", "PASS"])
        self.assertFalse(preview["standard_met"])
        self.assertIn("treatment | FAIL", self._comment())
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))

    def test_invalid_arm_posts_but_does_not_tick(self):
        preview = self._run(control=["FAIL", "INVALID", "FAIL"])
        self.assertFalse(preview["standard_met"])
        self.assertIn("control | INVALID", self._comment())
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))

    def test_box_text_mismatch_posts_and_says_no_box_was_ticked(self):
        preview = self._run(box="a different acceptance criterion")
        self.assertTrue(preview["standard_met"])
        self.assertEqual(preview["checkbox_status"], "no matching checkbox")
        self.assertIn("checkbox: no matching checkbox", self._comment())
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))

    def test_missing_utc_start_posts_but_does_not_tick(self):
        results, jobs = result(self.rec)
        for job in jobs:
            job.pop("status")
        self.fg.answers[("GET", f"repos/{REPO}/issues/{ISSUE}")] = {
            "state": "open",
            "body": BODY,
            "labels": [],
        }
        reporter = report.Reporter(
            self.cfg, FakeCluster(results, jobs), self.gh, env=ENV, out=self.logs.append
        )
        preview = reporter.run(BATCH)
        self.assertTrue(preview["standard_met"])
        self.assertFalse(preview["timestamps_complete"])
        self.assertEqual(preview["checkbox_status"], "missing UTC start time")
        self.assertIn("timestamps_complete: no", self._comment())
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))

    def test_unique_stable_box_prefix_ticks_one_match(self):
        preview = self._run(box="The family leaves")
        self.assertEqual(preview["checkbox_status"], "ticked")
        self.assertIn("- [x] The family leaves without a defeat", self._writes()[0][2])

    def test_a_prefix_that_ends_mid_word_does_not_tick(self):
        preview = self._run(
            box="The family leave", body="- [ ] The family leaves without a defeat\n"
        )
        self.assertEqual(preview["checkbox_status"], "no matching checkbox")
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))

    def test_ambiguous_box_prefix_does_not_tick_either_match(self):
        body = f"- [ ] {BOX}\n- [ ] {BOX} after the next step\n"
        preview = self._run(box=BOX, body=body)
        self.assertEqual(preview["checkbox_status"], "ambiguous checkbox prefix")
        self.assertFalse(any(x[0] == "PATCH" for x in self._writes()))
        self.assertIn("checkbox: ambiguous checkbox prefix", self._comment())

    def test_private_host_and_node_details_are_omitted_from_reason_lines(self):
        rec = batch()
        results, jobs = result(rec)
        results[0]["data"]["result.json"] = json.dumps(
            {
                "verdict": "FAIL",
                "decree_sha256": SHA,
                "reasons": [
                    "could not connect to worker.example.com via node example-node"
                ],
            }
        )
        self._save(rec)
        self.fg.answers[("GET", f"repos/{REPO}/issues/{ISSUE}")] = {
            "state": "open",
            "body": BODY,
            "labels": [],
        }
        reporter = report.Reporter(
            self.cfg, FakeCluster(results, jobs), self.gh, env=ENV, out=self.logs.append
        )
        reporter.run(BATCH)
        comment = self._comment()
        self.assertNotIn("worker.example.com", comment)
        self.assertNotIn("example-node", comment)
        self.assertIn("reason withheld by privacy guard", comment)

    def test_dry_run_prints_the_comment_without_writing(self):
        preview = self._run(dry_run=True)
        self.assertIn("batch_ids: abc123", "\n".join(self.logs))
        self.assertTrue(preview["standard_met"])
        self.assertEqual(self._writes(), [])

    def test_repeating_a_completed_report_does_not_duplicate_the_comment(self):
        first = self._run()
        patched = json.loads(self._writes()[0][2])["body"]
        self.fg.answers[("GET", f"repos/{REPO}/issues/{ISSUE}")]["body"] = patched
        second = self._run()
        comments = self.fg.comments[f"repos/{REPO}/issues/{ISSUE}/comments"]
        self.assertEqual(len(comments), 1)
        self.assertEqual(first["standard_met"], second["standard_met"])

    def test_three_one_pair_batches_can_meet_the_decree_standard(self):
        records = [
            batch(1, batch_id=batch_id, expected_pairs=3)
            for batch_id in ("abc123", "def456", "fedcba")
        ]
        result_maps, jobs = [], []
        for rec in records:
            self._save(rec)
            result_rows, job_rows = result(rec)
            result_maps.extend(result_rows)
            jobs.extend(job_rows)
        self.fg.answers[("GET", f"repos/{REPO}/issues/{ISSUE}")] = {
            "state": "open",
            "body": BODY,
            "labels": [],
        }
        reporter = report.Reporter(
            self.cfg,
            FakeCluster(result_maps, jobs),
            self.gh,
            env=ENV,
            out=self.logs.append,
        )
        preview = reporter.run([rec["batch"] for rec in records])
        self.assertTrue(preview["standard_met"])
        self.assertIn("batch_ids: abc123,def456,fedcba", self._comment())
        self.assertEqual(
            [row["batch_id"] for row in preview["rows"] if row["arm"] == "control"],
            ["abc123", "def456", "fedcba"],
        )
        self.assertEqual(self._writes()[0][0], "PATCH")


if __name__ == "__main__":
    unittest.main()
