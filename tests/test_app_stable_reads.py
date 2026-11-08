"""A read whose only news is a ticking clock has not changed.

The Now page polls /api/eye and /api/v2/roll every five seconds. Both
payloads carry per-second clock fields (uptime_seconds, when_seconds,
generated_at, including a nested deploy uptime), so their raw text differs
on every poll even when nothing in the world moved. The fetch layer judged
"changed" by raw text, so the whole page redrew every five seconds and
fought anyone trying to scroll it. These run api.js under node with the
browser stubbed, the same harness as test_app_saved_reads.py.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
API = HERE / "app" / "api.js"

PRELUDE = r"""
const STORE = new Map(Object.entries(globalThis.__store || {}));
globalThis.__fetches = [];
globalThis.document = {
  querySelector: () => ({ getAttribute: () => "/dev" }),
  addEventListener: () => {},
  hidden: false,
};
globalThis.window = {
  sessionStorage: {
    getItem: (k) => (STORE.has(k) ? STORE.get(k) : null),
    setItem: (k, v) => STORE.set(k, String(v)),
    removeItem: (k) => STORE.delete(k),
  },
  setTimeout: () => 0,
  clearTimeout: () => {},
};
globalThis.fetch = async (url) => {
  globalThis.__fetches.push(url);
  const a = (globalThis.__answers || {})[url];
  if (!a || a === "throw") throw new Error("offline");
  return { ok: a.status === 200, status: a.status, text: async () => a.text };
};
"""


def run(script, answers=None):
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "api.mjs"
        dst.write_text(API.read_text(encoding="utf-8"), encoding="utf-8")
        setup = f"globalThis.__answers = {json.dumps(answers or {})};\n"
        code = (
            setup
            + PRELUDE
            + f"const M = await import({json.dumps(dst.as_uri())});\n{script}"
        )
        out = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", code],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


ROLL_A = {
    "build": "core 8a4e76e, module ef6ab10a",
    "when_seconds": 13845,
    "uptime_seconds": 13875,
    "deploy": {"commit": "6bc8074671c9", "uptime_seconds": 3900, "starting": False},
}
ROLL_B = {
    "build": "core 8a4e76e, module ef6ab10a",
    "when_seconds": 13852,
    "uptime_seconds": 13882,
    "deploy": {"commit": "6bc8074671c9", "uptime_seconds": 3907, "starting": False},
}
ROLL_C = dict(ROLL_B, build="core 9b9b9b9b, module ef6ab10a")


def roll(text):
    return {"/dev/api/v2/roll": {"status": 200, "text": text}}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class StableProjection(unittest.TestCase):
    def test_clock_only_differences_project_the_same(self):
        got = run(
            "console.log(JSON.stringify(["
            "M.stableProjection({}) === M.stableProjection({}),"
            "M.stableProjection({}) === M.stableProjection({})]));".format(
                json.dumps(json.dumps(ROLL_A)),
                json.dumps(json.dumps(ROLL_B)),
                json.dumps(
                    json.dumps({"generated_at": "2026-11-08T17:39:16", "tiers": []})
                ),
                json.dumps(
                    json.dumps({"generated_at": "2026-11-08T17:39:23", "tiers": []})
                ),
            )
        )
        self.assertEqual(got, [True, True])

    def test_a_real_change_projects_differently(self):
        got = run(
            "console.log(JSON.stringify("
            f"M.stableProjection({json.dumps(json.dumps(ROLL_B))}) === M.stableProjection({json.dumps(json.dumps(ROLL_C))})));"
        )
        self.assertFalse(got)

    def test_key_order_does_not_matter(self):
        got = run(
            "console.log(JSON.stringify("
            'M.stableProjection(\'{"a": 1, "b": {"c": 2, "d": 3}}\')'
            ' === M.stableProjection(\'{"b": {"d": 3, "c": 2}, "a": 1}\')));'
        )
        self.assertTrue(got)

    def test_a_proto_key_is_data_not_a_prototype(self):
        one = json.dumps({"__proto__": {"x": 1}, "a": 1})
        two = json.dumps({"__proto__": {"x": 2}, "a": 1})
        got = run(
            "console.log(JSON.stringify(["
            f"M.stableProjection({json.dumps(one)}) === M.stableProjection({json.dumps(two)}),"
            f" M.stableProjection({json.dumps(one)})]));"
        )
        self.assertFalse(got[0])
        self.assertIn('"__proto__":{"x":1}', got[1])

    def test_non_json_text_passes_through(self):
        got = run("console.log(JSON.stringify(M.stableProjection('not json at all')));")
        self.assertEqual(got, "not json at all")


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ChangeDetection(unittest.TestCase):
    def test_a_clock_only_reanswer_is_not_a_change(self):
        script = (
            "const seen = [];"
            "M.onChange((path, changed) => { if (path === '/api/v2/roll') seen.push(changed); });"
            "await M.load('/api/v2/roll');"
            f"globalThis.__answers['/dev/api/v2/roll'] = {{status: 200, text: {json.dumps(json.dumps(ROLL_B))}}};"
            "await M.load('/api/v2/roll');"
            f"globalThis.__answers['/dev/api/v2/roll'] = {{status: 200, text: {json.dumps(json.dumps(ROLL_C))}}};"
            "await M.load('/api/v2/roll');"
            "console.log(JSON.stringify(seen));"
        )
        got = run(script, answers=roll(json.dumps(ROLL_A)))
        # First answer changes (nothing was known), the clock-only one does
        # not, the real one does.
        self.assertEqual(got, [True, False, True])

    def test_the_data_served_is_the_latest_answer(self):
        script = (
            "await M.load('/api/v2/roll');"
            f"globalThis.__answers['/dev/api/v2/roll'] = {{status: 200, text: {json.dumps(json.dumps(ROLL_B))}}};"
            "await M.load('/api/v2/roll');"
            "console.log(JSON.stringify(M.peek('/api/v2/roll').data));"
        )
        got = run(script, answers=roll(json.dumps(ROLL_A)))
        self.assertEqual(got["uptime_seconds"], ROLL_B["uptime_seconds"])
