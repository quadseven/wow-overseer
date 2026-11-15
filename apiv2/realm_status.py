"""GET /api/v2/realm-status - is the worldserver up, and if not, why and until when.

The realm's database cannot say this: when the worldserver is scaled to 0 its
own tables go quiet and look like an empty realm. So this route reads the
worldserver Deployment and its pods from the cluster API, read only, with the
serving pod's own service account, and the maintenance notice that
`tools/realm-maintenance` writes as an annotation (realmmaint.py).

    {checked_at, state, alert, summary, worldserver: {up, desired_replicas,
     ready_replicas, started_at, image_digest, restart_count, down_since},
     notice, last_notice, last_restart_reason, overrun_seconds, unmeasured}

`state`:

  UP                 a ready pod, started more than RESTART_WINDOW ago
  RESTARTED          a ready pod that started within RESTART_WINDOW;
                     `last_restart_reason` is the last notice's reason when
                     that notice ended after the pod started, else null
  MAINTENANCE        down, with a notice not yet past its expected_back
  OVERRUN            down (or still coming back), notice past expected_back
  STARTING           wanted and not ready yet, no notice, newest pod younger
                     than STARTUP_GRACE: a normal boot, not an alert
  DOWN_UNEXPLAINED   down with no notice (scaled to 0, or a pod that never
                     became ready inside STARTUP_GRACE)
  UNKNOWN            the cluster read failed; `unmeasured.state` says why

`alert` is true for OVERRUN and DOWN_UNEXPLAINED only. A read the cluster
refuses is never a guess: it is UNKNOWN with the reason.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone

import realmmaint

log = logging.getLogger(__name__)

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
STARTUP_GRACE = 15 * 60
DEFAULT_RESTART_WINDOW = 30 * 60
ALERT_STATES = ("OVERRUN", "DOWN_UNEXPLAINED")
TIMEOUT = 4


def _setting(name: str, default: str) -> str:
    return os.environ.get(name) or default


def restart_window() -> int:
    try:
        return max(0, int(_setting("REALM_RESTARTED_MINUTES", "30")) * 60)
    except ValueError:
        return DEFAULT_RESTART_WINDOW


def _namespace() -> str:
    explicit = os.environ.get("OVERSEER_NAMESPACE")
    if explicit:
        return explicit
    with open(SA + "/namespace") as fh:
        return fh.read().strip()


def _get(path: str) -> dict:
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    with open(SA + "/token") as fh:
        token = fh.read().strip()
    context = ssl.create_default_context(cafile=SA + "/ca.crt")
    # The scheme is the literal "https" and the host is the pod's own cluster
    # address from the environment, so S310's file: and custom-scheme worry
    # does not apply.
    req = urllib.request.Request(  # noqa: S310
        "https://%s:%s%s" % (host, port, path),
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    with urllib.request.urlopen(  # noqa: S310 - https only, see above
        req, timeout=TIMEOUT, context=context
    ) as resp:
        return json.load(resp)


def fetch() -> tuple[dict, list]:
    """(the worldserver Deployment, its pods) from the cluster API."""
    name = _setting("REALM_STATUS_DEPLOYMENT", "worldserver")
    ns = _namespace()
    dep = _get("/apis/apps/v1/namespaces/%s/deployments/%s" % (ns, name))
    pods = _get("/api/v1/namespaces/%s/pods?labelSelector=app%%3D%s" % (ns, name))
    return dep, pods.get("items") or []


def _time(text) -> datetime | None:
    return realmmaint.parse_time(text) if text else None


def _live_pod(pods: list) -> dict | None:
    live = [p for p in pods if not (p.get("metadata") or {}).get("deletionTimestamp")]
    live.sort(key=lambda p: (p.get("metadata") or {}).get("creationTimestamp") or "")
    return live[-1] if live else None


def _ready(pod: dict | None) -> bool:
    if not pod:
        return False
    conds = (pod.get("status") or {}).get("conditions") or []
    return any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds)


def _digest(pod: dict | None, deployment: dict) -> str | None:
    statuses = ((pod or {}).get("status") or {}).get("containerStatuses") or []
    for ref in [s.get("imageID") or "" for s in statuses] + [
        c.get("image") or ""
        for c in (
            ((deployment.get("spec") or {}).get("template") or {}).get("spec") or {}
        ).get("containers")
        or []
    ]:
        if "@sha256:" in ref:
            return "sha256:" + ref.split("@sha256:", 1)[1]
    return None


def _started(pod: dict | None) -> datetime | None:
    if not pod:
        return None
    status = pod.get("status") or {}
    for s in status.get("containerStatuses") or []:
        running = (s.get("state") or {}).get("running") or {}
        if running.get("startedAt"):
            return _time(running["startedAt"])
    return _time(status.get("startTime"))


def _down_since(deployment: dict, notice: dict | None) -> str | None:
    if notice:
        return notice["started_at"]
    for c in (deployment.get("status") or {}).get("conditions") or []:
        if c.get("type") == "Available" and c.get("status") == "False":
            return c.get("lastTransitionTime")
    return None


def _clock(when: datetime) -> str:
    return when.strftime("%H:%M UTC")


def _summary(
    state: str, notice: dict | None, reason: str | None, overrun: int, now
) -> str:
    if state == "MAINTENANCE":
        back = realmmaint.parse_time(notice["expected_back"])
        return "Realm down for maintenance: %s (%s). Back by %s." % (
            notice["reason"],
            notice["who"],
            _clock(back),
        )
    if state == "OVERRUN":
        return "Realm maintenance OVERRAN by %d min: %s (%s). Expected back %s." % (
            overrun // 60,
            notice["reason"],
            notice["who"],
            _clock(realmmaint.parse_time(notice["expected_back"])),
        )
    if state == "DOWN_UNEXPLAINED":
        return "Realm is down and nobody has said why."
    if state == "STARTING":
        return "Realm is starting."
    if state == "RESTARTED":
        return "Realm restarted recently: %s." % (reason or "no maintenance notice")
    if state == "UNKNOWN":
        return "Realm status not measured."
    return "Realm is up."


def _dig(obj, *keys):
    """obj[k1][k2]... where any missing or null step reads as None."""
    for key in keys:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj


def _up_state(started, notice, last, now, window) -> tuple[str, str | None]:
    """(UP or RESTARTED, the reason for the restart if a notice explains it)."""
    if not started or (now - started) > timedelta(seconds=window):
        return "UP", None
    if notice:
        return "RESTARTED", notice["reason"]
    ended = realmmaint.parse_time(last.get("ended_at")) if last else None
    if ended and ended >= started:
        return "RESTARTED", last["reason"]
    return "RESTARTED", None


def _down_state(pod, desired, notice, now) -> tuple[str, int]:
    """(state, seconds past the ETA) for a worldserver that is not ready."""
    if notice:
        back = realmmaint.parse_time(notice["expected_back"])
        if now <= back:
            return "MAINTENANCE", 0
        return "OVERRUN", int((now - back).total_seconds())
    born = _time(_dig(pod, "metadata", "creationTimestamp"))
    young = born is not None and (now - born).total_seconds() < STARTUP_GRACE
    if desired >= 1 and (pod is None or young):
        return "STARTING", 0
    return "DOWN_UNEXPLAINED", 0


def build_status(
    deployment: dict,
    pods: list,
    now: datetime,
    restart_window: int = DEFAULT_RESTART_WINDOW,
) -> dict:
    """Cluster objects in, the route's JSON out. Pure."""
    annotations = _dig(deployment, "metadata", "annotations") or {}
    notice = realmmaint.parse_notice(annotations.get(realmmaint.NOTICE_KEY))
    last = realmmaint.parse_notice(annotations.get(realmmaint.LAST_KEY))
    desired = int(_dig(deployment, "spec", "replicas") or 0)
    pod = _live_pod(pods)
    up = _ready(pod)
    started = _started(pod) if up else None
    overrun = 0
    reason = None
    if up:
        state, reason = _up_state(started, notice, last, now, restart_window)
    else:
        state, overrun = _down_state(pod, desired, notice, now)
    statuses = _dig(pod, "status", "containerStatuses") or []
    return {
        "checked_at": realmmaint.iso(now),
        "state": state,
        "alert": state in ALERT_STATES,
        "summary": _summary(state, notice, reason, overrun, now),
        "worldserver": {
            "up": up,
            "desired_replicas": desired,
            "ready_replicas": int(_dig(deployment, "status", "readyReplicas") or 0),
            "started_at": realmmaint.iso(started) if started else None,
            "image_digest": _digest(pod, deployment),
            "restart_count": sum(int(s.get("restartCount") or 0) for s in statuses),
            "down_since": None if up else _down_since(deployment, notice),
        },
        "notice": notice,
        "last_notice": last,
        "last_restart_reason": reason,
        "overrun_seconds": overrun if state == "OVERRUN" else None,
        "unmeasured": {},
    }


def unknown(why: str, now: datetime) -> dict:
    return {
        "checked_at": realmmaint.iso(now),
        "state": "UNKNOWN",
        "alert": False,
        "summary": _summary("UNKNOWN", None, None, 0, now),
        "worldserver": None,
        "notice": None,
        "last_notice": None,
        "last_restart_reason": None,
        "overrun_seconds": None,
        "unmeasured": {"state": why},
    }


def read_state(now: datetime | None = None) -> dict:
    """The route's payload; never raises. Shared with the health route."""
    now = now or datetime.now(timezone.utc)
    try:
        deployment, pods = fetch()
        return build_status(deployment, pods, now, restart_window())
    except Exception as err:  # noqa: BLE001 - an unreadable cluster is UNKNOWN, not a 500
        log.warning("realm status unreadable: %s", err)
        return unknown("The cluster API read failed: %s" % err, now)


def realm_status(_query: dict, _ctx) -> tuple[int, dict]:
    return 200, read_state()


ROUTES = {"/api/v2/realm-status": realm_status}
