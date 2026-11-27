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
from ephemeral import submit


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
        configmaps = [
            cm
            for cm in self.cluster.of("configmaps", "wow-ephemeral")
            if cm["metadata"].get("labels", {}).get("eph/run")
        ]
        self.assertEqual(
            [cm["data"]["decree.yaml"].encode() for cm in configmaps], [self.raw] * 6
        )
        for cm in configmaps:
            control = cm["metadata"]["labels"]["eph/arm"] == "control"
            self.assertEqual(
                "Overseer.ObsoleteExample" in cm["data"]["overseer.overrides.conf"],
                not control,
            )

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
