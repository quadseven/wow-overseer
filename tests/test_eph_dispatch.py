"""eph dispatch: one dispatcher, a node budget, the disk rule, backfill, early stop."""

import json
import unittest
from datetime import datetime, timezone

from eph_fakes import CLASSES, FakeCluster, make_cfg
from ephemeral import dispatch, kube

GIB = 1024**3
T0 = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp()


def iso(offset=0):
    return datetime.fromtimestamp(T0 + offset, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def job(
    rid,
    arm,
    claim="client-data-a",
    klass="lean",
    age=0,
    suspend=True,
    finished=None,
    started=None,
):
    c = CLASSES[klass]
    status = {}
    if finished:
        status["conditions"] = [
            {"type": finished, "status": "True", "reason": "X", "message": "m"}
        ]
    if started is not None:
        status["startTime"] = iso(started)
        status["active"] = 1
    return {
        "metadata": {
            "name": f"eph-{rid}", "namespace": "wow-ephemeral",
            "creationTimestamp": iso(-age),
            "labels": {"eph/arm": arm, "eph/class": klass, "eph/batch": rid[:6], "eph/decree": "d"},
        },
        "spec": {"suspend": suspend, "template": {"spec": {
            "initContainers": [
                {"name": "mysql", "restartPolicy": "Always", "resources": {
                    "requests": {"ephemeral-storage": c["EPHEMERAL_REQUEST"]},
                    "limits": {"ephemeral-storage": c["EPHEMERAL_LIMIT"]},
                }},
                {"name": "ws", "restartPolicy": "Always", "resources": {
                    "requests": {"cpu": c["WS_CPU_REQUEST"], "memory": c["WS_MEMORY"], "ephemeral-storage": "64Mi"},
                    "limits": {"ephemeral-storage": "512Mi"},
                }},
            ],
            "containers": [{"name": "judge", "resources": {
                "requests": {"cpu": "150m", "memory": "256Mi", "ephemeral-storage": "32Mi"},
                "limits": {"ephemeral-storage": "128Mi"},
            }}],
            "volumes": [
                {"name": "client-data", "persistentVolumeClaim": {"claimName": claim}},
                {"name": "datadir", "emptyDir": {"sizeLimit": c["DATADIR_LIMIT"]}},
                {"name": "logs", "emptyDir": {"sizeLimit": "256Mi"}},
            ],
        }}},
        "status": status,
    }  # fmt: skip


class Base(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_cfg(self.tmp.name)
        self.c = FakeCluster()
        self.c.now = iso()
        self.kube = kube.Kubectl("wow-ephemeral", runner=self.c)
        self.c.put("resourcequotas", "wow-ephemeral", "wow-ephemeral", {
            "status": {"hard": {"requests.cpu": "10", "requests.memory": "36Gi"},
                       "used": {"requests.cpu": "0", "requests.memory": "0"}}})  # fmt: skip
        self.free(node_a=0.5, node_b=0.5)
        self.now = T0
        self.logs = []

    def free(self, **pct):
        for k, v in pct.items():
            self.c.node_stats["node-" + k[-1]] = {"node": {"fs": {
                "availableBytes": int(100 * GIB * v), "capacityBytes": 100 * GIB}}}  # fmt: skip

    def add(self, *a, **kw):
        j = job(*a, **kw)
        self.c.put("jobs", "wow-ephemeral", j["metadata"]["name"], j)
        return j

    def result(self, rid, verdict):
        self.c.put("configmaps", "wow-ephemeral", f"eph-result-{rid}", {
            "metadata": {"labels": {"eph/verdict": verdict, "eph/arm": "x", "eph/decree": "d"}},
            "data": {"verdict": verdict}})  # fmt: skip

    def tick(self):
        d = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now, out=self.logs.append
        )
        d.holder = "me"
        return d.tick()

    def suspended(self, rid):
        return self.c.objs[("jobs", "wow-ephemeral", f"eph-{rid}")]["spec"]["suspend"]


class BudgetTest(Base):
    def test_starts_at_most_the_node_cap(self):
        for i in range(1, 8):
            self.add(f"aaaaa{i}-c1", "control", age=100 - i)
        self.tick()
        running = [j for j in self.c.of("jobs") if j["spec"]["suspend"] is False]
        self.assertEqual(len(running), 5)

    def test_second_node_takes_one_and_only_one(self):
        self.add("bbbbb1-c1", "control", claim="client-data-b", age=9)
        self.add("bbbbb2-c1", "control", claim="client-data-b", age=8)
        self.tick()
        self.assertFalse(self.suspended("bbbbb1-c1"))
        self.assertTrue(self.suspended("bbbbb2-c1"))

    def test_full_world_is_not_started_on_a_lean_only_node(self):
        self.add("ccccc1-c1", "control", claim="client-data-b", klass="full")
        self.tick()
        self.assertTrue(self.suspended("ccccc1-c1"))

    def test_unknown_claim_is_never_started(self):
        self.add("ddddd1-c1", "control", claim="client-data-organic")
        self.tick()
        self.assertTrue(self.suspended("ddddd1-c1"))

    def test_quota_headroom_is_respected(self):
        self.c.objs[("resourcequotas", "wow-ephemeral", "wow-ephemeral")]["status"]["used"] = {
            "requests.cpu": "9500m", "requests.memory": "1Gi"}  # fmt: skip
        self.add("eeeee1-c1", "control")
        self.tick()
        self.assertTrue(self.suspended("eeeee1-c1"))

    def test_cpu_request_fits_exactly_at_the_quota_boundary(self):
        status = self.c.of("resourcequotas")[0]["status"]
        status["hard"]["requests.cpu"] = "10100m"
        status["used"]["requests.cpu"] = "8700m"
        self.add("eeeee2-c1", "control")
        queued = self.c.objs[("jobs", "wow-ephemeral", "eph-eeeee2-c1")]
        spec = queued["spec"]["template"]["spec"]
        spec["initContainers"][0]["resources"]["requests"]["cpu"] = "250m"
        self.assertEqual(self.tick(), ["eeeee2-c1"])

    def test_started_but_not_yet_scheduled_worlds_count(self):
        for i in range(1, 4):
            self.add(
                f"fffff{i}-c1", "control", suspend=False
            )  # unsuspended, no pod yet
        self.c.objs[("resourcequotas", "wow-ephemeral", "wow-ephemeral")]["status"][
            "hard"
        ]["requests.cpu"] = "4"
        self.add("fffff9-c1", "control")
        self.tick()
        self.assertTrue(self.suspended("fffff9-c1"))

    def test_finished_jobs_do_not_count(self):
        for i in range(1, 6):
            self.add(f"11111{i}-c1", "control", suspend=False, finished="Complete")
        self.add("222222-c1", "control")
        self.tick()
        self.assertFalse(self.suspended("222222-c1"))

    def test_ordinary_init_overlaps_earlier_sidecars_and_pod_overhead(self):
        queued = job("aa0010-c1", "control")
        spec = queued["spec"]["template"]["spec"]
        spec["initContainers"] = [
            {"restartPolicy": "Always", "resources": {"requests": {"cpu": "600m", "memory": "200Mi"}}},
            {"resources": {"requests": {"cpu": "800m", "memory": "700Mi"}}},
            {"restartPolicy": "Always", "resources": {"requests": {"cpu": "300m", "memory": "100Mi"}}},
        ]  # fmt: skip
        spec["containers"] = [
            {"resources": {"requests": {"cpu": "100m", "memory": "100Mi"}}}
        ]
        spec["overhead"] = {"cpu": "50m", "memory": "64Mi"}
        self.assertEqual(dispatch._job_quota_usage(queued, "requests.cpu"), 1450)
        self.assertEqual(
            dispatch._job_quota_usage(queued, "requests.memory"), 964 * 1024**2
        )


class StorageQuotaTest(Base):
    def quota(self, resource, hard, used=None):
        quota = self.c.of("resourcequotas")[0]
        status = quota["status"]
        quota["spec"] = {"hard": {**status["hard"], resource: hard}}
        if used is not None:
            status["hard"][resource] = hard
            status["used"][resource] = used
        return status

    def test_full_namespace_storage_requests_keep_a_world_suspended(self):
        self.quota("requests.ephemeral-storage", "12Gi", "12Gi")
        self.add("aa0001-c1", "control")
        self.assertEqual(self.tick(), [])
        self.assertTrue(self.suspended("aa0001-c1"))

    def test_storage_requests_fit_only_when_both_sidecars_and_judge_fit(self):
        status = self.quota("requests.ephemeral-storage", "12Gi", "10145Mi")
        self.add("aa0002-c1", "control")
        self.assertEqual(self.tick(), [])
        status["used"]["requests.ephemeral-storage"] = "10144Mi"
        self.assertEqual(self.tick(), ["aa0002-c1"])

    def test_storage_reserves_pending_jobs_and_same_tick_admissions_across_nodes(self):
        self.quota("requests.ephemeral-storage", "4300Mi", "0")
        self.add("aa0003-c1", "control", suspend=False)
        self.add("aa0004-c1", "control", claim="client-data-b", age=2)
        self.add("aa0005-c1", "control", age=1)
        self.assertEqual(self.tick(), ["aa0004-c1"])
        self.assertTrue(self.suspended("aa0005-c1"))

    def test_created_pod_is_already_in_storage_quota_used(self):
        self.quota("requests.ephemeral-storage", "4288Mi", "2144Mi")
        self.add("aa0011-c1", "control", suspend=False)
        self.add("aa0012-c1", "control")
        self.assertEqual(self.tick(), [])
        running = self.c.objs[("jobs", "wow-ephemeral", "eph-aa0011-c1")]
        running["status"]["active"] = 1
        self.assertEqual(self.tick(), ["aa0012-c1"])

    def test_configured_storage_requests_wait_for_quota_status(self):
        status = self.quota("requests.ephemeral-storage", "12Gi")
        self.add("aa0006-c1", "control")
        self.assertEqual(self.tick(), [])
        status["hard"]["requests.ephemeral-storage"] = "12Gi"
        self.assertEqual(self.tick(), [])
        status["used"]["requests.ephemeral-storage"] = "0"
        self.assertEqual(self.tick(), ["aa0006-c1"])

    def test_storage_limits_can_block_with_request_headroom(self):
        self.quota("requests.ephemeral-storage", "12Gi", "0")
        self.quota("limits.ephemeral-storage", "24Gi", "21Gi")
        self.add("aa0007-c1", "control")
        self.assertEqual(self.tick(), [])
        self.assertTrue(self.suspended("aa0007-c1"))

    def test_storage_limit_includes_overhead_at_quota_boundary(self):
        status = self.quota("limits.ephemeral-storage", "4Gi", "321Mi")
        self.add("aa0013-c1", "control")
        queued = self.c.of("jobs")[0]
        queued["spec"]["template"]["spec"]["overhead"] = {"ephemeral-storage": "64Mi"}
        self.assertEqual(self.tick(), [])
        status["used"]["limits.ephemeral-storage"] = "320Mi"
        self.assertEqual(self.tick(), ["aa0013-c1"])

    def test_overhead_does_not_create_a_storage_limit(self):
        queued = job("aa0014-c1", "control")
        spec = queued["spec"]["template"]["spec"]
        spec["overhead"] = {"ephemeral-storage": "64Mi"}
        for container in spec["initContainers"] + spec["containers"]:
            del container["resources"]["limits"]
        self.assertEqual(
            dispatch._job_quota_usage(queued, "limits.ephemeral-storage"), 0
        )

    def test_namespace_pod_quota_counts_one_for_each_new_world(self):
        self.quota("pods", "2", "1")
        self.add("aa0008-c1", "control", age=2)
        self.add("aa0009-c1", "control", claim="client-data-b", age=1)
        self.assertEqual(self.tick(), ["aa0008-c1"])
        self.assertTrue(self.suspended("aa0009-c1"))


class DiskTest(Base):
    def test_refuses_when_node_would_drop_under_twenty_percent_free(self):
        self.free(node_a=0.23)  # a lean world reserves 2.75 GiB: 20.25 percent is left
        self.add("333333-c1", "control")
        self.tick()
        self.assertFalse(self.suspended("333333-c1"))
        self.c.objs[("jobs", "wow-ephemeral", "eph-333333-c1")]["spec"]["suspend"] = (
            True
        )
        self.free(node_a=0.21)  # 18.25 percent would be left
        self.tick()
        self.assertTrue(self.suspended("333333-c1"))

    def test_refuses_when_stats_cannot_be_read(self):
        del self.c.node_stats["node-a"]
        self.add("444444-c1", "control")
        self.tick()
        self.assertTrue(self.suspended("444444-c1"))
        self.assertTrue(any("disk" in line for line in self.logs))

    def test_refuses_on_garbage_stats(self):
        self.c.node_stats["node-a"] = {"node": {"fs": {"capacityBytes": 0}}}
        self.add("555555-c1", "control")
        self.tick()
        self.assertTrue(self.suspended("555555-c1"))

    def test_worlds_admitted_this_pass_reserve_their_disk(self):
        self.free(node_a=0.25)  # room for one world's reservation, not two
        self.add("666666-c1", "control", age=5)
        self.add("666666-t1", "treatment", age=4)
        self.tick()
        started = [j for j in self.c.of("jobs") if j["spec"]["suspend"] is False]
        self.assertEqual(len(started), 1)

    def test_recently_started_worlds_still_reserve_their_disk(self):
        self.free(node_a=0.25)
        self.add("777777-c1", "control", suspend=False, started=-10)
        self.add("777777-t1", "treatment")
        self.tick()
        self.assertTrue(self.suspended("777777-t1"))


class QueueTest(Base):
    def test_oldest_first(self):
        self.c.objs[("resourcequotas", "wow-ephemeral", "wow-ephemeral")]["status"][
            "hard"
        ]["requests.cpu"] = "1500m"
        self.add("888888-c1", "control", age=50)
        self.add("999999-c1", "control", age=500)
        self.tick()
        self.assertFalse(self.suspended("999999-c1"))
        self.assertTrue(self.suspended("888888-c1"))

    def test_small_job_backfills_past_a_waiting_big_one(self):
        self.c.objs[("resourcequotas", "wow-ephemeral", "wow-ephemeral")]["status"][
            "hard"
        ]["requests.cpu"] = "1500m"
        self.add("aaaaaa-c1", "control", klass="full", age=100)
        self.add("bbbbbb-c1", "control", klass="lean", age=50)
        self.tick()
        self.assertTrue(self.suspended("aaaaaa-c1"))
        self.assertFalse(self.suspended("bbbbbb-c1"))

    def test_nothing_skips_a_head_that_waited_thirty_minutes(self):
        self.c.objs[("resourcequotas", "wow-ephemeral", "wow-ephemeral")]["status"][
            "hard"
        ]["requests.cpu"] = "1500m"
        self.add("cccccc-c1", "control", klass="full", age=31 * 60)
        self.add("dddddd-c1", "control", klass="lean", age=50)
        self.tick()
        self.assertTrue(self.suspended("cccccc-c1"))
        self.assertTrue(self.suspended("dddddd-c1"))


class EarlyStopTest(Base):
    def test_second_runs_wait_for_the_first_pair(self):
        for rid, arm in (
            ("abc123-c1", "control"),
            ("abc123-t1", "treatment"),
            ("abc123-c2", "control"),
            ("abc123-t2", "treatment"),
        ):
            self.add(rid, arm)
        self.tick()
        self.assertFalse(self.suspended("abc123-c1"))
        self.assertFalse(self.suspended("abc123-t1"))
        self.assertTrue(self.suspended("abc123-c2"))
        self.assertTrue(self.suspended("abc123-t2"))

    def _pair(self, c1, t1):
        for rid, arm in (("abc123-c1", "control"), ("abc123-t1", "treatment")):
            self.add(rid, arm, suspend=False, finished="Complete")
        self.add("abc123-c2", "control")
        self.add("abc123-t2", "treatment")
        self.result("abc123-c1", c1)
        self.result("abc123-t1", t1)
        self.tick()

    def test_fail_then_pass_releases_the_rest(self):
        self._pair("FAIL", "PASS")
        self.assertFalse(self.suspended("abc123-c2"))
        self.assertFalse(self.suspended("abc123-t2"))

    def test_control_pass_stops_and_removes_the_rest(self):
        self._pair("PASS", "PASS")
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-abc123-c2"), self.c.objs)
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-abc123-t2"), self.c.objs)

    def test_treatment_fail_stops(self):
        self._pair("FAIL", "FAIL")
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-abc123-c2"), self.c.objs)

    def test_invalid_first_pair_stops(self):
        self._pair("INVALID", "PASS")
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-abc123-t2"), self.c.objs)


class SynthesisTest(Base):
    def test_a_finished_job_without_a_result_becomes_invalid(self):
        self.add("abc999-c1", "control", suspend=False, finished="Failed")
        self.tick()
        cm = self.c.objs[("configmaps", "wow-ephemeral", "eph-result-abc999-c1")]
        self.assertEqual(cm["data"]["verdict"], "INVALID")
        self.assertEqual(cm["metadata"]["labels"]["eph/verdict"], "INVALID")
        self.assertIn("no result", json.loads(cm["data"]["result.json"])["reasons"][0])

    def test_an_existing_result_is_not_overwritten(self):
        self.add("abc998-c1", "control", suspend=False, finished="Complete")
        self.result("abc998-c1", "PASS")
        self.tick()
        self.assertEqual(
            self.c.objs[("configmaps", "wow-ephemeral", "eph-result-abc998-c1")][
                "data"
            ]["verdict"],
            "PASS",
        )


BAD_IMAGE = "registry.example.com/db@sha256:" + "9" * 64


class StuckPullTest(Base):
    """A started world whose pod never pulls an image gives its slot back."""

    def pod(self, rid, age, reason="ImagePullBackOff", init=True, phase="Pending"):
        status = {"phase": phase}
        waiting = {
            "name": "mysql",
            "image": BAD_IMAGE,
            "state": {"waiting": {"reason": reason, "message": "pull refused"}},
        }
        status["initContainerStatuses" if init else "containerStatuses"] = [waiting]
        if reason == "Unschedulable":
            status = {
                "phase": "Pending",
                "conditions": [{"type": "PodScheduled", "status": "False",
                                "reason": "Unschedulable"}],
            }  # fmt: skip
        self.c.put("pods", "wow-ephemeral", f"eph-{rid}-x1y2z", {
            "metadata": {"labels": {"job-name": f"eph-{rid}", "eph/arm": "control"},
                         "creationTimestamp": iso(-age)},
            "status": status,
        })  # fmt: skip

    def result_of(self, rid):
        cm = self.c.objs.get(("configmaps", "wow-ephemeral", f"eph-result-{rid}"))
        return cm and json.loads(cm["data"]["result.json"])

    def test_a_pull_failure_past_the_grace_is_invalid_and_frees_the_node(self):
        self.add("aaa111-c1", "control", claim="client-data-b", suspend=False,
                 started=-20 * 60, age=20 * 60)  # fmt: skip
        self.pod("aaa111-c1", age=20 * 60)
        self.add("bbb222-c1", "control", claim="client-data-b", age=35 * 60)
        self.tick()
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-aaa111-c1"), self.c.objs)
        res = self.result_of("aaa111-c1")
        self.assertEqual(res["verdict"], "INVALID")
        self.assertIn("ImagePullBackOff", res["reasons"][0])
        self.assertIn(BAD_IMAGE, res["reasons"][0])
        self.assertIn("mysql", res["reasons"][0])
        cm = self.c.objs[("configmaps", "wow-ephemeral", "eph-result-aaa111-c1")]
        self.assertEqual(cm["metadata"]["labels"]["eph/verdict"], "INVALID")
        self.assertFalse(self.suspended("bbb222-c1"))

    def test_a_main_container_pull_failure_counts_too(self):
        self.add("aaa112-c1", "control", suspend=False, started=-20 * 60)
        self.pod("aaa112-c1", age=20 * 60, reason="ErrImagePull", init=False)
        self.tick()
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-aaa112-c1"), self.c.objs)
        self.assertIn("ErrImagePull", self.result_of("aaa112-c1")["reasons"][0])

    def test_a_pull_failure_inside_the_grace_is_left_alone(self):
        self.add("aaa113-c1", "control", claim="client-data-b", suspend=False,
                 started=-5 * 60)  # fmt: skip
        self.pod("aaa113-c1", age=5 * 60)
        self.add("bbb223-c1", "control", claim="client-data-b")
        self.tick()
        self.assertIn(("jobs", "wow-ephemeral", "eph-aaa113-c1"), self.c.objs)
        self.assertIsNone(self.result_of("aaa113-c1"))
        self.assertTrue(self.suspended("bbb223-c1"))

    def test_a_pod_pending_for_cpu_is_not_a_pull_failure(self):
        self.add("aaa114-c1", "control", suspend=False, started=-20 * 60)
        self.pod("aaa114-c1", age=20 * 60, reason="Unschedulable")
        self.tick()
        self.assertIn(("jobs", "wow-ephemeral", "eph-aaa114-c1"), self.c.objs)
        self.assertIsNone(self.result_of("aaa114-c1"))

    def test_a_pod_still_creating_is_not_a_pull_failure(self):
        self.add("aaa115-c1", "control", suspend=False, started=-20 * 60)
        self.pod("aaa115-c1", age=20 * 60, reason="PodInitializing")
        self.tick()
        self.assertIn(("jobs", "wow-ephemeral", "eph-aaa115-c1"), self.c.objs)

    def test_a_refused_pod_list_leaves_the_tick_working(self):
        self.add("aaa116-c1", "control", claim="client-data-b", suspend=False,
                 started=-20 * 60)  # fmt: skip
        self.pod("aaa116-c1", age=20 * 60)
        self.add("bbb226-c1", "control")
        self.c.fail["pods"] = 1
        self.tick()
        self.assertIn(("jobs", "wow-ephemeral", "eph-aaa116-c1"), self.c.objs)
        self.assertFalse(self.suspended("bbb226-c1"))
        self.assertTrue(any("pods unreadable" in line for line in self.logs))

    def test_a_suspended_or_finished_job_is_never_judged_by_its_pod(self):
        self.add("aaa117-c1", "control", suspend=False, finished="Failed")
        self.result("aaa117-c1", "INVALID")
        self.pod("aaa117-c1", age=20 * 60)
        self.tick()
        self.assertIn(("jobs", "wow-ephemeral", "eph-aaa117-c1"), self.c.objs)

    def test_a_failed_result_write_keeps_the_job_for_the_next_pass(self):
        self.add("aaa118-c1", "control", suspend=False, started=-20 * 60)
        self.pod("aaa118-c1", age=20 * 60)
        self.c.fail["eph-result-aaa118-c1"] = 1
        self.tick()
        self.assertIn(("jobs", "wow-ephemeral", "eph-aaa118-c1"), self.c.objs)

    def test_a_stuck_first_control_stops_its_batch_on_the_same_pass(self):
        self.add("abc777-c1", "control", suspend=False, started=-20 * 60)
        self.add("abc777-t1", "treatment", suspend=False, finished="Complete")
        self.result("abc777-t1", "PASS")
        self.pod("abc777-c1", age=20 * 60)
        self.add("abc777-c2", "control")
        self.tick()
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-abc777-c2"), self.c.objs)

    def test_the_grace_is_a_runner_setting(self):
        self.cfg.image_pull_grace_seconds = 60
        self.add("aaa119-c1", "control", suspend=False, started=-5 * 60)
        self.pod("aaa119-c1", age=5 * 60)
        self.tick()
        self.assertNotIn(("jobs", "wow-ephemeral", "eph-aaa119-c1"), self.c.objs)


class LeaseTest(Base):
    def test_second_dispatcher_is_refused_while_the_lease_is_live(self):
        a = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now, out=lambda *_: None
        )
        a.holder = "one"
        a.tick()
        b = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now + 10, out=lambda *_: None
        )
        b.holder = "two"
        with self.assertRaises(dispatch.LeaseHeld):
            b.tick()

    def test_an_expired_lease_is_taken_over_and_the_holder_renews(self):
        a = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now, out=lambda *_: None
        )
        a.holder = "one"
        a.tick()
        a.tick()
        b = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now + 3600, out=lambda *_: None
        )
        b.holder = "two"
        b.tick()
        lease = self.c.objs[
            ("leases.coordination.k8s.io", "wow-ephemeral", "eph-dispatcher")
        ]
        self.assertEqual(lease["spec"]["holderIdentity"], "two")

    def test_a_lost_race_is_refused(self):
        a = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now, out=lambda *_: None
        )
        a.holder = "one"
        a.tick()
        self.c.fail["replace"] = 1
        with self.assertRaises(dispatch.LeaseHeld):
            a.tick()


class StandbyTest(Base):
    LEASE = ("leases.coordination.k8s.io", "wow-ephemeral", "eph-dispatcher")

    def dispatcher(self, holder, clock):
        d = dispatch.Dispatcher(self.cfg, self.kube, clock=clock, out=self.logs.append)
        d.holder = holder
        return d

    def test_a_standby_dispatcher_waits_for_a_live_lease_then_takes_over_by_itself(
        self,
    ):
        a = self.dispatcher("one", lambda: self.now)
        a.tick()
        clock = {"t": self.now + 10}
        b = self.dispatcher("two", lambda: clock["t"])
        naps = []

        def sleep(seconds):
            naps.append(seconds)
            clock["t"] += 3600  # the holder never renews: the lease runs out
            if len(naps) > 3:
                raise KeyboardInterrupt

        self.assertEqual(b.run(interval=15, sleep=sleep, standby=True), 0)
        self.assertEqual(self.c.objs[self.LEASE]["spec"]["holderIdentity"], "")
        standby_lines = [m for m in self.logs if m.startswith("standby:")]
        self.assertEqual(len(standby_lines), 1)
        self.assertIn("held by one", standby_lines[0])
        self.assertTrue(any("standby over" in m for m in self.logs))
        self.assertEqual(naps[0], 15)

    def test_without_standby_a_held_lease_still_raises(self):
        self.dispatcher("one", lambda: self.now).tick()
        b = self.dispatcher("two", lambda: self.now + 10)
        with self.assertRaises(dispatch.LeaseHeld):
            b.run(sleep=lambda s: None)

    def test_once_keeps_the_strict_answer_even_in_standby(self):
        self.dispatcher("one", lambda: self.now).tick()
        b = self.dispatcher("two", lambda: self.now + 10)
        with self.assertRaises(dispatch.LeaseHeld):
            b.run(once=True, standby=True, sleep=lambda s: None)

    def test_a_standby_never_starts_a_world_while_it_waits(self):
        self.add("aaaaaa-c1", "control")
        self.dispatcher("one", lambda: self.now).tick()
        self.c.objs[("jobs", "wow-ephemeral", "eph-aaaaaa-c1")]["spec"]["suspend"] = (
            True
        )
        b = self.dispatcher("two", lambda: self.now + 10)
        calls = []

        def sleep(seconds):
            calls.append(seconds)
            if len(calls) > 2:
                raise KeyboardInterrupt

        b.run(sleep=sleep, standby=True)
        self.assertTrue(self.suspended("aaaaaa-c1"))

    def test_the_lease_is_released_when_the_loop_ends_so_a_successor_need_not_wait(
        self,
    ):
        a = self.dispatcher("one", lambda: self.now)
        self.assertEqual(a.run(once=True, sleep=lambda s: None), 0)
        self.assertEqual(self.c.objs[self.LEASE]["spec"]["holderIdentity"], "")
        b = self.dispatcher("two", lambda: self.now + 1)
        b.tick()  # no LeaseHeld: it is free the moment the first one is gone
        self.assertEqual(self.c.objs[self.LEASE]["spec"]["holderIdentity"], "two")

    def test_release_leaves_a_lease_another_dispatcher_now_holds(self):
        a = self.dispatcher("one", lambda: self.now)
        a.tick()
        self.dispatcher("two", lambda: self.now + 3600).tick()
        a.release()
        self.assertEqual(self.c.objs[self.LEASE]["spec"]["holderIdentity"], "two")

    def test_a_dispatcher_that_never_held_the_lease_releases_nothing(self):
        self.dispatcher("one", lambda: self.now).tick()
        b = self.dispatcher("two", lambda: self.now + 10)
        with self.assertRaises(dispatch.LeaseHeld):
            b.tick()
        b.release()
        self.assertEqual(self.c.objs[self.LEASE]["spec"]["holderIdentity"], "one")

    def test_a_failed_release_is_logged_and_never_raised(self):
        a = self.dispatcher("one", lambda: self.now)
        a.tick()
        self.c.fail["replace"] = 1
        a.release()
        self.assertTrue(any("could not release" in m for m in self.logs))


class QuantityTest(unittest.TestCase):
    def test_quantities(self):
        self.assertEqual(dispatch.quantity("250m"), 0.25)
        self.assertEqual(dispatch.quantity("3584Mi"), 3584 * 1024**2)
        self.assertEqual(dispatch.quantity("2Gi"), 2 * GIB)
        self.assertEqual(dispatch.quantity("768M"), 768 * 10**6)
        self.assertEqual(dispatch.quantity("4"), 4)
        with self.assertRaises(ValueError):
            dispatch.quantity("lots")


class ReviewFixesTest(Base):
    def test_a_result_without_its_verdict_label_is_skipped_not_a_crash(self):
        d = dispatch.Dispatcher(
            self.cfg, self.kube, clock=lambda: self.now, out=self.logs.append
        )
        d.kube = type(
            "K",
            (),
            {
                "list": lambda s, kind, selector=None, namespace=None: [
                    {"metadata": {"name": "eph-result-abc123-c1"}},
                    {
                        "metadata": {
                            "name": "eph-result-abc123-t1",
                            "labels": {"eph/verdict": "PASS"},
                        }
                    },
                ]
            },
        )()
        self.assertEqual(d._verdicts(), {"abc123-t1": "PASS"})

    def test_a_head_that_can_never_fit_does_not_block_an_honest_job(self):
        self.add("badbad-c1", "control", claim="client-data-organic", age=40 * 60)
        self.add("abcabc-c1", "control", age=50)
        self.tick()
        self.assertFalse(self.suspended("abcabc-c1"))
        self.assertTrue(self.suspended("badbad-c1"))

    def test_unreadable_disk_stats_log_the_reason(self):
        self.c.node_stats["node-a"] = {
            "node": {"fs": {"availableBytes": {}, "capacityBytes": 5}}
        }
        self.add("112233-c1", "control")
        self.tick()
        self.assertTrue(
            any("unreadable" in line and "112233" in line for line in self.logs)
        )


class CleanupTest(Base):
    """Withdrawn batches, a queue age limit and orphaned run inputs (#3407)."""

    def request(self, batch):
        self.c.put("configmaps", "wow-ephemeral", f"eph-withdraw-{batch}", {
            "metadata": {"labels": {"eph/withdraw": batch}}, "data": {"batch": batch}})  # fmt: skip

    def run_cm(self, rid):
        self.c.put("configmaps", "wow-ephemeral", f"eph-run-{rid}", {
            "metadata": {"labels": {"eph/run": rid}}, "data": {}})  # fmt: skip

    def has(self, plural, name):
        return (plural, "wow-ephemeral", name) in self.c.objs

    def reasons(self, rid):
        cm = self.c.objs[("configmaps", "wow-ephemeral", f"eph-result-{rid}")]
        return json.loads(cm["data"]["result.json"])["reasons"]

    def test_a_withdrawn_batch_loses_its_suspended_jobs_with_an_invalid_result_each(
        self,
    ):
        self.add("aaa001-c1", "control")
        self.add("aaa001-c2", "control")
        self.add("bbb002-c1", "control")
        self.request("aaa001")
        self.tick()
        for rid in ("aaa001-c1", "aaa001-c2"):
            self.assertFalse(self.has("jobs", f"eph-{rid}"))
            cm = self.c.objs[("configmaps", "wow-ephemeral", f"eph-result-{rid}")]
            self.assertEqual(cm["metadata"]["labels"]["eph/verdict"], "INVALID")
            self.assertIn("withdrawn", self.reasons(rid)[0])
        self.assertTrue(self.has("jobs", "eph-bbb002-c1"))
        self.assertFalse(self.has("configmaps", "eph-result-bbb002-c1"))
        self.assertFalse(self.has("configmaps", "eph-withdraw-aaa001"))

    def test_a_withdrawal_leaves_a_running_job_of_the_batch_alone(self):
        self.add("aaa003-c1", "control", suspend=False, started=-60)
        self.add("aaa003-c2", "control")
        self.request("aaa003")
        self.tick()
        self.assertTrue(self.has("jobs", "eph-aaa003-c1"))
        self.assertFalse(self.has("jobs", "eph-aaa003-c2"))

    def test_a_withdrawn_job_keeps_its_place_when_the_result_cannot_be_written(self):
        self.add("aaa004-c1", "control")
        self.request("aaa004")
        self.c.fail["eph-result-aaa004-c1"] = 1
        self.tick()
        self.assertTrue(self.has("jobs", "eph-aaa004-c1"))
        self.assertTrue(self.has("configmaps", "eph-withdraw-aaa004"))

    def test_a_request_with_a_malformed_batch_id_removes_nothing(self):
        self.add("aaa005-c1", "control")
        self.request("not-a-batch")
        self.tick()
        self.assertTrue(self.has("jobs", "eph-aaa005-c1"))
        self.assertFalse(self.has("configmaps", "eph-result-aaa005-c1"))

    def test_a_job_older_than_the_queue_limit_is_removed_with_an_invalid_result(self):
        self.cfg.queue_max_age_seconds = 3600
        self.add("aaa006-c1", "control", age=2 * 3600)
        self.add("aaa007-c1", "control", age=600)
        self.c.node_stats.clear()  # nothing may start, so only the age rule acts
        self.tick()
        self.assertFalse(self.has("jobs", "eph-aaa006-c1"))
        self.assertIn("queue_max_age_seconds", self.reasons("aaa006-c1")[0])
        self.assertTrue(self.has("jobs", "eph-aaa007-c1"))
        self.assertFalse(self.has("configmaps", "eph-result-aaa007-c1"))

    def test_the_queue_limit_defaults_to_a_day_and_spares_a_running_job(self):
        self.assertEqual(self.cfg.queue_max_age_seconds, 24 * 3600)
        self.add("aaa008-c1", "control", suspend=False, started=-60, age=3 * 86400)
        self.tick()
        self.assertTrue(self.has("jobs", "eph-aaa008-c1"))

    def test_a_run_configmap_with_no_job_and_a_result_is_deleted(self):
        self.run_cm("aaa009-c1")
        self.result("aaa009-c1", "PASS")
        self.tick()
        self.assertFalse(self.has("configmaps", "eph-run-aaa009-c1"))
        self.assertTrue(self.has("configmaps", "eph-result-aaa009-c1"))

    def test_a_run_configmap_whose_job_exists_or_has_no_result_is_kept(self):
        self.add("aaa010-c1", "control", suspend=False, finished="Complete")
        self.run_cm("aaa010-c1")
        self.result("aaa010-c1", "PASS")
        self.run_cm("aaa011-c1")  # no Job, but no result either
        self.tick()
        self.assertTrue(self.has("configmaps", "eph-run-aaa010-c1"))
        self.assertTrue(self.has("configmaps", "eph-run-aaa011-c1"))

    def test_a_withdrawn_batch_leaves_no_run_configmap_in_one_pass(self):
        self.add("aaa012-c1", "control")
        self.run_cm("aaa012-c1")
        self.request("aaa012")
        self.tick()
        self.assertFalse(self.has("jobs", "eph-aaa012-c1"))
        self.assertFalse(self.has("configmaps", "eph-run-aaa012-c1"))

    def test_every_cluster_call_stays_inside_the_declared_dispatcher_rules(self):
        self.add("aaa013-c1", "control")
        self.add("aaa014-c1", "control", age=3 * 86400)
        self.add("aaa015-c1", "control", suspend=False, started=-60)
        self.run_cm("aaa016-c1")
        self.result("aaa016-c1", "FAIL")
        self.request("aaa013")
        self.tick()
        plural = {
            "Job": "jobs",
            "ConfigMap": "configmaps",
            "Lease": "leases.coordination.k8s.io",
        }
        used = set()
        for argv, text in self.c.calls:
            a = argv[1:]
            while a and a[0] in ("--kubeconfig", "-n"):
                a = a[2:]
            verb, rest = a[0], a[1:]
            if verb in ("create", "replace"):
                used.add(
                    (
                        {"replace": "update"}.get(verb, verb),
                        plural[json.loads(text)["kind"]],
                    )
                )
            elif verb == "get" and rest[0] == "--raw":
                used.add(("get", "nodes/proxy"))
            elif verb == "get":
                named = len(rest) > 1 and not rest[1].startswith("-")
                used.add(("get" if named else "list", rest[0]))
            else:
                used.add((verb, rest[0]))
        self.assertLessEqual(used, dispatch.DISPATCHER_RULES)
        self.assertIn(("delete", "configmaps"), used)
        self.assertEqual(
            {r for v, r in dispatch.DISPATCHER_RULES if v == "delete"},
            {"jobs", "configmaps"},
        )


if __name__ == "__main__":
    unittest.main()
