"""eph dispatch: one dispatcher, a node budget, the disk rule, backfill, early stop."""

import json
import unittest
from datetime import datetime, timezone

from eph_fakes import CLASSES, FakeCluster, make_cfg
from ephemeral import batchseal, dispatch, judge, kube, runids

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
                {"name": "ws", "restartPolicy": "Always", "resources": {"requests": {"cpu": c["WS_CPU_REQUEST"], "memory": c["WS_MEMORY"]}}},
            ],
            "containers": [{"name": "judge", "resources": {"requests": {"cpu": "150m", "memory": "256Mi"}}}],
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


class SealedBatchTest(Base):
    batch = "deadbe"
    sha = "a" * 64

    def stage(self, rid, **kwargs):
        batch, arm, _ = runids.parse_run(rid)
        j = {"kind": "Job", "apiVersion": "batch/v1", **job(rid, arm, **kwargs)}
        meta = j["metadata"]
        meta["labels"][batchseal.STAGED_LABEL] = batch
        if j["spec"]["suspend"]:
            del meta["labels"][runids.JOB_LABEL_ARM]
        meta = self.kube.create(j)["metadata"]
        cm = self.kube.create({
            "kind": "ConfigMap", "apiVersion": "v1", "immutable": True,
            "metadata": {
                "name": runids.run_cm_name(rid), "namespace": self.cfg.namespace,
                "labels": {runids.JOB_LABEL_REALM: "100"},
                "ownerReferences": [{
                    "apiVersion": "batch/v1", "kind": "Job", "name": meta["name"], "uid": meta["uid"],
                }],
            },
            "data": {"decree.yaml": rid},
        })  # fmt: skip
        return {
            "job_uid": meta["uid"], "input_uid": cm["metadata"]["uid"],
            "input_sha256": batchseal.fingerprint(cm["data"]),
        }  # fmt: skip

    def seal(self, count=1):
        arms = ("control", "treatment")
        runs, members = [], {}
        for n in range(1, count + 1):
            for arm in arms:
                rid = runids.run_id(self.batch, arm, n)
                members[rid] = self.stage(rid)
                runs.append(
                    {
                        "run_id": rid,
                        "arm": arm,
                        "n": n,
                        "images": {"worldserver": "test"},
                    }
                )
        record = {
            "batch": self.batch, "decree_id": "d", "decree_sha256": self.sha,
            "proves": [{"repo": "owner/repo", "issue": 2}],
            "presence": {arm: {} for arm in arms},
            "runs_wanted": dict.fromkeys(arms, count), "runs": runs,
        }  # fmt: skip
        self.kube.create(batchseal.manifest(self.cfg.namespace, record, members))

    def sealed_result(self, rid, verdict, sha):
        _, arm, _ = runids.parse_run(rid)
        self.kube.create(judge.result_configmap({
            "run_id": rid, "verdict": verdict, "arm": arm,
            "decree": "d", "decree_sha256": sha,
        }, self.cfg.namespace))  # fmt: skip

    def test_partial_staging_is_invisible_to_old_dispatcher_and_cannot_block_legacy(
        self,
    ):
        self.stage("deadbe-c1", age=60 * 60)
        self.add("beeeee-c1", "control")
        visible = self.kube.list("jobs", selector=runids.JOB_LABEL_ARM)
        self.assertEqual([runids.run_of_job(j) for j in visible], ["beeeee-c1"])
        self.assertEqual(self.tick(), ["beeeee-c1"])
        self.assertTrue(self.suspended("deadbe-c1"))

    def test_complete_batch_publishes_each_arm_with_its_version_when_started(self):
        self.seal()
        expected = {
            j["metadata"]["name"]: j["metadata"]["resourceVersion"]
            for j in self.c.of("jobs")
        }
        self.assertCountEqual(self.tick(), ["deadbe-c1", "deadbe-t1"])
        patches = {
            args[args.index("jobs") + 1]: json.loads(args[args.index("-p") + 1])
            for args, _ in self.c.calls
            if "patch" in args and "jobs" in args
        }
        self.assertEqual(patches, {
            f"eph-deadbe-{suffix}": {
                "spec": {"suspend": False},
                "metadata": {
                    "resourceVersion": expected[f"eph-deadbe-{suffix}"],
                    "labels": {runids.JOB_LABEL_ARM: arm},
                },
            }
            for suffix, arm in (("c1", "control"), ("t1", "treatment"))
        })  # fmt: skip

    def test_a_missing_or_replaced_member_holds_every_run(self):
        self.seal()
        key = ("configmaps", self.cfg.namespace, runids.run_cm_name("deadbe-t1"))
        cm = self.c.objs.pop(key)
        self.assertEqual(self.tick(), [])
        self.c.objs[key] = cm
        j = self.c.objs[("jobs", self.cfg.namespace, runids.job_name("deadbe-t1"))]
        owner = cm["metadata"]["ownerReferences"][0]
        for obj, field, changed in (
            (cm, "immutable", False),
            (j["metadata"], "uid", "replacement-job"),
            (owner, "uid", "other-job"),
            (cm["metadata"], "uid", "other-input"),
            (cm["data"], "decree.yaml", "changed bytes"),
        ):
            with self.subTest(field=field):
                original = obj[field]
                obj[field] = changed
                self.assertEqual(self.tick(), [])
                obj[field] = original
        self.assertCountEqual(self.tick(), ["deadbe-c1", "deadbe-t1"])

    def test_reaped_first_pair_requires_matching_verdicts_to_release_followers(self):
        self.seal(count=2)
        self.assertCountEqual(self.tick(), ["deadbe-c1", "deadbe-t1"])
        for rid in ("deadbe-c1", "deadbe-t1"):
            self.kube.delete("jobs", runids.job_name(rid))
        self.sealed_result("deadbe-c1", "FAIL", self.sha)
        self.sealed_result("deadbe-t1", "PASS", "b" * 64)
        self.assertEqual(self.tick(), [])
        self.kube.delete("configmaps", runids.result_name("deadbe-t1"))
        self.sealed_result("deadbe-t1", "PASS", self.sha)
        self.assertCountEqual(self.tick(), ["deadbe-c2", "deadbe-t2"])

    def test_restart_continues_removing_verified_followers_of_a_stopped_batch(self):
        self.seal(count=2)
        self.assertCountEqual(self.tick(), ["deadbe-c1", "deadbe-t1"])
        self.sealed_result("deadbe-c1", "FAIL", self.sha)
        self.kube.delete("jobs", runids.job_name("deadbe-c2"))

        self.assertEqual(self.tick(), [])
        self.assertTrue(self.suspended("deadbe-t2"))
        self.sealed_result("deadbe-t1", "PASS", self.sha)
        self.assertEqual(self.tick(), [])
        self.assertTrue(self.suspended("deadbe-t2"))

        self.kube.delete("configmaps", runids.result_name("deadbe-t1"))
        self.sealed_result("deadbe-t1", "FAIL", self.sha)
        self.assertEqual(self.tick(), [])
        self.assertIsNone(
            self.kube.get("jobs", runids.job_name("deadbe-t2"), missing_ok=True)
        )

    def test_finished_staged_job_without_a_result_is_synthesized_for_its_batch(self):
        self.seal(count=2)
        self.assertCountEqual(self.tick(), ["deadbe-c1", "deadbe-t1"])
        j = self.c.objs[("jobs", self.cfg.namespace, runids.job_name("deadbe-c1"))]
        j["metadata"]["labels"][runids.JOB_LABEL_ARM] = "control"
        j["status"]["conditions"] = [{"type": "Failed", "status": "True"}]
        self.sealed_result("deadbe-t1", "PASS", self.sha)
        self.assertEqual(self.tick(), [])
        cm = self.kube.get("configmaps", runids.result_name("deadbe-c1"))
        result = json.loads(cm["data"]["result.json"])
        self.assertEqual(
            (result["arm"], result["decree_sha256"]), ("control", self.sha)
        )
        self.assertEqual(result["verdict"], "INVALID")
        self.assertIsNone(
            self.kube.get("jobs", runids.job_name("deadbe-t2"), missing_ok=True)
        )

    def test_running_stage_without_seal_counts_once_even_with_both_labels(self):
        self.stage("deadbe-c1", suspend=False)
        for i in range(1, 6):
            self.add(f"abcde{i}-c1", "control")
        self.assertEqual(len(self.tick()), 4)


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
