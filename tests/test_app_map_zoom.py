"""The world map's touch pass (quadseven/wow-overseer#3377).

- Dots carry whether the member is inside an instance, so the page can
  split its count honestly instead of drawing instance members as if
  standing in the open world.
- Dots within 44 screen px of each other cluster into one count badge;
  the grouping is a pure function of the dots and the current scale, so
  it is pinned here without a browser.
- No label is ever clipped by the map edge: zone labels shift inside the
  viewBox or drop, member labels flip to end anchored near the right
  edge or drop. A missing label beats a clipped one. The same placement
  code draws the Now minimaps, so the pins here cover them too.
- Pinch zooms toward the pinch midpoint and a double tap zooms toward
  the tap point; both are driven through the view's own pointer
  handlers against a stand-in box.
- The map page leads with family chips, splits its continent count
  (placed, in an instance, position not read), names the guildmates on
  continents the map cannot draw, and caps each Where card at 8 names
  behind a show-all disclosure with no spectate buttons.

The JavaScript runs under node against small stand-ins for the browser.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from test_app_flagship import app_file, needs_node, run_node

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
NODE = shutil.which("node")


def run_app_node(script):
    """Run `script` as an ES module with the whole app tree beside it;
    it prints JSON on its last line (the test_perf_wave2 pattern)."""
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
    return json.loads(out.stdout.strip().splitlines()[-1])


WM_FILES = {
    "views/now/worldmap.js": app_file("views/now/worldmap.js"),
    "ui.js": app_file("ui.js"),
}


@needs_node
class DotsCarryInstance(unittest.TestCase):
    def test_dots_for_keeps_the_instance_flag(self):
        got = run_node(
            WM_FILES,
            r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, zones: [] };
const people = new Map([
  ["In", { family: true, color: "#fff", ghost: false, head: true }],
  ["Out", { family: false, color: "#fff", ghost: false, head: false }],
]);
const dots = wm.dotsFor(shape, "0", [
  { name: "In", continent: "0", u: 0.5, v: 0.5, zone: "Z", instance: true },
  { name: "Out", continent: "0", u: 0.25, v: 0.25, zone: "Z", instance: false },
], people);
console.log(JSON.stringify(dots.map((d) => [d.name, d.instance])));
""",
        )
        self.assertEqual(got, [["In", True], ["Out", False]])


@needs_node
class Clustering(unittest.TestCase):
    def cluster(self, dots, ppu):
        return run_node(
            WM_FILES,
            r"""
const wm = await import("./views/now/worldmap.js");
const out = wm.clusterDots(%s, %s);
console.log(JSON.stringify({
  singles: out.singles.map((d) => d.name),
  clusters: out.clusters.map((c) => ({ names: c.names, x: c.x, y: c.y, x0: c.x0, y0: c.y0, x1: c.x1, y1: c.y1 })),
}));
"""
            % (dots, ppu),
        )

    def test_close_dots_cluster_at_full_view_scale(self):
        # 10 units apart at 0.36 px per unit is 3.6 screen px: one badge.
        got = self.cluster(
            '[{ "name": "A", "x": 100, "y": 100 }, { "name": "B", "x": 110, "y": 100 }, { "name": "C", "x": 500, "y": 500 }]',
            "0.36",
        )
        self.assertEqual(got["singles"], ["C"])
        self.assertEqual(len(got["clusters"]), 1)
        self.assertEqual(got["clusters"][0]["names"], ["A", "B"])
        self.assertEqual(got["clusters"][0]["x"], 105)
        self.assertEqual(got["clusters"][0]["y"], 100)

    def test_dots_beyond_44_screen_px_stay_single(self):
        # 200 units apart at 0.36 px per unit is 72 screen px: no badge.
        got = self.cluster(
            '[{ "name": "A", "x": 100, "y": 100 }, { "name": "B", "x": 300, "y": 100 }]',
            "0.36",
        )
        self.assertEqual(got["singles"], ["A", "B"])
        self.assertEqual(got["clusters"], [])

    def test_a_chain_groups_into_one_badge_with_its_bounds(self):
        got = self.cluster(
            '[{ "name": "A", "x": 0, "y": 0 }, { "name": "B", "x": 30, "y": 0 }, { "name": "C", "x": 60, "y": 0 }]',
            "1",
        )
        self.assertEqual(got["singles"], [])
        self.assertEqual(len(got["clusters"]), 1)
        c = got["clusters"][0]
        self.assertEqual(c["names"], ["A", "B", "C"])
        self.assertEqual([c["x0"], c["y0"], c["x1"], c["y1"]], [0, 0, 60, 0])


FAKE_BOX = r"""
function fakeBox(w, h) {
  const attrs = new Map();
  let lastHtml = "";
  const svgAttrs = {};
  const svg = {
    addEventListener() {},
    setAttribute(k, v) { svgAttrs[k] = String(v); },
    getBoundingClientRect: () => ({ width: w, height: h, left: 0, top: 0 }),
    _attrs: svgAttrs,
  };
  return {
    clientWidth: w, clientHeight: h,
    get innerHTML() { return lastHtml; },
    set innerHTML(v) { lastHtml = v; },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    setAttribute(k, v) { attrs.set(k, String(v)); },
    addEventListener() {},
    classList: { add() {}, remove() {} },
    querySelector(sel) {
      if (sel === "svg" && lastHtml.includes("<svg")) return svg;
      return null;
    },
    _svg: svg,
  };
}
function viewBoxOf(box) {
  if (box._svg._attrs.viewBox) return box._svg._attrs.viewBox.split(" ").map(Number);
  const m = /viewBox="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"/.exec(box.innerHTML);
  return m ? m.slice(1).map(Number) : null;
}
const NO_TARGET = { closest: () => null };
function labels(html) {
  const out = [];
  const re = /<text ([^>]*)>([^<]*)<\/text>/g;
  let m;
  while ((m = re.exec(html))) {
    const attrs = {};
    const are = /([\w-]+)="([^"]*)"/g;
    let a;
    while ((a = are.exec(m[1]))) attrs[a[1]] = a[2];
    out.push({ attrs, text: m[2] });
  }
  return out;
}
// The label box model the placement code works to: a label is fs tall-ish
// and about 0.56 * fs per character wide, anchored per its text-anchor.
function labelBox(l) {
  const fs = Number(l.attrs["font-size"]);
  const w = fs * 0.56 * l.text.length;
  const x = Number(l.attrs.x), y = Number(l.attrs.y);
  const anchor = l.attrs["text-anchor"] || "start";
  const x0 = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
  return [x0, y - fs * 1.05 * 0.8, x0 + w, y + fs * 1.05 * 0.25];
}
"""


class ZoneLabelStyle(unittest.TestCase):
    def test_zone_labels_are_not_italic(self):
        # Zone labels render between 12 and 13px, always under the 14px
        # line below which they must not be italic.
        css = app_file("views/now.css")
        rule = next(line for line in css.splitlines() if line.startswith(".wm-zl {"))
        self.assertNotIn("italic", rule)


@needs_node
class ClusterBadges(unittest.TestCase):
    DOTS = (
        '[{ "name": "Aaa", "x": 100, "y": 100, "color": "#fff", "family": true, "head": false },'
        ' { "name": "Bbb", "x": 110, "y": 100, "color": "#fff", "family": false, "head": false },'
        ' { "name": "Ccc", "x": 900, "y": 900, "color": "#fff", "family": true, "head": true }]'
    )

    def test_full_map_draws_one_badge_for_a_dense_group(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
const box = fakeBox(360, 360);
wm.draw(box, { key: "clu-full", shape, compact: false, focus: null, summary: "", dots: %s });
const html = box.innerHTML;
console.log(JSON.stringify({
  badges: (html.match(/data-cluster=/g) || []).length,
  badgeSays2: /data-cluster="0"[^>]*>[\s\S]*?<text[^>]*>2<\/text>/.test(html),
  cccLinked: html.includes('href="#/m/Ccc"'),
  aaaLinked: html.includes('href="#/m/Aaa"'),
}));
"""
            % self.DOTS,
        )
        self.assertEqual(got["badges"], 1)
        self.assertTrue(got["badgeSays2"])
        self.assertTrue(got["cccLinked"])
        self.assertFalse(got["aaaLinked"])

    def test_minimap_keeps_every_dot_individual(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Kalimdor", aspect: 1, coast: [], zones: [] };
const box = fakeBox(360, 360);
wm.draw(box, { key: "clu-mini", shape, compact: true, focus: [0, 0, 1000, 1000], summary: "", dots: %s });
const html = box.innerHTML;
console.log(JSON.stringify({
  badges: (html.match(/data-cluster=/g) || []).length,
  dots: (html.match(/wm-dot/g) || []).length,
}));
"""
            % self.DOTS,
        )
        self.assertEqual(got["badges"], 0)
        self.assertEqual(got["dots"], 3)

    def test_a_badge_still_zooms_after_an_unchanged_redraw(self):
        # A redraw with identical data skips the repaint, but draw()
        # rebinds the tap handler every call; the badge must still work.
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
const box = fakeBox(360, 360);
const opts = { key: "clu-redraw", shape, compact: false, focus: null, summary: "", dots: %s };
wm.draw(box, opts);
wm.draw(box, opts);
const badge = { getAttribute: (k) => (k === "data-cluster" ? "0" : null) };
box.onclick({ target: { closest: (sel) => (sel === "[data-cluster]" ? badge : null) } });
const m = /viewBox="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"/.exec(box.innerHTML);
console.log(JSON.stringify({ vb: m ? m.slice(1).map(Number) : null }));
"""
            % self.DOTS,
        )
        self.assertIsNotNone(got["vb"])
        self.assertLess(got["vb"][2], 1000)

    def test_tapping_a_badge_zooms_to_its_members(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
const box = fakeBox(360, 360);
wm.draw(box, { key: "clu-tap", shape, compact: false, focus: null, summary: "", dots: %s });
const badge = { getAttribute: (k) => (k === "data-cluster" ? "0" : null) };
box.onclick({ target: { closest: (sel) => (sel === "[data-cluster]" ? badge : null) } });
const m = /viewBox="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"/.exec(box.innerHTML);
console.log(JSON.stringify({ vb: m ? m.slice(1).map(Number) : null }));
"""
            % self.DOTS,
        )
        vb = got["vb"]
        self.assertIsNotNone(vb)
        self.assertLess(vb[2], 1000)
        # The zoomed view contains the two clustered members at (100..110, 100).
        self.assertLessEqual(vb[0], 100)
        self.assertLessEqual(vb[1], 100)
        self.assertGreaterEqual(vb[0] + vb[2], 110)
        self.assertGreaterEqual(vb[1] + vb[3], 100)


@needs_node
class PinchAndDoubleTap(unittest.TestCase):
    SETUP = r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
"""

    def test_pinch_zooms_toward_the_pinch_midpoint(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + self.SETUP
            + r"""
const box = fakeBox(1000, 1000);
wm.draw(box, { key: "pinch", shape, compact: false, focus: null, summary: "", dots: [] });
box.onpointerdown({ pointerId: 1, clientX: 400, clientY: 500, target: NO_TARGET });
box.onpointerdown({ pointerId: 2, clientX: 600, clientY: 500, target: NO_TARGET });
box.onpointermove({ pointerId: 2, clientX: 800, clientY: 500 });
const vb = viewBoxOf(box);
// Fingers spread from 200px apart to 400px: the view halves in width,
// and the map point under the moving midpoint (500, 500) stays under it.
console.log(JSON.stringify({ vb, underMid: vb ? [vb[0] + 600 * (vb[2] / 1000), vb[1] + 500 * (vb[2] / 1000)] : null }));
""",
        )
        self.assertEqual(got["vb"], [200, 250, 500, 500])
        self.assertEqual(got["underMid"], [500, 500])

    def test_pinch_at_phone_width_390(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + self.SETUP
            + r"""
const box = fakeBox(390, 390);
wm.draw(box, { key: "pinch390", shape, compact: false, focus: null, summary: "", dots: [] });
box.onpointerdown({ pointerId: 1, clientX: 150, clientY: 195, target: NO_TARGET });
box.onpointerdown({ pointerId: 2, clientX: 240, clientY: 195, target: NO_TARGET });
box.onpointermove({ pointerId: 2, clientX: 330, clientY: 195 });
const vb = viewBoxOf(box);
const round = (v) => Math.round(v * 10) / 10;
console.log(JSON.stringify({ vb: vb.map(round), underMid: [round(vb[0] + 240 * (vb[2] / 390)), round(vb[1] + 195 * (vb[2] / 390))] }));
""",
        )
        # Fingers spread 90px to 180px: the view halves, and the map
        # point under the moving midpoint stays under it.
        self.assertEqual(got["vb"], [192.3, 250, 500, 500])
        self.assertEqual(got["underMid"], [500, 500])

    def test_double_tap_zooms_toward_the_tap_point(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + self.SETUP
            + r"""
const box = fakeBox(1000, 1000);
wm.draw(box, { key: "dbltap", shape, compact: false, focus: null, summary: "", dots: [] });
const tap = () => {
  box.onpointerdown({ pointerId: 1, clientX: 250, clientY: 250, target: NO_TARGET });
  box.onpointerup({ pointerId: 1, clientX: 250, clientY: 250, type: "pointerup", target: NO_TARGET });
};
tap();
const afterOne = viewBoxOf(box);
tap();
const afterTwo = viewBoxOf(box);
console.log(JSON.stringify({ afterOne, afterTwo }));
""",
        )
        self.assertEqual(got["afterOne"], [0, 0, 1000, 1000])
        self.assertEqual(got["afterTwo"], [125, 125, 500, 500])

    def test_one_pointer_drag_still_pans(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + self.SETUP
            + r"""
const box = fakeBox(1000, 1000);
wm.draw(box, { key: "pan", shape, compact: false, focus: [200, 200, 500, 500], summary: "", dots: [] });
box.onpointerdown({ pointerId: 1, clientX: 500, clientY: 500, target: NO_TARGET });
box.onpointermove({ pointerId: 1, clientX: 400, clientY: 500 });
box.onpointerup({ pointerId: 1, clientX: 400, clientY: 500, type: "pointerup", target: NO_TARGET });
console.log(JSON.stringify({ vb: viewBoxOf(box) }));
""",
        )
        self.assertEqual(got["vb"], [250, 200, 500, 500])


@needs_node
class ZoneTapPins(unittest.TestCase):
    def test_a_tapped_zone_stays_after_the_pointer_leaves(self):
        got = run_node(
            WM_FILES,
            r"""
const wm = await import("./views/now/worldmap.js");
const listeners = {};
const line = { textContent: "" };
const svg = {
  addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
  setAttribute() {},
  getBoundingClientRect: () => ({ width: 1000, height: 1000, left: 0, top: 0 }),
};
const attrs = new Map();
let lastHtml = "";
const box = {
  clientWidth: 1000, clientHeight: 1000,
  get innerHTML() { return lastHtml; },
  set innerHTML(v) { lastHtml = v; },
  getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
  setAttribute(k, v) { attrs.set(k, String(v)); },
  addEventListener() {},
  classList: { add() {}, remove() {} },
  querySelector(sel) {
    if (sel === "svg" && lastHtml.includes("<svg")) return svg;
    if (sel === "[data-hover]") return line;
    return null;
  },
};
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
wm.draw(box, { key: "pin", shape, compact: false, focus: null, summary: "the summary",
  dots: [], whoIn: (z) => z + ": Aaa, Bbb" });
const fire = (t, e) => (listeners[t] || []).forEach((fn) => fn(e));
const zoneTarget = { closest: (sel) => (sel === "[data-zone]" ? { getAttribute: () => "BurningSteppes" } : null) };
const bareTarget = { closest: () => null };
const seen = [];
fire("pointerover", { target: zoneTarget });
seen.push(line.textContent);
fire("pointerleave", {});
seen.push(line.textContent);
fire("click", { target: zoneTarget });
fire("pointerleave", {});
seen.push(line.textContent);
fire("click", { target: bareTarget });
seen.push(line.textContent);
console.log(JSON.stringify(seen));
""",
        )
        self.assertEqual(
            got,
            [
                "BurningSteppes: Aaa, Bbb",
                "the summary",
                "BurningSteppes: Aaa, Bbb",
                "the summary",
            ],
        )


@needs_node
class SetView(unittest.TestCase):
    def test_set_view_points_the_next_draw_at_a_new_box(self):
        got = run_node(
            WM_FILES,
            FAKE_BOX
            + r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
const box = fakeBox(1000, 1000);
const opts = { key: "sv", shape, compact: false, focus: null, summary: "", dots: [] };
wm.draw(box, opts);
const before = viewBoxOf(box);
wm.setView("sv", shape, [100, 100, 400, 400]);
wm.draw(box, opts);
console.log(JSON.stringify({ before, after: viewBoxOf(box) }));
""",
        )
        self.assertEqual(got["before"], [0, 0, 1000, 1000])
        self.assertEqual(got["after"], [100, 100, 400, 400])


MAP_FIXTURE = r"""
globalThis.window = {
  addEventListener() {},
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  dispatchEvent(e) { (globalThis.__events = globalThis.__events || []).push(e.type); },
};
globalThis.document = { addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
const mapView = (await import("./app/views/map.js")).default;
const fams = await import("./app/families.js");
fams.learn({
  families: [
    { key: "Grug", names: ["Grug", "Ugga", "Fally"] },
    { key: "Zug", names: ["Zug"] },
  ],
  guilds: [],
});
const shape = {
  name: "Eastern Kingdoms", aspect: 1, coast: [],
  zones: [
    { name: "StormwindCity", label: "Stormwind City", d: "M0 0 L5 5 Z", cx: 100, cy: 100, room: 40 },
    { name: "SearingGorge", label: "Searing Gorge", d: "M0 0 L5 5 Z", cx: 500, cy: 500, room: 40 },
  ],
};
const sg = Array.from({ length: 10 }, (_, i) => ({
  name: "SG" + String(i + 1).padStart(2, "0"), continent: "0", u: 0.5, v: 0.5, zone: "SearingGorge", instance: false,
}));
const mapData = {
  unplaced: 3,
  dots: [
    { name: "Grug", continent: "0", u: 0.1, v: 0.1, zone: "StormwindCity", instance: false },
    { name: "Ugga", continent: "0", u: 0.11, v: 0.1, zone: "StormwindCity", instance: false },
    { name: "Insto", continent: "0", u: 0.6, v: 0.6, zone: "BlackrockDepths", instance: true },
    { name: "Offy", continent: "quelthalas", u: 0.5, v: 0.5, zone: "Outland", instance: false },
    ...sg,
  ],
};
const wallData = {
  members: [
    { name: "Grug", family: "Grug", class: "warrior", class_colour: "#c79c6e", leader: true },
    { name: "Ugga", family: "Grug", class: "priest", class_colour: "#fff" },
    { name: "Fally", family: "Grug", class: "mage", class_colour: "#69c", present: true, zone: "StormwindCity" },
    { name: "Zug", family: "Zug", class: "warrior", class_colour: "#c79c6e", leader: true },
  ],
};
const gearData = {
  guilds: [{ name: "Cave", members: [
    { name: "Insto", class: "rogue" }, { name: "Offy", class: "mage" },
    ...sg.map((d) => ({ name: d.name, class: "warrior" })),
  ] }],
};
const reads = {
  "/shapes.json": { data: { "0": shape, "1": shape }, at: 1 },
  "/api/map": { data: mapData, at: 1 },
  "/api/wall": { data: wallData, at: 1 },
  "/api/guildgear": { data: gearData, at: 1 },
  "/api/v2/roster": { data: { members: [] }, at: 1 },
  "/api/spectate": { data: null, at: 0 },
  "/api/v2/operator": { data: { enabled: false }, at: 1 },
};
const ctx = { params: { continent: "ek" }, get: (p) => reads[p] || { data: null, at: 0 } };
"""


@needs_node
class MapPage(unittest.TestCase):
    def test_chips_counts_offmap_and_where_cap(self):
        got = run_app_node(
            MAP_FIXTURE
            + r"""
const html = mapView.render(ctx).s.replace(/&#39;/g, "'");
const where = html.slice(html.indexOf('class="where"'));
console.log(JSON.stringify({
  grugChip: html.includes('data-fam="Grug"') && html.includes("Stormwind City") && html.includes("3 here"),
  zugChip: html.includes('data-fam="Zug"') && html.includes("not placed") && html.includes("disabled"),
  counts: html.includes("12 placed") && html.includes("1 in an instance") && html.includes("1 position not read"),
  offMap: html.includes("Offy") && html.includes("Quel'Thalas"),
  unplaced: html.includes("3 characters in the world could not be placed"),
  hint: html.includes("Pinch or use the buttons to zoom"),
  oldProse: html.includes("scroll or use the buttons"),
  whereCount: where.includes("10 here"),
  shownNames: ["SG01", "SG02", "SG03", "SG04", "SG05", "SG06", "SG07", "SG08"].every((n) => where.includes(n)),
  cappedNames: !where.includes("SG09") && !where.includes("SG10"),
  showAll: where.includes("Show all 10"),
  spectateInWhere: where.includes("sp-mini"),
}));
"""
        )
        for key, want in [
            ("grugChip", True),
            ("zugChip", True),
            ("counts", True),
            ("offMap", True),
            ("unplaced", True),
            ("hint", True),
            ("oldProse", False),
            ("whereCount", True),
            ("shownNames", True),
            ("cappedNames", True),
            ("showAll", True),
            ("spectateInWhere", False),
        ]:
            self.assertEqual(got[key], want, key)

    def test_show_all_opens_the_whole_zone_card(self):
        got = run_app_node(
            MAP_FIXTURE
            + r"""
mapView.render(ctx);
let clicked = null;
const btn = { getAttribute: (k) => (k === "data-showall" ? "Searing Gorge" : null), addEventListener: (t, fn) => { clicked = fn; } };
const main = {
  querySelector: () => null,
  querySelectorAll: (sel) => (sel === "[data-showall]" ? [btn] : []),
};
mapView.after(main, ctx);
clicked();
const html = mapView.render(ctx).s;
const where = html.slice(html.indexOf('class="where"'));
console.log(JSON.stringify({
  allShown: where.includes("SG09") && where.includes("SG10"),
  redraws: (globalThis.__events || []).filter((t) => t === "overseer:redraw").length,
}));
"""
        )
        self.assertTrue(got["allShown"])
        self.assertGreaterEqual(got["redraws"], 1)


@needs_node
class LabelPlacement(unittest.TestCase):
    def draw(self, script):
        return run_node(WM_FILES, FAKE_BOX + script)

    def test_member_label_flips_to_end_anchored_at_the_right_edge(self):
        got = self.draw(
            r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
const box = fakeBox(1000, 1000);
wm.draw(box, { key: "lbl-flip", shape, compact: false, focus: null, summary: "",
  dots: [{ name: "Longname", x: 990, y: 500, color: "#fff", family: true, head: true }] });
const ls = labels(box.innerHTML).filter((l) => l.text.startsWith("Longname"));
console.log(JSON.stringify({ found: ls.length, anchor: ls.length ? (ls[0].attrs["text-anchor"] || "start") : null,
  box: ls.length ? labelBox(ls[0]) : null }));
"""
        )
        self.assertEqual(got["found"], 1)
        self.assertEqual(got["anchor"], "end")
        self.assertGreaterEqual(got["box"][0], 0)
        self.assertLessEqual(got["box"][2], 1000)

    def test_member_label_drops_when_neither_side_fits(self):
        got = self.draw(
            r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [] };
const box = fakeBox(120, 120);
wm.draw(box, { key: "lbl-drop", shape, compact: false, focus: [400, 400, 120, 120], summary: "",
  dots: [{ name: "Averyverylongnameindeed", x: 460, y: 460, color: "#fff", family: true, head: true }] });
const ls = labels(box.innerHTML).filter((l) => l.text.startsWith("Averyverylongnameindeed"));
console.log(JSON.stringify({ found: ls.length, hasDot: box.innerHTML.includes("wm-dot") }));
"""
        )
        self.assertEqual(got["found"], 0)
        self.assertTrue(got["hasDot"])

    def test_zone_label_shifts_inside_the_right_edge(self):
        got = self.draw(
            r"""
const wm = await import("./views/now/worldmap.js");
const zone = { name: "Edgezone", label: "Edgezone", d: "M0 0 L5 5 Z", cx: 985, cy: 500, room: 40 };
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [zone] };
const box = fakeBox(1000, 1000);
wm.draw(box, { key: "lbl-zone-shift", shape, compact: false, focus: null, summary: "", dots: [] });
const ls = labels(box.innerHTML).filter((l) => l.text === "Edgezone");
console.log(JSON.stringify({ found: ls.length, box: ls.length ? labelBox(ls[0]) : null }));
"""
        )
        self.assertEqual(got["found"], 1)
        self.assertGreaterEqual(got["box"][0], 0)
        self.assertLessEqual(got["box"][2], 1000)

    def test_zone_label_drops_when_wider_than_the_view(self):
        got = self.draw(
            r"""
const wm = await import("./views/now/worldmap.js");
const zone = { name: "Wide", label: "Averyverylongzonename", d: "M0 0 L5 5 Z", cx: 60, cy: 500, room: 40 };
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [zone] };
const box = fakeBox(120, 1000);
wm.draw(box, { key: "lbl-zone-drop", shape, compact: false, focus: [0, 0, 120, 1000], summary: "", dots: [] });
const ls = labels(box.innerHTML).filter((l) => l.text === "Averyverylongzonename");
console.log(JSON.stringify({ found: ls.length }));
"""
        )
        self.assertEqual(got["found"], 0)

    def test_zone_labels_have_a_12px_floor(self):
        got = self.draw(
            r"""
const wm = await import("./views/now/worldmap.js");
const zone = { name: "Small", label: "Small", d: "M0 0 L5 5 Z", cx: 500, cy: 500, room: 20 };
const shape = { name: "Eastern Kingdoms", aspect: 1, coast: [], zones: [zone] };
const box = fakeBox(1000, 1000);
wm.draw(box, { key: "lbl-floor", shape, compact: false, focus: null, summary: "", dots: [] });
const ls = labels(box.innerHTML).filter((l) => l.text === "Small");
console.log(JSON.stringify({ found: ls.length, fs: ls.length ? Number(ls[0].attrs["font-size"]) : null }));
"""
        )
        self.assertEqual(got["found"], 1)
        self.assertGreaterEqual(got["fs"], 12)

    def test_minimap_member_label_is_not_clipped_either(self):
        got = self.draw(
            r"""
const wm = await import("./views/now/worldmap.js");
const shape = { name: "Kalimdor", aspect: 0.7, coast: [], zones: [] };
const box = fakeBox(320, 220);
wm.draw(box, { key: "lbl-mini", shape, compact: true, focus: [0, 0, 420, 294], summary: "",
  dots: [{ name: "Edge", x: 415, y: 100, color: "#fff", family: true, head: true }] });
const ls = labels(box.innerHTML).filter((l) => l.text.startsWith("Edge"));
console.log(JSON.stringify({ found: ls.length, anchor: ls.length ? (ls[0].attrs["text-anchor"] || "start") : null,
  box: ls.length ? labelBox(ls[0]) : null }));
"""
        )
        self.assertEqual(got["found"], 1)
        self.assertEqual(got["anchor"], "end")
        self.assertLessEqual(got["box"][2], 420)


if __name__ == "__main__":
    unittest.main()
