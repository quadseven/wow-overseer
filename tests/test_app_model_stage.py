"""Gear 3D model stage placement and animation loop pause/resume (Refs #2321).

On a phone width (max-width: 759.98px), only the model stage nearest the
middle of the viewport (by intersection ratio, tie-broken by distance to
viewport center) stays live; the others keep their static portraits and swap
as the view scrolls. A hidden model or hidden tab cancels its animation frame
loop and resumes when visible again.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
NODE = shutil.which("node")

FAKE_DOM = """
globalThis.document = {
  hidden: false,
  querySelector: () => null,
  addEventListener() {},
  createElement: () => ({ className: "", addEventListener() {}, remove() {}, parentElement: null }),
  head: { appendChild() {} },
  contains: () => false,
};
globalThis.window = {
  addEventListener() {},
  setTimeout: () => 0,
  matchMedia: () => ({ matches: false }),
};
globalThis.sessionStorage = { getItem() {}, setItem() {} };
"""


def run_node(script):
    """Run an ES-module script in a temporary app copy with minimal DOM stubs."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root.parent / "package.json").write_text(
            '{"type": "module"}', encoding="utf-8"
        )
        (root.parent / "dom.js").write_text(FAKE_DOM, encoding="utf-8")
        (root.parent / "run.js").write_text(
            'import "./dom.js";\n' + script, encoding="utf-8"
        )
        out = subprocess.run(
            [NODE, str(root.parent / "run.js")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node is needed to run the app's modules")
class PhonePlacement(unittest.TestCase):
    def test_four_stages_on_phone_keeps_only_highest_intersection_ratio_live(self):
        got = run_node(
            """
import { pickPhoneStage, createModelController } from "./app/views/_model.js";

function stageEl(name, rect) {
  return {
    classList: { added: [], removed: [], add(c) { this.added.push(c); }, remove(c) { this.removed.push(c); } },
    getAttribute(k) { return k === "data-model" ? name : null; },
    getBoundingClientRect() { return rect; },
    appendChild() {},
  };
}

const viewport = { width: 390, height: 844 };
const placed = [];
const dropped = [];
let built = 0;

const ctrl = createModelController({
  isPhone: () => true,
  isHidden: () => false,
  stillMotion: () => false,
  raf: () => 1,
  caf: () => {},
  viewport: () => viewport,
  createPane: () => ({ className: "", parentElement: null, addEventListener() {}, remove() {} }),
  buildViewer: async (name, stage, model, entry) => {
    built++;
    entry.viewer = { renderer: { actors: [{ loaded: true }], azimuth: 0, distance: 0 }, destroy() {} };
  },
  onPlace: (name) => placed.push(name),
  onDrop: (name) => dropped.push(name),
});

for (const n of ["A", "B", "C", "D"]) {
  ctrl.models.set(n, { race: 1, gender: 0, items: [] });
}

const stages = [
  { name: "A", stage: stageEl("A", { left: 0, top: -350, right: 390, bottom: 70, width: 390, height: 420 }), intersectionRatio: 0.17 },
  { name: "B", stage: stageEl("B", { left: 0, top: 100, right: 390, bottom: 520, width: 390, height: 420 }), intersectionRatio: 0.92 },
  { name: "C", stage: stageEl("C", { left: 0, top: 550, right: 390, bottom: 970, width: 390, height: 420 }), intersectionRatio: 0.65 },
  { name: "D", stage: stageEl("D", { left: 0, top: 1000, right: 390, bottom: 1420, width: 390, height: 420 }), intersectionRatio: 0.0 },
];

const picked = pickPhoneStage(stages, viewport);
const liveAfterFirst = ctrl.reconcilePhone(stages, viewport);

// Simulate scrolling down so C moves to full view (ratio 0.98) and B moves up (ratio 0.35).
const scrolled = [
  { name: "A", stage: stages[0].stage, intersectionRatio: 0.0 },
  { name: "B", stage: stages[1].stage, intersectionRatio: 0.35 },
  { name: "C", stage: stages[2].stage, intersectionRatio: 0.98 },
  { name: "D", stage: stages[3].stage, intersectionRatio: 0.40 },
];
const liveAfterScroll = ctrl.reconcilePhone(scrolled, viewport);

// Equal ratio tie breaks in favor of the stage nearest viewport center (y=422).
const tied = [
  { name: "A", stage: stageEl("A", { left: 0, top: 10, right: 390, bottom: 210, width: 390, height: 200 }), intersectionRatio: 1.0 },
  { name: "B", stage: stageEl("B", { left: 0, top: 320, right: 390, bottom: 520, width: 390, height: 200 }), intersectionRatio: 1.0 },
  { name: "C", stage: stageEl("C", { left: 0, top: 640, right: 390, bottom: 940, width: 390, height: 300 }), intersectionRatio: 0.68 },
  { name: "D", stage: stageEl("D", { left: 0, top: 960, right: 390, bottom: 1260, width: 390, height: 300 }), intersectionRatio: 0.0 },
];
const tieWinner = pickPhoneStage(tied, viewport);

// Zero intersection anywhere leaves zero live models.
const noneVisible = scrolled.map((s) => ({ ...s, intersectionRatio: 0.0 }));
const liveWhenOffscreen = ctrl.reconcilePhone(noneVisible, viewport);

console.log(JSON.stringify({
  picked: picked && picked.name,
  liveAfterFirst,
  liveAfterScroll,
  liveKeysAfterFirst: liveAfterFirst ? [liveAfterFirst] : [],
  liveKeysEnd: Array.from(ctrl.live.keys()),
  tieWinner: tieWinner && tieWinner.name,
  liveWhenOffscreen,
  placed,
  dropped,
}));
"""
        )
        self.assertEqual(got["picked"], "B")
        self.assertEqual(got["liveAfterFirst"], "B")
        self.assertEqual(got["liveAfterScroll"], "C")
        self.assertEqual(got["tieWinner"], "B")
        self.assertIsNone(got["liveWhenOffscreen"])
        self.assertEqual(got["liveKeysEnd"], [])
        self.assertEqual(got["placed"], ["B", "C"])
        self.assertEqual(got["dropped"], ["B", "C"])

    def test_wide_screen_places_every_intersecting_stage(self):
        got = run_node(
            """
import { createModelController } from "./app/views/_model.js";

function stageEl(name) {
  return {
    classList: { add() {}, remove() {} },
    getAttribute(k) { return k === "data-model" ? name : null; },
    getBoundingClientRect() { return { left: 0, top: 0, right: 300, bottom: 420, width: 300, height: 420 }; },
    appendChild() {},
  };
}

const ctrl = createModelController({
  isPhone: () => false,
  isHidden: () => false,
  stillMotion: () => false,
  raf: () => 1,
  caf: () => {},
  viewport: () => ({ width: 1440, height: 900 }),
  createPane: () => ({ className: "", parentElement: null, addEventListener() {}, remove() {} }),
  buildViewer: async (name, stage, model, entry) => {
    entry.viewer = { renderer: { actors: [{ loaded: true }], azimuth: 0, distance: 0 }, destroy() {} };
  },
});

for (const n of ["A", "B", "C", "D"]) {
  ctrl.models.set(n, { race: 1, gender: 0, items: [] });
}

ctrl.reconcileWide([
  { name: "A", stage: stageEl("A"), isIntersecting: true },
  { name: "B", stage: stageEl("B"), isIntersecting: true },
  { name: "C", stage: stageEl("C"), isIntersecting: true },
  { name: "D", stage: stageEl("D"), isIntersecting: false },
]);

console.log(JSON.stringify(Array.from(ctrl.live.keys()).sort()));
"""
        )
        self.assertEqual(got, ["A", "B", "C"])


@unittest.skipUnless(NODE, "node is needed to run the app's modules")
class AnimationLoopVisibility(unittest.TestCase):
    def test_hidden_tab_cancels_animation_frame_and_resumes_on_return(self):
        got = run_node(
            """
import { createModelController } from "./app/views/_model.js";

let nextRaf = 1;
const frames = new Map();
const cancelled = [];
let hidden = false;
const renderer = { actors: [{ loaded: true }], azimuth: 0, distance: 0, mouseDown: false, width: 300, height: 420, onResize() {} };
let destroyed = 0;

function flushFrames(count) {
  for (let i = 0; i < count; i++) {
    const batch = Array.from(frames.entries());
    frames.clear();
    for (const [, fn] of batch) fn();
  }
}

const stageClasses = new Set();
const stage = {
  clientWidth: 300,
  clientHeight: 420,
  classList: {
    add(c) { stageClasses.add(c); },
    remove(c) { stageClasses.delete(c); },
    contains(c) { return stageClasses.has(c); },
  },
  getAttribute(k) { return k === "data-model" ? "A" : null; },
  appendChild() {},
};

const ctrl = createModelController({
  isPhone: () => false,
  isHidden: () => hidden,
  stillMotion: () => false,
  raf: (fn) => { const id = nextRaf++; frames.set(id, fn); return id; },
  caf: (id) => { cancelled.push(id); frames.delete(id); },
  viewport: () => ({ width: 1280, height: 800 }),
  createPane: () => ({ className: "", parentElement: stage, addEventListener() {}, remove() {} }),
  buildViewer: async (name, st, model, entry) => {
    entry.viewer = { renderer, destroy() { destroyed++; } };
  },
});

ctrl.models.set("A", { race: 1, gender: 0, items: [] });
ctrl.place(stage, "A");
await Promise.resolve();
await Promise.resolve();

flushFrames(2);
const azimuthAfterRun = renderer.azimuth;
const pendingBeforeHide = Array.from(frames.keys());

hidden = true;
ctrl.syncLoops();
const pendingWhileHidden = frames.size;
flushFrames(2);
const azimuthWhileHidden = renderer.azimuth;

hidden = false;
ctrl.syncLoops();
const pendingAfterResume = frames.size;
flushFrames(2);
const azimuthAfterResume = renderer.azimuth;

const liveBeforeDrop = stage.classList.contains("live");
ctrl.drop("A");
const liveAfterDrop = stage.classList.contains("live");
const pendingAfterDrop = frames.size;

console.log(JSON.stringify({
  azimuthAfterRun,
  pendingBeforeHide,
  cancelled,
  pendingWhileHidden,
  azimuthWhileHidden,
  pendingAfterResume,
  azimuthAfterResume,
  liveBeforeDrop,
  liveAfterDrop,
  pendingAfterDrop,
  destroyed,
}));
"""
        )
        self.assertGreater(got["azimuthAfterRun"], 0)
        self.assertEqual(len(got["pendingBeforeHide"]), 1)
        self.assertEqual(got["pendingWhileHidden"], 0)
        self.assertIn(got["pendingBeforeHide"][0], got["cancelled"])
        self.assertEqual(got["azimuthWhileHidden"], got["azimuthAfterRun"])
        self.assertEqual(got["pendingAfterResume"], 1)
        self.assertGreater(got["azimuthAfterResume"], got["azimuthWhileHidden"])
        self.assertTrue(got["liveBeforeDrop"])
        self.assertFalse(got["liveAfterDrop"])
        self.assertEqual(got["pendingAfterDrop"], 0)
        self.assertEqual(got["destroyed"], 1)

    def test_offscreen_stage_visibility_cancels_loop_without_destroy_and_resumes(self):
        got = run_node(
            """
import { createModelController } from "./app/views/_model.js";

let nextRaf = 1;
const frames = new Map();
const cancelled = [];
const renderer = { actors: [{ loaded: true }], azimuth: 0, distance: 0, mouseDown: false, width: 300, height: 420, onResize() {} };
let destroyed = 0;

function flushOne() {
  const batch = Array.from(frames.entries());
  frames.clear();
  for (const [, fn] of batch) fn();
}

const stageClasses = new Set();
const stage = {
  clientWidth: 300,
  clientHeight: 420,
  classList: {
    add(c) { stageClasses.add(c); },
    remove(c) { stageClasses.delete(c); },
    contains(c) { return stageClasses.has(c); },
  },
  getAttribute(k) { return k === "data-model" ? "A" : null; },
  appendChild() {},
};

const ctrl = createModelController({
  isPhone: () => false,
  isHidden: () => false,
  stillMotion: () => false,
  raf: (fn) => { const id = nextRaf++; frames.set(id, fn); return id; },
  caf: (id) => { cancelled.push(id); frames.delete(id); },
  viewport: () => ({ width: 1280, height: 800 }),
  createPane: () => ({ className: "", parentElement: stage, addEventListener() {}, remove() {} }),
  buildViewer: async (name, st, model, entry) => {
    entry.viewer = { renderer, destroy() { destroyed++; } };
  },
});

ctrl.models.set("A", { race: 1, gender: 0, items: [] });
ctrl.place(stage, "A");
await Promise.resolve();
await Promise.resolve();
flushOne();

ctrl.setVisible("A", false);
const framesWhenOffscreen = frames.size;
ctrl.setVisible("A", true);
const framesWhenReturned = frames.size;

console.log(JSON.stringify({
  cancelledCount: cancelled.length,
  framesWhenOffscreen,
  framesWhenReturned,
  destroyed,
}));
"""
        )
        self.assertEqual(got["cancelledCount"], 1)
        self.assertEqual(got["framesWhenOffscreen"], 0)
        self.assertEqual(got["framesWhenReturned"], 1)
        self.assertEqual(got["destroyed"], 0)


@unittest.skipUnless(NODE, "node is needed to run the app's modules")
class MountModelsWiring(unittest.TestCase):
    def test_mount_models_on_phone_observes_and_pauses_on_visibility_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "app"
            shutil.copytree(APP, root)
            (root.parent / "package.json").write_text(
                '{"type": "module"}', encoding="utf-8"
            )
            harness = """
const listeners = { win: {}, doc: {} };
let nextRaf = 1;
const rafs = new Map();
const cancelled = [];
const fetched = [];
let destroyed = 0;

globalThis.requestAnimationFrame = (fn) => { const id = nextRaf++; rafs.set(id, fn); return id; };
globalThis.cancelAnimationFrame = (id) => { cancelled.push(id); rafs.delete(id); };
globalThis.fetch = async (url) => {
  fetched.push(String(url));
  return { ok: true, async json() { return { Options: [] }; } };
};

const observers = [];
globalThis.IntersectionObserver = class FakeIO {
  constructor(cb, opts) { this.cb = cb; this.opts = opts; this.observed = []; observers.push(this); }
  observe(el) { this.observed.push(el); }
  disconnect() { this.observed = []; }
};

const headChildren = [];
globalThis.document = {
  hidden: false,
  querySelector: () => null,
  addEventListener(ev, fn) { (listeners.doc[ev] = listeners.doc[ev] || []).push(fn); },
  createElement(tag) {
    const el = {
      tagName: tag, className: "", src: "", parentElement: null,
      addEventListener() {}, remove() { this.parentElement = null; },
      onload: null, onerror: null,
    };
    return el;
  },
  head: {
    appendChild(s) {
      headChildren.push(s);
      if (s.src && s.src.includes("viewer.min.js")) {
        globalThis.window.ZamModelViewer = function MockViewer() {
          this.renderer = { actors: [{ loaded: true }], azimuth: 0, distance: 0, mouseDown: false, width: 300, height: 420, onResize() {} };
          this.destroy = () => { destroyed++; };
        };
      }
      if (s.onload) queueMicrotask(() => s.onload());
    },
  },
  contains: () => true,
};
globalThis.window = {
  innerWidth: 390,
  innerHeight: 844,
  jQuery: (el) => el,
  addEventListener(ev, fn) { (listeners.win[ev] = listeners.win[ev] || []).push(fn); },
  setTimeout: () => 0,
  matchMedia: (q) => ({ matches: q.includes("759.98px") }),
};
globalThis.sessionStorage = { getItem() {}, setItem() {} };

const { modelStage, mountModels } = await import("./app/views/_model.js");

function makeStage(name, top, bottom) {
  return {
    clientWidth: 300, clientHeight: 420,
    classList: {
      added: [], removed: [],
      add(c) { this.added.push(c); },
      remove(c) { this.removed.push(c); },
    },
    getAttribute(k) { return k === "data-model" ? name : null; },
    getBoundingClientRect() { return { left: 0, top, right: 390, bottom, width: 390, height: bottom - top }; },
    appendChild(child) { child.parentElement = this; },
  };
}

const specs = [
  { name: "A", race: 1, gender: 0, items: [] },
  { name: "B", race: 2, gender: 1, items: [] },
  { name: "C", race: 3, gender: 0, items: [] },
  { name: "D", race: 4, gender: 1, items: [] },
];
for (const s of specs) modelStage({ name: s.name, model: s, portrait: {} });

const stages = [
  makeStage("A", -300, 120),
  makeStage("B", 150, 570),
  makeStage("C", 600, 1020),
  makeStage("D", 1050, 1470),
];
const fakeRoot = {
  querySelectorAll(sel) { return sel === "[data-model]" ? stages : []; },
};

mountModels(fakeRoot);
for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));
const fetchedAfterMount = fetched.slice();
const rafsAfterMount = rafs.size;

globalThis.document.hidden = true;
for (const fn of listeners.doc.visibilitychange || []) fn();
const rafsWhenHidden = rafs.size;
const cancelledCount = cancelled.length;

globalThis.document.hidden = false;
for (const fn of listeners.doc.visibilitychange || []) fn();
const rafsWhenResumed = rafs.size;

// Now simulate IO reporting stage C became dominant (ratio 0.96 vs B 0.30).
const phoneIO = observers.find((o) => o.opts && o.opts.rootMargin === "0px");
phoneIO.cb([
  { target: stages[0], isIntersecting: false, intersectionRatio: 0, boundingClientRect: stages[0].getBoundingClientRect() },
  { target: stages[1], isIntersecting: true, intersectionRatio: 0.30, boundingClientRect: stages[1].getBoundingClientRect() },
  { target: stages[2], isIntersecting: true, intersectionRatio: 0.96, boundingClientRect: stages[2].getBoundingClientRect() },
  { target: stages[3], isIntersecting: true, intersectionRatio: 0.25, boundingClientRect: stages[3].getBoundingClientRect() },
]);
for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0));

console.log(JSON.stringify({
  fetchedAfterMount,
  rafsAfterMount,
  rafsWhenHidden,
  cancelledCount,
  rafsWhenResumed,
  fetchedAfterSwap: fetched.slice(),
  destroyedAfterSwap: destroyed,
}));
"""
            (root.parent / "mount_test.js").write_text(harness, encoding="utf-8")
            out = subprocess.run(
                [NODE, str(root.parent / "mount_test.js")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if out.returncode != 0:
                self.fail(out.stderr)
            got = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(len(got["fetchedAfterMount"]), 1)
        self.assertEqual(got["rafsAfterMount"], 1)
        self.assertEqual(got["rafsWhenHidden"], 0)
        self.assertEqual(got["cancelledCount"], 1)
        self.assertEqual(got["rafsWhenResumed"], 1)
        self.assertEqual(len(got["fetchedAfterSwap"]), 2)
        self.assertEqual(got["destroyedAfterSwap"], 1)


if __name__ == "__main__":
    unittest.main()
