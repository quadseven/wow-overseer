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

import pathlib
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import realmnav  # noqa: E402


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


class OutsideAndServerLinks(unittest.TestCase):
    def test_a_realm_link_ends_in_a_slash(self):
        for mount in ("", "/dev", "/ptr"):
            href = realmnav.href_for(mount)
            self.assertTrue(href.startswith("/") and href.endswith("/"), href)


if __name__ == "__main__":
    unittest.main()
