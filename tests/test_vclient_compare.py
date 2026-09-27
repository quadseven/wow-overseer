"""Two character sheets side by side (#371).

The character frame on the Watch wall opened one sheet, and choosing another
member replaced it, so two members' gear could not be read together. The
sheet's head now has a CMP button that opens a second sheet beside it, each
with its own picker and its own close button, and while both are open every
slot is marked against the same slot on the other sheet.

The behaviour is pinned by running the page's own overlay code under node
against a small stand-in DOM: open a sheet, open the second, change one
picker, close each on its own, and the same at phone width.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")


def overlay():
    js = PAGE[PAGE.index("// --- the virtual game client (vclient.py)") :]
    return js[: js.index("</script>")]


def helper(name):
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


def run(width):
    script = (
        FAKE_DOM.replace("__WIDTH__", str(width)) + helper("el") + overlay() + SCENARIO
    )
    out = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class TheCompareButton(unittest.TestCase):
    def test_only_the_character_sheet_has_it_and_it_opens_the_second(self):
        code = overlay()
        self.assertIn('const VC_COMPARE = { kind: "compare"', code)
        self.assertIn('if (kind === "character") {', code)
        self.assertIn("vcCompareToggle()", code)
        self.assertIn("compare: vcCharacter,", code)

    def test_the_marks_are_styled_and_the_phone_stacks(self):
        self.assertIn('.vcslot[data-cmp="up"]', PAGE)
        self.assertIn('.vcslot[data-cmp="lack"]', PAGE)
        self.assertIn(".vcframe.vcpaired { max-height:calc(50vh - 12px); }", PAGE)


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's own overlay")
class TwoSheetsSideBySide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wide = run(1440)
        cls.phone = run(390)

    def test_the_second_sheet_opens_beside_the_first(self):
        s = self.wide["both"]
        self.assertEqual(s["shown"], [True, True])
        self.assertEqual(s["names"], ["Aldren", "Morka"])
        self.assertEqual(s["pressed"], "true")
        # Same height, to the right: the slot rows line up.
        self.assertEqual(s["tops"][0], s["tops"][1])
        self.assertGreater(s["lefts"][1], s["lefts"][0] + 262)
        self.assertEqual(s["paired"], [True, True])

    def test_each_slot_is_marked_against_the_other(self):
        s = self.wide["both"]
        # head: 20 against 15. neck: filled against empty. chest: the same
        # level. feet: both empty. hands: a level the world does not know.
        self.assertEqual(
            s["marks"][0],
            {"head": "up", "neck": "has", "chest": None, "feet": None, "hands": None},
        )
        self.assertEqual(
            s["marks"][1],
            {
                "head": "down",
                "neck": "lack",
                "chest": None,
                "feet": None,
                "hands": None,
            },
        )
        self.assertEqual(s["labels"]["neck"], "neck thing (the other has nothing here)")
        self.assertEqual(s["ilvl"], ["20", "15"])

    def test_changing_one_picker_leaves_the_other_alone(self):
        s = self.wide["picked"]
        self.assertEqual(s["names"], ["Aldren", "Tovi"])
        self.assertTrue(s["first_untouched"])
        self.assertEqual(s["asked"], ["Tovi"])
        # Tovi wears nothing, so every filled slot of the first now "has".
        self.assertEqual(s["marks"][0]["head"], "has")
        self.assertEqual(s["marks"][1]["head"], "lack")

    def test_each_close_button_works_on_its_own(self):
        s = self.wide["closed_second"]
        self.assertEqual(s["shown"], [True, False])
        self.assertEqual(s["paired"], [False, False])
        self.assertEqual(s["marks"][0]["head"], None)
        self.assertEqual(s["pressed"], "false")
        s = self.wide["closed_first"]
        self.assertEqual(s["shown"], [False, True])
        self.assertEqual(s["paired"], [False, False])

    def test_on_a_phone_the_sheets_stack_and_stay_inside_the_width(self):
        s = self.phone["both"]
        self.assertEqual(s["shown"], [True, True])
        self.assertEqual(s["lefts"], [8, 8])
        self.assertGreaterEqual(s["tops"][1], s["tops"][0] + 445)
        for left in s["lefts"]:
            self.assertLessEqual(left + 262, 390 - 8)
        self.assertEqual(s["marks"][0]["head"], "up")


# A stand-in for the DOM calls the overlay makes: enough to hold a tree, run
# its listeners and report sizes, and nothing that could pass for a browser.
# Every frame is 262 by 445, the character sheet's size.
FAKE_DOM = r"""
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentElement = null;
    this._text = ""; this.className = ""; this.attrs = {}; this.dataset = {}; this.hidden = false;
    this.listeners = {}; this.style = { setProperty() {} }; this.value = "";
    const self = this;
    const set = () => new Set(self.className.split(" ").filter(Boolean));
    this.classList = {
      add(...c) { const s = set(); c.forEach((x) => s.add(x)); self.className = [...s].join(" "); },
      remove(...c) { const s = set(); c.forEach((x) => s.delete(x)); self.className = [...s].join(" "); },
      contains(c) { return set().has(c); },
      toggle(c, on) { const s = set(); if (on === undefined ? !s.has(c) : on) s.add(c); else s.delete(c); self.className = [...s].join(" "); },
    };
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  get options() { return this.children.filter((c) => c.tagName === "OPTION"); }
  appendChild(c) { if (c.parentElement) c.remove(); c.parentElement = this; this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  prepend(c) { if (c.parentElement) c.remove(); c.parentElement = this; this.children.unshift(c); }
  remove() { const p = this.parentElement; if (p) p.children = p.children.filter((x) => x !== this); this.parentElement = null; }
  replaceChildren(...cs) { this.children.forEach((c) => { c.parentElement = null; }); this.children = []; this.append(...cs); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  fire(t, e) { for (const fn of this.listeners[t] || []) fn(Object.assign({ target: this, button: 0, stopPropagation() {}, preventDefault() {} }, e || {})); }
  matches(sel) { return sel.split(",").map((x) => x.trim()).some((x) =>
    x.startsWith(".") ? this.classList.contains(x.slice(1)) : this.tagName === x.toUpperCase()); }
  closest(sel) { for (let n = this; n; n = n.parentElement) if (n.matches(sel)) return n; return null; }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  querySelector(sel) { return this.all().find((c) => c.matches(sel)) || null; }
  querySelectorAll(sel) { return this.all().filter((c) => c.matches(sel)); }
  get isFrame() { return this.classList.contains("vcframe"); }
  get offsetWidth() { return this.isFrame ? 262 : 0; }
  get offsetHeight() { return this.isFrame ? 445 : 0; }
  get offsetLeft() { return parseInt(this.style.left || "0", 10); }
  get offsetTop() { return parseInt(this.style.top || "0", 10); }
  getBoundingClientRect() { return { left: 100, top: 100, right: 400, bottom: 300 }; }
  setPointerCapture() {} hasPointerCapture() { return false; } releasePointerCapture() {}
}
class Option extends El { constructor(text, value) { super("option"); this.textContent = text; this.value = value; } }
const body = new El("body");
const docListeners = [];
const document = { body, createElement: (t) => new El(t), getElementById: () => null,
  addEventListener: (t, fn) => docListeners.push([t, fn]),
  querySelectorAll: (sel) => body.querySelectorAll(sel) };
const window = { innerWidth: __WIDTH__, innerHeight: 844 };
const view = "watch", WATCH_VIEW = "watch", wall = { hero: null, slots: new Map() };
function u(p) { return p; }
function iconImg() { return new El("img"); }
function itemTipLines() {}
const GEAR = {
  Aldren: { head: 20, neck: 12, chest: 18, hands: null },
  Morka: { head: 15, chest: 18, hands: 9 },
  Tovi: {},
};
const asked = [];
async function fetch(url) {
  const name = decodeURIComponent(url.split("name=")[1]);
  let body;
  if (url.startsWith("/api/client/social")) {
    body = { family: { key: "f1", members: ["Aldren", "Morka", "Tovi"].map((n) => ({ name: n })) } };
  } else {
    asked.push(name);
    const g = GEAR[name];
    const slots = ["head", "neck", "chest", "feet", "hands"].map((s) => s in g
      ? { slot: s, empty: false, entry: 1, name: s + " thing", quality: 2, icon: null, mark: "XX",
          item_level: g[s], tooltip: {} }
      : { slot: s, empty: true, mark: "HE", empty_label: "nothing" });
    body = { member: { name, level: 20, slots, gear: { chips: [] }, stats: { rows: [] } },
             doll: { left: ["head", "neck", "chest"], right: ["feet", "hands"] } };
  }
  return { ok: true, status: 200, json: async () => body };
}
"""

SCENARIO = r"""
const flush = () => new Promise((r) => setTimeout(r, 0));
function snap() {
  const a = vc.frames.get("character"), b = vc.frames.get("compare");
  const fs = [a, b];
  const marks = fs.map((f) => {
    const out = {};
    if (!f || !f.state.slots) return out;
    for (const [k, v] of f.state.slots) out[k] = v.cell.dataset.cmp || null;
    return out;
  });
  const labels = {};
  if (a && a.state.slots) for (const [k, v] of a.state.slots) labels[k] = v.cell.getAttribute("aria-label");
  return {
    shown: fs.map((f) => !!f && !f.el.hidden),
    names: fs.map((f) => f && f.name),
    lefts: fs.map((f) => f && f.el.offsetLeft),
    tops: fs.map((f) => f && f.el.offsetTop),
    paired: fs.map((f) => !!f && f.el.classList.contains("vcpaired")),
    pressed: a.cmp.getAttribute("aria-pressed"),
    marks, labels,
    ilvl: fs.map((f) => { const c = f && f.state.slots && f.state.slots.get("head").cell.querySelector(".vcilvl"); return c ? c.textContent : null; }),
  };
}
(async () => {
  const got = {};
  vcOpen("character", "Aldren", null);
  await flush(); await flush();
  const a = vc.frames.get("character");
  a.cmp.fire("click");
  await flush(); await flush();
  got.both = snap();
  const firstBody = a.body.children[0];
  asked.length = 0;
  const b = vc.frames.get("compare");
  b.who.value = "Tovi";
  b.who.fire("change");
  await flush(); await flush();
  got.picked = snap();
  got.picked.first_untouched = a.body.children[0] === firstBody && a.name === "Aldren";
  got.picked.asked = asked.slice();
  b.el.querySelector(".vcx").fire("click");
  got.closed_second = snap();
  a.cmp.fire("click");
  await flush(); await flush();
  a.el.querySelector(".vcx").fire("click");
  got.closed_first = snap();
  process.stdout.write(JSON.stringify(got));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


if __name__ == "__main__":
    unittest.main()
