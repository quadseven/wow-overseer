"""Layout stability and rendering performance regressions for the live watch UI."""

import pathlib
import shutil
import unittest

from test_app_flagship import app_file, needs_node, run_node

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
NODE = shutil.which("node")


class CssStabilityAndCompositing(unittest.TestCase):
    def test_app_css_prevents_scroll_bounce_and_blur_jank(self):
        css = (APP / "app.css").read_text(encoding="utf-8")
        self.assertIn("scrollbar-gutter: stable;", css)
        self.assertIn("overflow-anchor: none;", css)
        self.assertNotIn("transform: translateY(8px)", css)
        self.assertNotIn("backdrop-filter: saturate(180%) blur(20px)", css)

    def test_now_css_stabilizes_stream_tiles_and_compositing(self):
        css = (APP / "views" / "now.css").read_text(encoding="utf-8")
        self.assertIn("contain: layout style;", css)
        self.assertIn("transform: translateZ(0);", css)
        self.assertIn("min-height: 2.9em;", css)
        self.assertNotIn("backdrop-filter: blur(10px)", css)
        self.assertNotIn(".st-act:hover > i", css)


@needs_node
class WorldmapAndDarkSamplerPerformance(unittest.TestCase):
    def test_compact_minimap_omits_svg_filters_and_skips_unchanged_redraw(self):
        files = {
            "views/now/worldmap.js": app_file("views/now/worldmap.js"),
            "ui.js": app_file("ui.js"),
        }
        script = r"""
const wm = await import("./views/now/worldmap.js");
let writes = 0;
const attrs = new Map();
let lastHtml = "";
const box = {
  clientWidth: 320,
  clientHeight: 220,
  get innerHTML() { return lastHtml; },
  set innerHTML(v) { writes += 1; lastHtml = v; },
  getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
  setAttribute(k, v) { attrs.set(k, String(v)); },
  querySelector(sel) {
    if (sel === "svg" && lastHtml.includes("<svg")) return { addEventListener() {} };
    return null;
  },
};
const shape = {
  name: "Kalimdor",
  aspect: 1.2,
  coast: ["M0 0 L10 10 Z"],
  zones: [{ name: "Durotar", label: "Durotar", d: "M0 0 L5 5 Z", cx: 2, cy: 2, room: 40 }],
};
const opts = { key: "mini-test", shape, dots: [{ name: "Hero", x: 10, y: 10, color: "#fff", family: true, head: true }], compact: true, focus: [0, 0, 420, 294], summary: "1 here" };
wm.draw(box, opts);
const firstHtml = lastHtml;
wm.draw(box, opts);
console.log(JSON.stringify({
  writes,
  hasTurbulence: firstHtml.includes("feTurbulence"),
  hasBlur: firstHtml.includes("feGaussianBlur"),
  hasSvg: firstHtml.includes("<svg"),
}));
"""
        got = run_node(files, script)
        self.assertEqual(got["writes"], 1)
        self.assertFalse(got["hasTurbulence"])
        self.assertFalse(got["hasBlur"])
        self.assertTrue(got["hasSvg"])

    def test_dark_sampler_skips_when_hidden_and_reuses_canvas_dimensions(self):
        files = {"views/now/dark.js": app_file("views/now/dark.js")}
        script = r"""
let widthSets = 0;
let heightSets = 0;
let drawCalls = 0;
let w = 0;
let h = 0;
const fakeCanvas = {
  get width() { return w; },
  set width(v) { widthSets += 1; w = v; },
  get height() { return h; },
  set height(v) { heightSets += 1; h = v; },
  getContext() {
    return {
      drawImage() { drawCalls += 1; },
      getImageData() { return { data: new Uint8ClampedArray([100, 100, 100, 255]) }; },
    };
  },
};
let tick = null;
globalThis.document = { hidden: false, createElement() { return fakeCanvas; } };
globalThis.window = {
  setInterval(fn) { tick = fn; return 1; },
  clearInterval() {},
};
const dark = await import("./views/now/dark.js");
const video = { videoWidth: 160, videoHeight: 90, readyState: 2, paused: false };
const sampler = dark.darkSampler(video, () => {});
sampler.start();
tick();
globalThis.document.hidden = true;
tick();
globalThis.document.hidden = false;
video.paused = true;
tick();
sampler.stop();
console.log(JSON.stringify({ widthSets, heightSets, drawCalls }));
"""
        got = run_node(files, script)
        self.assertEqual(got["widthSets"], 1)
        self.assertEqual(got["heightSets"], 1)
        self.assertEqual(got["drawCalls"], 2)


if __name__ == "__main__":
    unittest.main()
