"""The fetch layer's saved copies: a reload paints at once, and says so.

app/api.js keeps the last good answer to each read in sessionStorage. A
reload draws from it straight away, and health() reports "saved" (the page's
banner) until the world answers. These run api.js under node with the browser
stubbed: storage, fetch and the page's mount.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
API = HERE / "app" / "api.js"

# The browser api.js touches, stubbed. `STORE` is sessionStorage's contents;
# `ANSWERS` maps a URL to {status, text} or "throw". Every fetch is counted.
PRELUDE = r"""
const STORE = new Map(Object.entries(globalThis.__store || {}));
globalThis.__fetches = [];
globalThis.document = {
  querySelector: () => ({ getAttribute: () => "/dev" }),
  addEventListener: () => {},
  hidden: false,
};
globalThis.window = {
  sessionStorage: globalThis.__storageOff ? {
    getItem() { throw new Error("off"); }, setItem() { throw new Error("off"); }, removeItem() { throw new Error("off"); },
  } : {
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
globalThis.__dump = () => Object.fromEntries(STORE);
"""


def run(script, store=None, answers=None, storage_off=False):
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "api.mjs"
        dst.write_text(API.read_text(encoding="utf-8"), encoding="utf-8")
        setup = (
            "globalThis.__store = %s; globalThis.__answers = %s; globalThis.__storageOff = %s;\n"
            % (
                json.dumps(store or {}),
                json.dumps(answers or {}),
                "true" if storage_off else "false",
            )
        )
        code = (
            setup
            + PRELUDE
            + "const M = await import(%s);\n%s" % (json.dumps(dst.as_uri()), script)
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


def kept(path, data, at=1000):
    return {
        "overseer.read:/dev" + path: json.dumps({"at": at, "text": json.dumps(data)})
    }


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ASavedCopy(unittest.TestCase):
    def test_a_reload_paints_the_saved_copy_at_once_and_says_so(self):
        got = run(
            "const p = M.peek('/api/realm');"
            "console.log(JSON.stringify({data: p.data, saved: p.saved, loading: p.loading, at: p.at,"
            " health: M.health(['/api/realm'])}));",
            store=kept("/api/realm", {"realm": "dev"}),
        )
        self.assertEqual(got["data"], {"realm": "dev"})
        self.assertTrue(got["saved"])
        self.assertFalse(got["loading"])
        self.assertEqual(got["at"], 1000)
        self.assertEqual(got["health"]["state"], "saved")

    def test_the_mark_goes_when_the_world_answers_even_unchanged(self):
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

    def test_another_mounts_copy_is_never_read(self):
        got = run(
            "console.log(JSON.stringify(M.peek('/api/realm')));",
            store={
                "overseer.read:/live/api/realm": json.dumps({"at": 1, "text": "{}"})
            },
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
        self.assertEqual(sorted(got), ["overseer.read:/dev/api/a"])
        self.assertEqual(
            json.loads(got["overseer.read:/dev/api/a"])["text"], '{"n": 1}'
        )

    def test_storage_that_throws_changes_nothing(self):
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
        """A member page reads the roster, then widens its reads to the
        member's own; the roster that answered a moment ago is not refetched."""
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
