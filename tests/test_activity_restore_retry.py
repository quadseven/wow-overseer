"""A break's restore is written again until its fishers are off the break's job.

On wow-dev (2026-09-28) Jev sent Zug's family fishing. When the break ended,
Zug was offline for that moment, and his `quest` row came back
`target not online`. The restore had already been forgotten, so the leader
kept job=fish for 37 more minutes while his four followers quested without
him. This drives the real `Bridge._activity_restore_job` with the job write
stubbed.
"""

import asyncio
import types
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, fresh_import, stub_modules

with stub_modules(pymysql=PYMYSQL):
    import jev_activity


def _import_bridge():
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    bridge = fresh_import("bridge", discord=stub, pymysql=PYMYSQL)
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
        self.jobs = dict.fromkeys(NAMES, FISH)
        for name, fake in (
            (
                "_insert_job",
                lambda name, mode, source: self.written.append((name, mode)),
            ),
            ("_jobs_of", lambda names: {n: self.jobs[n] for n in names}),
            ("_last_job_source", lambda name: jev_activity.SOURCE),
        ):
            patcher = mock.patch.object(bridge, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def restore(self, this, now):
        return asyncio.run(bridge.Bridge._activity_restore_job(this, "Zug", NAMES, now))

    def test_a_restore_the_leader_missed_is_written_again(self):
        this = _Pass(until=100.0)
        self.assertTrue(self.restore(this, 100.0))
        self.assertEqual([(n, BACK) for n in NAMES], self.written)
        # The leader's row was refused: he still reads the break's job.
        self.written.clear()
        self.assertFalse(self.restore(this, 101.0))
        self.assertEqual([], self.written)
        later = 100.0 + bridge.ACTIVITY_RESTORE_RETRY_SECONDS
        self.jobs.update(dict.fromkeys(NAMES[1:], BACK))
        self.assertTrue(self.restore(this, later))
        self.assertEqual([("Zug", BACK)], self.written)

    def test_it_stops_once_the_leader_is_off_the_break(self):
        this = _Pass(until=100.0)
        self.assertTrue(self.restore(this, 100.0))
        later = 100.0 + bridge.ACTIVITY_RESTORE_RETRY_SECONDS
        self.jobs.update(dict.fromkeys(NAMES, BACK))
        self.assertFalse(self.restore(this, later))
        self.assertNotIn("Zug", this._activity_restore)

    def test_a_family_moved_on_by_somebody_else_is_left_alone(self):
        this = _Pass(until=100.0)
        self.jobs.update(dict.fromkeys(NAMES, "dungeon:ragefire"))
        self.assertFalse(self.restore(this, 100.0))
        self.assertEqual([], self.written)
        self.assertNotIn("Zug", this._activity_restore)


if __name__ == "__main__":
    unittest.main()
