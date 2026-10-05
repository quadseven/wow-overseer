"""An in-page jump link scrolls to its card instead of changing the view.

The operator tapped Grog in the Armory and landed on Grug's family page: the
member chips are anchors (#aprof-Grog), and the hub router read the anchor as a
route, found no view by that name and fell back to the family view. applyHash
is run under node with a fake document: an anchor naming a card on the shown
view scrolls to it and keeps the view.
"""

import json
import pathlib
import shutil
import subprocess
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")


def fn(name):
    js = PAGE[PAGE.index("function %s(" % name) :]
    return js[: js.index("\n}\n") + 3]


HARNESS = """
const MAP_VIEW = "map", FAMILY_VIEW = "family", ARMORY_VIEW = "armory",
  DUNGEONS_VIEW = "dungeons", CHRONICLE_VIEW = "chronicle";
const HASH_VIEWS = [FAMILY_VIEW, ARMORY_VIEW, DUNGEONS_VIEW, CHRONICLE_VIEW];
const HASH_ALIASES = new Map();
let view = ARMORY_VIEW, shown = [], scrolled = [], replaced = [];
let wantedContinent = "", familyKey = "", dungeonTargetMap = null;
function adoptContinent() {} function render() {} function pollAgenda() {}
function hashFor(v) { return "#" + v; }
function showView(v) { view = v; shown.push(v); }
const cards = { "aprof-Grog": { hidden: false } };
globalThis.window = { matchMedia: () => ({ matches: true }) };
globalThis.history = { replaceState: (a, b, h) => replaced.push(h) };
globalThis.document = { getElementById: (id) => cards[id] ? {
  closest: () => ({ hidden: cards[id].hidden }),
  scrollIntoView: () => scrolled.push(id) } : null };
globalThis.location = { hash: "" };
"""


def run(hash_, hidden=False):
    script = (
        HARNESS
        + ('cards["aprof-Grog"].hidden = %s;\n' % ("true" if hidden else "false"))
        + ("location.hash = %s;\n" % json.dumps(hash_))
        + fn("applyHash")
        + "applyHash();\n"
        + "process.stdout.write(JSON.stringify({view, shown, scrolled, replaced}));"
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


@unittest.skipUnless(shutil.which("node"), "needs node to run applyHash")
class AJumpLinkScrolls(unittest.TestCase):
    def test_a_member_chip_scrolls_and_keeps_the_armory(self):
        got = run("#aprof-Grog")
        self.assertEqual(got["view"], "armory")
        self.assertEqual(got["shown"], [])
        self.assertEqual(got["scrolled"], ["aprof-Grog"])
        self.assertEqual(got["replaced"], ["#armory"])

    def test_a_view_hash_still_routes(self):
        got = run("#chronicle")
        self.assertEqual(got["view"], "chronicle")
        self.assertEqual(got["scrolled"], [])

    def test_an_unknown_hash_still_falls_back_to_family(self):
        got = run("#nothing-here")
        self.assertEqual(got["view"], "family")

    def test_a_card_on_a_hidden_view_routes_as_before(self):
        got = run("#aprof-Grog", hidden=True)
        self.assertEqual(got["view"], "family")


if __name__ == "__main__":
    unittest.main()
