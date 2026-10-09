"""The Lineup tab's gear table fits a phone without sideways scrolling (#559).

WHAT THIS IS FOR. Eleven columns of the gear table ran off a 375px screen
even inside their own scrolling box. Below 60rem, the breakpoint #555 gave
the Upgrades tab, each member is a card: the name heads it and every other
cell draws its column name above itself. The header row stays as a row of
sort pills. From 60rem up it is a table again.

The rows are pinned by running the page's own lgRender under node against a
small stand-in DOM; the two layouts are pinned in the stylesheet.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "classic.html").read_text(encoding="utf-8")

CSS = PAGE[
    PAGE.index("  /* THE GEAR TABLE (guildgear.py).") : PAGE.index("  .lg-note {")
]


def fn(name):
    """One function of the page, from its declaration to its closing brace."""
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


def block(start, end):
    js = PAGE[PAGE.index(start) :]
    return js[: js.index(end)]


FAKE_DOM = r"""
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentElement = null;
    this._text = ""; this.className = ""; this.attrs = {}; this.dataset = {}; this.style = {};
    this.listeners = {}; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  appendChild(c) { c.parentElement = this; this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(typeof c === "string" ? text(c) : c)); }
  replaceChildren(...cs) { this.children = []; this._text = ""; this.append(...cs); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, e) {
    // Bubbles, like the browser: each element's listeners, then its parent's,
    // until one stops it.
    const ev = Object.assign({ target: this, stopped: false, key: "",
      stopPropagation() { this.stopped = true; }, preventDefault() {} }, e || {});
    for (let n = this; n && !ev.stopped; n = n.parentElement) {
      for (const f of n.listeners[t] || []) f(ev);
    }
  }
  has(c) { return this.className.split(" ").includes(c); }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
}
function text(s) { const t = new El("#text"); t._text = s; return t; }
const ids = { lgpick: new El("div"), lghead: new El("div"), lgtable: new El("table") };
const document = { createElement: (t) => new El(t), getElementById: (id) => ids[id] };
// The tooltip's own code is pinned in test_item_tooltip_everywhere; here a
// gear name only has to come out of it as a control carrying its item.
function itemTipName(item, label, cls) {
  const b = new El("button"); b.className = "iname " + cls; b.textContent = label; b.item = item;
  return b;
}
function vclientBar(name) { const d = new El("div"); d.className = "vcbar"; return d; }
"""

SCENARIO = r"""
function member(name, extra) {
  return Object.assign({ name, "class": "Mage", class_colour: "#69ccf0", level: 30, role: "dps",
    avg_item_level: 22.5, worn: 15, of: 17, empty: 2, empty_slots: ["neck", "back"],
    weapon: true, weakest: null, gold: { total: 100, text: "1s" }, presence: "online",
    flags: [] }, extra || {});
}
lg.payload = { slots: 17, empty_warn: 6, empty_warn_level: 20, guilds: [{ name: "Cave", members: [
  member("Og", { weakest: { slot: "chest", item_level: 12, name: "Frayed Robe", entry: 1234 } }),
  member("Ug"),
] }] };
lgRender();
const body = ids.lgtable.children[1];
const og = body.children.find((tr) => tr.children[0].textContent === "Og");
const got = {
  labels: og.children.map((td) => td.dataset.label),
  columns: LG_COLUMNS.map((c) => c.label),
  weak: og.children[8].className,
  weakText: og.children[8].textContent,
  noWeak: body.children.find((tr) => tr.children[0].textContent === "Ug").children[8].textContent,
};
const name = og.all().find((n) => n.has("iname"));
got.item = name ? name.item.entry : null;
name.fire("click");
got.openAfterNameTap = lg.open;
name.fire("keydown", { key: "Enter" });
got.openAfterNameKey = lg.open;
og.fire("click");
got.openAfterRowTap = lg.open;
process.stdout.write(JSON.stringify(got));
"""


def run():
    script = (
        FAKE_DOM
        + fn("el")
        + fn("classInk")
        + block("const lgpick = ", "\nasync function pollGuildGear")
        + SCENARIO
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


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's own lgRender")
class EveryCellNamesItsColumn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = run()

    def test_each_cell_carries_its_columns_label(self):
        self.assertEqual(self.got["labels"], self.got["columns"])

    def test_the_weakest_piece_is_named_and_opens_its_tooltip(self):
        self.assertIn("lg-weak", self.got["weak"])
        self.assertEqual(self.got["weakText"], "chest 12 Frayed Robe")
        self.assertEqual(self.got["item"], 1234)
        self.assertEqual(self.got["noWeak"], "-")

    def test_the_name_opens_the_tooltip_and_not_the_members_frames(self):
        self.assertIsNone(self.got["openAfterNameTap"])
        self.assertIsNone(self.got["openAfterNameKey"])
        self.assertEqual(self.got["openAfterRowTap"], "Og")


class APhoneGetsOneCardPerMember(unittest.TestCase):
    def test_the_base_layout_is_cards_with_labelled_cells(self):
        self.assertIn(
            ".lg-table thead, .lg-table tbody, .lg-table tr, .lg-table th, "
            ".lg-table td { display:block; }",
            CSS,
        )
        base = CSS[: CSS.index("@media (min-width:60rem)")]
        self.assertIn(".lg-table tbody tr.lg-row { display:grid;", base)
        self.assertIn("content:attr(data-label)", base)
        # The sort controls stay on a phone, as a wrapping row of pills.
        self.assertIn(".lg-table thead tr { display:flex; flex-wrap:wrap;", base)
        # Nothing on the phone is pinned for a sideways scroll any more.
        self.assertNotIn("position:sticky", base)

    def test_the_table_comes_back_at_the_upgrades_breakpoint(self):
        self.assertIn("@media (min-width:60rem)", PAGE[PAGE.index("  .up-scroll {") :])
        wide = CSS[CSS.index("@media (min-width:60rem)") :]
        self.assertIn("display:table-row;", wide)
        self.assertIn("display:table-cell;", wide)
        self.assertIn(".lg-table td::before { content:none; }", wide)
        self.assertIn("position:sticky; left:0;", wide)


if __name__ == "__main__":
    unittest.main()
