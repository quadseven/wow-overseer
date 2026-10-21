"""Every family on Now is one unit: its status card, its live picture and its map.

The old page drew the second family's card inside the first one (the
container for the other families was a child of the viewed family's card), so
it came out indented with a second state bar. The app's Now view draws one
card per family the realm reports. These tests render that view under node
with three families and check the markup it returns:

- each family is one `.fam` unit, a direct child of the one `.families` row,
  holding its status card, then its live picture, then its map, so what a
  family is doing, what it looks like and where it is read together;
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
globalThis.localStorage = { getItem: () => null, setItem: noop };
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


def render(families, agendas):
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
                json.dumps({"families": families, "agendas": agendas}),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


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
        cls.cards = [n for n in cls.row.walk() if is_card(n)]

    def test_one_card_per_family_each_in_its_own_unit_of_the_one_row(self):
        self.assertEqual(len(self.cards), len(self.families))
        self.assertEqual(len(units(self.row)), len(self.families))
        for unit, card in zip(units(self.row), self.cards, strict=True):
            self.assertIs(card.parent, unit)
            self.assertEqual([c for c in unit.children if is_card(c)], [card])

    def test_a_unit_is_the_card_then_the_live_picture_then_the_map(self):
        for fam, unit in zip(self.families, units(self.row), strict=True):
            self.assertEqual(unit.attrs.get("data-family"), fam)
            parts = [c.classes[0] for c in unit.children]
            self.assertEqual(parts, ["agenda", "fam-live", "minimap"])
            self.assertEqual(unit.children[2].attrs.get("data-minimap"), fam)

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
        for card in self.cards:
            self.assertFalse(
                [a for a in card.ancestors() if is_card(a)],
                "a family card is nested inside another card",
            )
            self.assertFalse(
                [n for n in card.walk() if n.tag == "a"], "a link inside a card link"
            )

    def test_the_cards_follow_the_realms_family_order_and_link_to_their_family(self):
        for fam, card in zip(self.families, self.cards, strict=True):
            self.assertEqual(card.attrs.get("href"), "#/now/family/" + fam.lower())
            self.assertIn(fam + "'s family", card.all_text())

    def test_one_fact_per_line(self):
        for card in self.cards:
            parts = [c.classes[0] for c in card.children]
            self.assertEqual(parts[0], "agenda-label")
            self.assertEqual(parts[1], "agenda-head")
            self.assertEqual(parts[-1], "agenda-foot")
            lines = [c.all_text() for c in card.children if "agenda-line" in c.classes]
            self.assertIn("Queue: The Deadmines x3, Wailing Caverns x2", lines)
            self.assertIn("0 of 10 runs done.", lines)
            self.assertIn("last moved", card.children[-1].all_text())

    def test_only_the_stalled_family_says_stalled(self):
        by_fam = dict(zip(self.families, self.cards, strict=True))
        zug = by_fam["Zug"]
        self.assertIn("is-stalled", zug.classes)
        self.assertIn("STALLED", zug.all_text())
        self.assertIn("No progress for 2 hours", zug.all_text())
        for fam in ("Grug", "Mok"):
            self.assertNotIn("is-stalled", by_fam[fam].classes)
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
        cards = [n for n in row.walk() if is_card(n)]
        self.assertEqual([c.classes[0] for c in cards], ["agenda-wait", "agenda"])
        for unit, card in zip(units(row), cards, strict=True):
            self.assertIs(card.parent, unit)

    def test_realm_text_that_looks_like_markup_stays_text(self):
        sneaky = '</a><a class="agenda" href="#/x">'
        tree = Tree(
            render(
                ["Grug", "Zug"],
                {"Grug": agenda("Grug", headline=sneaky), "Zug": agenda("Zug")},
            )
        )
        (row,) = tree.find("families")
        cards = [n for n in row.walk() if is_card(n)]
        self.assertEqual(len(cards), 2)
        self.assertIn(sneaky, cards[0].all_text())


class TheRowFitsAPhone(unittest.TestCase):
    def rule(self, selector):
        m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", NOW_CSS)
        self.assertIsNotNone(m, selector + " has no rule in now.css")
        return m.group(1)

    def test_a_card_never_asks_for_more_than_the_screen(self):
        # A fixed minimum column wider than the phone would scroll sideways.
        self.assertIn("minmax(min(100%,", self.rule(".families").replace(" ", ""))

    def test_the_foot_wraps(self):
        self.assertIn("flex-wrap: wrap", self.rule(".agenda-foot"))


if __name__ == "__main__":
    unittest.main()
