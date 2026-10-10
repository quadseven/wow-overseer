"""The app keeps what is on screen live without a socket: cheap reads polled
faster than the rest (app/api.js `watch` with a view's `quick`), a read at
once when the page is shown again or the network comes back, and a data age
that counts up every second (app/shell.js) without a screen reader reading
every tick aloud.
"""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

# A browser just big enough for api.js: timers that run when told to, a
# fetch that records what was asked, and a document that can be hidden.
BROWSER = """
const timers = new Map(); let nextId = 1;
globalThis.window = {
  setTimeout(f, ms) { const id = nextId++; timers.set(id, {f, ms}); return id; },
  clearTimeout(id) { timers.delete(id); },
  setInterval() { return 0; },
  addEventListener() {},
};
const docOn = {};
globalThis.document = {hidden: false, querySelector: () => null, addEventListener(t, f) { docOn[t] = f; }};
const asked = [];
globalThis.fetch = (url) => { asked.push(url); return Promise.resolve({ok: true, text: () => Promise.resolve('{"n": ' + asked.length + '}')}); };
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); };
const pending = () => [...timers.values()].map((t) => t.ms).sort((a, b) => a - b);
async function fire(ms) {
  const due = [...timers.entries()].filter(([, t]) => t.ms === ms);
  due.forEach(([id]) => timers.delete(id));
  due.forEach(([, t]) => t.f());
  await settle();
}
"""


def run(module, script):
    """Run `script` with app/<module> imported as M, the app copied to a
    module package first so its own imports resolve."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = "%s\nconst M = await import(%s);\n%s" % (
            BROWSER,
            json.dumps((root / module).as_uri()),
            script,
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


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePolling(unittest.TestCase):
    def test_quick_reads_are_asked_for_at_their_own_pace(self):
        got = run(
            "api.js",
            """
M.watch(["/api/a", "/api/b", "/api/c"], 15000, {reads: ["/api/a", "/api/elsewhere"], every: 5000});
await settle();
const first = asked.splice(0), paces = pending();
await fire(5000);
const quick = asked.splice(0), afterQuick = pending();
await fire(15000);
const slow = asked.splice(0);
console.log(JSON.stringify({first, paces, quick, afterQuick, slow}));""",
        )
        self.assertEqual(got["first"], ["/api/a", "/api/b", "/api/c"])
        self.assertEqual(got["paces"], [5000, 15000])
        self.assertEqual(got["quick"], ["/api/a"])
        self.assertEqual(got["afterQuick"], [5000, 15000])
        self.assertEqual(got["slow"], ["/api/b", "/api/c"])

    def test_a_view_without_quick_reads_keeps_one_pace(self):
        got = run(
            "api.js",
            """
M.watch(["/api/a", "/api/b"], 30000);
await settle();
asked.splice(0);
const paces = pending();
await fire(30000);
console.log(JSON.stringify({paces, asked}));""",
        )
        self.assertEqual(got, {"paces": [30000], "asked": ["/api/a", "/api/b"]})

    def test_a_new_route_stops_the_old_paces(self):
        got = run(
            "api.js",
            """
M.watch(["/api/a", "/api/b"], 15000, {reads: ["/api/a"], every: 5000});
await settle();
M.watch(["/api/z"], 60000);
await settle();
asked.splice(0);
console.log(JSON.stringify({paces: pending()}));""",
        )
        self.assertEqual(got["paces"], [60000])

    def test_coming_back_on_screen_reads_at_once(self):
        got = run(
            "api.js",
            """
M.watch(["/api/a", "/api/b"], 15000, {reads: ["/api/a"], every: 5000});
await settle();
asked.splice(0);
document.hidden = true; docOn.visibilitychange();
const hidden = pending();
document.hidden = false; docOn.visibilitychange();
await settle();
console.log(JSON.stringify({hidden, asked, paces: pending()}));""",
        )
        self.assertEqual(got["hidden"], [])
        self.assertEqual(got["asked"], ["/api/a", "/api/b"])
        self.assertEqual(got["paces"], [5000, 15000])

    def test_coming_back_online_reads_at_once(self):
        main = (APP / "main.js").read_text(encoding="utf-8")
        self.assertRegex(
            main,
            r'window\.addEventListener\("online", \(\) => \{[^}]*api\.refreshNow\(\)',
        )

    def test_the_view_on_screen_hands_its_quick_reads_to_the_poll(self):
        main = (APP / "main.js").read_text(encoding="utf-8")
        calls = re.findall(r"api\.watch\(([^;]*)\);", main)
        self.assertEqual(len(calls), 2, calls)
        for call in calls:
            self.assertTrue(call.endswith(", module.quick"), call)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheNowView(unittest.TestCase):
    def test_the_realm_strip_is_polled_faster_than_the_rest(self):
        got = run(
            "views/now.js",
            "const V = M.default;\n"
            "console.log(JSON.stringify({reads: V.reads({}), every: V.every, quick: V.quick}));",
        )
        quick = got["quick"]
        self.assertEqual(sorted(quick["reads"]), ["/api/eye", "/api/v2/roll"])
        self.assertLessEqual(quick["every"], 5000)
        self.assertLess(quick["every"], got["every"])
        self.assertTrue(set(quick["reads"]) <= set(got["reads"]))
        # The 170KB position read stays on the slow pace.
        self.assertNotIn("/api/map", quick["reads"])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheDataAge(unittest.TestCase):
    def test_the_age_ticks_every_second(self):
        got = run("shell.js", "console.log(JSON.stringify(M.AGE_TICK_MS));")
        self.assertEqual(got, 1000)
        main = (APP / "main.js").read_text(encoding="utf-8")
        self.assertRegex(
            main,
            r"setInterval\(\(\) => \{[^}]*shell\.updateAge\([^}]*\}, shell\.AGE_TICK_MS\)",
        )

    def test_the_count_is_silent_and_only_a_change_of_state_is_spoken(self):
        got = run(
            "shell.js",
            """
const slots = {};
const said = [];
const root = {querySelector(sel) {
  const k = /data-slot="([^"]+)"/.exec(sel)[1];
  if (!slots[k]) slots[k] = k === "age-state"
    ? {set textContent(v) { said.push(v); }, get textContent() { return said[said.length - 1]; }}
    : {innerHTML: ""};
  return slots[k];
}};
const now = Date.now();
const seen = [];
for (const [state, secs] of [["fresh", 3], ["fresh", 4], ["fresh", 5], ["stale", 6], ["stale", 7]]) {
  M.updateAge(root, {state, at: now - secs * 1000, failures: state === "stale" ? 1 : 0});
  seen.push(slots.age.innerHTML);
}
console.log(JSON.stringify({seen, said, short: slots["age-short"].innerHTML}));""",
        )
        self.assertIn("Data 3s ago", got["seen"][0])
        self.assertIn("Data 4s ago", got["seen"][1])
        self.assertIn("Data 7s ago", got["seen"][4])
        for markup in got["seen"] + [got["short"]]:
            self.assertNotIn("role=", markup)
            self.assertNotIn("aria-live", markup)
        self.assertEqual(len(got["said"]), 2, got["said"])
        self.assertIn("current", got["said"][0])
        self.assertIn("stale", got["said"][1])

    def test_the_shell_has_one_polite_region_for_the_age(self):
        shell = (APP / "shell.js").read_text(encoding="utf-8")
        self.assertEqual(
            len(re.findall(r'role="status" data-slot="age-state"', shell)), 1
        )


if __name__ == "__main__":
    unittest.main()
