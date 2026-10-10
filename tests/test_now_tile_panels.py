"""The live tiles on Now: a full screen control on each picture, and the
member's frames (Bags, Bank, Guild bank, Character, Social, Quests) opened as
panels over the page instead of pages of their own.

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


if __name__ == "__main__":
    unittest.main()
