"""Exercise due submission through fake GitHub and Kubernetes."""

import base64
import hashlib
import io
import json
import pathlib
from contextlib import redirect_stdout
from unittest import mock

import test_eph_submit as fixture
from eph_fakes import OLD, OLD_DB, OLD_WS, SHA
from ephemeral import __main__ as cli
from ephemeral import batchseal, runids, submit


class DueSubmitIntegrationTest(fixture.Base):
    def setUp(self):
        super().setUp()
        self.history = pathlib.Path(self.tmp.name) / "history.json"
        self.control_entry = {
            "worldserver": OLD_WS,
            "dbimport": OLD_DB,
            "pin": OLD,
            "dist_inventory": fixture.ControlAutoTest.inventory(),
        }
        self.history.write_text(json.dumps([self.control_entry]), encoding="utf-8")
        self.cluster.put(
            "configmaps",
            "base-realm",
            "overseer-overrides-h1",
            {"data": {"overseer.overrides.conf": "Overseer.ObsoleteExample = 1\n"}},
        )
        self.compare(SHA, "ahead")
        self.compare(OLD, "behind")
        self.decree_id = "brd-guzzler-exit-zero-patron-deaths"
        self.raw = (
            "# Default branch fixture\n"
            + fixture.CHECKED.replace(
                "repo: quadseven/mod-dungeon-clear, issue: 12",
                f"repo: {self.cfg.decree_repo}, issue: 12",
            )
        ).encode()
        repo = self.cfg.decree_repo
        self.fake_gh.answers[
            (
                "GET",
                f"repos/{repo}/issues?state=open&labels=awaiting-live-check"
                "&sort=created&direction=asc&per_page=100",
            )
        ] = [{"number": 12, "body": f"Proof: decree {self.decree_id}"}]
        self.fake_gh.answers[
            ("GET", f"repos/{repo}/contents/data/decrees/{self.decree_id}.yaml")
        ] = {"encoding": "base64", "content": base64.b64encode(self.raw).decode()}
        self.fake_gh.answers[("GET", f"repos/{repo}/issues/12")] = {
            "number": 12,
            "state": "open",
            "body": f"Proof: decree {self.decree_id}",
            "labels": [{"name": "awaiting-live-check"}],
        }

    def run_due_cli(self, *options):
        with (
            mock.patch.object(
                cli, "_runner", return_value=(self.cfg, self.kube, self.gh)
            ),
            mock.patch.object(
                submit, "default_resolves", return_value=lambda _ref: True
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            code = cli.main(
                [
                    "submit",
                    "--due",
                    "1",
                    "--control-history",
                    str(self.history),
                    *options,
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        self.assertFalse(any("-X" in args for args, _ in self.fake_gh.calls))
        return output.getvalue()

    def submit_staged(self, out=lambda _: None):
        return submit.submit(
            self.cfg,
            self.kube,
            self.gh,
            f"data/decrees/{self.decree_id}.yaml",
            fixture.CONTROL,
            clock=self.clock,
            out=out,
            decree_bytes=self.raw,
            stage_batch=True,
        )

    def marker(self):
        return self.kube.get(
            "configmaps", batchseal.name(self.decree_id), missing_ok=True
        )

    def test_dry_run_never_creates_jobs_configmaps_or_records(self):
        before = list(pathlib.Path(self.cfg.results_dir).iterdir())
        output = self.run_due_cli("--dry-run")
        self.assertIn("nothing created", output)
        self.assertFalse(
            any(
                "create" in args and "--dry-run=client" not in args
                for args, _ in self.cluster.calls
            )
        )
        self.assertEqual(self.cluster.of("jobs", "wow-ephemeral"), [])
        self.assertEqual(list(pathlib.Path(self.cfg.results_dir).iterdir()), before)

    def test_real_submit_mounts_the_default_branch_bytes_in_both_arms(self):
        self.assertNotEqual(
            (fixture.ROOT / "data" / "decrees" / f"{self.decree_id}.yaml").read_bytes(),
            self.raw,
        )
        self.run_due_cli()
        batches = list(
            (pathlib.Path(self.cfg.results_dir) / self.decree_id).glob("batch-*.json")
        )
        self.assertEqual(len(batches), 1)
        record = json.loads(batches[0].read_text(encoding="utf-8"))
        self.assertEqual(record["decree_sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(record["decree_path"], f"data/decrees/{self.decree_id}.yaml")
        worlds = self.cluster.of("jobs", "wow-ephemeral")
        self.assertEqual(len(worlds), 6)
        self.assertTrue(all(job["spec"]["suspend"] for job in worlds))
        self.assertEqual(self.kube.list("jobs", selector=runids.JOB_LABEL_ARM), [])
        self.assertTrue(
            all(
                job["metadata"]["labels"][batchseal.STAGED_LABEL] == record["batch"]
                for job in worlds
            )
        )
        configmaps = [
            cm
            for cm in self.cluster.of("configmaps", "wow-ephemeral")
            if cm["metadata"].get("labels", {}).get("eph/run")
        ]
        self.assertEqual(
            [cm["data"]["decree.yaml"].encode() for cm in configmaps], [self.raw] * 6
        )
        for cm in configmaps:
            self.assertIs(cm.get("immutable"), True)
            control = cm["metadata"]["labels"]["eph/arm"] == "control"
            self.assertEqual(
                "Overseer.ObsoleteExample" in cm["data"]["overseer.overrides.conf"],
                not control,
            )
        marker = self.marker()
        self.assertTrue(marker["immutable"])
        saved, members = batchseal.parse(marker, self.cfg.namespace)
        self.assertEqual(saved, record)
        for job in worlds:
            rid = runids.run_of_job(job)
            self.assertEqual(
                job["metadata"]["ownerReferences"],
                [{
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "name": marker["metadata"]["name"],
                    "uid": marker["metadata"]["uid"],
                    "blockOwnerDeletion": False,
                }],
            )  # fmt: skip
            inputs = next(
                cm for cm in configmaps if cm["metadata"]["labels"]["eph/run"] == rid
            )
            self.assertEqual(
                members[rid],
                {
                    "job_uid": job["metadata"]["uid"],
                    "input_uid": inputs["metadata"]["uid"],
                    "input_sha256": batchseal.fingerprint(inputs["data"]),
                },
            )
        writes = [
            ("create" if "create" in args else "replace", json.loads(body))
            for args, body in self.cluster.calls
            if ("create" in args or "replace" in args)
            and "--dry-run=client" not in args
        ]
        verb, reservation = writes[0]
        self.assertEqual(verb, "create")
        self.assertEqual(
            batchseal.parse_reservation(reservation, self.cfg.namespace),
            (self.decree_id, record["batch"]),
        )
        verb, committed = writes[-1]
        self.assertEqual(verb, "replace")
        self.assertEqual(committed["metadata"]["name"], batchseal.name(self.decree_id))
        self.assertEqual(committed["metadata"]["uid"], marker["metadata"]["uid"])
        self.assertNotEqual(
            committed["metadata"]["resourceVersion"],
            marker["metadata"]["resourceVersion"],
        )

    def test_failed_input_discards_its_stage_and_allows_immediate_retry(self):
        original = self.cluster.v_create

        def fail_third_inputs(ns, args, body):
            obj = json.loads(body)
            if obj["kind"] == "ConfigMap" and obj["metadata"]["name"].endswith("-c2"):
                return 1, "", "input create was rejected"
            return original(ns, args, body)

        output = []
        with (
            mock.patch.object(self.cluster, "v_create", side_effect=fail_third_inputs),
            self.assertRaisesRegex(
                submit.SubmitError, r"could not stage run .*input create was rejected"
            ),
        ):
            self.submit_staged(out=output.append)
        self.assertIsNone(self.marker())
        self.assertEqual(self.cluster.of("jobs", self.cfg.namespace), [])
        self.assertEqual(
            self.kube.list("configmaps", selector=runids.JOB_LABEL_REALM), []
        )
        self.assertFalse((pathlib.Path(self.cfg.results_dir) / self.decree_id).exists())
        self.assertEqual(output, [])
        record = self.submit_staged()
        self.assertEqual(batchseal.parse(self.marker(), self.cfg.namespace)[0], record)

    def test_rejected_commit_discards_its_stage(self):
        with (
            mock.patch.object(
                self.cluster, "v_replace", return_value=(1, "", "Forbidden")
            ),
            self.assertRaisesRegex(submit.SubmitError, "reservation was not committed"),
        ):
            self.submit_staged()
        self.assertIsNone(self.marker())
        self.assertEqual(self.cluster.of("jobs", self.cfg.namespace), [])

    def test_failed_cleanup_reports_both_errors_and_leaves_the_stage_inert(self):
        original = self.cluster.v_create

        def fail_input(ns, args, body):
            if json.loads(body)["metadata"]["name"].startswith("eph-run-"):
                return 1, "", "input create was rejected"
            return original(ns, args, body)

        with (
            mock.patch.object(self.cluster, "v_create", side_effect=fail_input),
            mock.patch.object(
                self.cluster, "v_delete", return_value=(1, "", "Forbidden")
            ),
            self.assertRaisesRegex(
                submit.SubmitError, r"input create was rejected.*cleanup.*Forbidden"
            ),
        ):
            self.submit_staged()
        self.assertIsNotNone(
            batchseal.parse_reservation(self.marker(), self.cfg.namespace)
        )
        self.assertEqual(self.kube.list("jobs", selector=runids.JOB_LABEL_ARM), [])

    def test_unconfirmed_input_immutability_prevents_batch_commit(self):
        original = self.cluster.v_create

        def omit_immutability(ns, args, body):
            result = original(ns, args, body)
            obj = json.loads(body)
            if obj["kind"] == "ConfigMap" and obj["metadata"]["name"].startswith(
                "eph-run-"
            ):
                response = json.loads(result[1])
                response.pop("immutable", None)
                return 0, json.dumps(response), ""
            return result

        with (
            mock.patch.object(self.cluster, "v_create", side_effect=omit_immutability),
            self.assertRaisesRegex(
                submit.SubmitError, "API did not confirm staged inputs"
            ),
        ):
            self.submit_staged()
        self.assertIsNone(self.marker())
        self.assertEqual(self.cluster.of("jobs", self.cfg.namespace), [])

    def test_numeric_proves_and_box_are_preserved_in_the_receipt(self):
        box = "the family leaves the bar without a patron dying"
        start, end = self.raw.index(b"proves:\n"), self.raw.index(b"\nfix:")
        self.raw = (
            self.raw[:start] + f'proves: 12\nbox: "{box}"'.encode() + self.raw[end:]
        )
        record = self.submit_staged()
        self.assertEqual(record["proves"], 12)
        self.assertEqual(record["box"], box)
        self.assertEqual(batchseal.parse(self.marker(), self.cfg.namespace)[0], record)

    def test_lost_marker_response_is_confirmed_by_readback(self):
        original = self.cluster.v_replace

        def lose_response(ns, args, body):
            result = original(ns, args, body)
            obj = json.loads(body)
            if obj["metadata"]["name"] == batchseal.name(self.decree_id):
                self.assertEqual(result[0], 0)
                return 1, "", "connection lost after replace"
            return result

        output = []
        with mock.patch.object(self.cluster, "v_replace", side_effect=lose_response):
            record = self.submit_staged(out=output.append)
        self.assertEqual(batchseal.parse(self.marker(), self.cfg.namespace)[0], record)
        self.assertTrue(
            submit.record_path(self.cfg, self.decree_id, record["batch"]).is_file()
        )
        self.assertEqual(len(output), len(record["runs"]))
        with self.assertRaisesRegex(submit.SubmitError, "already exists"):
            self.submit_staged()
        self.assertEqual(len(self.cluster.of("jobs", "wow-ephemeral")), 6)

    def test_local_record_failure_does_not_roll_back_the_committed_stage(self):
        with (
            mock.patch.object(
                batchseal, "install_record", side_effect=OSError("disk full")
            ),
            self.assertRaisesRegex(
                submit.SubmitError, "committed but local record was not installed"
            ),
        ):
            self.submit_staged()
        self.assertIsNotNone(batchseal.parse(self.marker(), self.cfg.namespace))
        self.assertEqual(len(self.cluster.of("jobs", self.cfg.namespace)), 6)
        self.assertFalse(any("delete" in args for args, _ in self.cluster.calls))

    def test_ambiguous_marker_never_removes_potentially_committed_runs(self):
        original_replace = self.cluster.v_replace
        original_get = self.cluster.v_get
        marker_name = batchseal.name(self.decree_id)

        def lose_response(ns, args, body):
            result = original_replace(ns, args, body)
            if json.loads(body)["metadata"]["name"] == marker_name:
                self.assertEqual(result[0], 0)
                return 1, "", "connection lost after replace"
            return result

        def lose_readback(ns, args, body):
            current = self.cluster.objs.get(("configmaps", ns, marker_name))
            if marker_name in args and batchseal.parse(current, ns) is not None:
                return 1, "", "marker readback unavailable"
            return original_get(ns, args, body)

        output = []
        with (
            mock.patch.object(self.cluster, "v_replace", side_effect=lose_response),
            mock.patch.object(self.cluster, "v_get", side_effect=lose_readback),
            self.assertRaisesRegex(
                submit.SubmitError, "could not confirm batch marker"
            ),
        ):
            self.submit_staged(out=output.append)
        marker = self.marker()
        self.assertIsNotNone(batchseal.parse(marker, self.cfg.namespace))
        self.assertEqual(len(self.cluster.of("jobs", "wow-ephemeral")), 6)
        self.assertFalse((pathlib.Path(self.cfg.results_dir) / self.decree_id).exists())
        (options,) = [
            json.loads(body) for args, body in self.cluster.calls if "delete" in args
        ]
        preconditions = options["preconditions"]
        self.assertEqual(preconditions["uid"], marker["metadata"]["uid"])
        self.assertNotEqual(
            preconditions["resourceVersion"], marker["metadata"]["resourceVersion"]
        )
        self.assertEqual(output, [])

    def test_competing_reservation_cannot_stage_jobs(self):
        original = self.cluster.v_create
        competing_batch = "deadbe"

        def race_reservation(ns, args, body):
            obj = json.loads(body)
            if obj["metadata"]["name"] != batchseal.name(self.decree_id):
                return original(ns, args, body)
            reservation = batchseal.reservation(ns, {
                "decree_id": self.decree_id, "batch": competing_batch,
            })  # fmt: skip
            self.assertEqual(original(ns, args, json.dumps(reservation))[0], 0)
            return 1, "", "AlreadyExists"

        output = []
        with (
            mock.patch.object(self.cluster, "v_create", side_effect=race_reservation),
            self.assertRaises(submit.SubmitError),
        ):
            self.submit_staged(out=output.append)
        self.assertEqual(
            batchseal.parse_reservation(self.marker(), self.cfg.namespace),
            (self.decree_id, competing_batch),
        )
        self.assertEqual(self.cluster.of("jobs", "wow-ephemeral"), [])
        self.assertFalse((pathlib.Path(self.cfg.results_dir) / self.decree_id).exists())
        self.assertEqual(output, [])

    def test_receipt_write_failure_leaves_durable_marker_for_recovery(self):
        output = []
        with (
            mock.patch.object(
                batchseal, "install_record", side_effect=OSError("no space")
            ),
            self.assertRaisesRegex(
                submit.SubmitError, "committed but local record was not installed"
            ),
        ):
            self.submit_staged(out=output.append)
        self.assertIsNotNone(batchseal.parse(self.marker(), self.cfg.namespace))
        self.assertEqual(len(self.cluster.of("jobs", "wow-ephemeral")), 6)
        self.assertFalse((pathlib.Path(self.cfg.results_dir) / self.decree_id).exists())
        self.assertEqual(output, [])

    def test_due_skips_a_control_without_dist_inventory(self):
        del self.control_entry["dist_inventory"]
        self.history.write_text(json.dumps([self.control_entry]), encoding="utf-8")
        configmaps = self.cluster.of("configmaps", "wow-ephemeral")
        output = self.run_due_cli()
        self.assertIn(f"skip {self.decree_id}: ", output)
        self.assertIn("dist_inventory", output)
        self.assertEqual(self.cluster.of("jobs", "wow-ephemeral"), [])
        self.assertEqual(self.cluster.of("configmaps", "wow-ephemeral"), configmaps)
        self.assertFalse((pathlib.Path(self.cfg.results_dir) / self.decree_id).exists())
