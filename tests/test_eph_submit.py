"""eph submit: suspended Jobs only, honest refusals, nothing created on a refusal."""

import json
import pathlib
import tempfile
import unittest

from eph_fakes import (
    BRIDGE, DB, FIX, OLD, OLD_BRIDGE, OLD_DB, OLD_WS, SHA, WS, FakeCluster, FakeGh,
    make_cfg,
)  # fmt: skip
from ephemeral import confmerge, dispatch, ghx, kube, submit

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
BRIDGE_ON = GUZZLER.replace("bridge: off", 'bridge: "on"')
WITH_BRIDGE = {**CONTROL, "control_bridge": OLD_BRIDGE}


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
            image_env=getattr(self, "image_env", None),
        )  # fmt: skip

    def compare(self, pin, status):
        path = f"repos/quadseven/mod-dungeon-clear/compare/{FIX}...{pin}"
        self.fake_gh.answers[("GET", path)] = {"status": status}


class SubmitTest(Base):
    def _run_conf(self, suffix):
        cm = next(
            c for c in self.cluster.of("configmaps", "wow-ephemeral")
            if c["metadata"]["name"].endswith(suffix)
        )  # fmt: skip
        return cm["data"]["playerbots.overrides.conf"]

    def test_the_free_realm_ids_are_read_from_the_cluster_once(self):
        """The realm range is 100 ids; reading the used ones per id was a hundred kubectl calls."""
        self.submit(**CONTROL)
        listed = [
            c for c, _ in self.cluster.calls
            if "configmaps" in c and any(a.startswith("eph/realm") or a == "-l" for a in c)
        ]  # fmt: skip
        self.assertEqual(len(listed), 1, listed)

    def test_a_control_prefix_renames_only_the_control_arms_playerbots_keys(self):
        rec = self.submit(control_playerbots_prefix="AiPlayerbot", **CONTROL)
        for suffix in ("-c1", "-c2", "-c3"):
            keys = confmerge.parse(self._run_conf(suffix))
            self.assertIn("AiPlayerbot.Enabled", keys)
            self.assertIn("AiPlayerbot.MaxRandomBots", keys)
            self.assertFalse([k for k in keys if k.startswith("Playerbots.")], suffix)
        for suffix in ("-t1", "-t2", "-t3"):
            keys = confmerge.parse(self._run_conf(suffix))
            self.assertIn("Playerbots.Enabled", keys)
            self.assertFalse([k for k in keys if k.startswith("AiPlayerbot.")], suffix)
        self.assertTrue(any("AiPlayerbot" in d for d in rec["fidelity_deltas"]))

    def test_the_rename_keeps_values_and_leaves_comments_and_other_keys(self):
        lines = [
            "# Playerbots.Enabled is documented here",
            "Playerbots.Enabled = 1",
            "Overseer.X = 2",
            "",
        ]
        out = confmerge.rename_prefix(
            chr(10).join(lines), "Playerbots.", "AiPlayerbot."
        )
        lines[1] = "AiPlayerbot.Enabled = 1"
        self.assertEqual(out, chr(10).join(lines))

    def _conf(self, suffix, group="overseer"):
        cm = next(
            c for c in self.cluster.of("configmaps", "wow-ephemeral")
            if c["metadata"]["name"].endswith(suffix)
        )  # fmt: skip
        return cm["data"][f"{group}.overrides.conf"]

    def test_control_drop_keys_removes_them_from_the_control_arm_only(self):
        rec = self.submit(
            control_drop_keys="Overseer.HeadlessRoster,Playerbots.Enabled", **CONTROL
        )
        for suffix in ("-c1", "-c2", "-c3"):
            self.assertNotIn("Overseer.HeadlessRoster", self._conf(suffix))
            self.assertNotIn("Playerbots.Enabled", self._conf(suffix, "playerbots"))
            self.assertIn("Playerbots.MaxRandomBots", self._conf(suffix, "playerbots"))
        for suffix in ("-t1", "-t2", "-t3"):
            self.assertIn("Overseer.HeadlessRoster", self._conf(suffix))
            self.assertIn("Playerbots.Enabled", self._conf(suffix, "playerbots"))
        delta = [
            d for d in rec["fidelity_deltas"] if "control arm" in d and "dropped" in d
        ]
        self.assertTrue(
            delta
            and "Overseer.HeadlessRoster" in delta[0]
            and "Playerbots.Enabled" in delta[0]
        )

    def test_drop_keys_and_the_prefix_compose(self):
        self.submit(
            control_playerbots_prefix="AiPlayerbot",
            control_drop_keys="Playerbots.Enabled",
            **CONTROL,
        )
        keys = confmerge.parse(self._conf("-c1", "playerbots"))
        self.assertNotIn("AiPlayerbot.Enabled", keys)
        self.assertIn("AiPlayerbot.MaxRandomBots", keys)

    def test_a_malformed_drop_key_is_refused_and_creates_nothing(self):
        for bad in ("Overseer.X;DROP", "", "Overseer.A,,B", "has space"):
            with self.assertRaisesRegex(submit.SubmitError, "drop-keys"):
                self.submit(control_drop_keys=bad, **CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_without_the_prefix_nothing_changes(self):
        self.submit(**CONTROL)
        self.assertIn("Playerbots.Enabled", self._run_conf("-c1"))
        self.assertNotIn("AiPlayerbot", self._run_conf("-c1"))

    def test_a_malformed_prefix_is_refused_and_creates_nothing(self):
        for bad in ("Ai Playerbot", "AiPlayerbot.", "", "x" + chr(10) + "y"):
            with self.assertRaisesRegex(submit.SubmitError, "prefix"):
                self.submit(control_playerbots_prefix=bad, **CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

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

    def test_newest_template_is_resolved_and_the_job_names_it_by_digest(self):
        from unittest import mock

        from test_eph_imagecommit import TPL, TPL_MANIFEST, NewestTemplateTest, TemplateRegistry

        self.cfg.template_images["lean"] = f"{TPL}:newest"
        reg = TemplateRegistry(NewestTemplateTest.TAGS)
        with mock.patch("ephemeral.imagecommit.urlfetch", reg):
            rec = self.submit(**CONTROL)
        import hashlib

        want = f"{TPL}@sha256:" + hashlib.sha256(TPL_MANIFEST).hexdigest()
        self.assertEqual(rec["template_image"], want)
        for job in self.cluster.of("jobs"):
            self.assertIn(want, json.dumps(job))
            self.assertNotIn(":newest", json.dumps(job))

    def test_an_explicit_template_tag_still_works_without_the_registry(self):
        rec = self.submit(**CONTROL)
        self.assertEqual(rec["template_image"], "registry.example.com/t:lean-1")

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

    def _db_upgrade(self, job):
        spec = job["spec"]["template"]["spec"]
        c = next(c for c in spec["initContainers"] if c["image"] in (DB, OLD_DB))
        return c["image"], {e["name"]: e["value"] for e in c["env"]}

    def test_a_control_arm_rebuilds_the_world_database_with_its_own_db_import(self):
        """The template's world database is the live one; the old worldserver needs its era's tables.
        Characters and auth keep the live schema, so the old db-import is limited to the world."""
        self.submit(**CONTROL)
        seen = {"control": 0, "treatment": 0}
        for job in self.cluster.of("jobs"):
            arm = job["metadata"]["labels"]["eph/arm"]
            image, env = self._db_upgrade(job)
            if arm == "control":
                self.assertEqual(image, OLD_DB)
                self.assertEqual(env["EPH_RESET_WORLD"], "1")
                self.assertEqual(env["AC_UPDATES_ENABLE_DATABASES"], "4")
            else:
                self.assertEqual(image, DB)
                self.assertEqual(env["EPH_RESET_WORLD"], "0")
                self.assertEqual(env["AC_UPDATES_ENABLE_DATABASES"], "7")
            seen[arm] += 1
        self.assertEqual(seen, {"control": 3, "treatment": 3})

    def test_a_control_arm_needs_its_db_import_by_digest(self):
        no_db = {k: v for k, v in CONTROL.items() if k != "control_dbimport"}
        with self.assertRaisesRegex(submit.SubmitError, "control-dbimport"):
            self.submit(**no_db)
        with self.assertRaisesRegex(submit.SubmitError, "sha256"):
            self.submit(
                **{**CONTROL, "control_dbimport": "registry.example.com/db:latest"}
            )
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_control_image_must_be_a_digest(self):
        bad = {**CONTROL, "control_worldserver": "registry.example.com/ws:latest"}
        with self.assertRaisesRegex(submit.SubmitError, "sha256"):
            self.submit(**bad)

    def test_pr_images_are_refused(self):
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


def _names(job, key):
    return [c["name"] for c in job["spec"]["template"]["spec"].get(key, [])]


def _bridge(job):
    return next(
        c for c in job["spec"]["template"]["spec"]["initContainers"]
        if c["name"] == "bridge"
    )  # fmt: skip


class BridgeTest(Base):
    """bridge: on adds the sidecar at the arm's own digest; bridge: off renders without it (#2776)."""

    def jobs_by_arm(self):
        return {j["metadata"]["labels"]["eph/arm"]: j for j in self.cluster.of("jobs")}

    def test_bridge_off_renders_no_sidecar_pull_secret_or_placeholder(self):
        self.submit(**CONTROL)
        for job in self.cluster.of("jobs"):
            self.assertNotIn("bridge", _names(job, "initContainers"))
            pull = job["spec"]["template"]["spec"]["imagePullSecrets"]
            self.assertEqual(pull, [{"name": "registry-pull"}])
            self.assertNotIn("BRIDGE", json.dumps(job).upper().replace("BRIDGE:", ""))

    def test_bridge_off_needs_no_bridge_deployment_or_image(self):
        del self.cluster.objs[("deployments", "base-realm", "wow-overseer")]
        rec = self.submit(**CONTROL)
        self.assertTrue(all("bridge" not in r["images"] for r in rec["runs"]))

    def test_bridge_on_gives_each_arm_its_own_digest(self):
        rec = self.submit(BRIDGE_ON, **WITH_BRIDGE)
        jobs = self.jobs_by_arm()
        self.assertEqual(_bridge(jobs["treatment"])["image"], BRIDGE)
        self.assertEqual(_bridge(jobs["control"])["image"], OLD_BRIDGE)
        by = {r["arm"]: r["images"]["bridge"] for r in rec["runs"]}
        self.assertEqual(by, {"treatment": BRIDGE, "control": OLD_BRIDGE})

    def test_bridge_on_adds_the_pull_secret_and_keeps_the_rest_of_the_job(self):
        self.submit(BRIDGE_ON, **WITH_BRIDGE)
        job = self.jobs_by_arm()["treatment"]
        pull = [p["name"] for p in job["spec"]["template"]["spec"]["imagePullSecrets"]]
        self.assertEqual(pull, ["registry-pull", "ghcr"])
        self.assertEqual(
            _names(job, "initContainers"), ["worldserver", "mysql", "bridge", "x"]
        )

    def test_treatment_bridge_can_be_pinned_by_flag(self):
        other = "registry.example.com/bridge@sha256:" + "8" * 64
        self.submit(BRIDGE_ON, arm="treatment", treatment_bridge=other)
        self.assertEqual(_bridge(self.cluster.of("jobs")[0])["image"], other)

    def test_a_control_arm_with_bridge_on_needs_a_control_bridge(self):
        with self.assertRaisesRegex(submit.SubmitError, "control-bridge"):
            self.submit(BRIDGE_ON, **CONTROL)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_bridge_images_must_be_digests(self):
        for args in (
            {**CONTROL, "control_bridge": "registry.example.com/bridge:latest"},
            {**CONTROL, "control_bridge": OLD_BRIDGE, "treatment_bridge": "x:latest"},
        ):
            with self.assertRaisesRegex(submit.SubmitError, "bridge.*sha256"):
                self.submit(BRIDGE_ON, **args)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_the_base_bridge_image_must_be_a_digest(self):
        dep = self.cluster.objs[("deployments", "base-realm", "wow-overseer")]
        dep["spec"]["template"]["spec"]["containers"][0]["image"] = "x:latest"
        with self.assertRaisesRegex(submit.SubmitError, "bridge.*digest"):
            self.submit(BRIDGE_ON, arm="treatment")

    def test_a_template_without_the_sidecar_is_refused_not_downgraded(self):
        cm = self.cluster.objs[("configmaps", "wow-ephemeral", "eph-world-template")]
        doc = json.loads(cm["data"]["job.yaml"])
        spec = doc["spec"]["template"]["spec"]
        spec["initContainers"] = [
            c for c in spec["initContainers"] if c["name"] != "bridge"
        ]
        cm["data"]["job.yaml"] = json.dumps(doc).replace("{{BRIDGE_IMAGE}}", "")
        cm["data"]["tokens.txt"] = cm["data"]["tokens.txt"].replace(
            "BRIDGE_IMAGE: x", ""
        )
        with self.assertRaisesRegex(submit.SubmitError, "no bridge sidecar"):
            self.submit(BRIDGE_ON, arm="treatment")
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_a_sidecar_that_reaches_a_secret_or_the_api_is_refused(self):
        cm = self.cluster.objs[("configmaps", "wow-ephemeral", "eph-world-template")]
        for bad in (
            {
                "env": [
                    {
                        "name": "T",
                        "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}},
                    }
                ]
            },
            {"volumeMounts": [{"name": "api-token", "mountPath": "/x"}]},
            {"ports": [{"containerPort": 8080}]},
        ):
            doc = json.loads(cm["data"]["job.yaml"])
            for c in doc["spec"]["template"]["spec"]["initContainers"]:
                if c["name"] == "bridge":
                    c.update(bad)
            saved = cm["data"]["job.yaml"]
            cm["data"]["job.yaml"] = json.dumps(doc)
            with self.assertRaisesRegex(submit.SubmitError, "bridge sidecar must be"):
                self.submit(BRIDGE_ON, arm="treatment")
            cm["data"]["job.yaml"] = saved
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_a_sidecar_with_any_other_path_to_secret_data_is_refused(self):
        cm = self.cluster.objs[("configmaps", "wow-ephemeral", "eph-world-template")]
        saved = cm["data"]["job.yaml"]
        cases = {
            "envFrom secret": (
                {"envFrom": [{"secretRef": {"name": "s"}}]},
                [],
            ),
            "mount of a secret volume": (
                {"volumeMounts": [{"name": "creds", "mountPath": "/c"}]},
                [{"name": "creds", "secret": {"secretName": "s"}}],
            ),
            "mount of a projected volume": (
                {"volumeMounts": [{"name": "proj", "mountPath": "/p"}]},
                [
                    {
                        "name": "proj",
                        "projected": {"sources": [{"secret": {"name": "s"}}]},
                    }
                ],
            ),
        }
        for label, (patch, volumes) in cases.items():
            doc = json.loads(saved)
            spec = doc["spec"]["template"]["spec"]
            spec["volumes"] += volumes
            for c in spec["initContainers"]:
                if c["name"] == "bridge":
                    c.update(patch)
            cm["data"]["job.yaml"] = json.dumps(doc)
            with self.assertRaisesRegex(
                submit.SubmitError, "bridge sidecar must be", msg=label
            ):
                self.submit(BRIDGE_ON, arm="treatment")
        cm["data"]["job.yaml"] = saved
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_a_sidecar_may_mount_the_run_and_tmp_volumes_and_a_plain_configmap_env(
        self,
    ):
        cm = self.cluster.objs[("configmaps", "wow-ephemeral", "eph-world-template")]
        doc = json.loads(cm["data"]["job.yaml"])
        spec = doc["spec"]["template"]["spec"]
        spec["volumes"] += [
            {"name": "run", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ]
        for c in spec["initContainers"]:
            if c["name"] == "bridge":
                c["volumeMounts"] = [
                    {"name": "run", "mountPath": "/run/eph", "readOnly": True},
                    {"name": "tmp", "mountPath": "/scratch"},
                ]
        cm["data"]["job.yaml"] = json.dumps(doc)
        self.submit(BRIDGE_ON, arm="treatment")
        self.assertEqual(len(self.cluster.of("jobs")), 3)

    def test_the_dispatcher_counts_the_sidecar_requests(self):
        self.submit(BRIDGE_ON, **WITH_BRIDGE)
        on = dispatch.job_requests(self.jobs_by_arm()["treatment"])
        for j in self.cluster.of("jobs"):
            self.cluster.objs.pop(("jobs", "wow-ephemeral", j["metadata"]["name"]))
        self.submit(**CONTROL)
        off = dispatch.job_requests(self.jobs_by_arm()["treatment"])
        self.assertAlmostEqual(on[0] - off[0], 0.05)
        self.assertEqual(on[1] - off[1], 192 * 1024**2)

    def test_the_fidelity_deltas_say_what_the_bridge_is(self):
        rec = self.submit(BRIDGE_ON, **WITH_BRIDGE)
        text = "; ".join(rec["fidelity_deltas"])
        self.assertIn("bridge: on", text)
        self.assertNotIn("bridge: off", text)
        off = self.submit(**CONTROL)
        self.assertIn("bridge: off", "; ".join(off["fidelity_deltas"]))


BRIDGE_FIX = (
    BRIDGE_ON.replace("issue: TODO", "issue: 12")
    .replace("commit: TODO", f"commit: {FIX}")
    .replace("quadseven/mod-dungeon-clear", "quadseven/wow-overseer")
)


class BridgePinTest(Base):
    """A bridge fix proves presence from the commit baked into each arm's bridge image (no manual pins)."""

    def setUp(self):
        super().setUp()
        self.asked = []
        self.commits = {BRIDGE: SHA, OLD_BRIDGE: OLD}

        def image_env(ref, name):
            self.asked.append((ref, name))
            return self.commits.get(ref)

        self.image_env = image_env

    def compare(self, pin, status):
        path = f"repos/quadseven/wow-overseer/compare/{FIX}...{pin}"
        self.fake_gh.answers[("GET", path)] = {"status": status}

    def test_the_map_has_the_bridge_repo(self):
        from ephemeral import runcfg

        self.assertEqual(
            runcfg.DEFAULT_FIX_PIN_ENV["quadseven/wow-overseer"], "OVERSEER_COMMIT"
        )

    def test_both_arms_are_checked_from_their_own_images(self):
        self.compare(SHA, "ahead")
        self.compare(OLD, "diverged")
        rec = self.submit(BRIDGE_FIX, **WITH_BRIDGE)
        self.assertEqual(rec["presence"]["treatment"], {"pin": SHA, "state": "present"})
        self.assertEqual(rec["presence"]["control"], {"pin": OLD, "state": "absent"})
        self.assertIn((BRIDGE, "OVERSEER_COMMIT"), self.asked)
        self.assertIn((OLD_BRIDGE, "OVERSEER_COMMIT"), self.asked)

    def test_a_control_image_that_already_has_the_fix_is_refused(self):
        self.compare(SHA, "ahead")
        self.compare(OLD, "ahead")
        with self.assertRaisesRegex(submit.SubmitError, "control"):
            self.submit(BRIDGE_FIX, **WITH_BRIDGE)
        self.assertEqual(self.cluster.of("jobs"), [])

    def test_an_explicit_pin_beats_the_image(self):
        other = "e" * 40
        self.compare(other, "diverged")
        self.compare(SHA, "ahead")
        rec = self.submit(BRIDGE_FIX, **{**WITH_BRIDGE, "control_pin": other})
        self.assertEqual(rec["presence"]["control"]["pin"], other)

    def test_an_image_whose_commit_cannot_be_read_is_unchecked_not_an_error(self):
        self.commits = {}
        rec = self.submit(BRIDGE_FIX, **WITH_BRIDGE)
        self.assertEqual(rec["presence"]["treatment"]["state"], "unchecked")
        self.assertEqual(rec["presence"]["control"]["state"], "unchecked")

    def test_a_malformed_commit_from_an_image_is_not_trusted(self):
        self.commits = {BRIDGE: "not-a-sha", OLD_BRIDGE: "abc"}
        rec = self.submit(BRIDGE_FIX, **WITH_BRIDGE)
        self.assertEqual(rec["presence"]["treatment"]["state"], "unchecked")

    def test_other_repos_still_read_the_worldserver_pins_not_the_image(self):
        self.submit(CHECKED, arm="treatment")
        self.assertEqual(self.asked, [])


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
