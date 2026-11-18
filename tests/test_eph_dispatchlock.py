"""eph dispatch owner lock: one local dispatcher, named owner, stop by pid only."""

import io
import json
import os
import pathlib
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from eph_fakes import FakeCluster, make_cfg
from ephemeral import __main__ as cli, dispatch, dispatchlock

HOUR = 3600


class LockTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = pathlib.Path(self.dir.name) / "sub" / "dispatch.lock"
        self.logs = []

    def take(self, owner, pid, now=1000.0, alive=lambda p: True, max_hours=6):
        return dispatchlock.acquire(
            self.path, owner, pid=pid, now=now, alive=alive,
            max_age=max_hours * HOUR, log=self.logs.append,
        )  # fmt: skip

    def test_takes_the_lock_and_records_owner_pid_and_start(self):
        self.take("agent-a", 111, now=1000.0)
        rec = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(rec["owner"], "agent-a")
        self.assertEqual(rec["pid"], 111)
        self.assertEqual(rec["started"], 1000.0)

    def test_a_second_dispatcher_is_refused_and_the_owner_is_named(self):
        self.take("agent-a", 111)
        with self.assertRaises(dispatchlock.LockHeld) as cm:
            self.take("agent-b", 222, now=1100.0)
        self.assertIn("agent-a", str(cm.exception))
        self.assertIn("111", str(cm.exception))
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-a")

    def test_lock_held_is_a_lease_held_so_the_cli_exits_3(self):
        self.assertTrue(issubclass(dispatchlock.LockHeld, dispatch.LeaseHeld))

    def test_a_dead_pid_is_taken_over_with_a_log_line(self):
        self.take("agent-a", 111)
        self.take("agent-b", 222, now=1100.0, alive=lambda p: False)
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-b")
        self.assertTrue(any("stale" in m and "agent-a" in m for m in self.logs))

    def test_a_lock_not_renewed_for_n_hours_is_taken_over(self):
        self.take("agent-a", 111, now=1000.0)
        self.take("agent-b", 222, now=1000.0 + 7 * HOUR, max_hours=6)
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-b")
        self.assertTrue(any("stale" in m for m in self.logs))

    def test_renew_keeps_a_long_running_dispatcher_fresh(self):
        self.take("agent-a", 111, now=1000.0)
        dispatchlock.renew(self.path, pid=111, now=1000.0 + 5 * HOUR)
        with self.assertRaises(dispatchlock.LockHeld):
            self.take("agent-b", 222, now=1000.0 + 8 * HOUR, max_hours=6)

    def test_renew_by_a_non_holder_does_nothing(self):
        self.take("agent-a", 111, now=1000.0)
        dispatchlock.renew(self.path, pid=999, now=5000.0)
        self.assertEqual(json.loads(self.path.read_text())["renewed"], 1000.0)

    def test_a_corrupt_lock_is_stale(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json", encoding="utf-8")
        self.take("agent-b", 222)
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-b")

    def test_release_removes_only_our_own_lock(self):
        self.take("agent-a", 111)
        dispatchlock.release(self.path, pid=999)
        self.assertTrue(self.path.exists())
        dispatchlock.release(self.path, pid=111)
        self.assertFalse(self.path.exists())

    def test_the_same_pid_may_retake_its_own_lock(self):
        self.take("agent-a", 111)
        self.take("agent-a", 111, now=1500.0)
        self.assertEqual(json.loads(self.path.read_text())["pid"], 111)

    def test_takeover_never_unlinks_the_lock_so_it_cannot_delete_a_fresh_one(self):
        self.take("agent-a", 111)
        real = os.unlink

        def guarded(p, *a, **k):
            self.assertNotEqual(pathlib.Path(p), self.path, "unlinked the lock")
            return real(p, *a, **k)

        with mock.patch("os.unlink", guarded):
            self.take("agent-b", 222, now=1100.0, alive=lambda p: False)
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-b")
        self.assertFalse(pathlib.Path(str(self.path) + ".takeover").exists())

    def test_the_second_of_two_takeovers_sees_the_first_ones_fresh_lock(self):
        self.take("agent-a", 111)
        seen = []

        def alive(pid):
            # agent-a is dead; once agent-c holds the lock, it is alive
            seen.append(pid)
            return pid == 333

        self.take("agent-c", 333, now=1100.0, alive=alive)
        with self.assertRaises(dispatchlock.LockHeld) as cm:
            self.take("agent-b", 222, now=1200.0, alive=alive)
        self.assertIn("agent-c", str(cm.exception))

    def test_a_takeover_in_progress_blocks_another_one(self):
        self.take("agent-a", 111)
        guard = pathlib.Path(str(self.path) + ".takeover")
        guard.write_text("{}", encoding="utf-8")
        with (
            mock.patch.object(dispatchlock, "GUARD_TRIES", 2),
            mock.patch.object(dispatchlock, "GUARD_WAIT", 0),
            mock.patch.object(dispatchlock, "GUARD_STALE_SECONDS", 10**9),
        ):
            with self.assertRaises(dispatchlock.LockHeld):
                self.take("agent-b", 222, alive=lambda p: False)
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-a")

    def test_a_dead_takeovers_guard_is_cleared_when_old(self):
        self.take("agent-a", 111)
        guard = pathlib.Path(str(self.path) + ".takeover")
        guard.write_text("{}", encoding="utf-8")
        os.utime(guard, (0, 0))
        self.take("agent-b", 222, now=time.time(), alive=lambda p: False)
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-b")

    def test_renew_swaps_atomically_and_leaves_no_temp_file(self):
        self.take("agent-a", 111, now=1000.0)
        calls = []
        real = os.replace

        def spy(a, b):
            calls.append((pathlib.Path(a).name, pathlib.Path(b)))
            return real(a, b)

        with mock.patch("os.replace", spy):
            dispatchlock.renew(self.path, pid=111, now=2000.0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], self.path)
        self.assertEqual(json.loads(self.path.read_text())["renewed"], 2000.0)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def test_an_unreadable_lock_is_busy_not_stale(self):
        self.take("agent-a", 111)
        with mock.patch.object(
            dispatchlock, "_read", side_effect=PermissionError("swapping")
        ):
            with self.assertRaises(dispatchlock.LockHeld):
                self.take("agent-b", 222, alive=lambda p: False)


class StopTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = pathlib.Path(self.dir.name) / "dispatch.lock"
        self.out = []
        self.killed = []

    def write(self, owner, pid):
        dispatchlock.acquire(
            self.path, owner, pid=pid, now=1.0, alive=lambda p: True,
            max_age=HOUR, log=self.out.append,
        )  # fmt: skip

    def stop(self, owner, alive):
        return dispatchlock.stop(
            self.path, owner, alive=alive, terminate=self.killed.append,
            wait=lambda: None, log=self.out.append,
        )  # fmt: skip

    def test_stops_the_matching_owner_by_pid_and_clears_the_lock(self):
        self.write("agent-a", 111)
        states = iter([True, False])  # alive before the signal, gone after
        code = self.stop("agent-a", alive=lambda p: next(states))
        self.assertEqual(code, 0)
        self.assertEqual(self.killed, [111])
        self.assertFalse(self.path.exists())

    def test_refuses_another_owners_dispatcher(self):
        self.write("agent-a", 111)
        code = self.stop("agent-b", alive=lambda p: True)
        self.assertEqual(code, 3)
        self.assertEqual(self.killed, [])
        self.assertTrue(self.path.exists())
        self.assertTrue(any("agent-a" in m for m in self.out))

    def test_no_lock_means_nothing_to_stop(self):
        self.assertEqual(self.stop("agent-a", alive=lambda p: True), 0)
        self.assertEqual(self.killed, [])

    def test_stop_does_not_unlink_a_new_owners_lock(self):
        self.write("agent-a", 111)
        swapped = []

        def terminate(pid):
            dispatchlock._replace(
                self.path,
                {"owner": "agent-c", "pid": 333, "started": 2.0, "renewed": 2.0},
            )
            swapped.append(pid)

        states = iter([True, False])
        code = dispatchlock.stop(
            self.path, "agent-a", alive=lambda p: next(states, False),
            terminate=terminate, wait=lambda: None, log=self.out.append,
        )  # fmt: skip
        self.assertEqual(code, 3)
        self.assertTrue(self.path.exists())
        self.assertEqual(json.loads(self.path.read_text())["owner"], "agent-c")

    def test_release_reports_a_failed_unlink_instead_of_hiding_it(self):
        self.write("agent-a", 111)
        with mock.patch.object(
            dispatchlock.os, "unlink", side_effect=PermissionError("denied")
        ):
            dispatchlock.release(self.path, pid=111, log=self.out.append)
        self.assertTrue(
            any("could not release" in m and "denied" in m for m in self.out)
        )
        self.assertTrue(self.path.exists())

    def test_a_dead_holder_is_cleared_without_a_signal(self):
        self.write("agent-a", 111)
        self.assertEqual(self.stop("agent-a", alive=lambda p: False), 0)
        self.assertEqual(self.killed, [])
        self.assertFalse(self.path.exists())

    def test_a_dispatcher_that_will_not_die_is_an_error_and_keeps_the_lock(self):
        self.write("agent-a", 111)
        code = self.stop("agent-a", alive=lambda p: True)
        self.assertEqual(code, 2)
        self.assertTrue(self.path.exists())


class OwnerNameTest(unittest.TestCase):
    def test_flag_beats_env_beats_parent(self):
        env = {"EPH_OWNER": "from-env"}
        self.assertEqual(dispatchlock.owner_name("flag", env, ppid=7), "flag")
        self.assertEqual(dispatchlock.owner_name(None, env, ppid=7), "from-env")
        self.assertEqual(dispatchlock.owner_name(None, {}, ppid=7), "parent-7")

    def test_default_path_honours_eph_lock(self):
        self.assertEqual(
            dispatchlock.lock_path({"EPH_LOCK": "x/y.lock"}), pathlib.Path("x/y.lock")
        )
        self.assertEqual(
            dispatchlock.lock_path({}, home=pathlib.Path("h")),
            pathlib.Path("h") / ".ephemeral" / "dispatch.lock",
        )


class LeaseNamesOwnerTest(unittest.TestCase):
    def test_the_cluster_lease_holder_carries_the_owner(self):
        d = dispatch.Dispatcher(make_cfg("r"), FakeCluster(), owner="agent-a")
        self.assertTrue(d.holder.startswith("agent-a@"))
        self.assertIn(str(os.getpid()), d.holder)

    def test_without_an_owner_the_holder_is_unchanged(self):
        d = dispatch.Dispatcher(make_cfg("r"), FakeCluster())
        self.assertNotIn("@", d.holder)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.lock = str(pathlib.Path(self.dir.name) / "d.lock")
        env = mock.patch.dict(os.environ, {"EPH_LOCK": self.lock})
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        return code, buf.getvalue()

    def hold(self, owner):
        dispatchlock.acquire(
            pathlib.Path(self.lock), owner, pid=os.getppid(), now=time.time(),
            alive=lambda p: True, max_age=HOUR, log=print,
        )  # fmt: skip

    def runner(self):
        return mock.patch(
            "ephemeral.__main__._runner",
            lambda a: (make_cfg(self.dir.name), FakeCluster(), None),
        )

    def test_dispatch_refuses_when_another_owner_holds_the_lock(self):
        self.hold("agent-a")
        with self.runner():
            code, out = self.run_cli("dispatch", "--once", "--owner", "agent-b")
        self.assertEqual(code, 3)
        self.assertIn("agent-a", out)

    def test_dispatch_releases_the_lock_when_it_ends(self):
        with (
            self.runner(),
            mock.patch("ephemeral.dispatch.Dispatcher.run", return_value=0),
        ):
            code, _ = self.run_cli("dispatch", "--once", "--owner", "agent-a")
        self.assertEqual(code, 0)
        self.assertFalse(pathlib.Path(self.lock).exists())

    def test_stop_needs_no_config_and_refuses_a_different_owner(self):
        self.hold("agent-a")
        os.environ.pop("EPH_CONFIG", None)
        code, out = self.run_cli("dispatch", "--stop", "--owner", "agent-b")
        self.assertEqual(code, 3)
        self.assertIn("agent-a", out)
        self.assertTrue(pathlib.Path(self.lock).exists())


if __name__ == "__main__":
    unittest.main()
