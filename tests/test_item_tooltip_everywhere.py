"""Every gear name on the site opens the Armory's tooltip, and says where the
item comes from.

WHAT THIS IS FOR. The tooltip (infra#3501) only worked where a payload already
carried an item's lines, so most gear names on the site (upgrade targets,
council awards, the bank, the pre-raid table) were plain text. The operator
asked for every gear name to open the same panel, with where the item comes
from. A name now needs only its entry: the panel reads /api/item on first
open, keeps the answer for the life of the page, and draws a "Where it comes
from" section from its `sources`.

The read-and-draw behaviour is pinned by running the page's own tooltip code
under node against a small stand-in DOM and a stand-in fetch. The surfaces are
pinned by asserting each renderer goes through itemTipName. The Upgrades tab's
phone layout is pinned in its stylesheet.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "classic.html").read_text(encoding="utf-8")

BANNER = "// --- the item tooltip, on every gear name (infra#3501)"
BLOCK = PAGE[
    PAGE.index(BANNER) : PAGE.index("// --- what the guild can make (infra#3507)")
]


def fn(name):
    """One function of the page, from its declaration to its closing brace."""
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


def run(scenario):
    script = (
        FAKE_DOM
        + fn("el")
        + fn("itemTipLines")
        + fn("itemTipSources")
        + fn("itemTipChance")
        + fn("itemTipParts")
        + fn("itemTipSource")
        + BLOCK
        + scenario
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


FAKE_DOM = r"""
class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentElement = null;
    this._text = ""; this.className = ""; this.attrs = {}; this.dataset = {}; this.hidden = false;
    this.listeners = {}; this.href = ""; this.scrollTop = 0; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  appendChild(c) { if (c.parentElement) c.remove(); c.parentElement = this; this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(typeof c === "string" ? text(c) : c)); }
  remove() { const p = this.parentElement; if (p) p.children = p.children.filter((x) => x !== this); this.parentElement = null; }
  replaceChildren(...cs) { this.children.forEach((c) => { c.parentElement = null; }); this.children = []; this._text = ""; this.append(...cs); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  fire(t, e) { for (const fn of this.listeners[t] || []) fn(Object.assign({ target: this }, e || {})); }
  has(c) { return this.className.split(" ").includes(c); }
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }
  byClass(c) { return this.all().filter((n) => n.has(c)); }
}
function text(s) { const t = new El("#text"); t._text = s; return t; }
const ids = { itemtip: new El("div"), itemtipbody: new El("div"), itemtipout: new El("a"),
              itemtipclose: new El("button") };
ids.itemtip.hidden = true;
const document = { createElement: (t) => new El(t), createTextNode: text,
  getElementById: (id) => ids[id], addEventListener() {} };
const window = { matchMedia: () => ({ matches: true }) };
function u(p) { return "/base" + p; }
const TIP = { name: "Blade", quality: 3, item_level: 20, binding: null, slot: "One-Hand",
  kind: "Sword", damage: null, armor: 0, block: 0, stats: ["+3 Strength"], resistances: [],
  enchant: [], durability: null, classes: null, requires_level: 15, effects: [], set: null,
  flavor: null, sell_price: null };
const SOURCES = [
  { kind: "drop", boss: "Baron Rivendare", where: "Stratholme", map: "Stratholme", chance: 12 },
  { kind: "quest", quest: "A Test", giver: "Some Giver", zone: "Elwynn Forest" },
  { kind: "vendor", npc: "Quartermaster", zone: "Orgrimmar", copper: 0, honor: 13000, items: [] },
  { kind: "vendor", npc: "Smith", zone: "", copper: 12345, honor: 0,
    items: [{ entry: 5, name: "Badge", count: 2 }] },
  { kind: "craft", profession: "Blacksmithing", skill: 300, recipe: "Plans: Blade" },
  { kind: "object", object: "Battered Chest", where: "Deadmines" },
  { kind: "world", chance_max: 0.4 },
];
const asked = [];
const held = {};
async function fetch(url) {
  asked.push(url);
  const entry = Number(url.split("entry=")[1]);
  if (entry === 9) return { ok: false, status: 404, json: async () => ({}) };
  if (entry === 11) await new Promise((r) => { held.release = r; });
  const body = { entry, name: "Blade", quality: 3, tooltip: TIP,
                 wowhead: "https://example.com/item=" + entry,
                 sources: entry === 12 ? [] : SOURCES };
  return { ok: true, status: 200, json: async () => body };
}
"""


@unittest.skipUnless(shutil.which("node"), "needs node to run the page's own tooltip")
class AnEntryIsEnough(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = run(SCENARIO)

    def test_a_name_with_only_an_entry_is_a_control(self):
        self.assertEqual(self.got["control"], "BUTTON")
        self.assertEqual(self.got["control_controls"], "itemtip")

    def test_a_name_with_neither_reading_nor_entry_stays_text(self):
        self.assertEqual(self.got["plain"], "SPAN")
        self.assertEqual(self.got["zero"], "SPAN")

    def test_the_panel_goes_up_at_once_with_the_name_and_a_loading_line(self):
        self.assertFalse(self.got["open_hidden"])
        self.assertEqual(self.got["open_expanded"], "true")
        self.assertEqual(self.got["loading"], ["Blade", "reading the item..."])

    def test_it_reads_api_item_through_the_pages_own_base(self):
        self.assertEqual(self.got["first_ask"], "/base/api/item?entry=7")

    def test_the_answer_draws_the_items_lines(self):
        self.assertIn("Item Level 20", self.got["loaded"])
        self.assertIn("+3 Strength", self.got["loaded"])
        self.assertNotIn("reading the item", self.got["loaded"])
        self.assertEqual(self.got["link"], "https://example.com/item=7")

    def test_where_it_comes_from_is_drawn_for_every_kind(self):
        self.assertEqual(self.got["heading"], "Where it comes from")
        lines = self.got["sources"]
        self.assertEqual(lines[0], "Drops from Baron Rivendare - Stratholme - 12%")
        self.assertEqual(lines[1], "Quest reward: A Test (Some Giver, Elwynn Forest)")
        self.assertEqual(lines[2], "Sold by Quartermaster in Orgrimmar for 13000 honor")
        self.assertTrue(lines[3].startswith("Sold by Smith for "), lines[3])
        self.assertTrue(lines[3].endswith(" and 2 x Badge"), lines[3])
        self.assertEqual(self.got["coins"], ["g", "s", "c"])
        self.assertEqual(lines[4], "Crafted: Blacksmithing 300 - Plans: Blade")
        self.assertEqual(lines[5], "Found in Battered Chest - Deadmines")
        self.assertEqual(lines[6], "World drop, up to 0.4%")

    def test_an_item_with_no_source_says_so(self):
        self.assertEqual(self.got["no_sources"], ["No source in this world's tables."])

    def test_one_read_per_item_for_the_life_of_the_page(self):
        self.assertEqual(self.got["asked_seven"], 1)

    def test_a_failed_read_keeps_the_name_and_says_what_went_wrong(self):
        self.assertTrue(self.got["failed"].startswith("Gone"), self.got["failed"])
        self.assertIn("the item could not be read", self.got["failed"])
        self.assertIn("does not know the item", self.got["failed"])

    def test_a_failed_read_is_not_kept_so_opening_again_retries(self):
        self.assertEqual(self.got["asked_nine"], 2)

    def test_a_reading_in_hand_is_drawn_at_once_and_only_the_sources_are_read(self):
        self.assertIn("Item Level 20", self.got["inhand_now"])
        self.assertIn("reading where it comes from...", self.got["inhand_now"])
        self.assertEqual(self.got["inhand_link"], "https://example.com/given")
        self.assertEqual(len(self.got["inhand_sources"]), 7)

    def test_a_late_answer_never_lands_under_another_item(self):
        self.assertEqual(self.got["late_sources"], [])
        self.assertNotIn("reading", self.got["late_body"])

    def test_a_name_with_no_address_hides_the_way_out(self):
        self.assertTrue(self.got["no_link_hidden"])

    def test_the_payloads_note_rides_in_the_panel(self):
        self.assertIn("3 x Blade (rare)", self.got["noted"])


SCENARIO = r"""
const flush = () => new Promise((r) => setTimeout(r, 0));
const body = ids.itemtipbody;
const lines = () => body.byClass("srcl").map((n) => n.textContent);
(async () => {
  const got = {};
  got.plain = itemTipName({ name: "x" }, "x", "q1").tagName;
  got.zero = itemTipName({ entry: 0, name: "x" }, "x", "q1").tagName;
  const b = itemTipName({ entry: 7, name: "Blade", quality: 3 }, "Blade", "q3");
  got.control = b.tagName;
  got.control_controls = b.getAttribute("aria-controls");
  b.fire("click");
  got.open_hidden = ids.itemtip.hidden;
  got.open_expanded = b.getAttribute("aria-expanded");
  got.loading = body.children.map((c) => c.textContent);
  got.first_ask = asked[0];
  await flush(); await flush();
  got.loaded = body.textContent;
  got.heading = body.byClass("srch")[0].textContent;
  got.sources = lines();
  got.coins = body.byClass("coin").map((c) => c.className.split(" ")[1]);
  got.link = ids.itemtipout.href;
  b.fire("click");
  b.fire("click");
  await flush(); await flush();
  got.asked_seven = asked.filter((a) => a.endsWith("entry=7")).length;

  const empty = itemTipName({ entry: 12, name: "Plain" }, "Plain", "");
  empty.fire("click");
  await flush(); await flush();
  got.no_sources = lines();

  const bad = itemTipName({ entry: 9, name: "Gone" }, "Gone", "");
  bad.fire("click");
  await flush(); await flush();
  got.failed = body.textContent;
  bad.fire("click");
  bad.fire("click");
  await flush(); await flush();
  got.asked_nine = asked.filter((a) => a.endsWith("entry=9")).length;

  const inhand = itemTipName({ entry: 7, name: "Blade", tooltip: TIP,
                               wowhead: "https://example.com/given" }, "Blade", "q3");
  inhand.fire("click");
  got.inhand_now = body.textContent;
  await flush(); await flush();
  got.inhand_link = ids.itemtipout.href;
  got.inhand_sources = lines();

  const slow = itemTipName({ entry: 11, name: "Slow" }, "Slow", "");
  slow.fire("click");
  const other = itemTipName({ entry: 12, name: "Other" }, "Other", "");
  other.fire("click");
  await flush(); await flush();
  held.release();
  await flush(); await flush(); await flush();
  got.late_sources = lines().filter((l) => l.startsWith("Drops from"));
  got.late_body = body.textContent;

  const nolink = itemTipName({ entry: 0, name: "N", tooltip: TIP }, "N", "");
  nolink.fire("click");
  got.no_link_hidden = ids.itemtipout.hidden;

  const noted = itemTipName({ entry: 7, name: "Blade", tooltip: TIP, note: "3 x Blade (rare)" },
                            "3 x Blade", "q3");
  noted.fire("click");
  got.noted = body.textContent;
  process.stdout.write(JSON.stringify(got));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


class EveryGearNameGoesThroughIt(unittest.TestCase):
    """Each surface that draws a gear name draws it with itemTipName, so the
    same tap opens the same panel everywhere."""

    def assertControl(self, name, needle="itemTipName("):
        self.assertIn(needle, fn(name), name)

    def test_the_upgrades_tab(self):
        self.assertControl("upItem")
        self.assertControl("upAlso")
        render = fn("upRender")
        self.assertIn("upItem(s.worn, false)", render)
        self.assertIn("upItem(s.next, true)", render)
        self.assertIn("upAlso(list.slice(1))", fn("upTargets"))

    def test_the_chronicle_trades_and_dungeons_share_chrItem(self):
        self.assertControl("chrItem")
        self.assertIn("chrItem(recipe", fn("gcrMissing"))
        self.assertIn("chrItem(gain", fn("dgnGain"))

    def test_the_loot_council_line(self):
        self.assertControl("chrCouncilLine")
        self.assertIn("entry: a.item_entry", fn("chrCouncilLine"))

    def test_the_council_tabs_drops(self):
        self.assertControl("renderPlaces")
        self.assertIn("p.drop_items", fn("renderPlaces"))

    def test_the_bags_tab(self):
        self.assertControl("wlink")
        self.assertNotIn("a.href", fn("wlink"))
        self.assertControl("wbag")

    def test_what_a_trade_makes(self):
        self.assertControl("stMakes")

    def test_the_pre_raid_table(self):
        self.assertControl("rrItemCell")
        self.assertIn("rrItemCell(cell, (r.items || [])[i])", fn("rrCard"))

    def test_the_armorys_card_reads_where_it_comes_from(self):
        self.assertIn("itemTipMore(c.detail, entry", fn("renderDetail"))

    def test_the_bank_slots_read_where_it_comes_from(self):
        self.assertIn("itemTipMore(t, entry", fn("vcShowTip"))

    def test_no_gear_name_is_an_outbound_link_any_more(self):
        """Talents, skills and factions still link out; they are not gear."""
        for name in ("wlink", "wbag", "upItem", "chrCouncilLine", "renderPlaces"):
            self.assertNotIn("wowhead", fn(name).replace("itemTipName", ""), name)


class TheUpgradesTabFitsAPhone(unittest.TestCase):
    """Five columns of item names ran three columns off a 375px screen. Each
    slot is a card there, and a table only where the columns fit."""

    CSS = PAGE[PAGE.index("  .up-scroll {") : PAGE.index("  .up-sc {")]

    def test_the_base_layout_is_one_card_per_slot(self):
        self.assertIn(
            ".up-table tbody, .up-table tr, .up-table th, .up-table td { display:block; }",
            self.CSS,
        )
        self.assertIn("content:attr(data-label)", self.CSS)

    def test_the_table_comes_back_only_where_it_fits(self):
        wide = self.CSS[self.CSS.index("@media (min-width:60rem)") :]
        self.assertIn("display:table-row;", wide)
        self.assertIn("display:table-cell;", wide)
        self.assertIn("content:none", wide)

    def test_every_cell_names_its_column(self):
        self.assertIn("td.dataset.label = label;", fn("upCell"))
        render = fn("upRender")
        for col in ("cols[1]", "cols[2]", "cols[3]", "cols[4]"):
            self.assertIn(col, render)

    def test_the_slot_and_its_state_head_the_card(self):
        render = fn("upRender")
        self.assertIn('el("span", "up-slotname", s.label)', render)
        self.assertIn('el("span", "up-state " + s.state', render)


class QualityColoursStayReadableOnALightCard(unittest.TestCase):
    """#1eff00 and #ffffff on a white card are unreadable. On the light theme a
    quality-coloured gear name sits on a small dark plate; on every dark ground
    the plate is nothing."""

    def test_the_plate_is_defined_in_every_theme_state(self):
        self.assertIn("--item-ground:var(--shot);", PAGE)
        self.assertEqual(PAGE.count("--item-ground:transparent; --item-pad:0;"), 6)

    def test_the_name_wears_it(self):
        self.assertIn("background:var(--item-ground); padding:0 var(--item-pad);", PAGE)


if __name__ == "__main__":
    unittest.main()
