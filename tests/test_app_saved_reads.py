"""The app's persistent copies survive launches, expire, and stay bounded.

These run api.js under Node with a fake localStorage that outlives module
instances, along with a fake fetch and the page's mount and build.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import quote

HERE = pathlib.Path(__file__).resolve().parent.parent
API = HERE / "app" / "api.js"
BUILD = "a1b2c3d4e5f6"

PRELUDE = r"""
const STORE = new Map(Object.entries(globalThis.__store || {}));
globalThis.__storeMap = STORE;
globalThis.__fetches = [];
Date.now = () => globalThis.__now;
globalThis.document = {
  querySelector: (selector) => {
    if (selector === 'meta[name="overseer-base"]') return { getAttribute: () => "/dev" };
    if (selector === 'meta[name="overseer-build"]') return { getAttribute: () => globalThis.__build };
    return null;
  },
  addEventListener: () => {},
  hidden: false,
};
const localStorage = globalThis.__storageOff ? {
  getItem() { throw new Error("off"); },
  setItem() { throw new Error("off"); },
  removeItem() { throw new Error("off"); },
  key() { throw new Error("off"); },
  get length() { throw new Error("off"); },
} : {
  getItem: (k) => (STORE.has(k) ? STORE.get(k) : null),
  setItem: (k, v) => STORE.set(k, String(v)),
  removeItem: (k) => STORE.delete(k),
  key: (i) => Array.from(STORE.keys())[i] || null,
  get length() { return STORE.size; },
};
globalThis.window = {
  localStorage,
  setTimeout: () => 0,
  clearTimeout: () => {},
};
globalThis.fetch = async (url) => {
  globalThis.__fetches.push(url);
  if (url.endsWith("/api/large")) {
    return { ok: true, status: 200, text: async () => '{"v":"' + "x".repeat(1000001) + '"}' };
  }
  const a = (globalThis.__answers || {})[url];
  if (!a || a === "throw") throw new Error("offline");
  return { ok: a.status === 200, status: a.status, text: async () => a.text };
};
globalThis.__dump = () => Object.fromEntries(STORE);
"""


def run(script, store=None, answers=None, storage_off=False, build=BUILD, now=2000):
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "api.mjs"
        dst.write_text(API.read_text(encoding="utf-8"), encoding="utf-8")
        setup = (
            "globalThis.__store = %s; globalThis.__answers = %s; "
            "globalThis.__storageOff = %s; globalThis.__build = %s; "
            "globalThis.__now = %s;\n"
            % (
                json.dumps(store or {}),
                json.dumps(answers or {}),
                "true" if storage_off else "false",
                json.dumps(build),
                now,
            )
        )
        code = (
            setup
            + PRELUDE
            + f"globalThis.__apiUrl = {json.dumps(dst.as_uri())};\n"
            + "const M = await import(globalThis.__apiUrl);\n"
            + script
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


def save_key(path, mount="/dev", build=BUILD):
    build_key = build or "unversioned"
    return f"overseer.read:{quote(mount, safe='')}:{build_key}:{path}"


def kept(path, data, at=1000, mount="/dev", build=BUILD):
    return {
        save_key(path, mount, build): json.dumps({"at": at, "text": json.dumps(data)})
    }


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ASavedCopy(unittest.TestCase):
    def test_a_reload_paints_the_saved_copy_at_once_and_says_so(self):
        got = run(
            "const p = M.peek('/api/realm');"
            "console.log(JSON.stringify({data: p.data, saved: p.saved, loading: p.loading, "
            "at: p.at, state: M.health(['/api/realm']).state}));",
            store=kept("/api/realm", {"realm": "dev"}),
        )
        self.assertEqual(got["data"], {"realm": "dev"})
        self.assertTrue(got["saved"])
        self.assertFalse(got["loading"])
        self.assertEqual(got["at"], 1000)
        self.assertEqual(got["state"], "saved")

    def test_a_world_that_does_not_answer_is_stale_not_saved(self):
        got = run(
            "await M.load('/api/realm');"
            "const p = M.peek('/api/realm');"
            "console.log(JSON.stringify({data: p.data, state: M.health(['/api/realm']).state}));",
            store=kept("/api/realm", {"realm": "dev"}),
            answers={"/dev/api/realm": "throw"},
        )
        self.assertEqual(got["data"], {"realm": "dev"})
        self.assertEqual(got["state"], "stale")

    def test_a_new_page_load_restores_data_from_persistent_storage(self):
        got = run(
            "const text = JSON.stringify({realm: 'dev'});"
            "globalThis.__answers['/dev/api/realm'] = {status: 200, text};"
            "await M.load('/api/realm');"
            "const N = await import(globalThis.__apiUrl + '?new-page');"
            "const p = N.peek('/api/realm');"
            "console.log(JSON.stringify({data: p.data, saved: p.saved, loading: p.loading, "
            "at: p.at, state: N.health(['/api/realm']).state}));",
            answers={"/dev/api/realm": {"status": 200, "text": '{"realm":"dev"}'}},
        )
        self.assertEqual(got["data"], {"realm": "dev"})
        self.assertTrue(got["saved"])
        self.assertFalse(got["loading"])
        self.assertEqual(got["at"], 2000)
        self.assertEqual(got["state"], "saved")

    def test_the_saved_mark_goes_when_the_world_answers_even_unchanged(self):
        text = json.dumps({"realm": "dev"})
        got = run(
            "const seen = []; M.onChange((p, changed) => seen.push(changed));"
            "M.peek('/api/realm'); await M.load('/api/realm');"
            "console.log(JSON.stringify({saved: M.peek('/api/realm').saved, seen,"
            " state: M.health(['/api/realm']).state}));",
            store=kept("/api/realm", {"realm": "dev"}),
            answers={"/dev/api/realm": {"status": 200, "text": text}},
        )
        self.assertFalse(got["saved"])
        self.assertEqual(got["seen"], [True])
        self.assertEqual(got["state"], "fresh")

    def test_an_entry_older_than_one_day_is_removed_and_not_used(self):
        old_at = 1000
        got = run(
            "const p = M.peek('/api/realm');"
            "console.log(JSON.stringify({loading: p.loading, store: globalThis.__dump()}));",
            store=kept("/api/realm", {"realm": "dev"}, at=old_at),
            now=old_at + 24 * 60 * 60 * 1000 + 1,
        )
        self.assertTrue(got["loading"])
        self.assertEqual(got["store"], {})

    def test_a_copy_saved_under_another_build_is_removed_and_not_used(self):
        old_build = "111111111111"
        old_key = save_key("/api/realm", build=old_build)
        got = run(
            "const p = M.peek('/api/realm');"
            "console.log(JSON.stringify({loading: p.loading, store: globalThis.__dump()}));",
            store=kept("/api/realm", {"realm": "dev"}, build=old_build),
        )
        self.assertTrue(got["loading"])
        self.assertNotIn(old_key, got["store"])

    def test_another_mounts_copy_is_never_read(self):
        got = run(
            "console.log(JSON.stringify(M.peek('/api/realm')));",
            store=kept("/api/realm", {"realm": "dev"}, mount="/live"),
        )
        self.assertTrue(got["loading"])

    def test_a_good_answer_is_kept_and_an_error_is_not(self):
        got = run(
            "await M.load('/api/a'); await M.load('/api/b');"
            "console.log(JSON.stringify(globalThis.__dump()));",
            answers={
                "/dev/api/a": {"status": 200, "text": '{"n": 1}'},
                "/dev/api/b": {"status": 503, "text": '{"error": "world unreachable"}'},
            },
        )
        self.assertEqual(sorted(got), [save_key("/api/a")])
        self.assertEqual(json.loads(got[save_key("/api/a")])["text"], '{"n": 1}')

    def test_a_read_over_its_size_limit_is_not_kept(self):
        got = run(
            "await M.load('/api/large');"
            "console.log(JSON.stringify({store: globalThis.__dump(), saved: M.peek('/api/large').saved}));",
            store=kept("/api/large", {"v": "old"}),
        )
        self.assertNotIn(save_key("/api/large"), got["store"])
        self.assertFalse(got["saved"])

    def test_the_total_storage_cap_drops_the_oldest_copy_first(self):
        older = save_key("/api/older")
        newer = save_key("/api/newer")
        script = (
            f"globalThis.__storeMap.set({json.dumps(older)}, "
            "JSON.stringify({at: 100, text: JSON.stringify('x'.repeat(800000))}));"
            f"globalThis.__storeMap.set({json.dumps(newer)}, "
            "JSON.stringify({at: 200, text: JSON.stringify('y'.repeat(800000))}));"
            "await M.load('/api/new');"
            "const store = globalThis.__dump();"
            "const total = Object.entries(store).reduce((n, [k, v]) => n + k.length + v.length, 0);"
            "console.log(JSON.stringify({keys: Object.keys(store), total}));"
        )
        got = run(
            script,
            answers={"/dev/api/new": {"status": 200, "text": '{"ready":true}'}},
        )
        self.assertNotIn(older, got["keys"])
        self.assertIn(newer, got["keys"])
        self.assertIn(save_key("/api/new"), got["keys"])
        self.assertLessEqual(got["total"], 1_500_000)

    def test_storage_that_throws_does_not_break_a_read(self):
        got = run(
            "const before = M.peek('/api/a'); await M.load('/api/a');"
            "console.log(JSON.stringify({before: before.loading, after: M.peek('/api/a').data}));",
            answers={"/dev/api/a": {"status": 200, "text": '{"n": 1}'}},
            storage_off=True,
        )
        self.assertTrue(got["before"])
        self.assertEqual(got["after"], {"n": 1})


class ThePageSaysSo(unittest.TestCase):
    def test_the_saved_state_draws_its_own_banner(self):
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        self.assertIn('if (h.state === "saved") return savedBanner(h);', main)
        self.assertIn("Showing the copy saved ${ago(secs)}", main)
        css = (HERE / "app" / "app.css").read_text(encoding="utf-8")
        self.assertIn('.age-dot[data-state="saved"]', css)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class WideningReads(unittest.TestCase):
    def test_a_read_that_just_answered_is_not_asked_again(self):
        """A member page widens its reads without refetching a fresh roster."""
        got = run(
            "await M.load('/api/v2/roster');"
            "M.watch(['/api/v2/roster', '/api/v2/activity?name=Grug'], 15000);"
            "await new Promise((r) => setTimeout(r, 10));"
            "console.log(JSON.stringify(globalThis.__fetches));",
            answers={
                "/dev/api/v2/roster": {"status": 200, "text": "{}"},
                "/dev/api/v2/activity?name=Grug": {"status": 200, "text": "{}"},
            },
        )
        self.assertEqual(got, ["/dev/api/v2/roster", "/dev/api/v2/activity?name=Grug"])


if __name__ == "__main__":
    unittest.main()
