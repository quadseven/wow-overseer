"""eph submit: suspended Jobs only, honest refusals, nothing created on a refusal."""

import json
import pathlib
import tempfile
import unittest

from eph_fakes import (
    DB, FIX, OLD, OLD_DB, OLD_WS, SHA, WS, FakeCluster, FakeGh, make_cfg,
)  # fmt: skip
from ephemeral import confmerge, ghx, kube, submit

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUZZLER = (
    ROOT / "data" / "decrees" / "brd-guzzler-exit-zero-patron-deaths.yaml"
).read_text(encoding="utf-8")
CHECKED = GUZZLER.replace("issue: TODO", "issue: 12").replace(
    "commit: TODO", f"commit: {FIX}"
)
CONTROL = {
    "control_worldserver": OLD_WS, "control_dbimport": OLD_DB, "control_pin": OLD,
}  # fmt: skip


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_cfg(self.tmp.name)
        self.cluster = FakeCluster()
        self.kube = kube.Kubectl("wow-ephemeral", runner=self.cluster)
        self.fake_gh = FakeGh()
        self.gh = ghx.Gh(self.fake_gh)
        self.decree = pathlib.Path(self.tmp.name) / "d.yaml"

    def clock(self):
        self.t = getattr(self, "t", 1000.0) + 1
        return self.t

    def write(self, text):
        self.decree.write_bytes(text.encode("utf-8"))

    def submit(self, text=GUZZLER, **args):
        self.write(text)
        return submit.submit(
            self.cfg, self.kube, self.gh, self.decree, args,
            clock=self.clock, out=lambda *_: None,
        )  # fmt: skip

    def compare(self, pin, status):
        path = f"repos/quadseven/mod-dungeon-clear/compare/{FIX}...{pin}"
        self.fake_gh.answers[("GET", path)] = {"status": status}


class SubmitTest(Base):
    def test_creates_six_suspended_jobs_with_owned_run_configs(self):
        rec = self.submit(**CONTROL)
        jobs = self.cluster.of("jobs")
        self.assertEqual(len(jobs), 6)
        self.assertTrue(all(j["spec"]["suspend"] is True for j in jobs))
        self.assertEqual(
            [r["run_id"][7:] for r in rec["runs"]], ["c1", "t1", "c2", "t2", "c3", "t3"]
        )
        cms = [
            c for c in self.cluster.of("configmaps", "wow-ephemeral")
            if c["metadata"]["name"].startswith("eph-run-")
        ]  # fmt: skip
        self.assertEqual(len(cms), 6)
        owner = cms[0]["metadata"]["ownerReferences"][0]
        self.assertIn(owner["uid"], [j["metadata"]["uid"] for j in jobs])
        self.assertEqual(cms[0]["data"]["decree.yaml"], GUZZLER)

    def test_arms_use_their_own_images_and_the_node_claim(self):
        rec = self.submit(**CONTROL)
        by = {r["arm"]: r["images"] for r in rec["runs"]}
        self.assertEqual(by["treatment"], {"worldserver": WS, "dbimport": DB})
        self.assertEqual(by["control"], {"worldserver": OLD_WS, "dbimport": OLD_DB})
        text = json.dumps(self.cluster.of("jobs")[0])
        self.assertIn("client-data-a", text)
        self.assertNotIn("{{", text)

    def test_realm_ids_are_unique_and_in_range(self):
        rec = self.submit(**CONTROL)
        ids = [r["realm_id"] for r in rec["runs"]]
        self.assertEqual(len(set(ids)), 6)
        self.assertTrue(all(1 <= i <= 255 for i in ids))
        again = self.submit(**CONTROL)
        self.assertFalse(set(ids) & {r["realm_id"] for r in again["runs"]})

    def test_merged_config_replaces_keys_and_lists_deltas(self):
        rec = self.submit(**CONTROL)
        cm = next(
            c for c in self.cluster.of("configmaps", "wow-ephemeral")
            if c["metadata"]["name"].endswith("-c1")
        )  # fmt: skip
        text = cm["data"]["playerbots.overrides.conf"]
        self.assertEqual(text.count("Playerbots.MaxRandomBots"), 1)
        self.assertIn("Playerbots.MaxRandomBots = 0", text)
        self.assertEqual(confmerge.parse(text)["Playerbots.Enabled"], "1")
        self.assertIn("Playerbots.MaxRandomBots: 2600 -> 0", rec["fidelity_deltas"])
        self.assertIn(
            "clients: none (every character is headless)", rec["fidelity_deltas"]
        )

    def test_record_is_saved_for_collect(self):
        rec = self.submit(**CONTROL)
        p = submit.record_path(self.cfg, rec["decree_id"], rec["batch"])
        saved = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(saved["batch"], rec["batch"])

    def test_dry_run_creates_nothing(self):
        self.submit(dry_run=True, **CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_treatment_only_needs_no_control_images(self):
        rec = self.submit(arm="treatment")
        self.assertEqual({r["arm"] for r in rec["runs"]}, {"treatment"})

    def test_control_arm_without_images_is_refused_and_creates_nothing(self):
        with self.assertRaisesRegex(submit.SubmitError, "control"):
            self.submit()
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_control_image_must_be_a_digest(self):
        bad = {**CONTROL, "control_worldserver": "registry.example.com/ws:latest"}
        with self.assertRaisesRegex(submit.SubmitError, "sha256"):
            self.submit(**bad)

    def test_bridge_on_and_pr_images_are_refused(self):
        with self.assertRaisesRegex(submit.SubmitError, "bridge"):
            self.submit(GUZZLER.replace("bridge: off", 'bridge: "on"'), **CONTROL)
        pr = GUZZLER.replace(
            "image: follow-dev", "image: {pr: quadseven/mod-overseer#5}"
        )
        with self.assertRaisesRegex(submit.SubmitError, "follow-dev"):
            self.submit(pr, **CONTROL)

    def test_a_decree_that_does_not_lint_is_refused(self):
        with self.assertRaisesRegex(submit.SubmitError, "lint"):
            self.submit(GUZZLER.replace("class: lean", "class: huge"), **CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_wrong_fix_presence_is_refused(self):
        self.compare(SHA, "behind")  # treatment lacks the fix
        with self.assertRaisesRegex(submit.SubmitError, "treatment"):
            self.submit(CHECKED, **CONTROL)
        self.compare(SHA, "ahead")
        self.compare(OLD, "ahead")  # control already has it
        with self.assertRaisesRegex(submit.SubmitError, "control"):
            self.submit(CHECKED, **CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_right_fix_presence_is_recorded_as_checked(self):
        self.compare(SHA, "ahead")
        self.compare(OLD, "diverged")
        rec = self.submit(CHECKED, **CONTROL)
        self.assertEqual(rec["presence"]["treatment"]["state"], "present")
        self.assertEqual(rec["presence"]["control"]["state"], "absent")

    def test_todo_fix_is_recorded_unchecked(self):
        rec = self.submit(**CONTROL)
        self.assertEqual(rec["presence"]["treatment"]["state"], "unchecked")

    def test_unknown_template_token_is_refused(self):
        cm = self.cluster.objs[("configmaps", "wow-ephemeral", "eph-world-template")]
        cm["data"]["job.yaml"] += "{{SURPRISE}}"
        with self.assertRaisesRegex(submit.SubmitError, "SURPRISE"):
            self.submit(**CONTROL)

    def test_unsuspended_template_is_refused(self):
        cm = self.cluster.objs[("configmaps", "wow-ephemeral", "eph-world-template")]
        cm["data"]["job.yaml"] = cm["data"]["job.yaml"].replace(
            '"suspend": true', '"suspend": false'
        )
        with self.assertRaisesRegex(submit.SubmitError, "suspended"):
            self.submit(**CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_base_image_must_be_a_digest(self):
        dep = self.cluster.objs[("deployments", "base-realm", "worldserver")]
        dep["spec"]["template"]["spec"]["containers"][0]["image"] = (
            "registry.example.com/ws:latest"
        )
        with self.assertRaisesRegex(submit.SubmitError, "digest"):
            self.submit(**CONTROL)

    def test_full_class_never_lands_on_a_lean_only_node(self):
        with self.assertRaisesRegex(submit.SubmitError, "class"):
            self.submit(
                GUZZLER.replace("class: lean", "class: full"), node="node-b", **CONTROL
            )

    def test_failed_run_config_removes_its_job(self):
        self.cluster.fail["eph-run"] = 1
        with self.assertRaises(kube.KubeError):
            self.submit(**CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])


class ModuleLogTest(Base):
    """The world writes the module's and the bots' log lines to the file the judge reads."""

    def worldserver_conf(self, rid_suffix="-c1"):
        cm = next(
            c for c in self.cluster.of("configmaps", "wow-ephemeral")
            if c["metadata"]["name"].endswith(rid_suffix)
        )  # fmt: skip
        return cm["data"]["worldserver.overrides.conf"]

    def setUp(self):
        super().setUp()
        cm = self.cluster.objs[("configmaps", "base-realm", "worldserver-overrides-h1")]
        cm["data"]["worldserver.overrides.conf"] = (
            "MaxPlayerLevel = 60\nAppender.Overseer = 1,6,7\n"
            "Logger.module.overseer = 6,Overseer\n"
        )

    def test_a_file_appender_writes_the_file_the_judge_reads(self):
        from ephemeral import podpaths

        self.submit(**CONTROL)
        conf = confmerge.parse(self.worldserver_conf())
        kind, level, _flags, name, mode = (
            conf["Appender.EphModule"].strip('"').split(",")
        )
        self.assertEqual(kind, "2")  # a file appender
        self.assertEqual(level, "6")
        self.assertEqual(name, podpaths.LOG_NAME)
        self.assertEqual(mode, "w")

    def test_the_judge_resolves_that_same_file_from_the_pods_logs_directory(self):
        from ephemeral import podpaths

        self.submit(**CONTROL)
        conf = confmerge.parse(self.worldserver_conf())
        written = conf["Appender.EphModule"].strip('"').split(",")[3]
        self.assertEqual(
            podpaths.log_path(None, {"EPH_LOGS_DIR": "/logs"}), "/logs/Module.log"
        )
        self.assertEqual(
            podpaths.log_path(None, {"EPH_LOGS_DIR": "/logs"}), "/logs/" + written
        )

    def test_the_module_and_the_bots_log_to_it_and_keep_their_other_appenders(self):
        self.submit(**CONTROL)
        conf = confmerge.parse(self.worldserver_conf())
        self.assertEqual(
            conf["Logger.module.overseer"].strip('"'), "6,Overseer EphModule"
        )
        self.assertIn("EphModule", conf["Logger.playerbots"])
        self.assertIn("Console", conf["Logger.playerbots"])

    def test_each_key_appears_once_even_when_the_base_file_set_it(self):
        self.submit(**CONTROL)
        text = self.worldserver_conf()
        for key in (
            "Logger.module.overseer",
            "Appender.EphModule",
            "Appender.Overseer",
        ):
            self.assertEqual(text.count(key + " "), 1, key)

    def test_the_change_is_listed_as_a_fidelity_delta(self):
        rec = self.submit(**CONTROL)
        self.assertTrue(
            any(d.startswith("Appender.EphModule:") for d in rec["fidelity_deltas"])
        )


class ConfMergeTest(unittest.TestCase):
    def test_value_rendering(self):
        self.assertEqual(confmerge.render_value(True), "1")
        self.assertEqual(confmerge.render_value("a,b"), '"a,b"')
        self.assertEqual(confmerge.render_value("2.5"), "2.5")
        with self.assertRaises(confmerge.ConfError):
            confmerge.render_value('x"y')

    def test_unknown_prefix_goes_to_worldserver(self):
        self.assertEqual(confmerge.group_of("MaxPlayerLevel"), "worldserver")
        self.assertEqual(confmerge.group_of("Overseer.X"), "overseer")


if __name__ == "__main__":
    unittest.main()
