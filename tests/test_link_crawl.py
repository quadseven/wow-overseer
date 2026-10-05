"""Every link the page can draw goes somewhere that exists.

The operator asked for every link to work. A link here is one of four things,
and each has its own way of being wrong:

  a ROUTE (#dungeons/33, #chronicle)  - must open the view it names, not fall
                                        back to the family page;
  an ANCHOR (#aprof-Grog)             - must name a card the page builds, in
                                        a view the router knows to open;
  an OUTSIDE page (wowhead, a ticket) - must open in a new tab without
                                        handing that page this one;
  a SERVER path (u("/..."))           - must be a route map_server serves, or
                                        the one sibling app the page probes.

The crawl reads the markup's hrefs and every `.href =` the scripts assign, and
holds them against the table below. A link added without a row here fails the
first test, which is the point: it has to be classified before it ships.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402  (must follow the pymysql stub)
import realmnav  # noqa: E402

PAGE = (HERE / "index.html").read_text(encoding="utf-8")

# Every href the page assigns or writes, by its exact right-hand side, and
# what kind of link it is. For routes and anchors, the sample is a real value
# of the expression; for the rest it is what to check.
LINKS = {
    # markup
    '"#dungeons"': ("route", "#dungeons", "dungeons"),
    # scripts
    "row[1]": ("server", None, None),  # the head's manifest and icons
    'u("/recordings/?c=dev-grug")': ("sibling", None, None),
    "href": ("built", None, None),  # gcDungeonHref and itemTipLink, below
    '"#dungeons/" + encodeURIComponent(c.map_id)': (
        "route",
        "#dungeons/33",
        "dungeons",
    ),
    '"#" + prof.id': ("anchor", "#aprof-Grog", "armory"),
    '"#chronicle"': ("route", "#chronicle", "chronicle"),
    '"#" + card.id': ("anchor", "#stcard-Grog", "armory"),
    "item.wowhead": ("outside", None, None),
    "m.wowhead": ("outside", None, None),
    "t.wowhead": ("outside", None, None),
    "s.ticket.url": ("outside", None, None),
    "t.url": ("outside", None, None),
    "r.href": ("realm", None, None),
}

# The two `href` variables: what each is built from.
BUILT = {
    "gcDungeonHref": ('"#dungeons/" + ask.target', "#dungeons/33", "dungeons"),
}


def page_hrefs():
    """(right-hand side, line number) for every href on the page."""
    found = []
    for n, line in enumerate(PAGE.splitlines(), 1):
        if line.lstrip().startswith("//"):
            continue
        for m in re.finditer(r'<a\b[^>]*\bhref="([^"]*)"', line):
            found.append(('"%s"' % m.group(1), n))
        m = re.search(r"\.href = (.+);\s*$", line)
        if m:
            found.append((m.group(1), n))
    return found


def fn(name):
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


HARNESS = """
const HASH_VIEWS = %s;
const MAP_VIEW = "map", FAMILY_VIEW = "family", ARMORY_VIEW = "armory",
  DUNGEONS_VIEW = "dungeons", CHRONICLE_VIEW = "chronicle";
%s
let view = "watch", wantedContinent = "", familyKey = "", dungeonTargetMap = null,
  dungeonScrolledTo = null;
function adoptContinent() {} function render() {} function pollAgenda() {}
function hashFor(v) { return "#" + v; }
function showView(v) { view = v; }
function jumpWhenDrawn(id) {}
globalThis.history = { replaceState: () => {} };
globalThis.document = { getElementById: () => null };
globalThis.location = { hash: "" };
"""


def route_of(hashes):
    """The view applyHash opens for each hash, run under node."""
    views = re.search(r"const HASH_VIEWS = \[(.*?)\];", PAGE, re.S).group(1)
    names = [v.strip() for v in views.split(",")]
    consts = dict(re.findall(r'const (\w+_VIEW) = "(\w+)";', PAGE))
    hash_views = json.dumps([consts[n] for n in names])
    aliases = re.search(r"const HASH_ALIASES = .*?;\n", PAGE).group(0)
    script = (
        HARNESS % (hash_views, aliases)
        + PAGE[
            PAGE.index("const ANCHOR_VIEWS") : PAGE.index(
                ";\n", PAGE.index("const ANCHOR_VIEWS")
            )
            + 2
        ]
        + "".join(
            fn(f)
            for f in (
                "routeName",
                "isRoute",
                "viewHolding",
                "anchorView",
                "openAnchor",
                "applyHash",
            )
        )
        + "const out = {};\n"
        + "for (const h of %s) { view = 'watch'; location.hash = h; applyHash(); out[h] = view; }\n"
        % json.dumps(hashes)
        + "process.stdout.write(JSON.stringify(out));"
    )
    run = subprocess.run(
        [shutil.which("node"), "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if run.returncode != 0:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


class EveryLinkIsClassified(unittest.TestCase):
    def test_no_link_is_missing_from_the_table(self):
        unknown = [(rhs, n) for rhs, n in page_hrefs() if rhs not in LINKS]
        self.assertEqual(unknown, [], "a link with no row in LINKS: classify it")

    def test_the_crawl_found_the_links_it_should(self):
        # A crawl that finds nothing passes the test above vacuously.
        self.assertGreaterEqual(len(page_hrefs()), len(LINKS))

    def test_the_built_hrefs_are_built_where_the_table_says(self):
        self.assertIn(
            'return ask.kind === "dungeon" && /^\\d+$/.test(String(ask.target)) '
            '? "#dungeons/" + ask.target : "";',
            fn("gcDungeonHref"),
        )
        # The tooltip's outside link is the payload's address, opened beside.
        self.assertIn('<a id="itemtipout" target="_blank" rel="noopener">', PAGE)


@unittest.skipUnless(shutil.which("node"), "needs node to run the router")
class RoutesAndAnchorsOpenTheirView(unittest.TestCase):
    def test_every_route_and_anchor_opens_the_view_it_names(self):
        rows = [v for v in LINKS.values() if v[0] in ("route", "anchor")] + list(
            BUILT.values()
        )
        got = route_of([sample for _kind, sample, _want in rows])
        for _kind, sample, want in rows:
            self.assertEqual(got[sample], want, sample)

    def test_every_view_address_opens_itself(self):
        consts = dict(re.findall(r'const (\w+_VIEW) = "(\w+)";', PAGE))
        views = re.search(r"const HASH_VIEWS = \[(.*?)\];", PAGE, re.S).group(1)
        names = [consts[v.strip()] for v in views.split(",")]
        got = route_of(
            ["#" + v for v in names] + ["#map/0", "#achievements", "#family/Grug"]
        )
        for v in names:
            self.assertEqual(got["#" + v], v)
        self.assertEqual(got["#map/0"], "map")
        self.assertEqual(got["#achievements"], "chronicle")
        self.assertEqual(got["#family/Grug"], "family")

    def test_every_anchor_prefix_is_an_id_the_page_builds(self):
        prefixes = re.findall(
            r'\["(\w+-)", (\w+_VIEW)\]', PAGE[PAGE.index("const ANCHOR_VIEWS") :][:200]
        )
        self.assertTrue(prefixes)
        for prefix, _view in prefixes:
            self.assertRegex(PAGE, r'\.id = "%s" \+ name;' % re.escape(prefix))


class OutsideAndServerLinks(unittest.TestCase):
    def test_every_outside_link_opens_beside_the_page(self):
        lines = PAGE.splitlines()
        for rhs, n in page_hrefs():
            if LINKS.get(rhs, ("",))[0] != "outside":
                continue
            near = "\n".join(lines[n - 1 : n + 3])
            self.assertIn('.target = "_blank";', near, "line %d" % n)
            self.assertIn('.rel = "noopener";', near, "line %d" % n)

    def test_every_server_path_is_a_route_the_server_serves(self):
        head = PAGE[PAGE.index("THE HOME SCREEN FILES (the meta tags") :][:900]
        paths = re.findall(r'u\("(/[^"]+)"\)', head)
        self.assertEqual(len(paths), 3)
        for p in paths:
            self.assertIn(p, map_server.Handler.GET_ROUTES)

    def test_a_realm_link_ends_in_a_slash(self):
        for mount in ("", "/dev", "/ptr"):
            href = realmnav.href_for(mount)
            self.assertTrue(href.startswith("/") and href.endswith("/"), href)


if __name__ == "__main__":
    unittest.main()
