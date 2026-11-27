"""`eph dispatch`: the only thing that starts worlds.

The queue is the set of suspended Jobs in the ephemeral namespace, oldest
first. A tick unsuspends a Job only when ALL of these hold:

- this process holds the `eph-dispatcher` Lease (one dispatcher, enforced by
  the cluster, not by good manners);
- the Job's node is one the config lists, never one it names as off limits, and
  takes the Job's class;
- the node's world count is under its cap;
- the namespace quota has room for the Job's pod count and resources, counting
  worlds this tick already started and worlds started before a pod exists;
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

from . import runids
from .kube import KubeError

_Q = re.compile(r"^(\d+(?:\.\d+)?)(m|Ki|Mi|Gi|Ti|k|M|G|T)?$")
_MUL = {
    None: 1, "m": 0.001, "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
    "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12,
}  # fmt: skip
_REQUIRED_QUOTA = ("requests.cpu", "requests.memory")
_OPTIONAL_QUOTA = (
    "requests.ephemeral-storage",
    "limits.memory",
    "limits.ephemeral-storage",
    "pods",
)
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


def _quota_quantity(field, text):
    parsed = quantity(text)
    # CPU is measured in millicores at admission. Use integers so an exact
    # fit such as 100m + 200m = 300m stays an exact fit.
    return round(parsed * 1000) if field == "requests.cpu" else parsed


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


def _job_quota_usage(job, field):
    """Effective consumption of one pod in a namespace quota dimension."""
    if field == "pods":
        return 1
    kind, resource = field.split(".", 1)
    spec = job["spec"]["template"]["spec"]

    def amount(container):
        resources = (container.get("resources") or {}).get(kind) or {}
        return _quota_quantity(field, resources.get(resource, 0))

    sidecars = init_peak = 0
    for container in spec.get("initContainers", []):
        allocated = amount(container)
        if container.get("restartPolicy") == "Always":
            sidecars += allocated
        else:
            # A regular init overlaps only the sidecars that started before it.
            init_peak = max(init_peak, sidecars + allocated)
    steady = sidecars + sum(amount(c) for c in spec.get("containers", []))
    total = max(steady, init_peak)
    if kind == "requests" or total:
        total += _quota_quantity(field, (spec.get("overhead") or {}).get(resource, 0))
    return total


def job_requests(job):
    """Return the pod's requested CPU cores and memory bytes."""
    return (
        _job_quota_usage(job, "requests.cpu") / 1000,
        _job_quota_usage(job, "requests.memory"),
    )


def _reserve_quota(used_extra, job):
    for field in used_extra:
        used_extra[field] += _job_quota_usage(job, field)


def job_disk(job):
    return sum(
        quantity(v["emptyDir"]["sizeLimit"])
        for v in job["spec"]["template"]["spec"].get("volumes", [])
        if "emptyDir" in v and v["emptyDir"].get("sizeLimit")
    )


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
        status = q.get("status") or {}
        hard, used = status.get("hard") or {}, status.get("used") or {}
        configured = (q.get("spec") or {}).get("hard") or {}
        dimensions = _REQUIRED_QUOTA + tuple(
            field for field in _OPTIONAL_QUOTA if field in hard or field in configured
        )
        try:
            return {
                field: (
                    _quota_quantity(field, hard[field]),
                    _quota_quantity(field, used[field]),
                )
                for field in dimensions
            }
        except (KeyError, ValueError):
            return None

    # -- one pass --
    def tick(self):
        self._lease()
        self._stats = {}
        jobs = sorted(
            self.kube.list("jobs", selector=runids.JOB_LABEL_ARM),
            key=lambda j: (j["metadata"]["creationTimestamp"], j["metadata"]["name"]),
        )
        verdicts = self._verdicts()
        self._synthesize(jobs, verdicts)
        jobs = self._early_stop(jobs, verdicts)
        return self._admit(jobs)

    def _verdicts(self):
        out = {}
        for cm in self.kube.list("configmaps", selector="eph/verdict"):
            name = cm["metadata"]["name"]
            verdict = (cm["metadata"].get("labels") or {}).get("eph/verdict")
            if name.startswith(RESULT_PREFIX) and verdict:
                out[name[len(RESULT_PREFIX) :]] = verdict
        return out

    def _synthesize(self, jobs, verdicts):
        for j in jobs:
            rid = runids.run_of_job(j)
            done = finished(j)
            if not rid or not done or rid in verdicts:
                continue
            reason = f"no result was written: job {done['type']} ({done.get('reason', '')}: {done.get('message', '')})"
            labels = j["metadata"].get("labels", {})
            cm = {
                "apiVersion": "v1", "kind": "ConfigMap",
                "metadata": {
                    "name": runids.result_name(rid), "namespace": self.cfg.namespace,
                    "labels": {
                        "eph/decree": labels.get(runids.JOB_LABEL_DECREE, ""),
                        "eph/arm": labels.get(runids.JOB_LABEL_ARM, ""),
                        "eph/verdict": "INVALID",
                    },
                },
                "data": {
                    "verdict": "INVALID",
                    "result.json": json.dumps({
                        "verdict": "INVALID", "reasons": [reason], "run_id": rid,
                        "arm": labels.get(runids.JOB_LABEL_ARM, ""), "synthesized": True,
                        "assertions": [], "acts": [],
                    }),
                },
            }  # fmt: skip
            try:
                self.kube.create(cm)
            except KubeError as exc:
                self.log(f"could not record INVALID for {rid}: {exc}")
                continue
            verdicts[rid] = "INVALID"
            self.log(f"{rid}: INVALID, {reason}")

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

    def _early_stop(self, jobs, verdicts):
        """Drop waiting runs of a batch whose first pair was not control FAIL, treatment PASS."""
        gone, self._held = set(), set()
        for batch, info in self._batches(jobs, verdicts).items():
            decided, ok = self._first_pair(batch, info["arms"], verdicts)
            for j, rid, n in info["members"]:
                waiting = j["spec"].get("suspend") is True and not finished(j)
                if n == 1 or not waiting or ok:
                    continue
                if decided:
                    self.kube.delete("jobs", j["metadata"]["name"])
                    gone.add(j["metadata"]["name"])
                    self.log(
                        f"{rid}: removed, the first pair of {batch} stopped the batch"
                    )
                else:
                    self._held.add(j["metadata"]["name"])
        return [j for j in jobs if j["metadata"]["name"] not in gone]

    def _admit(self, jobs):
        cfg = self.cfg
        quota = self._quota()
        now = self.clock()
        per_node, reserved, used_extra = {}, {}, dict.fromkeys(quota or (), 0)
        for j in jobs:
            if not is_running(j):
                continue
            st = j.get("status") or {}
            # Quota can charge a new pod before the Job reports it active.
            # Reserve through that gap so a stale Job never frees quota early.
            if not st.get("active"):
                _reserve_quota(used_extra, j)
            node = self.claim_node.get(job_claim(j))
            if node is None:
                continue
            per_node[node.name] = per_node.get(node.name, 0) + 1
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
                self.kube.patch_merge("jobs", name, {"spec": {"suspend": False}})
                node = self.claim_node[job_claim(j)].name
                per_node[node] = per_node.get(node, 0) + 1
                reserved[node] = reserved.get(node, 0) + job_disk(j)
                _reserve_quota(used_extra, j)
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
        for field, (hard, used) in quota.items():
            if used + used_extra[field] + _job_quota_usage(j, field) > hard:
                return False, f"the namespace quota has no room for {field}", False
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
