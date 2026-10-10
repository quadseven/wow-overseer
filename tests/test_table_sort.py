"""The two sortable roster tables, Members (app/views/members.js) and the gear
table (app/views/gear.js), run under node with a stand-in page: a header
click on the column already sorted reverses it, aria-sort says the direction
the rows are in, and the direction lives in the URL query.
"""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

# A page just big enough for a view's after(): every element is a stand-in
# that remembers its markup and its listeners, and replaceState moves the
# address bar the view reads its query from.
PAGE = """
globalThis.window = {setTimeout: (f) => f(), addEventListener() {}};
globalThis.location = {hash: START};
globalThis.history = {replaceState: (_s, _t, url) => { location.hash = url; }};
globalThis.document = {querySelector: () => null, addEventListener() {}};
function el() {
  return {innerHTML: "", value: "", textContent: "", on: {}, focused: false,
    addEventListener(t, f) { this.on[t] = f; }, querySelector: (s) => main.querySelector(s), querySelectorAll: () => [],
    setAttribute() {}, focus() { this.focused = true; }};
}
const els = new Map();
const main = {querySelector: (s) => { if (!els.has(s)) els.set(s, el()); return els.get(s); }, querySelectorAll: () => []};
function button(attrs) {
  return {getAttribute: (n) => (n in attrs ? attrs[n] : null), hasAttribute: (n) => n in attrs};
}
function click(wrap, attrs) { main.querySelector(wrap).on.click({target: {closest: () => button(attrs)}}); }
function ctx(tab, reads) {
  return {view: VIEW, section: "members", params: {tab}, query: {}, hash: START, isPhone: false,
    get: (p) => (p in reads ? {data: reads[p], at: 1, error: null} : {data: undefined, at: 0, error: null, loading: true})};
}
"""


def run(view, start, script):
    """Run `script` with the app copied to a module package; V is the view."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        code = (
            "const START = %s, VIEW = %s;\n%s\n"
            "const V = (await import(%s)).default;\n"
            "const M = await import(%s);\n%s"
        ) % (
            json.dumps(start),
            json.dumps(view),
            PAGE,
            json.dumps((root / "views" / (view + ".js")).as_uri()),
            json.dumps((root / "views" / "_members.js").as_uri()),
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


def member(name, level, stuck=False, since=None):
    return {
        "name": name,
        "level": level,
        "class": "Warrior",
        "guild": "Cave",
        "zone": "Durotar",
        "stuck": stuck,
        "since": since,
        "blocker": "waiting on a party" if stuck else "",
        "step": "questing",
        "family": True,
        "life": "alive",
        "online": True,
    }


ROSTER = {
    "checked_at": 10000,
    "members": [
        member("Grug", 20, stuck=True, since=4000),
        member("Zug", 30, stuck=True, since=9000),
        member("Og", 10),
    ],
    "basis": "",
}


def gear(name, ilvl):
    return {
        "name": name,
        "class": "Warrior",
        "level": 20,
        "role": "tank",
        "avg_item_level": ilvl,
        "worn": 12,
        "empty": 2,
        "weapon": True,
        "weakest": None,
        "gold": None,
        "flags": [],
        "presence": "online",
        "guild": "Cave",
    }


GUILDGEAR = {
    "guilds": [
        {
            "guild": "Cave",
            "members": [gear("Grug", 21), gear("Zug", 35), gear("Og", 9)],
        }
    ]
}

READS = json.dumps({"/api/v2/roster": ROSTER, "/api/guildgear": GUILDGEAR})


def heads(markup):
    """{column key: aria-sort or None} for every sortable header."""
    out = {}
    for th in re.findall(r"<th[^>]*>.*?</th>", markup):
        key = re.search(r'data-g?sort="([a-z]+)"', th)
        if key:
            sort = re.search(r'aria-sort="([a-z]+)"', th)
            out[key.group(1)] = sort.group(1) if sort else None
    return out


def order(markup):
    """Member names in table row order."""
    body = markup.split("<tbody>", 1)[1]
    return re.findall(r'class="mname"[^>]*>([A-Za-z]+)</a>', body)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheMembersTable(unittest.TestCase):
    def clicks(self, start, keys):
        """The address bar and the table after clicking each header in turn."""
        script = (
            "const c = ctx(undefined, %s);\nconst first = V.render(c).s;\nV.after(main, c);\n"
            "const steps = [];\n"
            "for (const k of %s) { click('.ro-wrap', {'data-sort': k});"
            " steps.push([location.hash, main.querySelector('[data-region=roster]').innerHTML]); }\n"
            "console.log(JSON.stringify({first, steps}));"
        ) % (READS, json.dumps(keys))
        return run("members", start, script)

    def test_the_sorted_column_reverses_on_a_second_click(self):
        got = self.clicks("#/members", ["stuck", "stuck"])
        # Stuck longest first by default: Grug since 4000, then Zug, then Og.
        self.assertEqual(heads(got["first"])["stuck"], "descending")
        self.assertEqual(order(got["first"]), ["Grug", "Zug", "Og"])
        hash1, table1 = got["steps"][0]
        self.assertIn("sort=stuck", hash1)
        self.assertIn("dir=asc", hash1)
        self.assertEqual(heads(table1)["stuck"], "ascending")
        self.assertEqual(order(table1), ["Og", "Zug", "Grug"])
        hash2, table2 = got["steps"][1]
        self.assertIn("dir=desc", hash2)
        self.assertEqual(heads(table2)["stuck"], "descending")
        self.assertEqual(order(table2), ["Grug", "Zug", "Og"])

    def test_a_new_column_starts_in_its_own_direction(self):
        got = self.clicks("#/members?sort=level&dir=asc", ["name", "level"])
        hash1, table1 = got["steps"][0]
        self.assertIn("sort=name", hash1)
        self.assertIn("dir=asc", hash1)
        self.assertEqual(order(table1), ["Grug", "Og", "Zug"])
        hash2, table2 = got["steps"][1]
        self.assertIn("dir=desc", hash2)
        self.assertEqual(
            heads(table2),
            {"name": None, "level": "descending", "ilvl": None, "stuck": None},
        )
        self.assertEqual(order(table2), ["Zug", "Grug", "Og"])

    def test_aria_sort_says_the_direction_the_rows_are_in(self):
        # Name runs A to Z, which is ascending, whatever the other columns do.
        got = self.clicks("#/members?sort=name", [])
        self.assertEqual(heads(got["first"])["name"], "ascending")
        self.assertEqual(order(got["first"]), ["Grug", "Og", "Zug"])

    def test_a_linked_direction_is_read_back_from_the_query(self):
        got = self.clicks("#/members?sort=ilvl&dir=asc", [])
        self.assertEqual(heads(got["first"])["ilvl"], "ascending")
        self.assertEqual(order(got["first"]), ["Og", "Grug", "Zug"])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheGearTable(unittest.TestCase):
    def clicks(self, start, steps):
        script = (
            "const c = ctx('table', %s);\nconst first = V.render(c).s;\nV.after(main, c);\n"
            "const steps = [];\n"
            "for (const a of %s) { click('.gt-wrap', a);"
            " steps.push([location.hash, main.querySelector('[data-region=gtable]').innerHTML]); }\n"
            "console.log(JSON.stringify({first, steps}));"
        ) % (READS, json.dumps(steps))
        return run("gear", start, script)

    def test_the_sorted_column_reverses_every_time(self):
        ilvl = {"data-gsort": "ilvl"}
        got = self.clicks("#/members/gear/table", [ilvl, ilvl, ilvl])
        hashes = [h for h, _ in got["steps"]]
        self.assertTrue(hashes[0].endswith("sort=ilvl"), hashes[0])
        self.assertTrue(hashes[1].endswith("sort=-ilvl"), hashes[1])
        # The third click reverses again rather than dropping the sort.
        self.assertTrue(hashes[2].endswith("sort=ilvl"), hashes[2])
        self.assertEqual(heads(got["steps"][0][1])["ilvl"], "ascending")
        self.assertEqual(order(got["steps"][0][1]), ["Og", "Grug", "Zug"])
        self.assertEqual(heads(got["steps"][1][1])["ilvl"], "descending")
        self.assertEqual(order(got["steps"][1][1]), ["Zug", "Grug", "Og"])

    def test_worst_first_comes_back_from_its_own_button(self):
        got = self.clicks("#/members/gear/table?sort=-ilvl", [{"data-gworst": ""}])
        self.assertIn("data-gworst", got["first"])
        hash1, table1 = got["steps"][0]
        self.assertNotIn("sort=", hash1)
        self.assertEqual(set(heads(table1).values()), {None})


@unittest.skipUnless(shutil.which("node"), "node is needed to run the app's modules")
class TheSortHelpers(unittest.TestCase):
    def test_flip_sort(self):
        got = run(
            "members",
            "#/members",
            "console.log(JSON.stringify(["
            "M.flipSort({key: 'a', dir: 'asc'}, 'a', 'asc'),"
            "M.flipSort({key: 'a', dir: 'desc'}, 'a', 'asc'),"
            "M.flipSort({key: 'a', dir: 'asc'}, 'b', 'desc')]));",
        )
        self.assertEqual(
            got,
            [
                {"key": "a", "dir": "desc"},
                {"key": "a", "dir": "asc"},
                {"key": "b", "dir": "desc"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
