"""The fetch layer's saved copies: a launch paints at once, and says so.

app/api.js keeps the last good answer to each read in local storage, so a
launch from the home screen draws from it straight away, and health() reports
"saved" (the page's banner) until the world answers. The copy is bounded in
age, in build and in total size. These run api.js under node with the browser
stubbed: storage, fetch, the clock and the page's mount and build.

Tickets: #2313 (epic #2309); the saved copy itself is older.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
API = HERE / "app" / "api.js"

BUILD = "0123456789ab"
HOUR = 3600 * 1000

# The browser api.js touches, stubbed. `STORE` is local storage's contents;
# `ANSWERS` maps a URL to {status, text} or "throw". Every fetch is counted.
PRELUDE = r"""
const STORE = new Map(Object.entries(globalThis.__store || {}));
// Entries too big to pass on a command line are made here: {key: [at, size]}.
for (const [key, [at, size]] of Object.entries(globalThis.__fill || {})) {
  STORE.set(key, "v1|" + at + "|" + globalThis.__build + "|" + JSON.stringify({ p: "x".repeat(size) }));
}
const BIG = globalThis.__bigAnswers || {};
globalThis.__fetches = [];
const METAS = globalThis.__metas || {};
globalThis.document = {
  querySelector: (q) => { const m = /name="([a-z-]+)"/.exec(q); const v = m && METAS[m[1]]; return v === undefined || v === null ? null : { getAttribute: () => v }; },
  addEventListener: () => {},
  hidden: false,
};
const storage = globalThis.__storageOff ? {
  get length() { throw new Error("off"); }, key() { throw new Error("off"); },
  getItem() { throw new Error("off"); }, setItem() { throw new Error("off"); }, removeItem() { throw new Error("off"); },
} : {
  get length() { return STORE.size; },
  key: (i) => [...STORE.keys()][i] ?? null,
  getItem: (k) => (STORE.has(k) ? STORE.get(k) : null),
  setItem: (k, v) => { if (globalThis.__quota && [...STORE.values()].reduce((a, x) => a + x.length, 0) + v.length > globalThis.__quota) throw new Error("quota"); STORE.set(k, String(v)); },
  removeItem: (k) => STORE.delete(k),
};
globalThis.window = { localStorage: storage, setTimeout: () => 0, clearTimeout: () => {} };
globalThis.fetch = async (url) => {
  globalThis.__fetches.push(url);
  const a = BIG[url] ? { status: 200, text: JSON.stringify({ p: "x".repeat(BIG[url]) }) } : (globalThis.__answers || {})[url];
  if (!a || a === "throw") throw new Error("offline");
  return { ok: a.status === 200, status: a.status, text: async () => a.text };
};
globalThis.__dump = () => Object.fromEntries(STORE);
"""


def now_ms():
    return int(time.time() * 1000)


def run(
    script,
    store=None,
    answers=None,
    storage_off=False,
    build=BUILD,
    base="/dev",
    quota=0,
    fill=None,
    big=None,
):
    with tempfile.TemporaryDirectory() as tmp:
        dst = pathlib.Path(tmp) / "api.mjs"
        dst.write_text(API.read_text(encoding="utf-8"), encoding="utf-8")
        metas = {"overseer-base": base}
        if build is not None:
            metas["overseer-build"] = build
        setup = (
            "globalThis.__store = %s; globalThis.__answers = %s; globalThis.__storageOff = %s;"
            " globalThis.__metas = %s; globalThis.__quota = %d; globalThis.__fill = %s;"
            " globalThis.__bigAnswers = %s; globalThis.__build = %s;\n"
            % (
                json.dumps(store or {}),
                json.dumps(answers or {}),
                "true" if storage_off else "false",
                json.dumps(metas),
                quota,
                json.dumps(fill or {}),
                json.dumps(big or {}),
                json.dumps(build or ""),
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


def entry(data, at=None, build=BUILD, text=None):
    """One stored copy, in the format api.js writes."""
    body = text if text is not None else json.dumps(data)
    return "v1|%d|%s|%s" % (at if at is not None else now_ms() - 5000, build, body)


def kept(path, data, at=None, build=BUILD, mount="/dev"):
    return {"overseer.read:%s%s" % (mount, path): entry(data, at, build)}


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ASavedCopy(unittest.TestCase):
    def test_a_launch_paints_the_saved_copy_at_once_and_says_so(self):
        at = now_ms() - 5000
        got = run(
            "const p = M.peek('/api/realm');"
            "console.log(JSON.stringify({data: p.data, saved: p.saved, loading: p.loading, at: p.at,"
            " health: M.health(['/api/realm'])}));",
            store=kept("/api/realm", {"realm": "dev"}, at=at),
        )
        self.assertEqual(got["data"], {"realm": "dev"})
        self.assertTrue(got["saved"])
        self.assertFalse(got["loading"])
        self.assertEqual(got["at"], at)
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
            store=kept("/api/realm", {}, mount="/live"),
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
        raw = got["overseer.read:/dev/api/a"]
        self.assertRegex(raw, r"^v1\|\d{13}\|%s\|" % BUILD)
        self.assertTrue(raw.endswith('|{"n": 1}'))

    def test_storage_that_throws_changes_nothing(self):
        got = run(
            "const before = M.peek('/api/a'); await M.load('/api/a');"
            "console.log(JSON.stringify({before: before.loading, after: M.peek('/api/a').data}));",
            answers={"/dev/api/a": {"status": 200, "text": '{"n": 1}'}},
            storage_off=True,
        )
        self.assertTrue(got["before"])
        self.assertEqual(got["after"], {"n": 1})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class SurvivesALaunch(unittest.TestCase):
    def test_what_one_page_load_saved_the_next_one_in_a_new_session_paints(self):
        text = json.dumps({"n": 7})
        first = run(
            "await M.load('/api/a'); console.log(JSON.stringify(globalThis.__dump()));",
            answers={"/dev/api/a": {"status": 200, "text": text}},
        )
        got = run(
            "const p = M.peek('/api/a'); console.log(JSON.stringify({data: p.data, saved: p.saved}));",
            store=first,
        )
        self.assertEqual(got, {"data": {"n": 7}, "saved": True})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheCopyIsBounded(unittest.TestCase):
    def test_a_copy_older_than_a_day_is_not_used_and_is_removed(self):
        store = kept("/api/old", {"n": 1}, at=now_ms() - 25 * HOUR)
        store.update(kept("/api/new", {"n": 2}, at=now_ms() - 23 * HOUR))
        got = run(
            "const a = M.peek('/api/old'); const b = M.peek('/api/new');"
            "console.log(JSON.stringify({old: a.loading, fresh: b.data, left: Object.keys(globalThis.__dump())}));",
            store=store,
        )
        self.assertTrue(got["old"])
        self.assertEqual(got["fresh"], {"n": 2})
        self.assertEqual(got["left"], ["overseer.read:/dev/api/new"])

    def test_a_copy_saved_by_another_build_is_not_used_and_is_removed(self):
        store = kept("/api/a", {"n": 1}, build="ffffffffffff")
        got = run(
            "const a = M.peek('/api/a');"
            "console.log(JSON.stringify({loading: a.loading, left: Object.keys(globalThis.__dump())}));",
            store=store,
        )
        self.assertTrue(got["loading"])
        self.assertEqual(got["left"], [])

    def test_without_a_stamped_build_only_unstamped_copies_match(self):
        store = kept("/api/a", {"n": 1}, build="")
        got = run(
            "console.log(JSON.stringify(M.peek('/api/a').data));",
            store=store,
            build=None,
        )
        self.assertEqual(got, {"n": 1})
        got = run(
            "console.log(JSON.stringify(M.peek('/api/a').loading));",
            store=kept("/api/a", {}, build=BUILD),
            build=None,
        )
        self.assertTrue(got)

    def test_another_mounts_copy_is_aged_out_but_not_judged_by_this_build(self):
        store = kept("/api/a", {"n": 1}, build="ffffffffffff", mount="/live")
        store.update(kept("/api/b", {"n": 1}, at=now_ms() - 30 * HOUR, mount="/live"))
        got = run(
            "console.log(JSON.stringify(Object.keys(globalThis.__dump())));",
            store=store,
        )
        self.assertEqual(got, ["overseer.read:/live/api/a"])

    def test_saving_past_the_total_drops_the_oldest_copies_first(self):
        fill = {
            "overseer.read:/dev/api/r%d" % i: [now_ms() - age * HOUR, 400000]
            for i, age in enumerate((9, 8, 7))
        }
        got = run(
            "await M.load('/api/new');"
            "const keys = Object.keys(globalThis.__dump()).sort();"
            "console.log(JSON.stringify(keys));",
            fill=fill,
            big={"/dev/api/new": 400000},
        )
        self.assertIn("overseer.read:/dev/api/new", got)
        self.assertNotIn("overseer.read:/dev/api/r0", got)
        self.assertIn("overseer.read:/dev/api/r2", got)

    def test_one_read_over_the_size_cap_is_never_kept_and_drops_its_old_copy(self):
        got = run(
            "await M.load('/api/a'); console.log(JSON.stringify(Object.keys(globalThis.__dump())));",
            store=kept("/api/a", {"n": 1}),
            big={"/dev/api/a": 1000000},
        )
        self.assertEqual(got, [])

    def test_a_full_storage_drops_the_old_copy_and_the_read_still_works(self):
        got = run(
            "await M.load('/api/a'); console.log(JSON.stringify({data: M.peek('/api/a').data, left: Object.keys(globalThis.__dump())}));",
            store=kept("/api/a", {"n": 1}),
            answers={"/dev/api/a": {"status": 200, "text": '{"n": 2}'}},
            quota=10,
        )
        self.assertEqual(got["data"], {"n": 2})
        self.assertEqual(got["left"], [])

    def test_a_stored_string_that_is_not_an_entry_is_dropped(self):
        got = run(
            "const a = M.peek('/api/a'); console.log(JSON.stringify({loading: a.loading, left: Object.keys(globalThis.__dump())}));",
            store={"overseer.read:/dev/api/a": "{not an entry", "unrelated": "kept"},
        )
        self.assertTrue(got["loading"])
        self.assertEqual(got["left"], ["unrelated"])


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
