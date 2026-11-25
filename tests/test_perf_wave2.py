"""Unit tests for the wave-2 map_server and view performance speedups.

Covers:
- map_server._gzipped JSON LRU cache (separate from static asset cache)
- map_server.Handler._send single SHA-256 pass for ETag + gzip cache key
- app/views/now.js stamp(ctx) object-identity and cached ghost-set stamping
- app/views/now/streams.js idle 1s interval guard and muted audio-query skip
- app/views/map.js model reuse across render() and after()
"""

from __future__ import annotations

import gzip
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
NODE = shutil.which("node")
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import map_server

from test_app_shell import FakeHandler  # noqa: E402


def _run_node(script: str) -> object:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(APP, root / "app")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.js").write_text(script, encoding="utf-8")
        out = subprocess.run(
            [NODE, str(root / "run.js")],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip())


class JsonGzipCacheTests(unittest.TestCase):
    def setUp(self):
        map_server._GZIP_KEPT.clear()
        map_server._GZIP_JSON_KEPT.clear()
        self.addCleanup(map_server._GZIP_KEPT.clear)
        self.addCleanup(map_server._GZIP_JSON_KEPT.clear)

    def test_identical_json_bodies_reuse_compressed_bytes(self):
        body = json.dumps(
            {"dots": [{"name": f"N{i}", "x": i} for i in range(400)]}
        ).encode()
        self.assertGreaterEqual(len(body), map_server.GZIP_MIN_BYTES)

        h1 = FakeHandler("/api/map", {"Accept-Encoding": "gzip"})
        h2 = FakeHandler("/api/map", {"Accept-Encoding": "gzip"})
        with mock.patch.object(
            map_server.gzip, "compress", wraps=map_server.gzip.compress
        ) as compress:
            h1._send(200, "application/json", body)
            h2._send(200, "application/json", body)

        self.assertEqual(compress.call_count, 1)
        self.assertEqual(h1.status(), 200)
        self.assertEqual(h2.status(), 200)
        self.assertEqual(h1.header("Content-Encoding"), "gzip")
        self.assertEqual(h2.header("Content-Encoding"), "gzip")
        self.assertEqual(h1.body(), h2.body())
        self.assertEqual(gzip.decompress(h1.body()), body)

    def test_json_cache_is_bounded_and_does_not_evict_static_assets(self):
        h = FakeHandler("/", {"Accept-Encoding": "gzip"})
        static_js = (
            b"export const x = " + b"1" * (map_server.GZIP_MIN_BYTES + 100) + b";\n"
        )
        packed_js = map_server._gzipped(h, "text/javascript; charset=utf-8", static_js)
        self.assertIsNotNone(packed_js)
        self.assertEqual(len(map_server._GZIP_KEPT), 1)

        for i in range(map_server.GZIP_JSON_KEPT_MAX + 15):
            payload = (
                (b'{"i":%d,"pad":"' % i) + b"a" * map_server.GZIP_MIN_BYTES + b'"}'
            )
            map_server._gzipped(h, "application/json", payload)

        self.assertLessEqual(
            len(map_server._GZIP_JSON_KEPT), map_server.GZIP_JSON_KEPT_MAX
        )
        self.assertEqual(len(map_server._GZIP_KEPT), 1)
        self.assertIs(
            map_server._gzipped(h, "text/javascript; charset=utf-8", static_js),
            packed_js,
        )

    def test_send_hashes_body_only_once_for_etag_and_gzip(self):
        body = json.dumps({"shapes": ["z" * 120 for _ in range(60)]}).encode()
        h = FakeHandler("/shapes.json", {"Accept-Encoding": "gzip"})
        with mock.patch.object(
            map_server.hashlib, "sha256", wraps=map_server.hashlib.sha256
        ) as sha:
            h._send(200, "application/json", body)
        self.assertEqual(sha.call_count, 1)
        self.assertTrue((h.header("ETag") or "").endswith('-gz"'))


@unittest.skipUnless(NODE, "node is required for app view tests")
class NowStampPerfTests(unittest.TestCase):
    def test_stamp_avoids_stringifying_large_payloads_and_detects_changes(self):
        got = _run_node(
            r"""
const noop = () => {};
globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener: noop }),
  addEventListener: noop,
  setInterval: () => 0,
  clearInterval: noop,
  speechSynthesis: undefined,
};
globalThis.location = { hash: "#/now" };
globalThis.localStorage = { getItem: () => null, setItem: noop };
globalThis.document = {
  hidden: false,
  addEventListener: noop,
  removeEventListener: noop,
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: () => ({ style: {}, setAttribute: noop, appendChild: noop }),
  documentElement: { setAttribute: noop, getAttribute: () => null },
  head: { appendChild: noop },
  body: { appendChild: noop },
};
const now = (await import("./app/views/now.js")).default;
const dots = Array.from({ length: 500 }, (_, i) => ({ name: "Dot" + i, x: i, y: i }));
const members = [{ name: "Alpha", family: "Alpha", class: "mage" }];
const state = {
  "/api/map": { data: { dots }, at: 1 },
  "/api/wall": { data: { members }, at: 1 },
  "/shapes.json": { data: { "0": { name: "EK" } }, at: 1 },
  "/api/v2/roster": { data: { members: [{ name: "Alpha", life: "alive" }, { name: "Beta", life: "ghost" }] }, at: 1 },
  "/api/v2/achievements": { data: { items: [{ id: 1 }] }, at: 1 },
};
const ctx = { get: (p) => state[p] || { data: null, at: 0 } };
const first = now.stamp(ctx);
const second = now.stamp(ctx);
// Same ghost set under a fresh roster object keeps the stamp identical.
state["/api/v2/roster"] = { data: { members: [{ name: "Alpha", life: "alive", xp: 99 }, { name: "Beta", life: "ghost" }] }, at: 2 };
const sameGhosts = now.stamp(ctx);
// New ghost changes the stamp.
state["/api/v2/roster"] = { data: { members: [{ name: "Alpha", life: "ghost" }, { name: "Beta", life: "ghost" }] }, at: 3 };
const newGhost = now.stamp(ctx);
// New map dots array changes the stamp.
state["/api/map"] = { data: { dots: dots.slice() }, at: 4 };
const newDots = now.stamp(ctx);
console.log(JSON.stringify({
  same: first === second,
  sameGhosts: first === sameGhosts,
  newGhostChanged: first !== newGhost,
  newDotsChanged: newGhost !== newDots,
  compact: first.length < 120,
}));
"""
        )
        self.assertTrue(got["same"])
        self.assertTrue(got["sameGhosts"])
        self.assertTrue(got["newGhostChanged"])
        self.assertTrue(got["newDotsChanged"])
        self.assertTrue(got["compact"])


@unittest.skipUnless(NODE, "node is required for app view tests")
class StreamsIdleTickTests(unittest.TestCase):
    def test_idle_tick_skips_dom_queries_and_muted_tick_skips_audio_query(self):
        got = _run_node(
            r"""
const noop = () => {};
const intervals = [];
const queries = [];
globalThis.window = {
  addEventListener: noop,
  setInterval: (fn) => { intervals.push(fn); return intervals.length; },
  clearInterval: noop,
  dispatchEvent: noop,
};
globalThis.location = { hash: "#/now" };
globalThis.CSS = { escape: (s) => s };
class El {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.classList = { toggle: noop };
  }
  append(...kids) { kids.forEach((k) => this.appendChild(k)); }
  appendChild(k) { k.parentElement = this; this.children.push(k); return k; }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  setAttribute() {}
  getAttribute() { return null; }
  addEventListener() {}
  remove() {}
}
globalThis.document = {
  hidden: false,
  addEventListener: noop,
  querySelector: () => null,
  querySelectorAll: (sel) => { queries.push(sel); return []; },
  createElement: (tag) => new El(tag),
  body: new El("body"),
};
globalThis.RTCPeerConnection = class {
  addTransceiver() {}
  addEventListener() {}
  removeEventListener() {}
  close() {}
  createOffer() { return new Promise(() => {}); }
};
const streams = await import("./app/views/now/streams.js");
const tick = intervals[0];
// Before any stream connects, tick does no DOM queries.
tick();
const idleQueries = queries.slice();
// Once connected (muted by default), tick updates frame age but skips [data-hear].
streams.connect("Alpha", "http://stream.example/alpha");
queries.length = 0;
tick();
const activeMutedQueries = queries.slice();
// After stopAll (leaving Now), tick does no DOM queries again.
streams.stopAll();
queries.length = 0;
tick();
const afterStopQueries = queries.slice();
console.log(JSON.stringify({ idleQueries, activeMutedQueries, afterStopQueries }));
"""
        )
        self.assertEqual(got["idleQueries"], [])
        self.assertEqual(got["activeMutedQueries"], ["[data-frame-age]"])
        self.assertEqual(got["afterStopQueries"], [])


@unittest.skipUnless(NODE, "node is required for app view tests")
class MapModelCacheTests(unittest.TestCase):
    def test_map_reuses_model_across_render_and_after(self):
        got = _run_node(
            r"""
const noop = () => {};
globalThis.window = {
  addEventListener: noop,
  matchMedia: () => ({ matches: false, addEventListener: noop }),
};
globalThis.document = {
  addEventListener: noop,
  querySelector: () => null,
  querySelectorAll: () => [],
};
const mapView = (await import("./app/views/map.js")).default;
const shape = {
  name: "Kalimdor",
  viewBox: [0, 0, 100, 100],
  zones: [{ id: 1, name: "Durotar", paths: ["M0,0 L10,10"], label: [5, 5], bbox: [0, 0, 10, 10] }],
};
const mapData = {
  dots: [
    { name: "Alpha", continent: "1", zone: 1, x: 5, y: 5 },
    { name: "Beta", continent: "1", zone: 1, x: 6, y: 6 },
  ],
};
const wallData = {
  members: [{ name: "Alpha", family: "Alpha", class: "warrior", class_colour: "#c79c6e", leader: true }],
};
const gearData = {
  guilds: [{ name: "Guild", members: [{ name: "Beta", class: "mage" }] }],
};
const rosterData = { members: [] };
const reads = {
  "/shapes.json": { data: { "1": shape }, at: 1 },
  "/api/map": { data: mapData, at: 1 },
  "/api/wall": { data: wallData, at: 1 },
  "/api/guildgear": { data: gearData, at: 1 },
  "/api/v2/roster": { data: rosterData, at: 1 },
  "/api/spectate": { data: null, at: 0 },
  "/api/v2/operator": { data: { enabled: false }, at: 1 },
};
let dotsReads = 0;
Object.defineProperty(mapData, "dots", {
  get() {
    dotsReads += 1;
    return [
      { name: "Alpha", continent: "1", zone: 1, x: 5, y: 5 },
      { name: "Beta", continent: "1", zone: 1, x: 6, y: 6 },
    ];
  },
});
const ctx = { params: { continent: "kal" }, get: (p) => reads[p] || { data: null, at: 0 } };
const html = mapView.render(ctx).s;
const readsAfterRender = dotsReads;
mapView.after({ querySelector: () => null, querySelectorAll: () => [] }, ctx);
const readsAfterAfter = dotsReads;
console.log(JSON.stringify({
  hasHeading: html.includes("World map"),
  readOnceInRender: readsAfterRender > 0,
  reusedInAfter: readsAfterAfter === readsAfterRender,
}));
"""
        )
        self.assertTrue(got["hasHeading"])
        self.assertTrue(got["readOnceInRender"])
        self.assertTrue(got["reusedInAfter"])


if __name__ == "__main__":
    unittest.main()
