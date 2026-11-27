import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest import mock

import test_eph_due_submit as due_fixture
from ephemeral import batchseal, collect, dispatch, due, kube, runids, submit
from test_eph_dispatch import GIB, T0, iso


class BatchSealTest(unittest.TestCase):
    def setUp(self):
        self.record = {
            "batch": "abcdef",
            "decree_id": "named-decree",
            "decree_sha256": "a" * 64,
            "proves": [{"repo": "owner/repo", "issue": 2}],
            "presence": {arm: {} for arm in ("control", "treatment")},
            "runs_wanted": {arm: 1 for arm in ("control", "treatment")},
            "runs": [
                {"run_id": "abcdef-c1", "arm": "control", "n": 1,
                 "images": {"worldserver": "control-image"}},
                {"run_id": "abcdef-t1", "arm": "treatment", "n": 1,
                 "images": {"worldserver": "treatment-image"}},
            ],
        }  # fmt: skip
        self.members = {
            rid: {
                "job_uid": "job-" + rid,
                "input_uid": "input-" + rid,
                "input_sha256": batchseal.fingerprint({"payload": rid}),
            }
            for rid in ("abcdef-c1", "abcdef-t1")
        }

    def test_receipt_fences_one_decree_and_preserves_its_run_identities(self):
        cm = batchseal.manifest("proofs", self.record, self.members)
        self.assertEqual(cm["metadata"]["name"], "eph-due-named-decree")
        self.assertEqual(batchseal.parse(cm, "proofs"), (self.record, self.members))
        self.assertIsNone(batchseal.parse(cm, "another-namespace"))

    def test_reservation_fences_the_decree_without_committing_it(self):
        reservation = batchseal.reservation("proofs", self.record)
        self.assertEqual(reservation["metadata"]["name"], "eph-due-named-decree")
        self.assertIsNot(reservation.get("immutable"), True)
        self.assertEqual(
            batchseal.parse_reservation(reservation, "proofs"),
            ("named-decree", "abcdef"),
        )
        self.assertIsNone(batchseal.parse(reservation, "proofs"))
        self.assertIsNone(batchseal.parse_reservation(reservation, "elsewhere"))
        reservation["metadata"]["name"] = "eph-due-other-decree"
        self.assertIsNone(batchseal.parse_reservation(reservation, "proofs"))

    def test_receipt_preserves_numeric_proof_and_box_for_report(self):
        record = {**self.record, "proves": 12, "box": "Expected receipt"}
        cm = batchseal.manifest("proofs", record, self.members)
        self.assertEqual(batchseal.parse(cm, "proofs"), (record, self.members))

    def test_refuses_incomplete_or_mismatched_receipts(self):
        incomplete = {"abcdef-c1": self.members["abcdef-c1"]}
        cm = batchseal.manifest("proofs", self.record, incomplete)
        self.assertIsNone(batchseal.parse(cm, "proofs"))
        members = copy.deepcopy(self.members)
        members["abcdef-t1"]["job_uid"] = members["abcdef-c1"]["job_uid"]
        cm = batchseal.manifest("proofs", self.record, members)
        self.assertIsNone(batchseal.parse(cm, "proofs"))
        duplicate = {**self.record, "runs": self.record["runs"] + self.record["runs"]}
        cm = batchseal.manifest("proofs", duplicate, self.members)
        self.assertIsNone(batchseal.parse(cm, "proofs"))
        cm = batchseal.manifest("proofs", self.record, self.members)
        cm["immutable"] = False
        self.assertIsNone(batchseal.parse(cm, "proofs"))

    def test_record_recovery_never_overwrites_a_competing_record(self):
        competing = {**self.record, "decree_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(2) as pool:
            first = pool.submit(batchseal.install_record, directory, self.record)
            second = pool.submit(batchseal.install_record, directory, competing)
            accepted = [
                task.result() for task in (first, second) if task.exception() is None
            ]
            errors = [
                task.exception()
                for task in (first, second)
                if task.exception() is not None
            ]
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)
            stored = json.loads(accepted[0].read_text(encoding="utf-8"))
            self.assertIn(stored, (self.record, competing))
            self.assertEqual(batchseal.install_record(directory, stored), accepted[0])
            self.assertEqual(list(accepted[0].parent.iterdir()), accepted)


class BatchFlowTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture = due_fixture.DueSubmitIntegrationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.ns = ns = fixture.cfg.namespace
        fixture.cluster.put("resourcequotas", ns, ns, {
            "status": {"hard": {"requests.cpu": "10", "requests.memory": "36Gi"},
                       "used": {"requests.cpu": "0", "requests.memory": "0"}},
        })  # fmt: skip
        fixture.cluster.node_stats["node-a"] = {
            "node": {"fs": {"availableBytes": 50 * GIB, "capacityBytes": 100 * GIB}}
        }
        self.now = T0
        self.dispatcher = dispatch.Dispatcher(
            fixture.cfg, fixture.kube, clock=lambda: self.now, out=lambda _: None
        )

    def interrupt_staging(self):
        fixture = self.fixture
        create = fixture.kube.create

        def fail_first_treatment_input(obj):
            if obj["kind"] == "ConfigMap" and obj["metadata"]["name"].endswith("-t1"):
                raise kube.KubeError("treatment input failed")
            return create(obj)

        with mock.patch.object(
            fixture.kube, "create", side_effect=fail_first_treatment_input
        ):
            with self.assertRaisesRegex(submit.SubmitError, "treatment input failed"):
                fixture.submit_staged()
        return fixture.marker()

    def run_due_at(self, seconds, *options):
        self.now = T0 + seconds
        self.fixture.cluster.now = iso(seconds)
        with mock.patch.object(due.time, "time", return_value=self.now):
            return self.fixture.run_due_cli(*options)

    def hide_due_issue(self):
        repo = self.fixture.cfg.decree_repo
        self.fixture.fake_gh.answers[
            "GET",
            (
                f"repos/{repo}/issues?state=open&labels=awaiting-live-check"
                "&sort=created&direction=asc&per_page=100"
            ),
        ] = []

    def test_input_failure_stays_inert_and_aged_cleanup_allows_retry(self):
        fixture, ns = self.fixture, self.ns
        reservation = self.interrupt_staging()
        _, batch = batchseal.parse_reservation(reservation, ns)
        self.assertEqual(self.dispatcher.tick(), [])
        original_jobs = fixture.cluster.of("jobs", ns)
        self.assertEqual(len(original_jobs), 2)
        self.assertTrue(all(job["spec"]["suspend"] for job in original_jobs))
        self.run_due_at(3599)
        self.assertEqual(fixture.marker(), reservation)

        self.run_due_at(3601)
        marker = fixture.marker()
        record, _ = batchseal.parse(marker, ns)
        self.assertNotEqual(marker["metadata"]["uid"], reservation["metadata"]["uid"])
        self.assertNotEqual(record["batch"], batch)
        self.assertEqual(len(fixture.cluster.of("jobs", ns)), 6)
        self.assertIsNone(fixture.kube.get(
            "configmaps", runids.run_cm_name(runids.run_id(batch, "control", 1)),
            missing_ok=True,
        ))  # fmt: skip
        self.assertEqual(
            set(self.dispatcher.tick()),
            {
                runids.run_id(record["batch"], "control", 1),
                runids.run_id(record["batch"], "treatment", 1),
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            cfg = replace(fixture.cfg, results_dir=directory)
            reader = collect.Collector(
                cfg, fixture.kube, fixture.gh, out=lambda _: None
            )
            self.assertEqual(reader.run(post=False), {record["batch"]: "pending"})
            (receipt,) = Path(directory).glob("*/batch-*.json")
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), record)

    def test_dry_run_keeps_aged_staging_and_empty_due_reaps_it(self):
        fixture = self.fixture
        reservation = self.interrupt_staging()
        self.hide_due_issue()
        self.run_due_at(3601, "--dry-run")
        self.assertEqual(fixture.marker(), reservation)
        self.assertEqual(len(fixture.cluster.of("jobs", self.ns)), 2)

        self.run_due_at(3601)
        self.assertIsNone(fixture.marker())
        self.assertEqual(fixture.cluster.of("jobs", self.ns), [])
        self.assertFalse(any(
            cm["metadata"]["name"].startswith("eph-run-")
            for cm in fixture.cluster.of("configmaps", self.ns)
        ))  # fmt: skip

    def test_delayed_commit_cannot_replace_a_fresh_reservation_after_expiry(self):
        fixture, ns = self.fixture, self.ns
        replace_marker = fixture.cluster.v_replace
        new_reservations = []
        self.hide_due_issue()

        def expire_before_replace(namespace, args, body):
            manifest = json.loads(body)
            if manifest["kind"] == "ConfigMap":
                original = fixture.marker()
                self.assertEqual(
                    manifest["metadata"]["uid"], original["metadata"]["uid"]
                )
                self.assertEqual(
                    manifest["metadata"]["resourceVersion"],
                    original["metadata"]["resourceVersion"],
                )
                self.run_due_at(3601)
                self.assertIsNone(fixture.marker())
                newer = fixture.kube.create(batchseal.reservation(ns, {
                    "decree_id": fixture.decree_id, "batch": "deadbe",
                }))  # fmt: skip
                self.assertNotEqual(
                    newer["metadata"]["uid"], original["metadata"]["uid"]
                )
                new_reservations.append(newer)
            return replace_marker(namespace, args, body)

        with (
            mock.patch.object(
                fixture.cluster, "v_replace", side_effect=expire_before_replace
            ),
            self.assertRaises(submit.SubmitError),
        ):
            fixture.submit_staged()
        self.assertEqual(new_reservations, [fixture.marker()])
        self.assertEqual(len(new_reservations), 1)
        self.assertEqual(fixture.cluster.of("jobs", ns), [])
        self.assertEqual(self.dispatcher.tick(), [])
        self.assertEqual(list(Path(fixture.cfg.results_dir).glob("*/batch-*.json")), [])

    def test_expiry_cannot_delete_a_reservation_committed_after_its_read(self):
        fixture, ns = self.fixture, self.ns
        replace_marker = fixture.cluster.v_replace
        delete_marker = fixture.kube.delete_configmap_version
        self.hide_due_issue()

        def commit_during_expiry(namespace, args, body):
            def commit_before_delete(staging):
                self.assertIsNotNone(batchseal.parse_reservation(staging, ns))
                committed = replace_marker(namespace, args, body)
                self.assertEqual(committed[0], 0, committed[2])
                return delete_marker(staging)

            with mock.patch.object(
                fixture.kube,
                "delete_configmap_version",
                side_effect=commit_before_delete,
            ):
                output = self.run_due_at(3601)
            self.assertIn("could not expire staging", output)
            self.assertIn("Conflict", output)
            return 1, "", "lost commit response"

        with mock.patch.object(
            fixture.cluster, "v_replace", side_effect=commit_during_expiry
        ):
            record = fixture.submit_staged()
        self.assertEqual(batchseal.parse(fixture.marker(), ns)[0], record)
        self.assertEqual(len(fixture.cluster.of("jobs", ns)), len(record["runs"]))
