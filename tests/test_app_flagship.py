"""The flagship pass: what the app does that can be checked from source.

- A new deploy is picked up. The page carries the app build it was served
  with, /api/realm reports the build the server holds now (`app_build`, the
  page and every app script and stylesheet), and app/update.js offers a
  refresh when they differ: a toast, or a reload on the next move to another
  page, never while someone types, with the reader's place kept.
- The item card says a tiny drop chance as "rare drop", never "0%", and
  several bosses dropping one item read under one "Drops from" heading.
- The guild bank grid groups a tab's stacks by kind when the read says it.
- A run's seats are chips: tank, healer, then damage, each linking to the
  member in its class colour, with a labelled role symbol, and no link
  nested inside another.

The JavaScript runs under node against small stand-ins for the browser.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
sys.path.insert(0, str(HERE))

import appbuild  # noqa: E402
import vclient  # noqa: E402

NODE = shutil.which("node")


def run_node(files, script):
    """Run `script` as an ES module beside `files` ({relative path: text});
    it prints JSON on its last line."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (root / "run.js").write_text(script, encoding="utf-8")
        out = subprocess.run(
            [NODE, str(root / "run.js")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


def app_file(name):
    return (APP / name).read_text(encoding="utf-8")


def text_of(markup):
    return re.sub(r"<[^>]+>", "", markup).replace("&#39;", "'")


# ---- the build a page runs, and the build the server holds -----------------------


class TheAppBuild(unittest.TestCase):
    def make_site(self, root):
        (root / "app" / "views").mkdir(parents=True)
        (root / "index.html").write_text("<html>__OVERSEER_BUILD__</html>")
        (root / "app" / "main.js").write_text("main")
        (root / "app" / "views" / "now.js").write_text("now")
        (root / "app" / "README.md").write_text("notes")

    def test_a_change_to_any_app_script_moves_the_build_and_nothing_else_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.make_site(root)
            first = appbuild.fingerprint(str(root))
            self.assertRegex(first, r"^[0-9a-f]{12}$")
            self.assertEqual(appbuild.fingerprint(str(root)), first)
            # Not a script or a stylesheet: the build is the same.
            (root / "app" / "README.md").write_text("other notes")
            self.assertEqual(appbuild.fingerprint(str(root)), first)
            # A view changed and index.html did not: the build moves.
            view = root / "app" / "views" / "now.js"
            view.write_text("now, changed")
            os.utime(view, ns=(1, 1))
            second = appbuild.fingerprint(str(root))
            self.assertNotEqual(second, first)
            (root / "app" / "views" / "new.css").write_text("x")
            self.assertNotEqual(appbuild.fingerprint(str(root)), second)

    def test_the_page_carries_the_placeholder_and_is_stamped(self):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="overseer-build" content="__OVERSEER_BUILD__">', page)
        self.assertEqual(
            appbuild.stamp(b"a __OVERSEER_BUILD__ b", "0123456789ab"),
            b"a 0123456789ab b",
        )

    def test_the_realm_and_the_served_page_name_the_same_build(self):
        sys.path.insert(0, str(HERE / "tests"))
        import test_app_shell as shell

        build = appbuild.fingerprint(str(HERE))
        h = shell.FakeHandler("/api/realm")
        with (
            mock.patch.object(shell.map_server, "_fetch_realm", return_value={}),
            mock.patch.object(shell.map_server.realm, "build_realm", return_value={}),
        ):
            h._realm({})
        payload = json.loads(h.body())
        self.assertEqual(payload["app_build"], build)
        # The fields readers already had are still there.
        self.assertIn("page", payload)
        self.assertIn("app_page", payload)
        page = shell.get("/").body().decode()
        self.assertIn('<meta name="overseer-build" content="%s">' % build, page)
        self.assertNotIn("__OVERSEER_BUILD__", page)


# ---- update.js: when the page refreshes ---------------------------------------------

UPDATE_HARNESS = r"""
const store = {};
let reloads = 0;
let active = { tagName: "BODY" };
globalThis.location = { hash: "#/members", reload() { reloads += 1; } };
globalThis.window = {
  scrollY: 640,
  sessionStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
  addEventListener() {}, setInterval() {}, requestAnimationFrame(fn) { fn(); }, scrollTo() {},
};
const appended = [];
globalThis.document = {
  hidden: false,
  get activeElement() { return active; },
  addEventListener() {},
  querySelector: (s) => (s === 'meta[name="overseer-build"]' ? { getAttribute: () => SERVED } : null),
  createElement: () => ({ setAttribute() {}, addEventListener() {}, set innerHTML(v) { this.markup = v; }, className: "" }),
  body: { appendChild: (el) => appended.push(el) },
};
let realm = { app_build: SERVED };
globalThis.REALM = (b) => { realm = { app_build: b }; };
"""

UPDATE_API_STUB = (
    "export const load = () => Promise.resolve({ data: globalThis.__realm() });\n"
    "export const peek = () => ({ data: globalThis.__realm() });\n"
    "export const onChange = () => {};\n"
)


def run_update(body, served="0123456789ab"):
    script = (
        "const SERVED = %s;\n" % json.dumps(served)
        + UPDATE_HARNESS
        + "globalThis.__realm = () => realm;\n"
        + 'const U = await import("./update.js");\n'
        + body
    )
    files = {
        "update.js": app_file("update.js"),
        "ui.js": app_file("ui.js"),
        "api.js": UPDATE_API_STUB,
    }
    return run_node(files, script)


class TheUpdatePickup(unittest.TestCase):
    def test_only_a_different_real_build_is_newer(self):
        out = run_update(
            "console.log(JSON.stringify([U.isNewer('0123456789ab', 'ba9876543210'),"
            " U.isNewer('0123456789ab', '0123456789ab'), U.isNewer('', 'ba9876543210'),"
            " U.isNewer('__OVERSEER_BUILD__', 'ba9876543210'), U.isNewer('0123456789ab', undefined)]));\n"
        )
        self.assertEqual(out, [True, False, False, False, False])

    def test_a_new_build_shows_the_toast_and_the_next_page_reloads(self):
        out = run_update(
            r"""
U.install();
await new Promise((r) => setTimeout(r, 0));
const before = [U.pendingUpdate(), appended.length];
REALM("ba9876543210");
await U.check();
const after = [U.pendingUpdate(), appended.length, String(appended[0].markup)];
// A filter on the same page is not a move: no reload.
location.hash = "#/members?stuck=1";
const filter = U.reloadIfPending();
// Typing in a field: no reload either.
active = { tagName: "INPUT" };
location.hash = "#/economy";
const typing = U.reloadIfPending();
active = { tagName: "BODY" };
location.hash = "#/raid/mc/cave";
const moved = U.reloadIfPending();
console.log(JSON.stringify({ before, after, filter, typing, moved, reloads }));
"""
        )
        self.assertEqual(out["before"], [False, 0])
        self.assertTrue(out["after"][0])
        self.assertEqual(out["after"][1], 1)
        self.assertIn("Updated, tap to refresh", out["after"][2])
        self.assertFalse(out["filter"])
        self.assertFalse(out["typing"])
        self.assertTrue(out["moved"])
        self.assertEqual(out["reloads"], 1)

    def test_the_same_build_never_reloads(self):
        out = run_update(
            r"""
U.install();
await U.check();
location.hash = "#/economy";
console.log(JSON.stringify({ moved: U.reloadIfPending(), reloads, toasts: appended.length }));
"""
        )
        self.assertEqual(out, {"moved": False, "reloads": 0, "toasts": 0})

    def test_the_toast_keeps_the_place_on_this_page(self):
        out = run_update(
            r"""
U.reloadHere();
const kept = JSON.parse(store["overseer.place"]);
const elsewhere = U.takePlace("#/economy");
store["overseer.place"] = JSON.stringify(kept);
const here = U.takePlace("#/members");
const again = U.takePlace("#/members");
console.log(JSON.stringify({ kept, reloads, elsewhere, here, again }));
"""
        )
        self.assertEqual(out["kept"], {"hash": "#/members", "y": 640})
        self.assertEqual(out["reloads"], 1)
        self.assertEqual(out["elsewhere"], 0)
        self.assertEqual(out["here"], 640)
        self.assertEqual(out["again"], 0)

    def test_main_asks_before_it_draws_a_new_page(self):
        main = app_file("main.js")
        self.assertIn("if (update.reloadIfPending()) return;", main)
        self.assertIn("window.scrollTo(0, update.takePlace(hash));", main)
        self.assertIn("update.install();", main)


# ---- the item card's drop chances ---------------------------------------------------

TOOLTIP_API_STUB = (
    "export const peek = () => ({ data: undefined });\n"
    "export const load = () => Promise.resolve();\n"
)


def card(sources):
    script = (
        'const T = await import("./tooltip.js");\n'
        "console.log(JSON.stringify({lines: T.lines(%s, 'X').map(String),"
        " chance: [0, 0.02, 0.05, 0.1, 0.88, 12.34, 20].map(T.chanceText)}));\n"
        % json.dumps({"tooltip": {"name": "X", "quality": 2}, "sources": sources})
    )
    files = {
        "tooltip.js": app_file("tooltip.js"),
        "ui.js": app_file("ui.js"),
        "api.js": TOOLTIP_API_STUB,
    }
    return run_node(files, script)


class TheDropChances(unittest.TestCase):
    def test_a_chance_too_small_to_show_is_a_rare_drop_never_zero(self):
        out = card(
            [
                {
                    "kind": "drop",
                    "boss": "Murta Grimgut",
                    "where": "Zul'Farrak",
                    "chance": 0.02,
                },
                {"kind": "world", "chance_max": 0.02},
            ]
        )
        self.assertEqual(
            out["chance"],
            ["rare drop", "rare drop", "rare drop", "0.1%", "0.9%", "12.3%", "20%"],
        )
        joined = " ".join(text_of(x) for x in out["lines"])
        self.assertNotIn("0%", joined.replace("20%", ""))
        self.assertIn("Source: World drop rare drop", joined)

    def test_several_bosses_read_under_one_drops_from_heading(self):
        out = card(
            [
                {
                    "kind": "drop",
                    "boss": "Blindlight Oracle",
                    "where": "Blackfathom Deeps",
                    "chance": 37.86,
                },
                {
                    "kind": "drop",
                    "boss": "Gelihast",
                    "where": "Blackfathom Deeps",
                    "chance": 28.0,
                },
                {"kind": "drop", "boss": "Ferra", "where": "Dire Maul", "chance": 1.0},
                {"kind": "quest", "quest": "Fins", "zone": "Ashenvale"},
            ]
        )
        rows = [text_of(x) for x in out["lines"]]
        self.assertEqual(rows.count("Drops from"), 1)
        self.assertFalse(any(r.startswith("Source: Drop") for r in rows))
        self.assertEqual(rows.count("Blackfathom Deeps"), 1)
        self.assertIn("Blindlight Oracle 37.9%", rows)
        self.assertIn("Gelihast 28%", rows)
        self.assertIn("Ferra 1%", rows)
        self.assertIn("Source: Quest", rows)
        heading = next(x for x in out["lines"] if "Drops from" in x)
        self.assertIn("ln-src ln-sep", heading)

    def test_one_drop_keeps_its_source_line(self):
        out = card(
            [
                {
                    "kind": "drop",
                    "boss": "Edwin VanCleef",
                    "where": "The Deadmines",
                    "chance": 12.34,
                }
            ]
        )
        rows = [text_of(x) for x in out["lines"]]
        self.assertIn("Source: Drop 12.3% chance", rows)
        self.assertNotIn("Drops from", rows)

    def test_the_new_rows_have_card_rules(self):
        css = app_file("app.css")
        for sel in (".tipcard .ln-zone", ".tipcard .ln-drop"):
            self.assertIn(sel + " {", css)


# ---- the guild bank grid's headers --------------------------------------------------


class TheBankCategories(unittest.TestCase):
    def test_classes_and_trade_goods_name_their_kind(self):
        cases = {
            (7, 5): "Cloth",
            (7, 9): "Herbs",
            (3, 0): "Gems",
            (7, 4): "Gems",
            (9, 2): "Recipes",
            (7, 11): "Other trade goods",
            (15, 0): "Miscellaneous",
            (42, 0): "Other",
        }
        for (cls, sub), label in cases.items():
            with self.subTest(cls=cls, sub=sub):
                got = vclient.item_category({"item_class": cls, "item_subclass": sub})
                self.assertEqual(got["category"], label)
        self.assertLess(
            vclient.item_category({"item_class": 7, "item_subclass": 5})[
                "category_rank"
            ],
            vclient.item_category({"item_class": 9, "item_subclass": 0})[
                "category_rank"
            ],
        )
        self.assertEqual(vclient.item_category({}), {})

    def test_the_guild_bank_cells_carry_their_category(self):
        bank = vclient.build_guild_bank(
            {"guild_id": 1, "guild_name": "Cave", "bank_money": 0},
            [{"tab_id": 0, "tab_name": "Materials"}],
            [
                {
                    "tab_id": 0,
                    "slot_id": 0,
                    "entry": 4306,
                    "count": 20,
                    "item_name": "Silk Cloth",
                    "quality": 1,
                    "item_class": 7,
                    "item_subclass": 5,
                },
            ],
            {},
        )
        cell = bank["tabs"][0]["cells"][0]
        self.assertEqual(cell["category"], "Cloth")
        self.assertEqual(cell["count"], 20)

    def test_the_grid_groups_by_category_in_rank_order(self):
        script = (
            "globalThis.window = { addEventListener() {} };\n"
            'const E = await import("./views/economy.js");\n'
            "const cells = [{entry: 1, category: 'Recipes', category_rank: 10},"
            " {entry: 2, category: 'Cloth', category_rank: 0}, {entry: 3, category: 'Recipes', category_rank: 10}];\n"
            "const plain = [{entry: 4}, {entry: 5}];\n"
            "console.log(JSON.stringify({groups: E.bankGroups(cells).map((g) => [g.label, g.cells.map((c) => c.entry)]),"
            " plain: E.bankGroups(plain).map((g) => [g.label, g.cells.length])}));\n"
        )
        files = {
            "views/economy.js": app_file("views/economy.js"),
            "ui.js": app_file("ui.js"),
            "router.js": app_file("router.js"),
            "api.js": TOOLTIP_API_STUB,
        }
        out = run_node(files, script)
        self.assertEqual(out["groups"], [["Cloth", [2]], ["Recipes", [1, 3]]])
        self.assertEqual(out["plain"], [["", 2]])


# ---- a run's seats ---------------------------------------------------------------------

RUN = {
    "id": 514,
    "place": "The Deadmines",
    "state": "inside",
    "bosses_total": 7,
    "bosses_done": 2,
    "seconds_inside": 600,
    "members": [
        {"name": "Snipp", "seat": "dps", "class": "mage", "level": 20},
        {"name": "Clate", "seat": "healer", "class": "priest", "level": 20},
        {"name": "Tugga", "seat": "dps", "class": "hunter", "level": 21},
        {"name": "Crag", "seat": "tank", "class": "warrior", "level": 21},
    ],
}


def run_markup():
    script = (
        "globalThis.window = { addEventListener() {} };\n"
        'const R = await import("./views/_runs.js");\n'
        "const r = %s;\n"
        "console.log(JSON.stringify({chips: String(R.seatChips(r)), card: String(R.runCard(r)),"
        " done: String(R.runCard(Object.assign({}, r, {state: 'done', outcome: 'cleared'}), {done: true})),"
        " rows: R.seatRows(r).map(String)}));\n" % json.dumps(RUN)
    )
    files = {
        "views/_runs.js": app_file("views/_runs.js"),
        "ui.js": app_file("ui.js"),
        "api.js": TOOLTIP_API_STUB,
    }
    return run_node(files, script)


class TheRunSeats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_markup()

    def test_seats_read_tank_healer_then_damage(self):
        names = re.findall(r'href="#/m/(\w+)"', self.out["chips"])
        self.assertEqual(names, ["Crag", "Clate", "Snipp", "Tugga"])
        rows = [re.search(r'href="#/m/(\w+)"', x).group(1) for x in self.out["rows"]]
        self.assertEqual(rows, ["Crag", "Clate", "Snipp", "Tugga"])

    def test_each_seat_links_to_its_member_in_its_class_colour(self):
        chips = self.out["chips"]
        self.assertIn(
            'href="#/m/Crag" style="color:var(--cls-warrior, var(--color-text))"', chips
        )
        self.assertIn(
            'href="#/m/Clate" style="color:var(--cls-priest, var(--color-text))"', chips
        )

    def test_tank_and_healer_symbols_have_words(self):
        chips = self.out["chips"]
        self.assertIn(
            'class="ph-fill ph-shield seat-ic seat-tank" role="img" aria-label="tank"',
            chips,
        )
        self.assertIn(
            'class="ph-fill ph-first-aid seat-ic seat-healer" role="img" aria-label="healer"',
            chips,
        )
        self.assertEqual(chips.count('aria-label="tank"'), 1)
        self.assertEqual(chips.count('aria-label="healer"'), 1)
        # Damage dealers carry no symbol.
        self.assertEqual(chips.count("seat-ic"), 2)
        self.assertIn('aria-label="tank"', self.out["rows"][0])

    def test_no_link_is_nested_in_another(self):
        for key in ("card", "done"):
            depth = 0
            for tag in re.findall(r"<(/?)a[\s>]", self.out[key]):
                depth += -1 if tag else 1
                self.assertLessEqual(depth, 1, key)
            self.assertEqual(depth, 0, key)
        self.assertIn(
            'class="g-run-name stretch-link" href="#/runs/514" data-run="514"',
            self.out["card"],
        )
        self.assertIn("Crag", self.out["done"])

    def test_every_seat_list_uses_the_chips(self):
        now = app_file("views/now.js")
        guild = app_file("views/guild.js")
        self.assertIn("${seatChips(r)}", now)
        self.assertIn("${seatChips(r)}", guild)
        self.assertNotIn('(r.members || []).map((m) => m.name).join(", ")', now + guild)

    def test_a_seat_is_a_44px_tap_on_a_touch_screen(self):
        css = re.sub(r"/\*.*?\*/", "", app_file("app.css"), flags=re.S)
        coarse = css[css.rindex("@media (pointer: coarse)") :]
        self.assertRegex(coarse, r"\.seat-chip\s*\{[^}]*min-height:\s*44px")


if __name__ == "__main__":
    unittest.main()
