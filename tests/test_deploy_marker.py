"""The bridge says which commit it runs; the dashboard shows it and a rollout.

Pins the startup line, the /api/realm `deploy` fields and the bridge start
they read, the Dockerfile and
build workflow wiring, and the dashboard marker (app/deploy.js, under node).
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))

import deployinfo  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
PREV = "fedcba9876543210fedcba9876543210fedcba98"
NODE = shutil.which("node")


def _import_bridge():
    sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))
    stub = types.ModuleType("discord")

    class Client:
        def __init__(self, *args, **kwargs):
            pass

    stub.Client = Client
    with mock.patch.dict(sys.modules, {"discord": stub}):
        sys.modules.pop("bridge", None)
        import bridge
    return bridge


class StartupLine(unittest.TestCase):
    def test_line_names_commit_previous_and_build_time(self):
        env = {
            "OVERSEER_COMMIT": SHA,
            "OVERSEER_PREVIOUS_COMMIT": PREV,
            "OVERSEER_BUILT": "2026-10-24T01:02:03Z",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                deployinfo.startup_line(),
                "bridge up: commit 0123456789ab, previous fedcba987654, built 2026-10-24T01:02:03Z",
            )

    def test_unset_or_malformed_reads_unknown(self):
        with mock.patch.dict(os.environ, {"OVERSEER_COMMIT": "not a sha"}, clear=True):
            self.assertEqual(
                deployinfo.startup_line(),
                "bridge up: commit unknown, previous unknown, built unknown",
            )

    def test_main_logs_the_line(self):
        bridge = _import_bridge()

        with (
            mock.patch.dict(
                os.environ,
                {"OVERSEER_HEADLESS": "1", "OVERSEER_COMMIT": SHA},
                clear=True,
            ),
            mock.patch.object(bridge, "HeadlessBridge"),
            mock.patch.object(bridge.asyncio, "run"),
            self.assertLogs("wow-overseer", level="INFO") as logs,
        ):
            bridge.main()
        self.assertTrue(any("bridge up: commit 0123456789ab" in m for m in logs.output))


class DeployFields(unittest.TestCase):
    def test_info_fields_and_starting_window(self):
        env = {
            "OVERSEER_COMMIT": SHA,
            "OVERSEER_PREVIOUS_COMMIT": PREV,
            "OVERSEER_SHIP_PR": "1400",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            fresh = deployinfo.info(1000, now=1005)
            settled = deployinfo.info(1000, now=1000 + deployinfo.STARTING_SECONDS + 1)
        self.assertEqual(fresh["commit"], "0123456789ab")
        self.assertEqual(fresh["previous"], "fedcba987654")
        self.assertEqual(fresh["ship_pr"], 1400)
        self.assertEqual(fresh["uptime_seconds"], 5)
        self.assertEqual(fresh["started_at"], 1000)
        self.assertTrue(fresh["starting"])
        self.assertFalse(settled["starting"])
        self.assertEqual(
            set(fresh),
            {
                "commit",
                "previous",
                "built",
                "ship_pr",
                "started_at",
                "uptime_seconds",
                "starting",
            },
        )

    def test_unknown_start_reports_no_uptime(self):
        got = deployinfo.info(None, now=1005)
        self.assertIsNone(got["started_at"])
        self.assertIsNone(got["uptime_seconds"])
        self.assertFalse(got["starting"])

    def realm_deploy(self, answer, now):
        """/api/realm's `deploy`, the memo read answering `answer`. The map
        server's own clock sits far from any bridge start, so a marker read
        from this process cannot pass."""
        import test_app_shell as shell

        reader = shell.map_server.realmread.Memory({deployinfo.BRIDGE_READ_SQL: answer})
        h = shell.FakeHandler("/api/realm")
        with (
            mock.patch.object(shell.map_server, "_fetch_realm", return_value={}),
            mock.patch.object(shell.map_server.realm, "build_realm", return_value={}),
            mock.patch.object(
                shell.map_server.realmread, "Session", lambda _connect: reader
            ),
            mock.patch.dict(
                os.environ,
                {
                    "OVERSEER_COMMIT": SHA,
                    "OVERSEER_PREVIOUS_COMMIT": PREV,
                    "OVERSEER_SHIP_PR": "1400",
                },
                clear=False,
            ),
            mock.patch.object(deployinfo, "PROCESS_STARTED", 1),
            mock.patch.object(deployinfo.time, "time", return_value=now),
        ):
            h._realm({})
        return json.loads(h.body())["deploy"]

    def test_realm_reports_the_bridge_start(self):
        deploy = self.realm_deploy([{"since": 1000.0}], now=1012)
        self.assertEqual(deploy["commit"], "0123456789ab")
        self.assertEqual(deploy["previous"], "fedcba987654")
        self.assertEqual(deploy["ship_pr"], 1400)
        self.assertEqual(deploy["uptime_seconds"], 12)
        self.assertTrue(deploy["starting"])
        self.assertEqual(deploy["started_at"], 1000)

    def test_bridge_only_restart_moves_uptime(self):
        before = self.realm_deploy([{"since": 1000.0}], now=9000)
        self.assertEqual(before["uptime_seconds"], 8000)
        self.assertFalse(before["starting"])
        after = self.realm_deploy([{"since": 8995.0}], now=9000)
        self.assertEqual(after["uptime_seconds"], 5)
        self.assertTrue(after["starting"])

    def test_no_bridge_row_reports_no_uptime(self):
        deploy = self.realm_deploy([], now=9000)
        self.assertIsNone(deploy["uptime_seconds"])
        self.assertFalse(deploy["starting"])

    def test_failed_bridge_read_keeps_the_banner(self):
        with self.assertLogs("wow-map", level="ERROR"):
            deploy = self.realm_deploy(RuntimeError("down"), now=9000)
        self.assertEqual(deploy["commit"], "0123456789ab")
        self.assertIsNone(deploy["uptime_seconds"])

    def test_beat_leaves_this_process_start_in_the_memo(self):
        bridge = _import_bridge()
        with (
            mock.patch.object(bridge, "_memo_upsert") as upsert,
            mock.patch.object(deployinfo, "PROCESS_STARTED", 1000),
            mock.patch.object(bridge.time, "time", return_value=5000),
        ):
            bridge._deploy_beat()
        upsert.assert_called_once_with(
            deployinfo.MEMO_KIND,
            deployinfo.MEMO_SUBJECT,
            {},
            1000,
            5000 + deployinfo.KEEP_SECONDS,
        )

    def test_beat_runs_in_both_start_modes(self):
        bridge = _import_bridge()
        beat = [p for p in bridge.PASSES if p.name == "_deploy_beat_loop"]
        self.assertEqual(len(beat), 1)
        self.assertTrue(beat[0].headless)

    def test_row_outlives_a_missed_beat(self):
        self.assertGreater(deployinfo.KEEP_SECONDS, 2 * deployinfo.BEAT_SECONDS)

    def test_image_and_workflow_carry_the_commit(self):
        docker = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("deployinfo.py", docker)
        self.assertIn("ARG OVERSEER_COMMIT", docker)
        self.assertIn("ENV OVERSEER_COMMIT=$OVERSEER_COMMIT", docker)
        build = (HERE / ".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("--build-arg OVERSEER_COMMIT=", build)


@unittest.skipIf(NODE is None, "node is not on PATH")
class DashboardMarker(unittest.TestCase):
    def marker(self, deploy, state):
        script = (
            'import {marker} from "%s";\nconsole.log(JSON.stringify(marker(%s, %s)));\n'
            % (
                (HERE / "app" / "deploy.js").as_uri(),
                json.dumps(deploy),
                json.dumps(state),
            )
        )
        out = subprocess.run(
            [NODE, "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_shows_commit_pr_and_uptime(self):
        d = {
            "commit": "0123456789ab",
            "ship_pr": 1400,
            "uptime_seconds": 7300,
            "starting": False,
        }
        self.assertEqual(
            self.marker(d, "fresh"),
            {"restarting": False, "text": "Build 0123456789ab PR #1400, up 2h"},
        )

    def test_unknown_uptime_is_said_not_shown_as_zero(self):
        d = {
            "commit": "0123456789ab",
            "ship_pr": 1400,
            "uptime_seconds": None,
            "starting": False,
        }
        self.assertEqual(
            self.marker(d, "fresh"),
            {
                "restarting": False,
                "text": "Build 0123456789ab PR #1400, uptime unknown",
            },
        )

    def test_starting_says_restarting(self):
        d = {"commit": "0123456789ab", "uptime_seconds": 4, "starting": True}
        m = self.marker(d, "fresh")
        self.assertTrue(m["restarting"])
        self.assertIn("Restarting", m["text"])

    def test_unreachable_says_restarting_not_stale_data(self):
        d = {"commit": "0123456789ab", "uptime_seconds": 900, "starting": False}
        m = self.marker(d, "stale")
        self.assertTrue(m["restarting"])
        self.assertIn("was 0123456789ab", m["text"])

    def test_age_tick_redraws_marker_when_realm_read_fails(self):
        import test_app_shell as shell_test

        script = """
globalThis.document = {querySelector(){return null;}, addEventListener(){}, hidden:false};
globalThis.window = {setTimeout(){return 1;}, clearTimeout(){}};
globalThis.fetch = async () => ({ok:true, async text(){return '{"deploy":{"commit":"0123456789ab","uptime_seconds":900,"starting":false}}';}});
globalThis.sessionStorage = {setItem(){}, getItem(){return null;}, removeItem(){}};
const A = await import("__API_URL__");
await A.load("/api/realm");
M.setDeploy(A.peek("/api/realm").data.deploy);
globalThis.fetch = async () => { throw new Error("unavailable"); };
await A.load("/api/realm");
const slots = [{textContent:"", hidden:true, attrs:{}, setAttribute(k,v){this.attrs[k]=v;}}];
const root = {querySelectorAll(){return slots;}, querySelector(){return null;}};
const health = A.health(["/api/realm"]);
M.updateAge(root, health);
M.updateDeploy(root, health);
console.log(JSON.stringify(slots.map(s => ({text:s.textContent, hidden:s.hidden, restarting:s.attrs["data-restarting"]}))));
""".replace("__API_URL__", (HERE / "app" / "api.js").as_uri())
        out = shell_test.node_module("shell.js", script)
        self.assertEqual(
            out,
            [
                {
                    "text": "Restarting or not answering (was 0123456789ab)",
                    "hidden": False,
                    "restarting": "1",
                }
            ],
        )

    def test_main_age_tick_refreshes_deploy_marker(self):
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        tick = main.split("window.setInterval(() => {", 1)[1].split(
            "}, shell.AGE_TICK_MS);", 1
        )[0]
        self.assertIn("api.health(ageReads())", tick)
        self.assertIn("shell.updateAge(root, health)", tick)
        self.assertIn("shell.updateDeploy(root, health)", tick)

    def test_nothing_known_shows_nothing(self):
        self.assertEqual(
            self.marker(None, "loading"), {"restarting": False, "text": ""}
        )


if __name__ == "__main__":
    unittest.main()
