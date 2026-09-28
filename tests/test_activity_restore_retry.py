"""A break's restore is written again until the leader is off the break's job.

On wow-dev (2026-09-28) Jev sent Zug's family fishing. When the break ended,
Zug was offline for that moment, and his `quest` row came back
`target not online`. The restore had already been forgotten, so the leader
kept job=fish for 37 more minutes while his four followers quested without
him. This drives the real `Bridge._activity_restore_job` with the job write
stubbed.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import jev_activity  # noqa: E402


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


bridge = _import_bridge()
NAMES = ["Zug", "Oz", "Uzza", "Zork", "Zrog"]
FISH = jev_activity.JOB[jev_activity.FISH]
BACK = jev_activity.RESTORE[jev_activity.FISH]


class _Pass:
    def __init__(self, until):
        self._activity_restore = {"Zug": (until, jev_activity.FISH, NAMES)}


class RestoreRetryTest(unittest.TestCase):
    def setUp(self):
        self.written = []
        patcher = mock.patch.object(
            bridge,
            "_insert_job",
            lambda name, mode, source: self.written.append((name, mode)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def restore(self, this, job, now):
        return asyncio.run(bridge.Bridge._activity_restore_job(this, "Zug", job, now))

    def test_a_restore_the_leader_missed_is_written_again(self):
        this = _Pass(until=100.0)
        self.assertTrue(self.restore(this, FISH, 100.0))
        self.assertEqual([(n, BACK) for n in NAMES], self.written)
        # The leader's row was refused: he still reads the break's job.
        self.written.clear()
        self.assertFalse(self.restore(this, FISH, 101.0))
        self.assertEqual([], self.written)
        later = 100.0 + bridge.ACTIVITY_RESTORE_RETRY_SECONDS
        self.assertTrue(self.restore(this, FISH, later))
        self.assertEqual([(n, BACK) for n in NAMES], self.written)

    def test_it_stops_once_the_leader_is_off_the_break(self):
        this = _Pass(until=100.0)
        self.assertTrue(self.restore(this, FISH, 100.0))
        later = 100.0 + bridge.ACTIVITY_RESTORE_RETRY_SECONDS
        self.assertFalse(self.restore(this, BACK, later))
        self.assertNotIn("Zug", this._activity_restore)

    def test_a_family_moved_on_by_somebody_else_is_left_alone(self):
        this = _Pass(until=100.0)
        self.assertFalse(self.restore(this, "dungeon:ragefire", 100.0))
        self.assertEqual([], self.written)
        self.assertNotIn("Zug", this._activity_restore)


if __name__ == "__main__":
    unittest.main()
