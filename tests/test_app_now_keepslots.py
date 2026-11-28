"""Now's wall: a redraw does not take a playing picture out of the page.

The Now view is rendered under node at a wide width into a small fake DOM
(the harness of test_app_now_stage.py, with a DOM that parses markup), and
drawn twice the way main.js draws: the view's own swap if it has one, the
plain body swap otherwise, then the view's after(). The fake DOM writes down
every <video> that leaves the document, which is what a browser interrupts.
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
needs_node = unittest.skipIf(NODE is None, "node is needed to run the app's modules")

# A DOM just large enough for Now: elements, text, attributes, the simple
# selectors the view uses, and markup parsing for innerHTML and <template>.
DOM = r"""
const VOID = new Set(["br", "img", "input", "hr", "meta", "link"]);
const removedVideos = [];
let root = null;

function unesc(s) {
  return s.replace(/&(amp|lt|gt|quot|#39|#x27);/g, (m, k) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", "#x27": "'" })[k]);
}

function matcher(selector) {
  const alts = selector.split(",").map((s) => s.trim());
  // "a b": the last part matches the node, the ones before it an ancestor each.
  const one = (sel) => {
    const parts = sel.split(/\s+/).map(compound);
    return (n) => {
      if (!parts[parts.length - 1](n)) return false;
      let up = n.parentNode;
      for (let i = parts.length - 2; i >= 0; i--) {
        while (up && !(up.isElement && parts[i](up))) up = up.parentNode;
        if (!up) return false;
        up = up.parentNode;
      }
      return true;
    };
  };
  const compound = (sel) => {
    const tests = [];
    let rest = sel;
    const take = (re, fn) => {
      const m = re.exec(rest);
      if (!m) return false;
      rest = rest.slice(m[0].length);
      tests.push(fn(m));
      return true;
    };
    while (rest) {
      const ok =
        take(/^[a-zA-Z][a-zA-Z0-9-]*/, (m) => (n) => n.nodeName === m[0].toUpperCase()) ||
        take(/^\.([a-zA-Z0-9_-]+)/, (m) => (n) => n.className.split(/\s+/).includes(m[1])) ||
        take(/^#([a-zA-Z0-9_-]+)/, (m) => (n) => n.getAttribute("id") === m[1]) ||
        take(/^\[([a-zA-Z0-9_-]+)="([^"]*)"\]/, (m) => (n) => n.getAttribute(m[1]) === m[2]) ||
        take(/^\[([a-zA-Z0-9_-]+)\]/, (m) => (n) => n.hasAttribute(m[1])) ||
        take(/^:not\(([^)]+)\)/, (m) => { const inner = matcher(m[1]); return (n) => !inner(n); });
      if (!ok) throw new Error("fake DOM: selector not supported: " + selector);
    }
    return (n) => tests.every((t) => t(n));
  };
  const fns = alts.map(one);
  return (n) => fns.some((f) => f(n));
}

class N {
  constructor(name) {
    this.nodeName = name.startsWith("#") ? name : name.toUpperCase();
    this.tagName = this.nodeName;
    this.attrs = new Map();
    this.childNodes = [];
    this.parentNode = null;
    this.listeners = {};
    this.style = {};
    this.data = "";
    this.hidden = false;
    this.paused = true;
    this.srcObject = null;
    if (this.nodeName === "TEMPLATE") this.content = new N("#fragment");
    const self = this;
    this.dataset = new Proxy({}, {
      get: (t, k) => { const v = self.attrs.get("data-" + String(k)); return v === undefined ? undefined : v; },
      set: (t, k, v) => { self.attrs.set("data-" + String(k), String(v)); return true; },
      deleteProperty: (t, k) => { self.attrs.delete("data-" + String(k)); return true; },
    });
    this.classList = {
      contains: (c) => self.className.split(/\s+/).includes(c),
      toggle: (c, on) => {
        const have = self.className.split(/\s+/).filter(Boolean).filter((x) => x !== c);
        if (on) have.push(c);
        self.className = have.join(" ");
      },
    };
  }
  get isElement() { return !this.nodeName.startsWith("#"); }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === root; }
  get parentElement() { return this.parentNode && this.parentNode.isElement ? this.parentNode : null; }
  get children() { return this.childNodes.filter((c) => c.isElement); }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get className() { return this.attrs.get("class") || ""; }
  set className(v) { this.attrs.set("class", String(v)); }
  get id() { return this.attrs.get("id") || ""; }
  set id(v) { this.attrs.set("id", String(v)); }
  setAttribute(k, v) { this.attrs.set(k, String(v)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  hasAttribute(k) { return this.attrs.has(k); }
  removeAttribute(k) { this.attrs.delete(k); }
  getAttributeNames() { return Array.from(this.attrs.keys()); }
  toggleAttribute(k, on) { if (on) this.attrs.set(k, ""); else this.attrs.delete(k); }
  walk(out = []) { this.childNodes.forEach((c) => { out.push(c); c.walk(out); }); return out; }
  contains(n) { return n === this || this.walk().includes(n); }
  detach() {
    const p = this.parentNode;
    if (!p) return;
    if (this.isConnected) [this, ...this.walk()].filter((n) => n.nodeName === "VIDEO").forEach((v) => removedVideos.push(v));
    p.childNodes.splice(p.childNodes.indexOf(this), 1);
    this.parentNode = null;
  }
  insertBefore(node, ref) {
    node.detach();
    const at = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
    if (at < 0) throw new Error("fake DOM: insertBefore a node that is not a child");
    this.childNodes.splice(at, 0, node);
    node.parentNode = this;
    return node;
  }
  appendChild(node) { return this.insertBefore(node, null); }
  append(...nodes) { nodes.forEach((n) => this.appendChild(n)); }
  removeChild(node) { if (node.parentNode !== this) throw new Error("fake DOM: removeChild of a node that is not a child"); node.detach(); return node; }
  remove() { this.detach(); }
  replaceChildren() { Array.from(this.childNodes).forEach((c) => c.detach()); }
  get textContent() { return this.nodeName === "#text" ? this.data : this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) {
    this.replaceChildren();
    if (String(v) === "") return;
    const t = new N("#text");
    t.data = String(v);
    this.appendChild(t);
  }
  querySelectorAll(sel) { const m = matcher(sel); return this.walk().filter((n) => n.isElement && m(n)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener() {}
  fire(type) { (this.listeners[type] || []).forEach((fn) => fn({ target: this, preventDefault() {} })); }
  focus() {}
  play() { return Promise.resolve(); }
  set innerHTML(markup) {
    const into = this.content || this;
    into.replaceChildren();
    const stack = [into];
    const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][a-zA-Z0-9-]*)\s*>|<([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>|[^<]+/g;
    let m;
    let end = 0;
    while ((m = re.exec(String(markup)))) {
      if (m.index !== end) throw new Error("fake DOM: cannot parse markup at " + end);
      end = re.lastIndex;
      const top = stack[stack.length - 1];
      if (m[1]) {
        if (top.nodeName !== m[1].toUpperCase()) throw new Error("fake DOM: </" + m[1] + "> closes " + top.nodeName);
        stack.pop();
      } else if (m[2]) {
        const el = new N(m[2]);
        const attr = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
        let a;
        while ((a = attr.exec(m[3] || ""))) el.attrs.set(a[1], unesc(a[2] ?? a[3] ?? a[4] ?? ""));
        top.appendChild(el);
        if (!VOID.has(m[2].toLowerCase())) stack.push(el);
      } else if (!m[0].startsWith("<!--")) {
        const t = new N("#text");
        t.data = unesc(m[0]);
        top.appendChild(t);
      }
    }
    if (end !== String(markup).length || stack.length !== 1) throw new Error("fake DOM: markup left open");
  }
}

// The tree as text, without what streams.js put in the slots: what the
// markup alone drew.
function drawn(node) {
  if (node.nodeName === "#text") return JSON.stringify(node.data);
  const attrs = Array.from(node.attrs.entries()).sort().map(([k, v]) => " " + k + "=" + JSON.stringify(v)).join("");
  const kids = node.childNodes.filter((c) => !(c.isElement && c.classList.contains("st-pic")));
  return "<" + node.nodeName + attrs + ">" + kids.map(drawn).join("") + "</" + node.nodeName + ">";
}

root = new N("html");
const body = root.appendChild(new N("body"));
const main = body.appendChild(new N("main"));
const noop = () => {};
globalThis.window = globalThis;
globalThis.addEventListener = noop;
globalThis.setInterval = () => 0;
globalThis.CSS = { escape: (s) => String(s) };
globalThis.location = { hash: "#/now", protocol: "https:" };
globalThis.document = {
  body, documentElement: root, head: new N("head"), hidden: false, activeElement: null, fullscreenElement: null,
  addEventListener: noop, removeEventListener: noop,
  createElement: (tag) => new N(tag),
  getElementById: (id) => root.walk().find((n) => n.isElement && n.id === id) || null,
  querySelector: (sel) => root.querySelector(sel),
  querySelectorAll: (sel) => root.querySelectorAll(sel),
};
"""

# The Now view over that DOM, three families streamed, drawn as main.js draws.
PAGE = r"""
const fx = { narrow: false };
globalThis.matchMedia = () => ({ matches: fx.narrow, addEventListener: noop });
globalThis.localStorage = { getItem: () => null, setItem: noop };

// Every WHEP connection opened and not yet closed.
const open = new Set();
globalThis.RTCPeerConnection = class {
  constructor() { open.add(this); this.iceGatheringState = "complete"; this.localDescription = { sdp: "" }; }
  addTransceiver() {}
  async createOffer() { return {}; }
  async setLocalDescription() {}
  async setRemoteDescription() {}
  close() { open.delete(this); }
};
globalThis.fetch = async () => ({ status: 201, headers: { get: () => null }, text: async () => "" });

const FAMS = ["Grug", "Zug", "Mok"];
const { learn } = await import("./app/families.js");
learn({ families: FAMS.map((key) => ({ key })), guilds: [] });
const now = (await import("./app/views/now.js")).default;
const streams = await import("./app/views/now/streams.js");
const keep = await import("./app/views/now/keepslots.js").catch(() => null);

// A wall read: `fams` are on the wall, `ended` are on it with no stream.
function wallRead(fams = FAMS, ended = []) {
  return {
    data: {
      members: fams.map((f) => ({ name: f + "ling", family: f, class: "mage" })),
      wall: { tiles: fams.map((f) => ({ name: f + "ling", url: ended.includes(f) ? "" : "https://stream.example/" + f })) },
    },
    at: 1, error: null,
  };
}

function ctx(headline, wall = wallRead()) {
  const agenda = (fam) => ({ data: { family: fam, headline: fam + " " + headline, stalled: false, moved_seconds: 5 }, at: 1, error: null });
  const get = (path) => {
    if (path === "/api/wall") return wall;
    const fam = FAMS.find((f) => path === "/api/agenda?family=" + f);
    return fam ? agenda(fam) : {};
  };
  return { get, isPhone: fx.narrow, previousVisit: 0, params: {}, query: {} };
}

// main.js's draw(), without the shell around it.
async function draw(c) {
  const markup = String(now.render(c).s);
  if (!(now.swap && now.swap(main, markup))) main.innerHTML = markup;
  now.after(main, c);
  await new Promise((r) => setTimeout(r, 0));
  return markup;
}

const videos = () => main.querySelectorAll("video");
const slot = (name) => main.querySelector('[data-stream="' + name + '"]');
const plain = (markup) => { const t = new N("main"); t.innerHTML = markup; return drawn(t); };
"""


def run(body, page=True):
    script = (
        DOM
        + (PAGE if page else "")
        + "\nconsole.log(JSON.stringify(await (async () => {\n"
        + body
        + "\n})()));\nprocess.exit(0);\n"
    )
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
        raise AssertionError(out.stderr or out.stdout)
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
class AWideRedrawLeavesThePicturesInThePage(unittest.TestCase):
    def test_a_changed_body_removes_no_mounted_video_from_the_document(self):
        got = run(
            """
            const first = await draw(ctx("clears Ragefire"));
            const before = videos();
            removedVideos.length = 0;
            const second = await draw(ctx("walks to Deadmines"));
            const after = videos();
            return {
              changed: first !== second,
              mounted: before.length,
              removed: removedVideos.length,
              same: after.length === before.length && after.every((v, i) => v === before[i]),
              connected: before.every((v) => v.isConnected),
              inSlot: before.every((v) => v.parentNode.parentNode.hasAttribute("data-stream")),
            };
            """
        )
        self.assertTrue(got["changed"], "the second body must differ from the first")
        self.assertEqual(got["mounted"], 3)
        self.assertEqual(got["removed"], 0)
        self.assertTrue(got["same"])
        self.assertTrue(got["connected"])
        self.assertTrue(got["inSlot"])

    def test_the_page_after_the_redraw_is_the_new_body(self):
        got = run(
            """
            await draw(ctx("clears Ragefire"));
            const next = ctx("walks to Deadmines");
            const second = String(now.render(next).s);
            const handled = now.swap(main, second);
            // Read before after() fills in what the markup does not say.
            const asDrawn = drawn(main) === plain(second);
            now.after(main, next);
            const text = main.textContent;
            return {
              handled, asDrawn,
              fresh: text.includes("Grug walks to Deadmines"),
              stale: text.includes("clears Ragefire"),
            };
            """
        )
        self.assertTrue(got["handled"])
        self.assertTrue(got["asDrawn"])
        self.assertTrue(got["fresh"])
        self.assertFalse(got["stale"])

    def test_hear_works_on_a_picture_kept_across_a_redraw(self):
        # The featured family's tile carries Hear (the rail thumbs do not),
        # and Grug is featured here: nothing is staged, so the first
        # streamed family is.
        got = run(
            """
            await draw(ctx("clears Ragefire"));
            const video = slot("Grugling").querySelector("video");
            await draw(ctx("walks to Deadmines"));
            const hear = main.querySelector('[data-hear="Grugling"]');
            hear.fire("click");
            return {
              kept: slot("Grugling").querySelector("video") === video,
              muted: video.muted,
              pressed: hear.getAttribute("aria-pressed"),
              others: videos().filter((v) => v !== video).every((v) => v.muted === true),
            };
            """
        )
        self.assertTrue(got["kept"])
        self.assertFalse(got["muted"])
        self.assertEqual(got["pressed"], "true")
        self.assertTrue(got["others"])

    def test_the_shell_asks_the_view_before_the_plain_swap(self):
        source = (APP / "main.js").read_text(encoding="utf-8")
        self.assertIn(
            "if (!(module.swap && module.swap(main, body))) main.innerHTML = body;",
            source,
        )
        self.assertEqual(source.count("main.innerHTML = body"), 1)


@needs_node
class APictureWithNoSlotIsLetGo(unittest.TestCase):
    def test_a_stream_that_ends_drops_its_connection_and_reads_off(self):
        got = run(
            """
            await draw(ctx("clears Ragefire"));
            const was = open.size;
            await draw(ctx("clears Ragefire", wallRead(FAMS, ["Zug"])));
            return {
              was, open: open.size,
              state: streams.stateOf("Zugling"),
              source: slot("Zugling").querySelector("video").srcObject,
              others: [streams.stateOf("Grugling"), streams.stateOf("Mokling")],
            };
            """
        )
        self.assertEqual(got["was"], 3)
        self.assertEqual(got["open"], 2)
        self.assertEqual(got["state"], "off")
        self.assertIsNone(got["source"])
        self.assertEqual(got["others"], ["connecting", "connecting"])

    def test_a_family_that_leaves_the_wall_has_its_slot_and_connection_released(self):
        got = run(
            """
            await draw(ctx("clears Ragefire"));
            const gone = slot("Mokling").querySelector("video");
            const stay = [slot("Grugling"), slot("Zugling")].map((s) => s.querySelector("video"));
            removedVideos.length = 0;
            await draw(ctx("clears Ragefire", wallRead(["Grug", "Zug"])));
            return {
              open: open.size,
              held: streams.held(),
              slot: slot("Mokling") === null,
              goneConnected: gone.isConnected,
              removedOnlyTheGone: removedVideos.every((v) => v === gone),
              stayed: stay.every((v) => v.isConnected) && videos().length === 2,
            };
            """
        )
        self.assertEqual(got["open"], 2)
        self.assertEqual(got["held"], ["Grugling", "Zugling"])
        self.assertTrue(got["slot"])
        self.assertFalse(got["goneConnected"])
        self.assertTrue(got["removedOnlyTheGone"])
        self.assertTrue(got["stayed"])

    def test_no_picture_is_left_behind_as_families_come_and_go(self):
        got = run(
            """
            for (let i = 0; i < 5; i++) {
              await draw(ctx("pass " + i, wallRead(FAMS)));
              await draw(ctx("pass " + i, wallRead(["Grug"])));
            }
            await draw(ctx("last", wallRead([])));
            return { open: open.size, held: streams.held(), videos: document.querySelectorAll("video").length };
            """
        )
        self.assertEqual(got, {"open": 0, "held": [], "videos": 0})

    def test_a_wall_read_that_fails_releases_nothing(self):
        got = run(
            """
            await draw(ctx("clears Ragefire"));
            await draw(ctx("clears Ragefire", { error: "the read failed" }));
            return { open: open.size, held: streams.held() };
            """
        )
        self.assertEqual(got["open"], 3)
        self.assertEqual(got["held"], ["Grugling", "Zugling", "Mokling"])

    def test_a_phone_keeps_its_one_staged_stream_through_a_redraw(self):
        got = run(
            """
            fx.narrow = true;
            await draw(ctx("clears Ragefire"));
            const was = [...open];
            await draw(ctx("walks to Deadmines"));
            return {
              slots: main.querySelectorAll("[data-stream]").length,
              held: streams.held(),
              same: open.size === 1 && [...open][0] === was[0],
            };
            """
        )
        self.assertEqual(got, {"slots": 0, "held": ["Grugling"], "same": True})


@needs_node
class APhoneRedrawnTenTimesShowsEachSectionOnce(unittest.TestCase):
    """#3030: ten draws on a phone, the reads changing between them the way
    the 5s quick and 30s full reads land. After each draw every section is
    counted once and the whole page must equal what that body alone draws."""

    def test_each_section_and_card_is_drawn_once_per_draw(self):
        got = run(
            """
            fx.narrow = true;
            const sp = (target) => ({ data: { active: true, state: "arrived", arrived: true, character: "Flintt", target, run: 0, stream: "https://s.example/w" }, at: 1, error: null });
            const live = (n) => ({ data: { dungeons: Array.from({ length: n }, (_, i) => ({ kind: "dungeon", title: "Cave " + i, place: "Cave " + i, progress: i + " of 8 bosses down", seats: [], order: { run: i + 1 } })) }, at: 1, error: null });
            const reads = (i) => {
              const c = ctx("pass " + i);
              const get = c.get;
              c.get = (p) => {
                if (p === "/api/spectate") return sp(i % 2 ? "Flintt" : "Dire Maul");
                if (p === "/api/live") return i % 4 === 1 ? {} : live(1 + (i % 3));
                if (p === "/api/eye") return { data: { tiers: [{ tier: "REALM", state: i % 2 ? "ON" : "OFF" }], strip: [{ label: "IN WORLD", value: String(20 + i) }] }, at: 1, error: null };
                return get(p);
              };
              return c;
            };
            const n = (sel) => main.querySelectorAll(sel).length;
            const out = [];
            const pages = [];
            for (let i = 0; i < 10; i++) {
              const markup = await draw(reads(i));
              out.push({
                head: n(".now-head"), watcher: n('[aria-label="Watcher"]'), card: n(".sp-stage"),
                live: n(".sp-live"), rows: n(".sp-live-group"), rowsWanted: i % 4 === 1 ? 0 : 1 + (i % 3),
                fams: n(".fams"), units: n(".fam"), slots: n("[data-stream]"),
              });
              pages.push(drawn(main));
            }
            // What each body alone draws, the same steps on an empty page.
            // The page after draw i must equal it, whatever the draws before
            // it left behind.
            for (let i = 0; i < 10; i++) {
              main.innerHTML = "";
              await draw(reads(i));
              out[i].asDrawn = drawn(main) === pages[i];
            }
            return out;
            """
        )
        self.assertEqual(len(got), 10)
        for i, c in enumerate(got):
            self.assertEqual(
                c,
                {
                    "head": 1,
                    "watcher": 1,
                    "card": 1,
                    "live": 1,
                    "rows": c["rowsWanted"],
                    "rowsWanted": c["rowsWanted"],
                    "fams": 1,
                    "units": 3,
                    "slots": 0,
                    "asDrawn": True,
                },
                "draw %d" % i,
            )


# keepslots.js on its own: small bodies, each slot holding a <video>.
SWAP = r"""
const keep = await import("./app/views/now/keepslots.js");
const unit = (name, extra = "") => '<div class="fam" data-family="' + name + '"' + extra + '><p>' + name + ' card</p><figure><div class="st-slot" data-stream="' + name + '"></div><figcaption>cap</figcaption></figure></div>';
const page = (names, lead = "") => lead + '<section><h2>Families</h2><div class="families">' + names.map((n) => unit(n)).join("") + "</div></section><footer>foot</footer>";
function fill() {
  return main.querySelectorAll("[data-stream]").map((s) => {
    const pic = new N("div");
    pic.className = "st-pic";
    const v = pic.appendChild(new N("video"));
    s.appendChild(pic);
    return v;
  });
}
const plain = (markup) => { const t = new N("main"); t.innerHTML = markup; return drawn(t); };
"""


@needs_node
class TheSwapKeepsSlotsInPlace(unittest.TestCase):
    def swap(self, body):
        return run(SWAP + body, page=False)

    def test_content_around_the_slots_is_replaced_and_the_slots_stay(self):
        got = self.swap(
            """
            main.innerHTML = page(["a", "b"]);
            const vids = fill();
            const next = page(["a", "b"], '<div class="banner">stale</div>').replace("a card", "a moved");
            const handled = keep.swapKeeping(main, next);
            return { handled, removed: removedVideos.length, asDrawn: drawn(main) === plain(next), connected: vids.every((v) => v.isConnected) };
            """
        )
        self.assertEqual(
            got, {"handled": True, "removed": 0, "asDrawn": True, "connected": True}
        )

    def test_a_kept_element_takes_the_new_bodys_attributes(self):
        got = self.swap(
            """
            main.innerHTML = page(["a"]).replace('class="families"', 'class="families" data-wall="side" data-old="1"');
            fill();
            const next = page(["a"]).replace('class="families"', 'class="families" data-wall="stacked"');
            keep.swapKeeping(main, next);
            const el = main.querySelector(".families");
            return { removed: removedVideos.length, wall: el.getAttribute("data-wall"), old: el.hasAttribute("data-old") };
            """
        )
        self.assertEqual(got, {"removed": 0, "wall": "stacked", "old": False})

    def test_a_slot_the_new_body_lacks_goes_with_its_unit(self):
        got = self.swap(
            """
            main.innerHTML = page(["a", "b", "c"]);
            const vids = fill();
            const next = page(["a", "c"]);
            keep.swapKeeping(main, next);
            return { asDrawn: drawn(main) === plain(next), connected: vids.map((v) => v.isConnected), removed: removedVideos.length };
            """
        )
        self.assertEqual(
            got, {"asDrawn": True, "connected": [True, False, True], "removed": 1}
        )

    def test_units_in_a_new_order_still_end_as_the_new_body(self):
        got = self.swap(
            """
            main.innerHTML = page(["a", "b", "c"]);
            const vids = fill();
            const next = page(["c", "a", "b"]);
            const handled = keep.swapKeeping(main, next);
            return { handled, asDrawn: drawn(main) === plain(next), kept: vids.filter((v) => v.isConnected).length };
            """
        )
        self.assertTrue(got["handled"])
        self.assertTrue(got["asDrawn"])
        self.assertGreaterEqual(got["kept"], 1)

    def test_a_slot_held_differently_is_swapped_the_plain_way(self):
        got = self.swap(
            """
            main.innerHTML = page(["a"]);
            fill();
            const next = '<article><div class="st-slot" data-stream="a"></div></article>';
            const handled = keep.swapKeeping(main, next);
            return { handled, asDrawn: drawn(main) === plain(next) };
            """
        )
        self.assertEqual(got, {"handled": True, "asDrawn": True})

    def test_nothing_to_keep_leaves_the_swap_to_the_caller(self):
        got = self.swap(
            """
            main.innerHTML = "<p>loading</p>";
            const none = keep.swapKeeping(main, page(["a"]));
            main.innerHTML = page(["a"]);
            fill();
            const gone = keep.swapKeeping(main, "<p>a phone body, no slot</p>");
            return { none, gone, untouched: main.querySelectorAll("video").length };
            """
        )
        self.assertEqual(got, {"none": False, "gone": False, "untouched": 1})

    def test_the_watchers_slot_is_not_the_walls_to_keep(self):
        got = self.swap(
            """
            const body = '<div class="sp-slot" data-spectate-slot data-stream="w"></div>';
            main.innerHTML = body;
            return keep.swapKeeping(main, body);
            """
        )
        self.assertFalse(got)


if __name__ == "__main__":
    unittest.main()
