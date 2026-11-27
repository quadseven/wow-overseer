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


if __name__ == "__main__":
    unittest.main()
