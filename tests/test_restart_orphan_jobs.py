"""A bridge restart leaves no family on a job nothing owns any more (#790).

The town errand and Jev's fishing break are the only writers of two jobs
whose way back lives in the bridge's memory: the errand ends its own
`town run`, and the break's restore puts `fish` back to the default. A
restart forgets both, so a family on either job when the bridge restarted
stayed on it until a campaign or a person moved it. These drive the real
bridge functions with the reads and the job writes stubbed, starting from
the empty memory a restart leaves.
"""

import asyncio
import sys
import types
import unittest
from unittest import mock

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import jev_activity  # noqa: E402
import jobs  # noqa: E402


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
NAMES = ["Grug", "Bork"]
FISH = jev_activity.JOB[jev_activity.FISH]
BACK = jev_activity.RESTORE[jev_activity.FISH]


class _World(unittest.TestCase):
    """The roster's jobs, each member's last job source, and the writes."""

    def setUp(self):
        self.jobs = {}
        self.sources = {}
        self.waiting = False
        self.written = []
        for name, fake in (
            (
                "_jobs_of",
                lambda names: {n: self.jobs[n] for n in names if n in self.jobs},
            ),
            ("_last_job_source", lambda name: self.sources.get(name, "")),
            ("_campaign_waiting", lambda names: self.waiting),
            ("_insert_job", self._write),
        ):
            patcher = mock.patch.object(bridge, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write(self, name, mode, source):
        self.written.append((name, mode, source))
        self.jobs[name] = mode
        self.sources[name] = source


class AnErrandTownRunAfterARestart(_World):
    def test_is_given_back_when_no_campaign_waits(self):
        for name in NAMES:
            self.jobs[name] = jobs.TOWN_RUN
            self.sources[name] = bridge.TOWN_ERRAND_SOURCE
        released = bridge._town_errand_release_orphans(NAMES)
        self.assertEqual(sorted(NAMES), sorted(released))
        self.assertEqual(
            sorted((n, jobs.DEFAULT, bridge.TOWN_ERRAND_SOURCE) for n in NAMES),
            sorted(self.written),
        )

    def test_is_left_for_a_waiting_campaign_to_take_back(self):
        self.jobs = {n: jobs.TOWN_RUN for n in NAMES}
        self.sources = {n: bridge.TOWN_ERRAND_SOURCE for n in NAMES}
        self.waiting = True
        self.assertEqual([], bridge._town_errand_release_orphans(NAMES))
        self.assertEqual([], self.written)

    def test_an_operators_own_town_run_stands(self):
        self.jobs = {n: jobs.TOWN_RUN for n in NAMES}
        self.sources = {n: "discord" for n in NAMES}
        self.assertEqual([], bridge._town_errand_release_orphans(NAMES))
        self.assertEqual([], self.written)

    def test_nothing_is_written_for_a_family_off_the_town_run(self):
        self.jobs = {n: jobs.DEFAULT for n in NAMES}
        self.assertEqual([], bridge._town_errand_release_orphans(NAMES))
        self.assertEqual([], self.written)


class _Pass:
    """The bridge as a fresh start leaves it: no break in memory."""

    def __init__(self):
        self._activity_restore = {}


class AFishingBreakAfterARestart(_World):
    def restore(self, this, job, now, names=NAMES, leader="Grug"):
        return asyncio.run(
            bridge.Bridge._activity_restore_job(this, "Grug", job, now, names, leader)
        )

    def test_is_ended_and_the_family_put_back_on_the_default_job(self):
        self.jobs = {n: FISH for n in NAMES}
        self.sources = {n: jev_activity.SOURCE for n in NAMES}
        this = _Pass()
        self.assertTrue(self.restore(this, FISH, 500.0))
        self.assertEqual(
            sorted((n, BACK) for n in NAMES),
            sorted((n, mode) for n, mode, _ in self.written),
        )
        # Adopted like any break, so a refused row is written again later.
        self.assertIn("Grug", this._activity_restore)
        later = 500.0 + bridge.ACTIVITY_RESTORE_RETRY_SECONDS
        self.assertFalse(self.restore(this, BACK, later))
        self.assertNotIn("Grug", this._activity_restore)

    def test_an_operators_own_fishing_order_stands(self):
        self.sources = {n: "discord" for n in NAMES}
        this = _Pass()
        self.assertFalse(self.restore(this, FISH, 500.0))
        self.assertEqual([], self.written)
        self.assertEqual({}, this._activity_restore)

    def test_a_family_on_another_job_is_not_read(self):
        def unread(name):
            raise AssertionError("no job source read for a family off a break")

        this = _Pass()
        with mock.patch.object(bridge, "_last_job_source", unread):
            self.assertFalse(self.restore(this, jobs.DEFAULT, 500.0))
        self.assertEqual([], self.written)


if __name__ == "__main__":
    unittest.main()
