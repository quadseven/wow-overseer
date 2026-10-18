"""The live tiles on Now: a full screen control on each picture, and the
member's frames (Bags, Bank, Guild bank, Character, Social, Quests) opened as
panels over the page instead of pages of their own. The Character panel can
compare two members' gear side by side (#371).

The modules run under node with a browser just big enough for them: elements
that hold attributes, children and listeners, and a document that records
where the picture went.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
sys.path.insert(0, str(HERE))

import apiv2  # noqa: E402
import map_server  # noqa: E402

BROWSER = r"""
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.attrs = {}; this.children = []; this.parentElement = null;
    this.on = {}; this.dataset = {}; this.style = {}; this.className = ""; this.textContent = "";
    const self = this;
    this.classList = {
      toggle(c, on) { const s = new Set(self.className.split(" ").filter(Boolean)); if (on) s.add(c); else s.delete(c); self.className = [...s].join(" "); },
      contains(c) { return self.className.split(" ").includes(c); },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  appendChild(c) { if (c.parentElement) c.remove(); c.parentElement = this; this.children.push(c); return c; }
  remove() { const p = this.parentElement; if (p) p.children = p.children.filter((x) => x !== this); this.parentElement = null; }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); }
  fire(t) { (this.on[t] || []).forEach((f) => f({ type: t, target: this })); }
  focus() { globalThis.document.activeElement = this; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  closest() { return null; }
  contains(n) { for (let x = n; x; x = x.parentElement) if (x === this) return true; return false; }
  play() { this.paused = false; return Promise.resolve(); }
}
globalThis.El = El;
globalThis.CSS = { escape: (s) => String(s) };
globalThis.window = {
  setTimeout() { return 0; }, clearTimeout() {}, setInterval() { return 0; }, clearInterval() {},
  addEventListener() {}, requestAnimationFrame() {},
  matchMedia: () => ({ matches: false }),
};
globalThis.location = { hash: "#/now" };
const docOn = {};
globalThis.document = {
  hidden: false, activeElement: null, fullscreenElement: null, body: new El("body"),
  createElement: (t) => new El(t),
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: () => null,
  addEventListener(t, f) { (docOn[t] = docOn[t] || []).push(f); },
};
globalThis.docOn = docOn;
"""


# The families and guilds /api/realm reports; app/families.js learns them
# before a view is drawn, as main.js does before the first route.
REALM = {
    "families": [{"key": "Grug", "names": ["Grug"]}, {"key": "Zug", "names": ["Zug"]}],
    "guilds": [
        {"name": "Cave", "family": "Grug"},
        {"name": "Bonkers", "family": "Zug"},
    ],
}


def learn(root):
    """The line that teaches the copied app the realm's families and guilds."""
    return "(await import(%s)).learn(%s);\n" % (
        json.dumps((root / "families.js").as_uri()),
        json.dumps(REALM),
    )


def run(module, script):
    """Run `script` with app/<module> imported as M."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = "%s\n%sconst M = await import(%s);\n%s" % (
            BROWSER,
            learn(root),
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


KEYS = ["bags", "bank", "guildbank", "gear", "social", "quests"]
LABELS = ["Bags", "Bank", "Guild bank", "Character", "Social", "Quests"]

# A tile's markup, then its frame buttons bound with a spy for openPanel and
# clicked, each one.
TILE = r"""
const markup = M.tileHtml({name: "Grug", class: "Warrior"}, null).s;
const buttons = [...markup.matchAll(/<button[^>]*data-panel="([^"]+)"[^>]*data-name="([^"]+)"[^>]*>/g)].map((m) => {
  const b = new El("button"); b.setAttribute("data-panel", m[1]); b.setAttribute("data-name", m[2]); return b;
});
const root = { querySelectorAll: (sel) => (sel === "[data-panel]" ? buttons : []) };
const opened = [];
M.bind(root, (name, kind, from) => opened.push([name, kind, from === buttons.find((b) => b.getAttribute("data-panel") === kind)]));
buttons.forEach((b) => b.fire("click"));
console.log(JSON.stringify({markup, opened, hash: location.hash}));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheFrameButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = run("views/now/streams.js", TILE)

    def test_each_frame_is_a_button_that_opens_a_panel(self):
        self.assertEqual(
            self.got["opened"], [["Grug", k, True] for k in KEYS], self.got["markup"]
        )
        self.assertEqual(self.got["hash"], "#/now", "a frame button never navigates")

    def test_no_frame_is_a_link_to_another_page(self):
        links = re.findall(r'href="([^"]+)"', self.got["markup"])
        # The member's name is the one link: their profile, as before.
        self.assertEqual(links, ["#/m/Grug"])

    def test_the_buttons_say_words_with_an_icon(self):
        m = self.got["markup"]
        for label in LABELS:
            self.assertIn("<span>%s</span>" % label, m)
        for code in ("BAG", "BNK", "GBK", "CHR", "SOC", "QST"):
            self.assertNotIn(">%s<" % code, m)
        self.assertEqual(m.count('<i class="ph ph-'), 7)  # Hear, then the six

    def test_hear_says_its_state(self):
        m = self.got["markup"]
        self.assertIn('data-hear="Grug"', m)
        self.assertIn('aria-pressed="false"', m)
        self.assertIn('<span class="st-hear-l">Hear</span>', m)


PANELS = r"""
const out = {};
for (const k of Object.keys(M.PANELS)) out[k] = M.PANELS[k].reads("Grug");
const social = {data: {
  name: "Grug", family_key: "Grug",
  family: {key: "Grug", members: [{name: "Grug", level: 43, line: "Level 43 Human Warrior", class: "Warrior", online: true},
                                  {name: "Oz", level: null, line: "not on this realm", class: null, online: false}]},
  guild: {name: "Cave", members: [{name: "Grug", level: 43, line: "Level 43 Human Warrior", class: "Warrior", online: true, rank: "Guild Master"},
                                  {name: "Ugga", level: 39, line: "Level 39 Human Priest", class: "Priest", online: false, rank: "Officer"}],
          online: 1, total: 2, note: null},
  friends: [], friends_note: "no friends on the list.", ignored: []}};
console.log(JSON.stringify({
  reads: out,
  social: M.socialBody(social, "Grug").s,
  waiting: M.socialBody({data: undefined, error: null}, "Grug").s,
  links: [
    M.inPanel("#/m/Grug/bank", "Grug"), M.inPanel("#/m/Grug/gear", "Grug"),
    M.inPanel("#/economy/bank?guild=bonkers&tab=2", "Grug"),
    M.inPanel("#/m/Grug/upgrades", "Grug"), M.inPanel("#/m/Zug/bags", "Grug"), M.inPanel("#/runs/7", "Grug"),
  ],
}));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class ThePanels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = run("views/now/panel.js", PANELS)

    def test_there_is_a_panel_for_every_frame_button(self):
        self.assertEqual(sorted(self.got["reads"]), sorted(KEYS))

    def test_every_panel_reads_an_endpoint_the_server_serves(self):
        served = set(map_server.Handler.GET_ROUTES) | set(apiv2.ROUTES)
        for kind, paths in self.got["reads"].items():
            self.assertTrue(paths, kind)
            for path in paths:
                self.assertIn(path.split("?", 1)[0], served, (kind, path))

    def test_social_reads_its_v2_endpoint(self):
        self.assertEqual(self.got["reads"]["social"], ["/api/v2/social?name=Grug"])

    def test_social_draws_the_family_friends_and_guild(self):
        s = self.got["social"]
        self.assertIn("Grug&#39;s family", s)
        self.assertIn("not on this realm", s)
        self.assertIn("No friends on the list.", s)
        self.assertIn("1 of 2 members online", s)
        self.assertIn("1 member offline", s)
        self.assertIn('href="#/m/Grug"', s)
        self.assertNotIn('href="#/m/Oz"', s, "a name not on this realm has no page")
        self.assertNotIn("undefined", s)
        self.assertIn('aria-busy="true"', self.got["waiting"])

    def test_a_link_to_one_of_its_frames_switches_the_panel(self):
        bank, gear, guildbank, upgrades, other, run_ = self.got["links"]
        self.assertEqual(bank, {"kind": "bank", "query": {}})
        self.assertEqual(gear, {"kind": "gear", "query": {}})
        self.assertEqual(
            guildbank, {"kind": "guildbank", "query": {"guild": "bonkers", "tab": "2"}}
        )
        self.assertIsNone(upgrades)
        self.assertIsNone(other)
        self.assertIsNone(run_)

    def test_the_panel_never_sets_the_hash(self):
        src = (APP / "views" / "now" / "panel.js").read_text(encoding="utf-8")
        self.assertNotRegex(
            src, r"location\.(hash|href)\s*=|location\.(assign|replace)\("
        )


FULL = r"""
const call = [];
const fake = (has) => {
  const pic = {}, video = {};
  if (has.includes("std")) pic.requestFullscreen = () => { call.push("pic.requestFullscreen"); return Promise.resolve(); };
  if (has.includes("webkit")) pic.webkitRequestFullscreen = () => call.push("pic.webkitRequestFullscreen");
  if (has.includes("video")) video.webkitEnterFullscreen = () => call.push("video.webkitEnterFullscreen");
  return [pic, video];
};
const how = [
  M.enterFullscreen(...fake(["std", "webkit", "video"])),
  M.enterFullscreen(...fake(["webkit", "video"])),
  M.enterFullscreen(...fake(["video"])),
  M.enterFullscreen(...fake([])),
];
// The tile's own control: mount a picture, press it.
const slot = new El("div");
slot.getAttribute = (k) => (k === "data-stream" ? "Grug" : null);
M.mount({ querySelectorAll: (sel) => (sel === "[data-stream]" ? [slot] : []) });
const pic = slot.firstChild;
const button = pic.children.find((c) => c.className === "st-full");
const before = {label: button.getAttribute("aria-label"), type: button.type, id: button.id};
let asked = 0;
pic.requestFullscreen = () => { asked++; document.fullscreenElement = pic; return Promise.resolve(); };
button.fire("click");
const during = {asked, inBody: pic.parentElement === document.body, label: button.getAttribute("aria-label")};
// A redraw while full screen leaves the picture where it is.
const slot2 = new El("div");
slot2.getAttribute = slot.getAttribute;
M.mount({ querySelectorAll: (sel) => (sel === "[data-stream]" ? [slot2] : []) });
during.stayed = pic.parentElement === document.body;
// Leaving full screen puts it back in its slot.
document.fullscreenElement = null;
document.querySelector = (sel) => (sel === '[data-stream="Grug"]' ? slot2 : null);
docOn.fullscreenchange.forEach((f) => f());
const after = {inSlot: pic.parentElement === slot2, label: button.getAttribute("aria-label")};
console.log(JSON.stringify({how, call, before, during, after}));
"""


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class FullScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = run("views/now/streams.js", FULL)

    def test_the_standard_api_first_then_webkit_then_the_iphone_video(self):
        self.assertEqual(self.got["how"], ["element", "webkit", "video", ""])
        self.assertEqual(
            self.got["call"],
            [
                "pic.requestFullscreen",
                "pic.webkitRequestFullscreen",
                "video.webkitEnterFullscreen",
            ],
        )

    def test_every_tile_has_a_labelled_control(self):
        b = self.got["before"]
        self.assertEqual(b["type"], "button")
        self.assertEqual(b["label"], "Full screen, Grug's stream")
        self.assertTrue(b["id"], "an id, so a redraw gives it its focus back")

    def test_the_control_takes_the_picture_full_screen_and_back(self):
        d, a = self.got["during"], self.got["after"]
        self.assertEqual(d["asked"], 1)
        self.assertTrue(d["inBody"], "held outside the view's markup while full")
        self.assertTrue(d["stayed"], "a redraw does not pull it out of full screen")
        self.assertEqual(d["label"], "Exit full screen, Grug's stream")
        self.assertTrue(a["inSlot"])
        self.assertEqual(a["label"], "Full screen, Grug's stream")

    def test_the_control_is_44px(self):
        css = (APP / "views" / "now.css").read_text(encoding="utf-8")
        rule = re.search(r"\.st-full \{([^}]*)\}", css).group(1)
        self.assertIn("width: 44px", rule)
        self.assertIn("height: 44px", rule)


# Three members and their armory reads, served by a stand-in fetch. Grug and
# Zug differ in every way a slot can: a higher and a lower item level, a slot
# worn on one side only, a slot empty on both, and a cosmetic shirt worn on
# one side only (never marked).
def _slot(slot, name=None, ilvl=None, cosmetic=False):
    if name is None:
        return {
            "slot": slot,
            "cosmetic": cosmetic,
            "empty": True,
            "empty_kind": "cosmetic" if cosmetic else "missing",
            "empty_label": "empty",
        }
    return {
        "slot": slot,
        "cosmetic": cosmetic,
        "empty": False,
        "entry": 100 + len(name),
        "name": name,
        "quality": 2,
        "item_level": ilvl,
    }


def _armory(name, slots, avg):
    return {
        "member": {
            "name": name,
            "present": True,
            "gear": {"average_item_level": avg, "worn": 3, "slots": 17},
            "slots": slots,
        },
        "doll": {"left": ["head", "chest", "shirt"], "right": ["legs", "feet"]},
    }


SERVED = {
    "/api/v2/roster": {
        "checked_at": 1,
        "members": [
            {"name": "Grug", "class": "Warrior"},
            {"name": "Zug", "class": "Mage"},
            {"name": "Ugga", "class": "Priest"},
        ],
    },
    "/api/armory/member?name=Grug": _armory(
        "Grug",
        [
            _slot("head", "Cap", 40),
            _slot("chest", "Vest", 30),
            _slot("shirt", "Shirt", 1, cosmetic=True),
            _slot("legs"),
            _slot("feet"),
        ],
        35,
    ),
    "/api/armory/member?name=Zug": _armory(
        "Zug",
        [
            _slot("head", "Hood", 35),
            _slot("chest", "Robe", 33),
            _slot("shirt", cosmetic=True),
            _slot("legs", "Pants", 20),
            _slot("feet"),
        ],
        29,
    ),
    "/api/armory/member?name=Ugga": _armory(
        "Ugga",
        [
            _slot("head", "Circlet", 50),
            _slot("chest", "Robe", 33),
            _slot("shirt", cosmetic=True),
            _slot("legs"),
            _slot("feet", "Boots", 12),
        ],
        40,
    ),
}

COMPARE = r"""
const SERVED = __SERVED__;
globalThis.fetch = async (url) => {
  const k = String(url);
  if (!(k in SERVED)) return { ok: false, status: 404, text: async () => "" };
  return { ok: true, status: 200, text: async () => JSON.stringify(SERVED[k]) };
};
const api = await import(new URL("../../api.js", __PANEL__).href);
await api.load("/api/v2/roster");
const settle = () => new Promise((r) => setTimeout(r, 20));
const target = (attrs, value) => ({
  value, getAttribute: (k) => (k in attrs ? attrs[k] : null),
  closest(sel) { const m = sel.match(/^\[([a-z-]+)\]$/); return m && m[1] in attrs ? this : null; },
});
const scrim = () => document.body.children[0];
const sheet = () => scrim().children[0];
const fire = (type, t) => (scrim().on[type] || []).forEach((f) => f({ target: t, preventDefault() {} }));
const click = (attrs) => fire("click", target(attrs));
const change = (side, value) => fire("change", target({ "data-pick": side }, value));
const snap = () => ({
  pair: M.pairOf(), open: M.isOpen(),
  head: sheet().children[0].innerHTML, body: sheet().children[1].innerHTML,
  wide: sheet().hasAttribute("data-compare"),
  bodies: document.body.children.length,
});
const out = {};
M.openPanel("Grug", "gear", null);
await settle();
out.single = snap();
click({ "data-compare": "" });
await settle();
out.two = snap();
change("b", "Ugga");
await settle();
out.picked = snap();
change("a", "Zug");
await settle();
out.pickedA = snap();
click({ "data-unpane": "a" });
await settle();
out.closedA = snap();
click({ "data-compare": "" });
await settle();
click({ "data-unpane": "b" });
await settle();
out.closedB = snap();
click({ "data-compare": "" });
await settle();
click({ "data-kind": "bags" });
out.switched = snap();
const notRead = M.__compare.diffRows({ data: undefined, error: null }, { data: SERVED["/api/armory/member?name=Zug"] });
out.notRead = notRead.map((r) => r.ma + "|" + r.mb);
click({ "data-close": "" });
out.closed = { open: M.isOpen() };
console.log(JSON.stringify(out));
""".replace("__SERVED__", json.dumps(SERVED))


def _panes(body):
    """The two panes' markup, first then second."""
    parts = body.split('<section class="cmp-pane"')[1:]
    return [p.split("</section>")[0] for p in parts]


def _marks(pane):
    """slot -> mark ('' when unmarked) for one pane's rows."""
    rows = re.findall(
        r'<li class="cmp-row[^"]*" data-slot="([^"]+)"(?: data-mark="([a-z]+)")?', pane
    )
    return dict(rows)


def _picked(pane):
    return re.findall(r'<option value="([^"]+)" selected>', pane)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheComparison(unittest.TestCase):
    """#371: two Character panels side by side, each with its own picker."""

    @classmethod
    def setUpClass(cls):
        cls.got = run_compare(COMPARE)

    def test_compare_opens_a_second_panel_and_both_stay_open(self):
        single, two = self.got["single"], self.got["two"]
        self.assertIsNone(single["pair"])
        self.assertIn(
            "data-compare", single["head"], "the Character panel offers Compare"
        )
        self.assertIn('aria-pressed="false"', single["head"])
        self.assertEqual(two["pair"], {"a": "Grug", "b": "Zug"})
        self.assertTrue(two["open"])
        self.assertTrue(two["wide"], "the sheet widens to hold two panes")
        panes = _panes(two["body"])
        self.assertEqual(len(panes), 2)
        self.assertEqual(_picked(panes[0]), ["Grug"])
        self.assertEqual(_picked(panes[1]), ["Zug"])
        for pane in panes:
            # Each pane has its own picker listing the roster, and its own close.
            self.assertEqual(len(re.findall(r"<option ", pane)), 3)
            self.assertEqual(pane.count("data-unpane="), 1)
        self.assertIn('aria-pressed="true"', two["head"])
        self.assertEqual(two["bodies"], 1, "one sheet, two panes")

    def test_the_slots_line_up_in_the_same_order(self):
        a, b = _panes(self.got["two"]["body"])
        order = ["head", "chest", "shirt", "legs", "feet"]
        self.assertEqual(list(_marks(a)), order)
        self.assertEqual(list(_marks(b)), order)

    def test_differences_are_marked_slot_by_slot(self):
        a, b = _panes(self.got["two"]["body"])
        self.assertEqual(
            _marks(a),
            {"head": "more", "chest": "less", "shirt": "", "legs": "empty", "feet": ""},
        )
        self.assertEqual(
            _marks(b),
            {
                "head": "less",
                "chest": "more",
                "shirt": "",
                "legs": "filled",
                "feet": "",
            },
        )
        # The mark is a word too, not only a colour.
        self.assertIn("+5 ilvl", a)
        self.assertIn("-3 ilvl", a)
        self.assertIn("missing", a)
        self.assertIn("only here", b)
        self.assertIn("5 item levels lower than the other", b)

    def test_changing_one_picker_leaves_the_other_panel_alone(self):
        before_a = _panes(self.got["two"]["body"])[0]
        picked = self.got["picked"]
        self.assertEqual(picked["pair"], {"a": "Grug", "b": "Ugga"})
        a, b = _panes(picked["body"])
        self.assertEqual(_picked(a), ["Grug"])
        self.assertEqual(_picked(b), ["Ugga"])
        # The first pane still draws Grug's own items; only the marks, which
        # are against the other side, moved.
        for item in ("Cap", "Vest"):
            self.assertIn(item, a)
            self.assertIn(item, before_a)
        self.assertNotIn("Circlet", a)
        self.assertIn("Circlet", b)
        self.assertEqual(_marks(a)["head"], "less")
        self.assertEqual(_marks(a)["feet"], "empty")
        # And the other way round: the first picker leaves the second alone.
        pa = self.got["pickedA"]
        self.assertEqual(pa["pair"], {"a": "Zug", "b": "Ugga"})
        self.assertEqual(_picked(_panes(pa["body"])[1]), ["Ugga"])
        self.assertIn("Circlet", _panes(pa["body"])[1])

    def test_each_pane_closes_on_its_own(self):
        a = self.got["closedA"]
        self.assertTrue(a["open"], "closing one pane keeps the panel")
        self.assertIsNone(a["pair"])
        self.assertFalse(a["wide"])
        self.assertIn(">Ugga<", a["head"], "the second pane's member is left showing")
        self.assertEqual(_panes(a["body"]), [])
        b = self.got["closedB"]
        self.assertTrue(b["open"])
        self.assertIsNone(b["pair"])
        self.assertIn(">Ugga<", b["head"], "closing the second pane keeps the first")
        self.assertFalse(
            self.got["closed"]["open"], "the sheet's own close still closes all"
        )

    def test_another_frame_ends_the_comparison(self):
        s = self.got["switched"]
        self.assertIsNone(s["pair"])
        self.assertTrue(s["open"])
        self.assertNotIn("data-compare", s["head"], "Compare is the Character panel's")

    def test_nothing_is_marked_until_both_sides_are_read(self):
        self.assertEqual(set(self.got["notRead"]), {"|"})

    def test_on_a_phone_the_panes_stack_and_nothing_scrolls_sideways(self):
        css = (APP / "views" / "now.css").read_text(encoding="utf-8")
        base = re.search(r"\.cmp \{([^}]*)\}", css).group(1)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", base)
        wide = re.search(
            r"@media \(min-width: 760px\) \{\s*\.np-sheet\[data-compare\][^@]*", css
        ).group(0)
        self.assertIn("repeat(2, minmax(0, 1fr))", wide)
        row = re.search(r"\.cmp-row \{([^}]*)\}", css).group(1)
        self.assertIn("height: 60px", row, "one row height, so the panes line up")
        self.assertIn("minmax(0, 1fr)", row)
        item = re.search(r"\.cmp-item \{([^}]*)\}", css).group(1)
        self.assertIn("text-overflow: ellipsis", item)
        self.assertIn(
            ".cmp-pane { display: flex; flex-direction: column; gap: 8px; min-width: 0;",
            css,
        )


def run_compare(script):
    """run() for the comparison: panel.js as M, with compare.js and the
    copy's own URL beside it so the script imports the same api.js."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        panel = (root / "views" / "now" / "panel.js").as_uri()
        code = (
            "%s\n%sconst M = Object.assign({}, await import(%s), {__compare: await import(%s)});\n%s"
            % (
                BROWSER,
                learn(root),
                json.dumps(panel),
                json.dumps((root / "views" / "now" / "compare.js").as_uri()),
                script.replace("__PANEL__", json.dumps(panel)),
            )
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


if __name__ == "__main__":
    unittest.main()
