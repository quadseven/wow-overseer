"""The seed and the judge share one handoff path, and the judge finds the log (#2775).

The world pod runs `seed` and `judge` as two containers with no flags the
template could forget: the command line layer supplies the same default
handoff path to both, and resolves the worldserver log from the pod's own
environment when no `--log` is given.
"""

import unittest
from unittest import mock

from ephemeral import __main__ as cli
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
        self.assertTrue(podpaths.VARS_FILE.startswith("/tmp/"))

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


if __name__ == "__main__":
    unittest.main()
