"""The seed and the judge share one handoff path, and the judge finds the log (#2775).

The world pod runs `seed` and `judge` as two containers with no flags the
template could forget: the command line layer supplies the same default
handoff path to both, and resolves the worldserver log from the pod's own
environment when no `--log` is given.
"""

import pathlib
import tempfile
import unittest
from unittest import mock

from ephemeral import __main__ as cli
from ephemeral import judge
from ephemeral import podpaths


class PodPathsTest(unittest.TestCase):
    def test_both_commands_get_the_same_handoff_path_when_none_is_set(self):
        seen = {}

        def fake_seed(decree, env, **kw):
            seen["seed"] = env.get("EPH_VARS_FILE")
            return 0

        def fake_judge(decree, env, **kw):
            seen["judge"] = env.get("EPH_VARS_FILE")
            return 0

        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("ephemeral.seedrun.run", fake_seed):
                cli.main(["seed", "d.yaml"])
            with mock.patch("ephemeral.judge.run", fake_judge):
                cli.main(["judge", "d.yaml"])
        self.assertTrue(seen["seed"])
        self.assertEqual(seen["seed"], seen["judge"])
        self.assertEqual(seen["seed"], podpaths.VARS_FILE)

    def test_an_explicit_handoff_path_wins_for_both(self):
        seen = []

        def fake(decree, env, **kw):
            seen.append(env.get("EPH_VARS_FILE"))
            return 0

        with mock.patch.dict("os.environ", {"EPH_VARS_FILE": "/x/v.json"}, clear=True):
            with mock.patch("ephemeral.seedrun.run", fake):
                cli.main(["seed", "d.yaml"])
            with mock.patch("ephemeral.judge.run", fake):
                cli.main(["judge", "d.yaml"])
        self.assertEqual(seen, ["/x/v.json", "/x/v.json"])

    def test_the_default_handoff_is_on_the_volume_both_containers_mount(self):
        # the template mounts `tmp` (read-write) in the seed and in the judge
        self.assertTrue(podpaths.VARS_FILE.startswith("/tmp/"))  # noqa: S108 - the pod volume's mount point

    def test_the_judge_resolves_the_log_from_the_logs_dir(self):
        got = {}

        def fake_judge(decree, env, log_path=None, **kw):
            got["log"] = log_path
            return 0

        with mock.patch.dict("os.environ", {"EPH_LOGS_DIR": "/logs"}, clear=True):
            with mock.patch("ephemeral.judge.run", fake_judge):
                cli.main(["judge", "d.yaml"])
        self.assertEqual(got["log"], "/logs/" + podpaths.LOG_NAME)

    def test_an_explicit_log_flag_beats_the_environment(self):
        got = {}

        def fake_judge(decree, env, log_path=None, **kw):
            got["log"] = log_path
            return 0

        env = {"EPH_LOGS_DIR": "/logs", "EPH_LOG_FILE": "/logs/other.log"}
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("ephemeral.judge.run", fake_judge):
                cli.main(["judge", "d.yaml", "--log", "/elsewhere/w.log"])
        self.assertEqual(got["log"], "/elsewhere/w.log")

    def test_a_log_file_variable_beats_the_logs_dir(self):
        self.assertEqual(
            podpaths.log_path(None, {"EPH_LOGS_DIR": "/l", "EPH_LOG_FILE": "/l/a.log"}),
            "/l/a.log",
        )

    def test_no_flag_and_no_directory_stays_unset(self):
        # unset is refused by the judge as a harness fault; it is never guessed
        self.assertIsNone(podpaths.log_path(None, {}))


class BridgeLogTest(unittest.TestCase):
    """A bridge-on decree reads the bridge sidecar's log as well as the worldserver's."""

    def _logs(self, tmp, module="module line\n", bridge=None):
        d = pathlib.Path(tmp)
        (d / "Module.log").write_text(module, encoding="utf-8")
        if bridge is not None:
            (d / "Bridge.log").write_text(bridge, encoding="utf-8")
        return str(d / "Module.log"), str(d / "Bridge.log")

    def test_the_bridge_log_is_found_in_the_logs_dir(self):
        self.assertEqual(
            podpaths.bridge_log_path({"EPH_LOGS_DIR": "/logs"}),
            "/logs/" + podpaths.BRIDGE_LOG_NAME,
        )
        self.assertEqual(
            podpaths.bridge_log_path(
                {"EPH_LOGS_DIR": "/l", "EPH_BRIDGE_LOG_FILE": "/l/b.log"}
            ),
            "/l/b.log",
        )
        self.assertIsNone(podpaths.bridge_log_path({}))

    def test_the_command_passes_the_bridge_log_to_the_judge(self):
        got = {}

        def fake_judge(decree, env, bridge_log_path=None, **kw):
            got["bridge"] = bridge_log_path
            return 0

        with mock.patch.dict("os.environ", {"EPH_LOGS_DIR": "/logs"}, clear=True):
            with mock.patch("ephemeral.judge.run", fake_judge):
                cli.main(["judge", "d.yaml"])
        self.assertEqual(got["bridge"], "/logs/Bridge.log")

    def test_a_bridge_on_decree_sees_a_line_only_the_bridge_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, bridge = self._logs(tmp, bridge="flight: leader=Zug taxi node 40\n")
            read = judge.log_reader({"world": {"bridge": "on"}}, module, bridge)
            self.assertIn("taxi node 40", read())
            self.assertIn("module line", read())

    def test_a_bridge_off_decree_reads_only_the_worldserver_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, bridge = self._logs(tmp, bridge="bridge only line\n")
            read = judge.log_reader({"world": {"bridge": "off"}}, module, bridge)
            self.assertNotIn("bridge only line", read())

    def test_a_bridge_on_decree_without_a_readable_bridge_log_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, bridge = self._logs(tmp)  # no Bridge.log written
            with self.assertRaises(judge.JudgeError):
                judge.log_reader({"world": {"bridge": "on"}}, module, bridge)()
            with self.assertRaises(judge.JudgeError):
                judge.log_reader({"world": {"bridge": "on"}}, module, None)()


if __name__ == "__main__":
    unittest.main()
