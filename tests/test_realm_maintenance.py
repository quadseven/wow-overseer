"""The maintenance notice and the `realm-maintenance` script (tools/realm_maintenance.py).

The script is the one way an agent takes the worldserver down on purpose: it
writes the notice (an annotation on the Deployment) before it scales, so a
watcher can tell a planned window from an outage. These tests drive it with a
fake kubectl and read back the calls it made.
"""

import json
import pathlib
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))

import realm_maintenance as tool  # noqa: E402
import realmmaint  # noqa: E402

NOW = datetime(2026, 11, 15, 9, 5, 0, tzinfo=timezone.utc)


class FakeKubectl:
    """Records each kubectl call; `get deploy/worldserver` answers the annotations."""

    def __init__(self, annotations=None, fail_on=None):
        self.calls = []
        self.annotations = dict(annotations or {})
        self.fail_on = fail_on

    def __call__(self, argv):
        self.calls.append(argv)
        if self.fail_on and self.fail_on in argv:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        if verb_of(argv) == "get":
            body = {"metadata": {"annotations": self.annotations}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def verbs(self):
        return [verb_of(c) for c in self.calls]

    def annotate_calls(self):
        return [c for c in self.calls if verb_of(c) == "annotate"]


def verb_of(argv):
    """The kubectl verb: the word after `-n <namespace>`."""
    return argv[argv.index("-n") + 2]


def run(argv, kube, env=None):
    out = []
    code = tool.main(
        argv,
        run=kube,
        now=lambda: NOW,
        env={
            "NAMESPACE": "realm-ns",
            "REALM_MAINTENANCE_WHO": "agent-x",
            **(env or {}),
        },
        out=out.append,
    )
    return code, out


class ParseEta(unittest.TestCase):
    def test_units(self):
        self.assertEqual(realmmaint.parse_eta("90s"), timedelta(seconds=90))
        self.assertEqual(realmmaint.parse_eta("20m"), timedelta(minutes=20))
        self.assertEqual(realmmaint.parse_eta("2h"), timedelta(hours=2))

    def test_junk_zero_and_huge_are_refused(self):
        for bad in ("", "20", "m", "0m", "-5m", "20x", "25h", "1.5h"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                realmmaint.parse_eta(bad)


class Notice(unittest.TestCase):
    def test_new_notice_shape_and_times(self):
        n = realmmaint.new_notice("db writes", "agent-x", NOW, timedelta(minutes=20))
        self.assertEqual(
            n,
            {
                "reason": "db writes",
                "who": "agent-x",
                "started_at": "2026-11-15T09:05:00Z",
                "expected_back": "2026-11-15T09:25:00Z",
            },
        )

    def test_parse_notice_is_tolerant(self):
        self.assertIsNone(realmmaint.parse_notice(None))
        self.assertIsNone(realmmaint.parse_notice("{not json"))
        self.assertIsNone(realmmaint.parse_notice('{"reason": "x"}'))
        ok = realmmaint.parse_notice(
            '{"reason":"x","who":"a","started_at":"2026-11-15T09:05:00Z",'
            '"expected_back":"2026-11-15T09:25:00Z"}'
        )
        self.assertEqual(ok["reason"], "x")

    def test_retire_adds_ended_at(self):
        n = realmmaint.new_notice("r", "w", NOW, timedelta(minutes=5))
        last = realmmaint.retire(n, NOW + timedelta(minutes=7))
        self.assertEqual(last["ended_at"], "2026-11-15T09:12:00Z")
        self.assertEqual(last["reason"], "r")


class Down(unittest.TestCase):
    def test_notice_is_written_before_the_scale(self):
        kube = FakeKubectl()
        code, _ = run(["down", "--reason", "db writes", "--eta", "20m"], kube)
        self.assertEqual(code, 0)
        verbs = kube.verbs()
        self.assertLess(verbs.index("annotate"), verbs.index("scale"))
        annotate = kube.annotate_calls()[0]
        pair = next(a for a in annotate if a.startswith(realmmaint.NOTICE_KEY + "="))
        notice = json.loads(pair.split("=", 1)[1])
        self.assertEqual(notice["reason"], "db writes")
        self.assertEqual(notice["who"], "agent-x")
        self.assertEqual(notice["expected_back"], "2026-11-15T09:25:00Z")
        scale = next(c for c in kube.calls if verb_of(c) == "scale")
        self.assertIn("--replicas=0", scale)
        self.assertIn("deploy/worldserver", scale)

    def test_a_failed_scale_clears_the_notice(self):
        kube = FakeKubectl(fail_on="scale")
        code, _ = run(["down", "--reason", "r", "--eta", "5m"], kube)
        self.assertNotEqual(code, 0)
        self.assertTrue(
            any(realmmaint.NOTICE_KEY + "-" in c for c in kube.annotate_calls())
        )

    def test_an_open_notice_blocks_a_second_down_unless_forced(self):
        held = json.dumps(
            realmmaint.new_notice("other", "agent-y", NOW, timedelta(hours=1))
        )
        kube = FakeKubectl({realmmaint.NOTICE_KEY: held})
        code, out = run(["down", "--reason", "r", "--eta", "5m"], kube)
        self.assertNotEqual(code, 0)
        self.assertNotIn("scale", kube.verbs())
        self.assertIn("agent-y", " ".join(out))
        kube = FakeKubectl({realmmaint.NOTICE_KEY: held})
        code, _ = run(["down", "--reason", "r", "--eta", "5m", "--force"], kube)
        self.assertEqual(code, 0)

    def test_reason_eta_and_who_are_required_and_nothing_runs_without_them(self):
        for argv, env in (
            (["down", "--eta", "5m"], None),
            (["down", "--reason", "r"], None),
            (["down", "--reason", "r", "--eta", "5m"], {"REALM_MAINTENANCE_WHO": ""}),
            (["down", "--reason", "r", "--eta", "zz"], None),
        ):
            with self.subTest(argv=argv):
                kube = FakeKubectl()
                with self.assertRaises(SystemExit):
                    run(argv, kube, env)
                self.assertEqual(kube.calls, [])

    def test_namespace_is_required(self):
        kube = FakeKubectl()
        with self.assertRaises(SystemExit):
            tool.main(
                ["down", "--reason", "r", "--eta", "5m", "--who", "w"],
                run=kube,
                now=lambda: NOW,
                env={},
                out=lambda _: None,
            )
        self.assertEqual(kube.calls, [])


class Up(unittest.TestCase):
    def test_scale_wait_then_move_notice_to_last(self):
        held = json.dumps(
            realmmaint.new_notice("db writes", "agent-x", NOW, timedelta(minutes=20))
        )
        kube = FakeKubectl({realmmaint.NOTICE_KEY: held})
        code, _ = run(["up"], kube)
        self.assertEqual(code, 0)
        verbs = kube.verbs()
        self.assertLess(verbs.index("scale"), verbs.index("rollout"))
        self.assertLess(verbs.index("rollout"), verbs.index("annotate"))
        scale = next(c for c in kube.calls if verb_of(c) == "scale")
        self.assertIn("--replicas=1", scale)
        annotate = kube.annotate_calls()[-1]
        self.assertIn(realmmaint.NOTICE_KEY + "-", annotate)
        last = next(a for a in annotate if a.startswith(realmmaint.LAST_KEY + "="))
        self.assertEqual(json.loads(last.split("=", 1)[1])["reason"], "db writes")

    def test_a_rollout_that_fails_leaves_the_notice_in_place(self):
        held = json.dumps(realmmaint.new_notice("r", "w", NOW, timedelta(minutes=5)))
        kube = FakeKubectl({realmmaint.NOTICE_KEY: held}, fail_on="status")
        code, _ = run(["up"], kube)
        self.assertNotEqual(code, 0)
        self.assertEqual(kube.annotate_calls(), [])

    def test_up_without_a_notice_still_scales_and_waits(self):
        kube = FakeKubectl()
        code, _ = run(["up"], kube)
        self.assertEqual(code, 0)
        self.assertIn("rollout", kube.verbs())
        self.assertEqual(kube.annotate_calls(), [])


class RollsDocRequiresIt(unittest.TestCase):
    def test_rolls_names_the_script_for_every_scale_down(self):
        text = (HERE / "docs" / "ROLLS.md").read_text(encoding="utf-8")
        self.assertIn("realm-maintenance down", text)
        self.assertIn("realm-maintenance up", text)
        self.assertIn("kubectl scale", text)  # named only to forbid it

    def test_the_wrapper_points_at_the_module(self):
        wrapper = (HERE / "tools" / "realm-maintenance").read_text(encoding="utf-8")
        self.assertIn("realm_maintenance.py", wrapper)


if __name__ == "__main__":
    unittest.main()
