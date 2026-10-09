"""An in-page jump link scrolls to its card instead of changing the view.

The operator tapped Grog in the Armory and landed on Grug's family page: the
member chips are anchors (#aprof-Grog), and the hub router read the anchor as a
route, found no view by that name and fell back to the family view.

Two paths reach a card now, and both are run under node with a fake document:
a TAP, which the page's click handler catches before the address bar ever
changes, and a TYPED or pasted anchor, which applyHash opens in the view that
holds the card (on a cold load, before the card is drawn, by its id's prefix).
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "classic.html").read_text(encoding="utf-8")


def fn(name):
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


def anchor_click_handler():
    """The page's one delegated click handler for in-page links."""
    start = PAGE.index(
        'document.addEventListener("click", (e) => {\n  if (e.defaultPrevented'
    )
    return PAGE[start : PAGE.index("\n});\n", start) + 5]


HARNESS = """
const MAP_VIEW = "map", FAMILY_VIEW = "family", ARMORY_VIEW = "armory",
  DUNGEONS_VIEW = "dungeons", CHRONICLE_VIEW = "chronicle";
const HASH_VIEWS = [FAMILY_VIEW, ARMORY_VIEW, DUNGEONS_VIEW, CHRONICLE_VIEW];
const HASH_ALIASES = new Map([["achievements", CHRONICLE_VIEW]]);
let view = ARMORY_VIEW, shown = [], jumped = [], replaced = [];
let wantedContinent = "", familyKey = "", dungeonTargetMap = null, dungeonScrolledTo = null;
function adoptContinent() {} function render() {} function pollAgenda() {}
function hashFor(v) { return "#" + v; }
function showView(v) { view = v; shown.push(v); }
function jumpWhenDrawn(id) { jumped.push(id); }
// Cards on the page, by id, and the view section each one sits in.
const cards = { "aprof-Grog": "armory", "stcard-Grog": "armory", "chr-note": "chronicle" };
let drawn = true;
globalThis.history = { replaceState: (a, b, h) => replaced.push(h) };
globalThis.document = {
  getElementById: (id) => drawn && cards[id] ? {
    closest: (sel) => sel === "body > section" ? { id: cards[id] } : null } : null,
  addEventListener: (type, f) => { globalThis.clickHandler = f; } };
globalThis.Element = function () {};
globalThis.location = { hash: "" };
"""

FUNCS = ["routeName", "isRoute", "viewHolding", "anchorView", "openAnchor", "applyHash"]


def run(body, start_view="armory", drawn=True):
    script = (
        HARNESS
        + (
            "view = %s; drawn = %s;\n"
            % (json.dumps(start_view), "true" if drawn else "false")
        )
        + PAGE[
            PAGE.index("const ANCHOR_VIEWS") : PAGE.index(
                ";\n", PAGE.index("const ANCHOR_VIEWS")
            )
            + 2
        ]
        + "".join(fn(f) for f in FUNCS)
        + anchor_click_handler()
        + body
        + "process.stdout.write(JSON.stringify({view, shown, jumped, replaced, out: globalThis.out}));"
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


def hashed(h, **kw):
    return run("location.hash = %s;\napplyHash();\n" % json.dumps(h), **kw)


def tapped(href, **kw):
    # A link element: closest() finds itself for the anchor selector.
    return run(
        """
const link = Object.create(Element.prototype);
link.getAttribute = () => %s;
link.closest = (sel) => sel === 'a[href^="#"]' ? link : null;
let prevented = false;
clickHandler({ defaultPrevented: false, button: 0, target: link,
               preventDefault: () => { prevented = true; } });
globalThis.out = { prevented };
"""
        % json.dumps(href),
        **kw,
    )


@unittest.skipUnless(shutil.which("node"), "needs node to run the router")
class AJumpLinkScrolls(unittest.TestCase):
    def test_a_tapped_member_chip_scrolls_and_keeps_the_armory(self):
        got = tapped("#aprof-Grog")
        self.assertTrue(
            got["out"]["prevented"], "the browser would have changed the hash"
        )
        self.assertEqual(got["view"], "armory")
        self.assertEqual(got["shown"], [])
        self.assertEqual(got["jumped"], ["aprof-Grog"])

    def test_a_tapped_route_link_is_left_to_the_router(self):
        for href in ("#dungeons/33", "#chronicle", "#achievements"):
            got = tapped(href)
            self.assertFalse(got["out"]["prevented"], href)
            self.assertEqual(got["jumped"], [], href)

    def test_a_typed_member_chip_scrolls_and_keeps_the_armory(self):
        got = hashed("#aprof-Grog")
        self.assertEqual(got["view"], "armory")
        self.assertEqual(got["shown"], [])
        self.assertEqual(got["jumped"], ["aprof-Grog"])
        self.assertEqual(got["replaced"], ["#armory"])

    def test_a_card_on_another_view_opens_that_view(self):
        got = hashed("#stcard-Grog", start_view="chronicle")
        self.assertEqual(got["view"], "armory")
        self.assertEqual(got["jumped"], ["stcard-Grog"])

    def test_a_cold_anchor_opens_the_view_its_card_will_be_drawn_in(self):
        got = hashed("#aprof-Grog", start_view="map", drawn=False)
        self.assertEqual(got["view"], "armory")
        self.assertEqual(got["jumped"], ["aprof-Grog"])

    def test_a_view_hash_still_routes(self):
        got = hashed("#chronicle")
        self.assertEqual(got["view"], "chronicle")
        self.assertEqual(got["jumped"], [])

    def test_a_malformed_hash_falls_back_to_family(self):
        got = hashed("#%E0%A4%A")
        self.assertEqual(got["view"], "family")
        self.assertEqual(got["jumped"], [])

    def test_an_unknown_hash_still_falls_back_to_family(self):
        got = hashed("#nothing-here")
        self.assertEqual(got["view"], "family")
        self.assertEqual(got["jumped"], [])


if __name__ == "__main__":
    unittest.main()
