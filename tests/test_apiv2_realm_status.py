"""GET /api/v2/realm-status: up or down, why, and the derived state.

Every state is produced from a Deployment and pod fixture shaped like the
cluster API's answer; the notice is the annotation realm-maintenance writes.
"""

import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import realmmaint  # noqa: E402
from apiv2 import realm_status as rs  # noqa: E402

NOW = datetime(2026, 11, 15, 10, 0, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + "a" * 64


def z(when):
    return realmmaint.iso(when)


def deployment(replicas=1, notice=None, last=None, down_since=None):
    annotations = {}
    if notice:
        annotations[realmmaint.NOTICE_KEY] = json.dumps(notice)
    if last:
        annotations[realmmaint.LAST_KEY] = json.dumps(last)
    conditions = []
    if down_since:
        conditions.append(
            {
                "type": "Available",
                "status": "False",
                "lastTransitionTime": z(down_since),
            }
        )
    return {
        "metadata": {"annotations": annotations},
        "spec": {
            "replicas": replicas,
            "template": {"spec": {"containers": [{"image": "reg/ws@" + DIGEST}]}},
        },
        "status": {"conditions": conditions},
    }


def pod(started=None, ready=True, restarts=0, created=None, terminating=False):
    started = started or NOW - timedelta(hours=5)
    meta = {"creationTimestamp": z(created or started)}
    if terminating:
        meta["deletionTimestamp"] = z(NOW)
    return {
        "metadata": meta,
        "status": {
            "startTime": z(started),
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "containerStatuses": [
                {
                    "restartCount": restarts,
                    "imageID": "reg/ws@" + DIGEST,
                    "state": {"running": {"startedAt": z(started)}} if ready else {},
                }
            ],
        },
    }


def notice(minutes_ago, eta_minutes, reason="one-off writes"):
    start = NOW - timedelta(minutes=minutes_ago)
    return realmmaint.new_notice(
        reason, "agent-x", start, timedelta(minutes=eta_minutes)
    )


class States(unittest.TestCase):
    def status(self, dep, pods):
        return rs.build_status(dep, pods, NOW)

    def test_up(self):
        s = self.status(deployment(), [pod(restarts=2)])
        self.assertEqual(s["state"], "UP")
        self.assertFalse(s["alert"])
        ws = s["worldserver"]
        self.assertTrue(ws["up"])
        self.assertEqual(ws["restart_count"], 2)
        self.assertEqual(ws["image_digest"], DIGEST)
        self.assertEqual(ws["started_at"], z(NOW - timedelta(hours=5)))
        self.assertIsNone(s["notice"])

    def test_maintenance_inside_the_eta(self):
        s = self.status(deployment(0, notice(5, 20)), [])
        self.assertEqual(s["state"], "MAINTENANCE")
        self.assertFalse(s["alert"])
        self.assertFalse(s["worldserver"]["up"])
        self.assertEqual(s["notice"]["reason"], "one-off writes")
        self.assertEqual(s["worldserver"]["down_since"], s["notice"]["started_at"])
        self.assertIn("one-off writes", s["summary"])

    def test_overrun_past_the_eta_is_an_alert(self):
        s = self.status(deployment(0, notice(80, 20)), [])
        self.assertEqual(s["state"], "OVERRUN")
        self.assertTrue(s["alert"])
        self.assertEqual(s["overrun_seconds"], 60 * 60)

    def test_overrun_while_up_is_still_coming_back_is_overrun_not_unexplained(self):
        s = self.status(deployment(1, notice(80, 20)), [pod(ready=False)])
        self.assertEqual(s["state"], "OVERRUN")

    def test_down_with_no_notice_is_unexplained(self):
        s = self.status(deployment(0, down_since=NOW - timedelta(minutes=75)), [])
        self.assertEqual(s["state"], "DOWN_UNEXPLAINED")
        self.assertTrue(s["alert"])
        self.assertEqual(s["worldserver"]["down_since"], z(NOW - timedelta(minutes=75)))

    def test_a_malformed_notice_counts_as_none(self):
        dep = deployment(0)
        dep["metadata"]["annotations"][realmmaint.NOTICE_KEY] = "{oops"
        self.assertEqual(self.status(dep, [])["state"], "DOWN_UNEXPLAINED")

    def test_a_normal_boot_is_starting_not_an_alert(self):
        fresh = pod(ready=False, created=NOW - timedelta(minutes=3))
        s = self.status(deployment(), [fresh])
        self.assertEqual(s["state"], "STARTING")
        self.assertFalse(s["alert"])

    def test_a_pod_that_never_gets_ready_becomes_unexplained(self):
        stuck = pod(ready=False, created=NOW - timedelta(minutes=40), restarts=9)
        self.assertEqual(
            self.status(deployment(), [stuck])["state"], "DOWN_UNEXPLAINED"
        )

    def test_a_terminating_pod_is_not_the_live_pod(self):
        old = pod(ready=True, terminating=True)
        s = self.status(deployment(0, notice(1, 20)), [old])
        self.assertEqual(s["state"], "MAINTENANCE")

    def test_restarted_keeps_the_last_notice_reason(self):
        started = NOW - timedelta(minutes=10)
        last = realmmaint.retire(
            notice(40, 20, "db repair"), NOW - timedelta(minutes=9)
        )
        s = self.status(deployment(1, last=last), [pod(started=started)])
        self.assertEqual(s["state"], "RESTARTED")
        self.assertFalse(s["alert"])
        self.assertEqual(s["last_restart_reason"], "db repair")

    def test_restarted_without_a_notice_has_no_reason(self):
        s = self.status(deployment(1), [pod(started=NOW - timedelta(minutes=10))])
        self.assertEqual(s["state"], "RESTARTED")
        self.assertIsNone(s["last_restart_reason"])

    def test_an_old_notice_is_not_the_reason_for_a_later_restart(self):
        last = realmmaint.retire(notice(300, 20, "old"), NOW - timedelta(minutes=280))
        s = self.status(
            deployment(1, last=last), [pod(started=NOW - timedelta(minutes=10))]
        )
        self.assertIsNone(s["last_restart_reason"])

    def test_restart_window_is_configurable(self):
        s = rs.build_status(
            deployment(),
            [pod(started=NOW - timedelta(minutes=10))],
            NOW,
            restart_window=300,
        )
        self.assertEqual(s["state"], "UP")


class Route(unittest.TestCase):
    def test_a_cluster_read_that_fails_answers_unknown_with_a_reason(self):
        with mock.patch.object(rs, "fetch", side_effect=OSError("denied")):
            code, payload = rs.realm_status({}, None)
        self.assertEqual(code, 200)
        self.assertEqual(payload["state"], "UNKNOWN")
        self.assertFalse(payload["alert"])
        self.assertIn("denied", payload["unmeasured"]["state"])

    def test_route_answers_the_built_status(self):
        with mock.patch.object(rs, "fetch", return_value=(deployment(), [pod()])):
            code, payload = rs.realm_status({}, None)
        self.assertEqual((code, payload["state"]), (200, "UP"))

    def test_route_is_registered(self):
        import apiv2

        self.assertIn("/api/v2/realm-status", apiv2.ROUTES)


if __name__ == "__main__":
    unittest.main()
