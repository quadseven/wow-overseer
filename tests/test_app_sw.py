"""Tests for the mount-scoped offline shell service worker (#2314, epic #2309)."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import appbuild
    import map_server

from test_app_shell import get  # noqa: E402

NODE = shutil.which("node")
needs_node = unittest.skipIf(NODE is None, "node is not on PATH")
BUILD = appbuild.fingerprint(str(HERE))


def _served(path: str, base: str = "", headers: dict[str, str] | None = None):
    original = map_server.BASE_PATH
    map_server.BASE_PATH = base
    try:
        return get(path, headers)
    finally:
        map_server.BASE_PATH = original


def _page_shell_urls(html_text: str, build: str) -> list[str]:
    urls = []
    for tag in re.findall(r"<link\b[^>]+>", html_text):
        rel = re.search(r'\brel="([^"]+)"', tag)
        href = re.search(r'\bhref="([^"]+)"', tag)
        if not rel or not href:
            continue
        if rel.group(1) in ("stylesheet", "modulepreload") and (
            "/app/%s/" % build
        ) in href.group(1):
            urls.append(href.group(1))
    return urls


def _boot_graph(entry: str = "main.js") -> list[str]:
    """`entry` and every app module it reaches by static imports alone."""
    app_dir = HERE / "app"
    seen: list[str] = []
    queue = [entry]
    while queue:
        rel = queue.pop(0)
        if rel in seen:
            continue
        seen.append(rel)
        text = (app_dir / rel).read_text(encoding="utf-8")
        parent = pathlib.PurePosixPath(rel).parent
        for m in re.finditer(
            r"""from\s+["'](\.[^"']+)["']|import\s+["'](\.[^"']+)["']""", text
        ):
            target = (parent / (m.group(1) or m.group(2))).as_posix()
            parts: list[str] = []
            for seg in target.split("/"):
                if seg in ("", "."):
                    continue
                if seg == "..":
                    parts.pop()
                else:
                    parts.append(seg)
            queue.append("/".join(parts))
    return seen


def _run_sw_node(sw_code: str, base: str, harness: str) -> dict:
    origin = "https://example.invalid"
    full = (
        """
const listeners = {};
const stores = new Map();
const fetchLog = [];
let skipWaitingCalls = 0;

function ensureStore(name) {
  if (!stores.has(name)) stores.set(name, new Map());
  return stores.get(name);
}

function makeCache(name) {
  const s = ensureStore(name);
  return {
    async addAll(urls) {
      for (const u of urls) s.set(new URL(u, %s).href, { url: u, body: "cached:" + u, ok: true });
    },
    async match(req) {
      const url = typeof req === "string" ? req : req.url;
      const key = new URL(url, %s).href;
      return s.get(key) || undefined;
    },
    async put(req, res) {
      const url = typeof req === "string" ? req : req.url;
      s.set(new URL(url, %s).href, res);
    },
  };
}

globalThis.caches = {
  async open(name) { return makeCache(name); },
  async keys() { return Array.from(stores.keys()); },
  async delete(name) { return stores.delete(name); },
  async match(req) {
    for (const name of stores.keys()) {
      const hit = await makeCache(name).match(req);
      if (hit) return hit;
    }
    return undefined;
  },
};

globalThis.fetch = async (req) => {
  const url = typeof req === "string" ? req : req.url;
  fetchLog.push(url);
  if (globalThis.__offline) throw new Error("network offline");
  return {
    ok: true,
    status: 200,
    url,
    body: "net:" + url,
    clone() { return { ok: true, status: 200, url, body: this.body }; },
  };
};

globalThis.self = {
  location: { origin: %s, href: %s + %s + "/sw.js" },
  skipWaiting() { skipWaitingCalls += 1; },
  addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
};

async function dispatchLifecycle(type) {
  const waits = [];
  for (const fn of listeners[type] || []) {
    fn({ waitUntil(p) { waits.push(Promise.resolve(p)); } });
  }
  await Promise.all(waits);
}

function dispatchFetch(url, opts = {}) {
  let responded = null;
  const waits = [];
  const req = { url: new URL(url, %s).href, method: opts.method || "GET", mode: opts.mode || "cors" };
  const ev = {
    request: req,
    respondWith(p) { responded = Promise.resolve(p); },
    waitUntil(p) { waits.push(Promise.resolve(p)); },
  };
  for (const fn of listeners.fetch || []) fn(ev);
  return { responded, waits };
}
"""
        % (
            json.dumps(origin),
            json.dumps(origin),
            json.dumps(origin),
            json.dumps(origin),
            json.dumps(origin),
            json.dumps(base),
            json.dumps(origin),
        )
        + "\n"
        + sw_code
        + "\n"
        + harness
    )
    out = subprocess.run(
        [NODE, "--input-type=module", "-e", full],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class ServiceWorkerHandlerTests(unittest.TestCase):
    def test_sw_is_served_at_mount_with_scope_and_no_cache(self):
        for base, expected_scope in (("", "/"), ("/dev", "/dev/")):
            r = _served("/sw.js", base)
            self.assertEqual(r.status(), 200, base)
            self.assertEqual(r.header("Content-Type"), "text/javascript; charset=utf-8")
            self.assertEqual(r.header("Cache-Control"), "no-cache")
            self.assertEqual(r.header("Service-Worker-Allowed"), expected_scope)
            tag = r.header("ETag")
            self.assertTrue(tag)
            again = _served("/sw.js", base, {"If-None-Match": tag})
            self.assertEqual(again.status(), 304)
            self.assertEqual(again.header("Service-Worker-Allowed"), expected_scope)

    def test_prefixed_mount_has_no_unprefixed_shell_urls(self):
        r = _served("/sw.js", "/dev")
        text = r.body().decode("utf-8")
        self.assertIn('"/dev"', text)
        self.assertNotIn('"__OVERSEER_BASE__"', text)
        self.assertNotIn('"__OVERSEER_BUILD__"', text)

    def test_sw_on_disk_has_no_literal_dev_mount_and_ships_in_docker(self):
        raw = (HERE / "app" / "sw.js").read_text(encoding="utf-8")
        self.assertIn("__OVERSEER_BASE__", raw)
        self.assertNotIn("/dev", raw)
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY app /app/app", dockerfile)


@needs_node
class PrecacheAndRuntimeTests(unittest.TestCase):
    def test_precache_list_equals_pages_modulepreload_and_style_list(self):
        for base in ("", "/dev"):
            page = _served("/", base).body().decode("utf-8")
            expected = [base + "/"] + _page_shell_urls(page, BUILD)
            self.assertGreater(len(expected), 3)
            sw_code = _served("/sw.js", base).body().decode("utf-8")
            got = _run_sw_node(
                sw_code,
                base,
                """
await dispatchLifecycle("install");
const keys = Array.from(stores.get("overseer-shell-" + %s).keys()).map((u) => new URL(u).pathname);
console.log(JSON.stringify({ keys, skipWaitingCalls }));
"""
                % json.dumps(BUILD),
            )
            self.assertEqual(got["keys"], expected, base)
            self.assertEqual(got["skipWaitingCalls"], 0)

    def test_index_modulepreload_covers_main_boot_graph(self):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        preloads = re.findall(
            r'<link rel="modulepreload" href="__OVERSEER_BASE__/app/__OVERSEER_BUILD__/([^"]+)">',
            page,
        )
        self.assertEqual(set(preloads), set(_boot_graph()))

    def test_activate_deletes_only_older_overseer_shell_caches(self):
        sw_code = _served("/sw.js", "").body().decode("utf-8")
        got = _run_sw_node(
            sw_code,
            "",
            """
ensureStore("overseer-shell-000000000000");
ensureStore("overseer-shell-deadbeef1234");
ensureStore("unrelated-cache");
await dispatchLifecycle("install");
await dispatchLifecycle("activate");
const remaining = Array.from(stores.keys()).sort();
console.log(JSON.stringify({ remaining }));
""",
        )
        self.assertEqual(
            got["remaining"], ["overseer-shell-" + BUILD, "unrelated-cache"]
        )

    def test_api_never_hits_shell_cache_and_app_file_is_cache_first(self):
        sw_code = _served("/sw.js", "/dev").body().decode("utf-8")
        got = _run_sw_node(
            sw_code,
            "/dev",
            """
await dispatchLifecycle("install");
fetchLog.length = 0;

const apiEv = dispatchFetch("/dev/api/realm");
const apiV2Ev = dispatchFetch("/dev/api/v2/roster");
const clipEv = dispatchFetch("/dev/clips/sample.mp4");
const mvEv = dispatchFetch("/dev/modelviewer/meta/1.json");
const staleEv = dispatchFetch("/dev/app/000000000000/main.js");
const foreignEv = dispatchFetch("https://cdn.example.invalid/font.css");

const appEv = dispatchFetch("/dev/app/" + %s + "/main.js");
const appRes = await appEv.responded;
const fetchesAfterAppHit = fetchLog.slice();

const viewUrl = "/dev/app/" + %s + "/views/now.js";
const viewEv1 = dispatchFetch(viewUrl);
const viewRes1 = await viewEv1.responded;
const viewEv2 = dispatchFetch(viewUrl);
const viewRes2 = await viewEv2.responded;
const fetchesAfterSecondView = fetchLog.slice();

const navEv = dispatchFetch("/dev/", { mode: "navigate" });
const navRes = await navEv.responded;
await Promise.all(navEv.waits);

globalThis.__offline = true;
const offlineNavEv = dispatchFetch("/dev/", { mode: "navigate" });
const offlineNavRes = await offlineNavEv.responded;
await Promise.all(offlineNavEv.waits);

console.log(JSON.stringify({
  apiIntercepted: apiEv.responded !== null,
  apiV2Intercepted: apiV2Ev.responded !== null,
  clipIntercepted: clipEv.responded !== null,
  mvIntercepted: mvEv.responded !== null,
  staleIntercepted: staleEv.responded !== null,
  foreignIntercepted: foreignEv.responded !== null,
  appBody: appRes.body,
  fetchesAfterAppHit,
  viewBody1: viewRes1.body,
  viewBody2: viewRes2.body,
  fetchesAfterSecondView,
  navBody: navRes.body,
  offlineNavBody: offlineNavRes.body,
}));
"""
            % (json.dumps(BUILD), json.dumps(BUILD)),
        )
        self.assertFalse(got["apiIntercepted"])
        self.assertFalse(got["apiV2Intercepted"])
        self.assertFalse(got["clipIntercepted"])
        self.assertFalse(got["mvIntercepted"])
        self.assertFalse(got["staleIntercepted"])
        self.assertFalse(got["foreignIntercepted"])
        self.assertTrue(got["appBody"].startswith("cached:"))
        self.assertEqual(got["fetchesAfterAppHit"], [])
        self.assertTrue(got["viewBody1"].startswith("net:"))
        self.assertEqual(got["viewBody2"], got["viewBody1"])
        self.assertEqual(len(got["fetchesAfterSecondView"]), 1)
        self.assertTrue(got["navBody"].startswith("cached:"))
        self.assertTrue(got["offlineNavBody"].startswith("net:"))


@needs_node
class RegistrationTests(unittest.TestCase):
    def test_page_without_service_worker_still_draws_and_insecure_skips_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(HERE / "app", root)
            (root.parent / "package.json").write_text(
                '{"type": "module"}', encoding="utf-8"
            )
            script = """
globalThis.document = {
  readyState: "complete",
  addEventListener() {},
  querySelector: (q) => q.includes("overseer-base") ? { getAttribute: () => "/dev" } : null,
};
const { installWorker, registerWorker } = await import("./app/worker.js");
const { html } = await import("./app/ui.js");

const calls = [];
const noSwOut = await registerWorker(
  { isSecureContext: true, location: { protocol: "https:", hostname: "example.invalid" } },
  {}
);
const httpOut = await registerWorker(
  { isSecureContext: false, location: { protocol: "http:", hostname: "example.invalid" } },
  { serviceWorker: { register(url, opts) { calls.push([url, opts]); } } }
);
const rejectOut = await registerWorker(
  { isSecureContext: true, location: { protocol: "https:", hostname: "example.invalid" } },
  { serviceWorker: { register() { return Promise.reject(new Error("blocked")); } } }
);

globalThis.window = { isSecureContext: true, requestAnimationFrame: (fn) => fn(), addEventListener() {} };
const rootNode = { innerHTML: "", dataset: {} };
const drawWithoutSw = (() => {
  installWorker(globalThis.window, globalThis.document, {});
  rootNode.innerHTML = String(html`<span>rendered</span>`);
  return rootNode.innerHTML;
})();
installWorker(
  globalThis.window,
  globalThis.document,
  { serviceWorker: { register(url, opts) { calls.push([url, opts]); return Promise.resolve({}); } } }
);

console.log(JSON.stringify({ noSwOut, httpOut, rejectOut, calls, drawWithoutSw }));
"""
            (root.parent / "test_reg.js").write_text(script, encoding="utf-8")
            out = subprocess.run(
                [NODE, str(root.parent / "test_reg.js")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if out.returncode != 0:
                self.fail(out.stderr)
            got = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertIsNone(got["noSwOut"])
        self.assertIsNone(got["httpOut"])
        self.assertIsNone(got["rejectOut"])
        self.assertEqual(got["drawWithoutSw"], "<span>rendered</span>")
        self.assertEqual(len(got["calls"]), 1)
        self.assertEqual(got["calls"][0][0], "/dev/sw.js")
        self.assertEqual(got["calls"][0][1], {"scope": "/dev/"})

    def test_main_installs_worker(self):
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        self.assertIn("installWorker()", main)


if __name__ == "__main__":
    unittest.main()
