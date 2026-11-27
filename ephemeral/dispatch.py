"""`eph dispatch`: the only thing that starts worlds.

The queue is the set of suspended Jobs in the ephemeral namespace, oldest
first. A tick unsuspends a Job only when ALL of these hold:

- this process holds the `eph-dispatcher` Lease (one dispatcher, enforced by
  the cluster, not by good manners);
- a staged Job's batch was committed and each expected run has verified
  inputs or a matching verdict;
- the Job's node is one the config lists, never one it names as off limits, and
  takes the Job's class;
- the node's world count is under its cap;
- the namespace quota has room for the Job's requests, counting worlds this
  tick already started and worlds started but not yet scheduled;
- the node would still have at least `min_free_percent` free disk after the
  Job's disk and every recently started world's disk are counted. If the node's
  stats cannot be read, the answer is no.

Smaller Jobs may skip a head that does not fit (backfill), but once the head
has waited `head_wait_seconds` nothing may skip it. Runs after the first pair of
a batch start only when the first pair came out control FAIL, treatment PASS;
any other first pair stops the batch and its waiting Jobs are removed.
"""

import json
import os
import re
import socket
import time
from datetime import datetime, timezone

from . import batchseal, runids
from .kube import KubeError

_Q = re.compile(r"^(\d+(?:\.\d+)?)(m|Ki|Mi|Gi|Ti|k|M|G|T)?$")
_MUL = {
    None: 1, "m": 0.001, "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
    "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12,
}  # fmt: skip
RESULT_PREFIX = "eph-result-"


class DispatchError(Exception):
    """The dispatcher cannot run (bad config or cluster answer)."""


class LeaseHeld(DispatchError):
    """Another dispatcher holds the lease, or this one lost a race for it."""


def quantity(text):
    m = _Q.match(str(text).strip())
    if not m:
        raise ValueError(f"not a quantity: {text!r}")
    v = float(m[1]) * _MUL[m[2]]
    return int(v) if v == int(v) and m[2] != "m" else v


def _ts(text):
    return (
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _micro(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_micro(text):
    return (
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


# -- reading a Job ---------------------------------------------------------------


def finished(job):
    for c in (job.get("status") or {}).get("conditions", []):
        if c.get("type") in ("Complete", "Failed") and c.get("status") == "True":
            return c
    return None


def is_running(job):
    return job["spec"].get("suspend") is False and not finished(job)


def job_class(job):
    return job["metadata"].get("labels", {}).get(runids.JOB_LABEL_CLASS, "")


def job_claim(job):
    for v in job["spec"]["template"]["spec"].get("volumes", []):
        if "persistentVolumeClaim" in v:
            return v["persistentVolumeClaim"].get("claimName")
    return None


def job_requests(job):
    """(cpu cores, memory bytes) the pod will hold: sidecars plus containers, or the largest plain init step."""
    spec = job["spec"]["template"]["spec"]

    def req(c):
        r = (c.get("resources") or {}).get("requests") or {}
        return quantity(r.get("cpu", 0)), quantity(r.get("memory", 0))

    steady = [req(c) for c in spec.get("containers", [])]
    steady += [
        req(c)
        for c in spec.get("initContainers", [])
        if c.get("restartPolicy") == "Always"
    ]
    cpu = sum(c for c, _ in steady)
    mem = sum(m for _, m in steady)
    for c in spec.get("initContainers", []):
        if c.get("restartPolicy") != "Always":
            ic, im = req(c)
            cpu, mem = max(cpu, ic), max(mem, im)
    return cpu, mem


def job_disk(job):
    return sum(
        quantity(v["emptyDir"]["sizeLimit"])
        for v in job["spec"]["template"]["spec"].get("volumes", [])
        if "emptyDir" in v and v["emptyDir"].get("sizeLimit")
    )


def _sealed_inputs(job, cm, rid, record, member, namespace):
    return (
        job is not None
        and cm is not None
        and _sealed_job_matches(job, rid, record, member["job_uid"], namespace)
        and _sealed_configmap_matches(cm, rid, member, namespace)
    )


def _sealed_job_matches(job, rid, record, uid, namespace):
    meta = job["metadata"]
    labels = meta.get("labels") or {}
    arm = labels.get(runids.JOB_LABEL_ARM)
    expected_arm = runids.parse_run(rid)[1]
    if arm is not None and (job["spec"].get("suspend") or arm != expected_arm):
        return False
    return (
        meta.get("uid") == uid
        and bool(meta.get("resourceVersion"))
        and meta.get("namespace") == namespace
        and not meta.get("deletionTimestamp")
        and labels.get(batchseal.STAGED_LABEL) == record["batch"]
        and labels.get(runids.JOB_LABEL_DECREE) == record["decree_id"]
    )


def _sealed_configmap_matches(cm, rid, member, namespace):
    meta = cm["metadata"]
    if (
        cm.get("immutable") is not True
        or meta.get("uid") != member["input_uid"]
        or meta.get("namespace") != namespace
        or meta.get("deletionTimestamp")
        or meta.get("name") != runids.run_cm_name(rid)
    ):
        return False
    expected_owner = {
        "apiVersion": "batch/v1", "kind": "Job", "name": runids.job_name(rid),
        "uid": member["job_uid"],
    }  # fmt: skip
    owners = meta.get("ownerReferences") or []
    return (
        len(owners) == 1
        and expected_owner.items() <= owners[0].items()
        and batchseal.fingerprint(cm.get("data") or {}) == member["input_sha256"]
    )


def _sealed_result(cm, rid, record):
    if cm is None:
        return None
    labels = cm["metadata"].get("labels") or {}
    verdict = labels.get("eph/verdict")
    arm = runids.parse_run(rid)[1]
    if verdict not in ("PASS", "FAIL", "INVALID"):
        return None
    if (
        labels.get(runids.JOB_LABEL_DECREE) != record["decree_id"]
        or labels.get(runids.JOB_LABEL_ARM) != arm
    ):
        return None
    try:
        result = json.loads((cm.get("data") or {}).get("result.json", ""))
    except (TypeError, ValueError):
        return None
    if isinstance(result, dict) and (
        result.get("run_id"), result.get("arm"), result.get("decree_sha256"),
        result.get("verdict"),
    ) == (rid, arm, record["decree_sha256"], verdict):  # fmt: skip
        return result
    return None


class Dispatcher:
    def __init__(self, cfg, kube, clock=time.time, out=print, owner=None, on_tick=None):
        self.cfg, self.kube, self.clock, self.out = cfg, kube, clock, out
        self.on_tick = on_tick
        who = f"{socket.gethostname()}-{os.getpid()}"
        self.holder = f"{owner}@{who}" if owner else who
        self.claim_node = {n.claim: n for n in cfg.nodes.values()}
        self._stats = {}
        self._holding = False

    def log(self, msg):
        self.out(msg)

    # -- the lease --
    def _lease(self):
        now = self.clock()
        spec = {
            "holderIdentity": self.holder,
            "leaseDurationSeconds": int(self.cfg.lease_seconds),
            "renewTime": _micro(now),
        }
        cur = self.kube.get(
            "leases.coordination.k8s.io", runids.LEASE_NAME, missing_ok=True
        )
        meta = {"name": runids.LEASE_NAME, "namespace": self.cfg.namespace}
        body = {
            "apiVersion": "coordination.k8s.io/v1",
            "kind": "Lease",
            "metadata": meta,
            "spec": spec,
        }
        try:
            if cur is None:
                spec["acquireTime"] = _micro(now)
                self.kube.create(body)
                self._holding = True
                return
            old = cur.get("spec", {})
            alive = (
                old.get("holderIdentity") not in (None, "", self.holder)
                and _parse_micro(old["renewTime"])
                + int(old.get("leaseDurationSeconds", 0))
                > now
            )
            if alive:
                raise LeaseHeld(
                    f"the dispatcher lease is held by {old.get('holderIdentity')}"
                )
            meta["resourceVersion"] = cur["metadata"]["resourceVersion"]
            spec["acquireTime"] = (
                old.get("acquireTime")
                if old.get("holderIdentity") == self.holder
                else _micro(now)
            )
            self.kube.replace(body)
            self._holding = True
        except KubeError as exc:
            raise LeaseHeld(f"could not take the dispatcher lease: {exc}") from exc

    def release(self):
        """Hand the lease back so the next dispatcher need not wait out its duration.

        Only a lease this process took is touched, and only while it still names
        this holder. A failure is logged, never raised: the lease then simply
        expires after `lease_seconds`, as it always did."""
        if not self._holding:
            return
        self._holding = False
        try:
            cur = self.kube.get(
                "leases.coordination.k8s.io", runids.LEASE_NAME, missing_ok=True
            )
            if cur is None or cur.get("spec", {}).get("holderIdentity") != self.holder:
                return
            cur["spec"]["holderIdentity"] = ""
            cur["spec"]["renewTime"] = _micro(self.clock())
            self.kube.replace(cur)
            self.log(f"released the dispatcher lease held as {self.holder}")
        except KubeError as exc:
            self.log(f"could not release the dispatcher lease: {exc}")

    # -- cluster reads --
    def _node_disk(self, node):
        if node not in self._stats:
            try:
                fs = self.kube.raw(f"/api/v1/nodes/{node}/proxy/stats/summary")["node"][
                    "fs"
                ]
                avail, cap = int(fs["availableBytes"]), int(fs["capacityBytes"])
                self._stats[node] = (avail, cap) if cap > 0 and avail >= 0 else None
            except (KubeError, KeyError, TypeError, ValueError) as exc:
                self.log(f"node stats unreadable ({type(exc).__name__}): {exc}")
                self._stats[node] = None
        return self._stats[node]

    def _quota(self):
        items = self.kube.list("resourcequotas")
        q = next(
            (i for i in items if i["metadata"]["name"] == self.cfg.namespace), None
        ) or (items[0] if items else None)
        if q is None:
            return None
        st = q.get("status", {})
        try:
            return {
                k: (quantity(st["hard"][k]), quantity(st["used"][k]))
                for k in ("requests.cpu", "requests.memory")
            }
        except (KeyError, ValueError):
            return None

    # -- one pass --
    def tick(self):
        self._lease()
        self._stats = {}
        legacy = self.kube.list("jobs", selector=runids.JOB_LABEL_ARM)
        staged = self.kube.list("jobs", selector=batchseal.STAGED_LABEL)
        staged_uids = {j["metadata"]["uid"] for j in staged}
        legacy = [
            j for j in legacy
            if j["metadata"]["uid"] not in staged_uids
            and batchseal.STAGED_LABEL not in j["metadata"]["labels"]
        ]  # fmt: skip
        results = self._results()
        verdicts = self._verdicts(results)
        staged, records, cleanup = self._ready_staged(staged, results, verdicts)
        jobs = sorted(
            legacy + staged,
            key=lambda j: (j["metadata"]["creationTimestamp"], j["metadata"]["name"]),
        )
        self._synthesize(jobs, verdicts, records)
        for job in cleanup:
            self._stop_waiting(job)
        jobs = self._early_stop(jobs, verdicts, records)
        return self._admit(jobs)

    def _results(self):
        return {
            name[len(RESULT_PREFIX) :]: cm
            for cm in self.kube.list("configmaps", selector="eph/verdict")
            if (name := cm["metadata"]["name"]).startswith(RESULT_PREFIX)
        }

    def _verdicts(self, results=None):
        return {
            rid: verdict
            for rid, cm in (self._results() if results is None else results).items()
            if (verdict := (cm["metadata"].get("labels") or {}).get("eph/verdict"))
        }

    def _ready_staged(self, staged, results, verdicts):
        """Separate runnable staged Jobs from the remains of stopped batches."""
        if not staged:
            return [], {}, []
        by_run = {runids.run_of_job(job): job for job in staged}
        staged_batches = {
            (labels.get(batchseal.STAGED_LABEL), labels.get(runids.JOB_LABEL_DECREE))
            for job in staged
            if (labels := job["metadata"].get("labels"))
        }
        inputs = {
            cm["metadata"]["name"]: cm
            for cm in self.kube.list("configmaps", selector=runids.JOB_LABEL_REALM)
        }
        ready, records, cleanup = {}, {}, []
        selector = f"{batchseal.COMMIT_LABEL}={batchseal.COMMITTED}"
        for cm in self.kube.list("configmaps", selector=selector):
            parsed = batchseal.parse(cm, self.cfg.namespace)
            if parsed is None:
                continue
            record, members = parsed
            if (record["batch"], record["decree_id"]) not in staged_batches:
                continue
            verified_jobs, lost_first = self._read_staged_members(
                record, members, by_run, inputs, results, verdicts
            )
            if lost_first:
                records[record["batch"]] = record
                cleanup.extend(
                    job for job in verified_jobs.values() if self._waiting(job)
                )
                # Keep terminal Jobs visible to synthesis without starting a peer.
                ready.update(
                    {rid: job for rid, job in verified_jobs.items() if finished(job)}
                )
            elif members.keys() <= verdicts.keys() | verified_jobs.keys():
                records[record["batch"]] = record
                ready.update(verified_jobs)
            elif followers := self._stopped_followers(record, verified_jobs, verdicts):
                records[record["batch"]] = record
                cleanup.extend(followers)

        # A missing or invalid marker cannot remove a running world's reservation.
        waiting = [job for job in ready.values() if not is_running(job)]
        return waiting + [job for job in staged if is_running(job)], records, cleanup

    def _read_staged_members(self, record, members, by_run, inputs, results, verdicts):
        verified_jobs, lost_first = {}, False
        for rid, member in members.items():
            verdicts.pop(rid, None)
            if result := _sealed_result(results.get(rid), rid, record):
                verdicts[rid] = result["verdict"]
                lost_first |= self._is_lost_first(rid, result)
            elif _sealed_inputs(
                by_run.get(rid), inputs.get(runids.run_cm_name(rid)), rid,
                record, member, self.cfg.namespace,
            ):  # fmt: skip
                verified_jobs[rid] = by_run[rid]
        if verified_jobs:
            lost_first |= self._record_missing_firsts(record, by_run, results, verdicts)
        return verified_jobs, lost_first

    @staticmethod
    def _is_lost_first(rid, result):
        return (
            runids.parse_run(rid)[2] == 1
            and result["verdict"] == "INVALID"
            and result.get("synthesized") is True
            and result.get("missing_job") is True
        )

    def _record_missing_firsts(self, record, by_run, results, verdicts):
        """An exact post-commit lookup distinguishes loss from an older list."""
        lost = False
        for arm in record["runs_wanted"]:
            rid = runids.run_id(record["batch"], arm, 1)
            if rid in by_run or rid in results:
                continue
            try:
                current = self.kube.get("jobs", runids.job_name(rid), missing_ok=True)
            except KubeError as exc:
                self.log(f"could not confirm missing Job for {rid}: {exc}")
                continue
            if current is not None:
                continue
            fields = {
                "run_id": rid, "arm": arm, "decree_sha256": record["decree_sha256"],
                "missing_job": True,
            }  # fmt: skip
            reason = "committed first-run Job disappeared without a result"
            lost |= self._record_invalid(fields, record["decree_id"], reason, verdicts)
        return lost

    @staticmethod
    def _waiting(job):
        return job["spec"].get("suspend") is True and not finished(job)

    def _stopped_followers(self, record, verified_jobs, verdicts):
        """Resume cleanup after a previous tick removed part of a stopped batch."""
        decided, passed = self._first_pair(
            record["batch"], record["runs_wanted"], verdicts
        )
        if not decided or passed:
            return []
        return [
            job for rid, job in verified_jobs.items()
            if runids.parse_run(rid)[2] > 1 and self._waiting(job)
        ]  # fmt: skip

    def _synthesize(self, jobs, verdicts, records):
        for j in jobs:
            rid = runids.run_of_job(j)
            done = finished(j)
            if not rid or not done or rid in verdicts:
                continue
            reason = f"no result was written: job {done['type']} ({done.get('reason', '')}: {done.get('message', '')})"
            labels = j["metadata"].get("labels", {})
            fields = {"run_id": rid, "arm": labels.get(runids.JOB_LABEL_ARM, "")}
            if record := records.get(labels.get(batchseal.STAGED_LABEL)):
                fields.update(
                    arm=runids.parse_run(rid)[1], decree_sha256=record["decree_sha256"]
                )
            self._record_invalid(
                fields, labels.get(runids.JOB_LABEL_DECREE, ""), reason, verdicts
            )

    def _record_invalid(self, fields, decree, reason, verdicts):
        rid = fields["run_id"]
        result = {
            **fields, "verdict": "INVALID", "reasons": [reason],
            "synthesized": True, "assertions": [], "acts": [],
        }  # fmt: skip
        cm = {
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {
                "name": runids.result_name(rid), "namespace": self.cfg.namespace,
                "labels": {
                    "eph/decree": decree, "eph/arm": fields["arm"], "eph/verdict": "INVALID",
                },
            },
            "data": {"verdict": "INVALID", "result.json": json.dumps(result)},
        }  # fmt: skip
        try:
            self.kube.create(cm)
        except KubeError as exc:
            # A racing judge can win the create. Read it through the next tick.
            self.log(f"could not record INVALID for {rid}: {exc}")
            return False
        verdicts[rid] = "INVALID"
        self.log(f"{rid}: INVALID, {reason}")
        return True

    @staticmethod
    def _batches(jobs, verdicts):
        """{batch: {"members": [(job, run id, n)], "arms": {arm}}} from Jobs and results."""
        out = {}

        def entry(batch):
            return out.setdefault(batch, {"members": [], "arms": set()})

        for j in jobs:
            rid = runids.run_of_job(j)
            parsed = runids.parse_run(rid) if rid else None
            if parsed:
                e = entry(parsed[0])
                e["members"].append((j, rid, parsed[2]))
                e["arms"].add(parsed[1])
        for rid in verdicts:
            parsed = runids.parse_run(rid)
            if parsed:
                entry(parsed[0])["arms"].add(parsed[1])
        return out

    @staticmethod
    def _first_pair(batch, arms, verdicts):
        """(decided, ok): is the first run of every arm in, and was it control FAIL, treatment PASS."""
        want = {"control": "FAIL", "treatment": "PASS"}
        first = {a: verdicts.get(runids.run_id(batch, a, 1)) for a in arms}
        decided = all(v is not None for v in first.values())
        return decided, decided and all(first[a] == want[a] for a in arms)

    def _stop_waiting(self, job):
        meta = job["metadata"]
        name = meta["name"]
        if batchseal.STAGED_LABEL in meta["labels"]:
            try:
                self.kube.delete_version("jobs", job)
            except KubeError as exc:
                self.log(f"{name}: could not remove stopped Job: {exc}")
                return
        else:
            self.kube.delete("jobs", name)
        rid = runids.run_of_job(job)
        batch = runids.parse_run(rid)[0]
        self.log(f"{rid}: removed, the first pair of {batch} stopped the batch")

    def _early_stop(self, jobs, verdicts, records):
        """Drop waiting runs of a batch whose first pair was not control FAIL, treatment PASS."""
        gone, self._held = set(), set()
        for batch, info in self._batches(jobs, verdicts).items():
            arms = records.get(batch, {}).get("runs_wanted", info["arms"])
            decided, ok = self._first_pair(batch, arms, verdicts)
            for j, _rid, n in info["members"]:
                if n == 1 or not self._waiting(j) or ok:
                    continue
                if decided:
                    self._stop_waiting(j)
                    gone.add(j["metadata"]["name"])
                else:
                    self._held.add(j["metadata"]["name"])
        return [j for j in jobs if j["metadata"]["name"] not in gone]

    def _start_job(self, job, name, rid):
        patch = {"spec": {"suspend": False}}
        if batchseal.STAGED_LABEL in job["metadata"]["labels"]:
            # Publish the arm with the start so older dispatchers count this world.
            patch["metadata"] = {
                "resourceVersion": job["metadata"]["resourceVersion"],
                "labels": {runids.JOB_LABEL_ARM: runids.parse_run(rid)[1]},
            }
        self.kube.patch_merge("jobs", name, patch)

    def _admit(self, jobs):
        cfg = self.cfg
        quota = self._quota()
        now = self.clock()
        per_node, reserved, used_extra = {}, {}, [0.0, 0.0]
        for j in jobs:
            if not is_running(j):
                continue
            node = self.claim_node.get(job_claim(j))
            if node is None:
                continue
            per_node[node.name] = per_node.get(node.name, 0) + 1
            st = j.get("status") or {}
            if not st.get("active"):
                cpu, mem = job_requests(j)
                used_extra[0] += cpu
                used_extra[1] += mem
            if st.get("startTime") and now - _ts(st["startTime"]) < cfg.settle_seconds:
                reserved[node.name] = reserved.get(node.name, 0) + job_disk(j)
        started = []
        for j in jobs:
            if j["spec"].get("suspend") is not True or finished(j):
                continue
            name, rid = j["metadata"]["name"], runids.run_of_job(j)
            if name in self._held:
                continue
            ok, why, never = self._fits(j, quota, used_extra, per_node, reserved)
            if ok:
                self._start_job(j, name, rid)
                node = self.claim_node[job_claim(j)].name
                per_node[node] = per_node.get(node, 0) + 1
                reserved[node] = reserved.get(node, 0) + job_disk(j)
                cpu, mem = job_requests(j)
                used_extra[0] += cpu
                used_extra[1] += mem
                started.append(rid)
                self.log(f"{rid}: started on {node}")
            else:
                self.log(f"{rid}: waits, {why}")
                waited = now - _ts(j["metadata"]["creationTimestamp"])
                if waited > cfg.head_wait_seconds and not never:
                    self.log(f"{rid}: has waited {int(waited)}s, nothing may skip it")
                    break
        return started

    def _fits(self, j, quota, used_extra, per_node, reserved):
        cfg = self.cfg
        node = self.claim_node.get(job_claim(j))
        if node is None or node.name in cfg.never_nodes:
            return False, "its node is not one the config allows", True
        if job_class(j) not in node.classes:
            return False, f"node does not take class {job_class(j)!r}", True
        if per_node.get(node.name, 0) >= node.max_worlds:
            return False, f"node is at its cap of {node.max_worlds}", False
        if quota is None:
            return False, "the namespace quota could not be read", False
        cpu, mem = job_requests(j)
        (hc, uc), (hm, um) = quota["requests.cpu"], quota["requests.memory"]
        if uc + used_extra[0] + cpu > hc or um + used_extra[1] + mem > hm:
            return False, "the namespace quota has no room", False
        stats = self._node_disk(node.name)
        if stats is None:
            return False, "disk stats unreadable, refusing", False
        avail, cap = stats
        left = avail - reserved.get(node.name, 0) - job_disk(j)
        if left * 100 < cfg.min_free_percent * cap:
            return (
                False,
                f"disk: node would drop under {cfg.min_free_percent}% free",
                False,
            )
        return True, "", False

    # -- the loop --
    def run(self, interval=15, once=False, sleep=time.sleep, standby=False):
        """Tick until stopped. With `standby`, a lease held by someone else is
        not fatal: wait and take it when it is released or expires, which lets a
        second dispatcher wait in the wings and take over by itself. `once`
        keeps the strict answer (the lease is held, so raise)."""
        waiting = None
        try:
            while True:
                try:
                    self.tick()
                except LeaseHeld as exc:
                    if not standby or once:
                        raise
                    if str(exc) != waiting:
                        waiting = str(exc)
                        self.log(f"standby: {exc}; checking every {interval}s")
                    sleep(interval)
                    continue
                if waiting is not None:
                    waiting = None
                    self.log(
                        f"standby over: this dispatcher now holds the lease as {self.holder}"
                    )
                if self.on_tick:
                    self.on_tick()
                if once:
                    return 0
                sleep(interval)
        except KeyboardInterrupt:
            return 0
        finally:
            self.release()
