"""Every family on Now is one unit: its status card, its live picture and its map.

The old page drew the second family's card inside the first one (the
container for the other families was a child of the viewed family's card), so
it came out indented with a second state bar. The app's Now view draws one
card per family the realm reports. These tests render that view under node
with three families and check the markup it returns:

- on a wide screen the staged family is the featured player (its live
  picture, then its status card and map under it) and every other family is
  a rail card beside it; on a phone each family is one `.fam` unit holding
  its status card, then its live picture, then its map, so what a family is
  doing, what it looks like and where it is read together;
- the cards are never one inside another, including while a family's read
  is still loading;
- each card says one fact per line (whose family, the headline, the queue,
  the progress, then the stall flag and the last-moved time);
- a stalled family carries the STALLED tag and its stall sentence, and a
  moving one does not;
- text from the realm that looks like markup stays text, so it cannot open a
  card inside a card;
- the page leads with what needs the operator and the families, and the
  guild ladders come after them; the Watcher placeholder is gone;
- the row is one column on a 360px phone and the card's foot wraps, so a
  long stall sentence never pushes the page sideways.
"""

import html.parser
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
NOW_CSS = (APP / "views" / "now.css").read_text(encoding="utf-8")

NODE = shutil.which("node")
needs_node = unittest.skipIf(NODE is None, "node is not on PATH")

# Just enough of a browser for views/now.js and what it imports to load:
# nothing here draws, the test only reads the markup render() returns.
RENDER = r"""
const noop = () => {};
globalThis.window = globalThis;
globalThis.addEventListener = noop;
globalThis.matchMedia = () => ({ matches: false, addEventListener: noop });
globalThis.localStorage = {
  getItem: (k) => (k === "overseer.stage" ? (fixture.saved ?? null) : null),
  setItem: noop,
};
globalThis.document = {
  addEventListener: noop, removeEventListener: noop,
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  createElement: () => ({ style: {}, setAttribute: noop, appendChild: noop }),
  documentElement: { setAttribute: noop, getAttribute: () => null },
  head: { appendChild: noop }, body: { appendChild: noop },
};
const fixture = JSON.parse(process.argv[2]);
const { learn } = await import("./app/families.js");
learn({ families: fixture.families.map((key) => ({ key })), guilds: [] });
const now = (await import("./app/views/now.js")).default;
const waiting = { data: null, at: 0, error: null, loading: true };
const get = (path) => {
  if (path === "/api/wall" && fixture.wall) return fixture.wall;
  const m = /^\/api\/agenda\?family=(.*)$/.exec(path);
  if (!m) return waiting;
  const a = fixture.agendas[decodeURIComponent(m[1])];
  return a ? { data: a, at: 1, error: null, loading: false } : waiting;
};
const out = now.render({ get, isPhone: true, previousVisit: 0, params: {}, query: {} });
console.log(JSON.stringify(String(out && out.s !== undefined ? out.s : out)));
process.exit(0);
"""


def agenda(fam, stalled=False, headline=None):
    return {
        "family": fam,
        "headline": headline
        or ("Walking to Razorfen Kraul" if stalled else "Running The Deadmines"),
        "queue": {
            "line": "Queue: The Deadmines x3, Wailing Caverns x2",
            "done": 0,
            "entries": [],
        },
        "detail": ["0 of 10 runs done."],
        "stalled": stalled,
        "stall_line": "No progress for 2 hours since the walk began."
        if stalled
        else "",
        "moved_seconds": 1000,
    }


def render(families, agendas, wall=None, saved=None):
    """The Now view's markup for these families and agenda payloads."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(APP, root / "app")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.js").write_text(RENDER, encoding="utf-8")
        out = subprocess.run(
            [
                NODE,
                str(root / "run.js"),
                json.dumps(
                    {
                        "families": families,
                        "agendas": agendas,
                        "wall": wall,
                        "saved": saved,
                    }
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


def wall_read(*specs):
    """A ready /api/wall read: one head per (family, streamed) spec."""
    members = [
        {"name": fam + "ling", "family": fam, "class": "mage"} for fam, _ in specs
    ]
    tiles = [
        {
            "name": fam + "ling",
            "url": "https://stream.example/" + fam if streamed else "",
        }
        for fam, streamed in specs
    ]
    return {
        "data": {"members": members, "wall": {"tiles": tiles}},
        "at": 1,
        "error": None,
        "loading": False,
    }


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self.text = []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def walk(self):
        for c in self.children:
            yield c
            yield from c.walk()

    def all_text(self):
        return "".join(self.text) + "".join(c.all_text() for c in self.children)

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}


class Tree(html.parser.HTMLParser):
    """The markup as a tree of elements, so nesting is read, not guessed."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.at = self.root
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.at)
        self.at.children.append(n)
        if tag not in VOID:
            self.at = n

    def handle_endtag(self, tag):
        n = self.at
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.at = n.parent

    def handle_data(self, data):
        self.at.text.append(data)

    def find(self, cls):
        return [n for n in self.root.walk() if cls in n.classes]


def is_card(n):
    return "agenda" in n.classes or "agenda-wait" in n.classes


def units(row):
    return [c for c in row.children if "fam" in c.classes]


def featured(row):
    (node,) = [c for c in row.children if "fam-featured" in c.classes]
    return node


def rail_cards(row):
    (rail,) = [c for c in row.children if "fam-rail" in c.classes]
    return [c for c in rail.children if "fam-rail-card" in c.classes]


@needs_node
class EachFamilyIsItsOwnCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.families = ["Grug", "Zug", "Mok"]
        cls.tree = Tree(
            render(
                cls.families, {f: agenda(f, stalled=(f == "Zug")) for f in cls.families}
            )
        )
        (cls.row,) = cls.tree.find("families")
        cls.featured = featured(cls.row)
        cls.rail = rail_cards(cls.row)
        (cls.card,) = [n for n in cls.row.walk() if is_card(n)]

    def test_one_featured_unit_and_a_rail_card_for_each_other_family(self):
        self.assertEqual(self.row.attrs.get("data-wall"), "player")
        self.assertEqual(self.featured.attrs.get("data-family"), "Grug")
        self.assertEqual(
            [c.attrs.get("data-family") for c in self.rail], ["Zug", "Mok"]
        )
        # The featured family holds the one full agenda card; the rail cards
        # carry their family's name and headline instead.
        self.assertIs(self.card.parent.parent, self.featured)
        heads = ["Walking to Razorfen Kraul", "Running The Deadmines"]
        for fam, card, headline in zip(["Zug", "Mok"], self.rail, heads, strict=True):
            (head,) = [n for n in card.walk() if "rail-head" in n.classes]
            self.assertIn(fam + "'s family", card.all_text())
            self.assertEqual(head.all_text(), headline)

    def test_the_featured_unit_is_the_player_then_the_card_and_map_under_it(self):
        # The wall read has not answered in this fixture, so the player slot
        # holds the stream state; with a ready wall it holds the tile.
        parts = [c.classes[0] for c in self.featured.children]
        self.assertEqual(parts, ["state", "fam-under"])
        under = self.featured.children[1]
        self.assertEqual([c.classes[0] for c in under.children], ["agenda", "minimap"])
        self.assertEqual(under.children[1].attrs.get("data-minimap"), "Grug")

    def test_the_families_lead_and_the_guild_ladders_follow(self):
        order = [
            n.classes[0]
            for n in self.tree.root.walk()
            if n.classes and n.classes[0] in ("nchips", "families", "nfold", "nr")
        ]
        self.assertEqual(order, ["nchips", "families", "nfold", "nr"])

    def test_the_watcher_placeholder_is_gone(self):
        self.assertFalse(self.tree.find("watcher"))
        self.assertNotIn("Coming soon", self.tree.root.all_text())

    def test_no_card_sits_inside_another(self):
        self.assertFalse(
            [a for a in self.card.ancestors() if is_card(a)],
            "a family card is nested inside another card",
        )
        self.assertFalse(
            [n for n in self.card.walk() if n.tag == "a"], "a link inside a card link"
        )

    def test_the_featured_card_links_to_its_family(self):
        self.assertEqual(self.card.attrs.get("href"), "#/now/family/grug")
        self.assertIn("Grug's family", self.card.all_text())

    def test_one_fact_per_line(self):
        card = self.card
        parts = [c.classes[0] for c in card.children]
        self.assertEqual(parts[0], "agenda-label")
        self.assertEqual(parts[1], "agenda-head")
        self.assertEqual(parts[-1], "agenda-foot")
        lines = [c.all_text() for c in card.children if "agenda-line" in c.classes]
        self.assertIn("Queue: The Deadmines x3, Wailing Caverns x2", lines)
        self.assertIn("0 of 10 runs done.", lines)
        self.assertIn("last moved", card.children[-1].all_text())

    def test_only_the_stalled_family_says_stalled(self):
        by_fam = {"Grug": self.featured, "Zug": self.rail[0], "Mok": self.rail[1]}
        zug = by_fam["Zug"]
        self.assertIn("STALLED", zug.all_text())
        (tag,) = [n for n in zug.walk() if "tag" in n.classes]
        self.assertEqual(tag.all_text(), "STALLED")
        for fam in ("Grug", "Mok"):
            self.assertNotIn("STALLED", by_fam[fam].all_text())


# The agenda's stall line as the bridge sends it since #1257: it opens with
# "STALLED:" and ends with the leader's own reading, which is also sent alone
# as stall_blocker.
BLOCKER = "Zug: walking to Razorfen Kraul, waiting for the mage to catch up."
STALL_LINE = "STALLED: no quest, level or gear change for 2 hours. " + BLOCKER


def stalled_card(**fields):
    """Zug's card, stalled, with these agenda fields over the fixture's."""
    zug = dict(agenda("Zug", stalled=True), **fields)
    tree = Tree(render(["Zug"], {"Zug": zug}))
    (card,) = [n for n in tree.root.walk() if "agenda" in n.classes]
    return card


@needs_node
class AStalledFamilySaysWhyOnce(unittest.TestCase):
    def test_stalled_is_said_once_by_the_tag(self):
        card = stalled_card(stall_line=STALL_LINE, stall_blocker=BLOCKER)
        self.assertEqual(card.all_text().count("STALLED"), 1)
        (tag,) = [n for n in card.walk() if "agenda-tag" in n.classes]
        self.assertEqual(tag.all_text(), "STALLED")

    def test_the_sentence_keeps_the_rest_of_the_line_and_names_the_blocker(self):
        card = stalled_card(stall_line=STALL_LINE, stall_blocker=BLOCKER)
        (warn,) = [n for n in card.walk() if "warn" in n.classes]
        self.assertEqual(
            warn.all_text(),
            "No quest, level or gear change for 2 hours. " + BLOCKER,
        )

    def test_a_blocker_the_line_does_not_carry_is_added(self):
        card = stalled_card(
            stall_line="STALLED: no quest, level or gear change for 2 hours.",
            stall_blocker=BLOCKER,
        )
        (warn,) = [n for n in card.walk() if "warn" in n.classes]
        self.assertTrue(warn.all_text().endswith(BLOCKER), warn.all_text())

    def test_a_line_that_does_not_open_with_the_word_is_left_as_it_is(self):
        card = stalled_card(stall_line="Held: STALLED: odd, but the realm's words.")
        (warn,) = [n for n in card.walk() if "warn" in n.classes]
        self.assertEqual(warn.all_text(), "Held: STALLED: odd, but the realm's words.")


@needs_node
class CardsStaySiblingsInEveryState(unittest.TestCase):
    def test_a_family_still_loading_is_a_sibling_too(self):
        tree = Tree(render(["Grug", "Zug"], {"Zug": agenda("Zug")}))
        (row,) = tree.find("families")
        (wait,) = tree.find("agenda-wait")
        self.assertIs(wait.parent.parent, featured(row))
        (card,) = rail_cards(row)
        (head,) = [n for n in card.walk() if "rail-head" in n.classes]
        self.assertEqual(head.all_text(), "Running The Deadmines")

    def test_realm_text_that_looks_like_markup_stays_text(self):
        sneaky = '</a><a class="agenda" href="#/x">'
        tree = Tree(
            render(
                ["Grug", "Zug"],
                {
                    "Grug": agenda("Grug", headline=sneaky),
                    "Zug": agenda("Zug", headline=sneaky),
                },
            )
        )
        (row,) = tree.find("families")
        cards = [n for n in row.walk() if is_card(n)]
        self.assertEqual(len(cards), 1)
        self.assertIn(sneaky, cards[0].all_text())
        (card,) = rail_cards(row)
        self.assertIn(sneaky, card.all_text())
        self.assertEqual(len(tree.find("rail-stage")), 1)


class TheRowFitsAPhone(unittest.TestCase):
    def rule(self, selector):
        m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", NOW_CSS)
        self.assertIsNotNone(m, selector + " has no rule in now.css")
        return m.group(1)

    def test_a_card_never_asks_for_more_than_the_screen(self):
        # The player column gives up its width first; only the rail is fixed.
        self.assertIn("minmax(0,1fr)340px", self.rule(".families").replace(" ", ""))

    def test_the_foot_wraps(self):
        self.assertIn("flex-wrap: wrap", self.rule(".agenda-foot"))


NOW_JS = (APP / "views" / "now.js").read_text(encoding="utf-8")


# The wide families wall is a player: one featured family large, the rest in
# a rail beside it. These rules pin that layout; they fail without the change.
class ThePlayerLayout(unittest.TestCase):
    def rule(self, selector):
        m = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", NOW_CSS)
        self.assertIsNotNone(m, selector + " has no rule in now.css")
        return m.group(1)

    def test_the_grid_is_the_player_and_a_340px_rail(self):
        body = self.rule(".families")
        self.assertIn("minmax(0,1fr)340px", body.replace(" ", ""))
        self.assertIn("align-items: start", body)

    def test_the_old_walls_and_the_layout_toggle_are_gone(self):
        self.assertNotIn('data-wall="side"', NOW_CSS)
        self.assertNotIn("subgrid", NOW_CSS)
        self.assertNotIn(".live-seg", NOW_CSS)
        self.assertNotIn("data-layout", NOW_JS)
        self.assertNotIn("readLayout", NOW_JS)
        self.assertNotIn("overseer.wall", NOW_JS)

    def test_the_rail_stacks_under_the_player_when_the_window_narrows(self):
        css = NOW_CSS.replace(" ", "")
        self.assertIn("@media(max-width:900px)", css)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", css)
        self.assertIn("@media(max-width:560px)", css)

    def test_the_live_badge_is_a_red_pill_at_the_top_left(self):
        self.assertIn("left: 8px", self.rule(".st-badge"))
        body = self.rule('.st-pic[data-state="live"] .st-badge')
        self.assertIn("oklch(0.55 0.19 25)", body)
        self.assertIn("color: #fff", body)

    def test_the_picture_has_a_bottom_scrim_under_its_controls(self):
        body = self.rule(".st-pic::after")
        self.assertIn("linear-gradient", body)
        self.assertIn("rgba(10,10,16,.55)", body.replace(" ", ""))
        self.assertIn("pointer-events: none", body)
        self.assertIn("z-index: 2", self.rule(".st-full"))
        self.assertIn("z-index: 2", self.rule(".st-badge"))

    def test_the_featured_name_is_larger(self):
        self.assertIn("font-size: var(--fs-4)", self.rule(".fam-featured .st-name"))

    def test_the_under_row_pairs_the_card_with_a_shorter_map(self):
        self.assertIn("300px", self.rule(".fam-under"))
        self.assertIn("height: 180px", self.rule(".fam-under .wm-compact"))

    def test_the_rail_is_a_column_of_whole_card_buttons(self):
        self.assertIn("flex-direction: column", self.rule(".fam-rail"))
        body = self.rule(".rail-stage")
        self.assertIn("cursor: pointer", body)
        self.assertIn("width: 100%", body)

    def test_rail_thumbs_hide_the_fullscreen_button(self):
        self.assertIn("display: none", self.rule(".rail-thumb .st-full"))

    def test_rail_thumbs_keep_the_picture_ratio(self):
        self.assertIn("aspect-ratio: 16 / 9", self.rule(".rail-thumb .st-slot"))

    def test_the_rail_headline_clamps_to_two_lines(self):
        body = self.rule(".rail-head")
        self.assertIn("-webkit-line-clamp: 2", body)
        self.assertIn("overflow: hidden", body)


@needs_node
class ThePlayerWall(unittest.TestCase):
    def test_the_saved_stage_is_the_featured_family(self):
        wall = wall_read(("Grug", True), ("Zug", True), ("Mok", True))
        tree = Tree(
            render(
                ["Grug", "Zug", "Mok"],
                {f: agenda(f) for f in ("Grug", "Zug", "Mok")},
                wall=wall,
                saved="Zug",
            )
        )
        (row,) = tree.find("families")
        self.assertEqual(featured(row).attrs.get("data-family"), "Zug")
        self.assertEqual(
            [c.attrs.get("data-family") for c in rail_cards(row)], ["Grug", "Mok"]
        )
        (slot,) = [n for n in featured(row).walk() if "data-stream" in n.attrs]
        self.assertEqual(slot.attrs.get("data-stream"), "Zugling")

    def test_the_first_family_is_featured_when_nothing_is_staged(self):
        wall = wall_read(("Grug", True), ("Zug", True))
        tree = Tree(
            render(
                ["Grug", "Zug"],
                {f: agenda(f) for f in ("Grug", "Zug")},
                wall=wall,
            )
        )
        (row,) = tree.find("families")
        self.assertEqual(featured(row).attrs.get("data-family"), "Grug")

    def test_a_family_with_no_stream_gets_the_offline_player(self):
        tree = Tree(
            render(["Mok"], {"Mok": agenda("Mok")}, wall=wall_read(("Grug", True)))
        )
        (row,) = tree.find("families")
        feat = featured(row)
        (off,) = [n for n in feat.walk() if "st-offline" in n.classes]
        text = off.all_text()
        self.assertIn("Not streaming", text)
        self.assertIn("Mok's family is not on the wall", text)
        self.assertIn("No member of this family has a stream tile.", text)
        self.assertFalse(tree.find("fam-live"))
        self.assertFalse([n for n in feat.walk() if "data-stream" in n.attrs])

    def test_a_rail_family_with_no_head_gets_the_offline_thumb(self):
        wall = wall_read(("Grug", True))
        tree = Tree(
            render(
                ["Grug", "Mok"],
                {f: agenda(f) for f in ("Grug", "Mok")},
                wall=wall,
            )
        )
        (row,) = tree.find("families")
        (card,) = rail_cards(row)
        (off,) = [n for n in card.walk() if "rail-off" in n.classes]
        self.assertIn("Not streaming", off.all_text())
        self.assertFalse([n for n in card.walk() if "data-stream" in n.attrs])

    def test_a_rail_thumb_waits_while_the_wall_is_still_loading(self):
        # No data yet: readState calls this loading, and the thumb must not
        # claim the family is not streaming before the wall has answered.
        loading = {"at": 0, "error": None, "loading": True}
        tree = Tree(
            render(
                ["Grug", "Zug"],
                {f: agenda(f) for f in ("Grug", "Zug")},
                wall=loading,
            )
        )
        (row,) = tree.find("families")
        (card,) = rail_cards(row)
        self.assertNotIn("Not streaming", card.all_text())
        (thumb,) = [n for n in card.walk() if "st-slot" in n.classes]
        self.assertIn("skeleton", thumb.classes)
        self.assertNotIn("data-stream", thumb.attrs)

    def test_each_rail_card_is_a_stage_button_for_its_family(self):
        wall = wall_read(("Grug", True), ("Zug", True))
        tree = Tree(
            render(
                ["Grug", "Zug"],
                {f: agenda(f) for f in ("Grug", "Zug")},
                wall=wall,
            )
        )
        (row,) = tree.find("families")
        (card,) = rail_cards(row)
        (button,) = [n for n in card.walk() if "rail-stage" in n.classes]
        self.assertEqual(button.tag, "button")
        self.assertEqual(button.attrs.get("data-stage-fam"), "Zug")
        self.assertEqual(
            button.attrs.get("aria-label"), "Put Zug's family on the main player"
        )
        (slot,) = [n for n in card.walk() if "data-stream" in n.attrs]
        self.assertEqual(slot.attrs.get("data-stream"), "Zugling")


# Clicking a rail card stages that family: after() binds the button, the
# pick is saved, and a redraw is asked for. The harness gives now.js just
# enough of a browser to run after() with unstreamed heads (no player starts).
CLICK = r"""
const noop = () => {};
function makeEl(tag) {
  const node = {
    tagName: String(tag).toUpperCase(),
    children: [], style: {}, dataset: {}, className: "", hidden: false,
    textContent: "", attrs: {}, listeners: {},
    classList: { toggle: noop, add: noop, remove: noop },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    hasAttribute(k) { return k in this.attrs; },
    removeAttribute(k) { delete this.attrs[k]; },
    append(...kids) { this.children.push(...kids); },
    appendChild(k) { this.children.push(k); return k; },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    remove: noop,
    querySelector: () => null,
    querySelectorAll: () => [],
    get firstChild() { return this.children[0] || null; },
    get lastChild() { return this.children[this.children.length - 1] || null; },
  };
  return node;
}
const store = {};
const dispatched = [];
globalThis.window = globalThis;
globalThis.addEventListener = noop;
globalThis.dispatchEvent = (e) => { dispatched.push(e.type); return true; };
globalThis.matchMedia = () => ({ matches: false, addEventListener: noop });
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
const stageEl = makeEl("section");
stageEl.hidden = true;
globalThis.document = {
  addEventListener: noop, removeEventListener: noop, hidden: false,
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: (id) => (id === "stage" ? stageEl : null),
  createElement: (tag) => makeEl(tag),
  documentElement: { setAttribute: noop, getAttribute: () => null, toggleAttribute: noop },
  head: { appendChild: noop }, body: { appendChild: noop },
};
const { learn } = await import("./app/families.js");
learn({ families: [{ key: "Grug" }, { key: "Zug" }], guilds: [] });
const now = (await import("./app/views/now.js")).default;
const wall = {
  data: {
    members: [
      { name: "Grugling", family: "Grug", class: "mage" },
      { name: "Zugling", family: "Zug", class: "mage" },
    ],
    wall: { tiles: [{ name: "Grugling", url: "" }, { name: "Zugling", url: "" }] },
  },
  at: 1, error: null, loading: false,
};
const waiting = { data: null, at: 0, error: null, loading: true };
const get = (path) => (path === "/api/wall" ? wall : waiting);
const zugBtn = makeEl("button");
zugBtn.setAttribute("data-stage-fam", "Zug");
const main = {
  querySelectorAll: (sel) => (sel === "button[data-stage-fam]" ? [zugBtn] : []),
  querySelector: () => null,
};
now.after(main, { get, previousVisit: 0, isPhone: false, params: {}, query: {} });
(zugBtn.listeners.click || []).forEach((f) => f());
console.log(JSON.stringify({ saved: store["overseer.stage"] ?? null, dispatched }));
process.exit(0);
"""


@needs_node
class ARailClickStagesTheFamily(unittest.TestCase):
    def test_clicking_a_rail_card_saves_the_stage_and_asks_for_a_redraw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            shutil.copytree(APP, root / "app")
            (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
            (root / "run.js").write_text(CLICK, encoding="utf-8")
            out = subprocess.run(
                [NODE, str(root / "run.js")],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        if out.returncode != 0:
            raise AssertionError(out.stderr)
        got = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(got["saved"], "Zug")
        self.assertIn("overseer:redraw", got["dispatched"])


if __name__ == "__main__":
    unittest.main()
