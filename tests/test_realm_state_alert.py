"""The realm state reaches the existing watch path and the dashboard header.

OVERRUN and DOWN_UNEXPLAINED become one finding in /api/v2/health (the list the
planners and the monitoring agent already read); every state but UP gets a
one-line banner (app/realmstate.js) styled as an alert for those two.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    from apiv2 import health

NODE = shutil.which("node")
NOW = 1_792_072_229
DOWN_SINCE = "2026-11-15T08:45:00Z"


def state(name, **extra):
    base = {
        "state": name,
        "alert": name in ("OVERRUN", "DOWN_UNEXPLAINED"),
        "summary": "Realm is something.",
        "worldserver": {"up": name in ("UP", "RESTARTED"), "down_since": DOWN_SINCE},
        "notice": None,
        "overrun_seconds": None,
    }
    base.update(extra)
    return base


def build(realm):
    return health.build(
        NOW, {"members": []}, [], {"questers": []}, [], [], {}, realm=realm
    )


class HealthFinding(unittest.TestCase):
    def test_only_the_two_alert_states_make_a_finding(self):
        for name in ("UP", "RESTARTED", "MAINTENANCE", "STARTING", "UNKNOWN"):
            with self.subTest(state=name):
                self.assertEqual(build(state(name))["findings"], [])
        self.assertEqual(build(None)["findings"], [])

    def test_overrun_and_unexplained_are_one_finding_each(self):
        for name in ("OVERRUN", "DOWN_UNEXPLAINED"):
            with self.subTest(state=name):
                found = build(state(name))["findings"]
                self.assertEqual(len(found), 1)
                f = found[0]
                self.assertEqual(f["key"], "realm-down")
                self.assertEqual(f["area"], "stability")
                self.assertEqual(f["since"], DOWN_SINCE)
                self.assertIn(name, f["evidence"])
                self.assertTrue(f["title"].isascii() and f["evidence"].isascii())

    def test_the_realm_finding_outranks_everything(self):
        stuck = {
            "members": [
                {
                    "name": "Grug",
                    "step": "s",
                    "blocker": "b",
                    "since": NOW - 90 * 3600,
                    "kind": "hold",
                }
            ]
        }
        payload = health.build(
            NOW, stuck, [], {"questers": []}, [], [], {}, realm=state("OVERRUN")
        )
        self.assertEqual(payload["findings"][0]["key"], "realm-down")

    def test_an_overrun_finding_names_the_notice(self):
        notice = {"reason": "db repair", "who": "agent-x", "expected_back": "x"}
        f = build(state("OVERRUN", notice=notice, overrun_seconds=3600))["findings"][0]
        self.assertIn("db repair", f["evidence"])
        self.assertIn("60 min", f["evidence"])

    def test_the_handler_asks_the_realm_status(self):
        source = (HERE / "apiv2" / "health.py").read_text(encoding="utf-8")
        self.assertIn("realm_status.read_state()", source)


@unittest.skipIf(NODE is None, "node is not on PATH")
class Banner(unittest.TestCase):
    def line(self, status):
        script = (
            'import {realmLine} from "%s";\n'
            "console.log(JSON.stringify(realmLine(%s)));\n"
            % ((HERE / "app" / "realmstate.js").as_uri(), json.dumps(status))
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

    def test_up_and_unknown_and_missing_show_nothing(self):
        for s in (None, {}, state("UP"), state("UNKNOWN")):
            self.assertFalse(self.line(s)["show"])

    def test_alert_states_are_tone_bad(self):
        for name in ("OVERRUN", "DOWN_UNEXPLAINED"):
            line = self.line(state(name, summary="Realm is down."))
            self.assertTrue(line["show"])
            self.assertEqual(line["tone"], "bad")
            self.assertEqual(line["text"], "Realm is down.")

    def test_planned_and_recovering_states_are_tone_warn(self):
        for name in ("MAINTENANCE", "STARTING", "RESTARTED"):
            line = self.line(state(name))
            self.assertTrue(line["show"])
            self.assertEqual(line["tone"], "warn")

    def test_shell_mounts_the_slot_and_main_polls_the_route(self):
        shell = (HERE / "app" / "shell.js").read_text(encoding="utf-8")
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        self.assertIn('data-slot="realm-state"', shell)
        self.assertIn("/api/v2/realm-status", main)


if __name__ == "__main__":
    unittest.main()
