import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest import mock

import test_eph_due_submit as due_fixture
from ephemeral import batchseal, collect, dispatch, kube, runids, submit
from test_eph_dispatch import GIB, T0


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
    def test_input_failure_stays_suspended_then_complete_retry_can_be_collected(self):
        fixture = due_fixture.DueSubmitIntegrationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ns = fixture.cfg.namespace
        fixture.cluster.put("resourcequotas", ns, ns, {
            "status": {"hard": {"requests.cpu": "10", "requests.memory": "36Gi"},
                       "used": {"requests.cpu": "0", "requests.memory": "0"}},
        })  # fmt: skip
        fixture.cluster.node_stats["node-a"] = {
            "node": {"fs": {"availableBytes": 50 * GIB, "capacityBytes": 100 * GIB}}
        }
        create = fixture.kube.create

        def fail_first_treatment_input(obj):
            if obj["kind"] == "ConfigMap" and obj["metadata"]["name"].endswith("-t1"):
                raise kube.KubeError("treatment input failed")
            return create(obj)

        dispatcher = dispatch.Dispatcher(
            fixture.cfg, fixture.kube, clock=lambda: T0, out=lambda _: None
        )
        with mock.patch.object(
            fixture.kube, "create", side_effect=fail_first_treatment_input
        ):
            with self.assertRaisesRegex(submit.SubmitError, "treatment input failed"):
                fixture.submit_staged()
        self.assertEqual(dispatcher.tick(), [])
        fixture.run_due_cli()
        record, _ = batchseal.parse(fixture.marker(), ns)
        started = dispatcher.tick()
        self.assertEqual(
            set(started),
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
