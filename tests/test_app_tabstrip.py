"""A view's tab strip keeps its lit tab on screen on a phone.

A strip wider than the screen scrolls sideways. Measured at 360px with a
fixture realm before this change: Economy's strip opened at its start with
"Guild bank" lit at 396..466px, wholly off a strip that ends at 348px, and a
profile's "Activity" was cut at the right edge. app/tabstrip.js brings the
current tab into view on a new page and keeps where the reader scrolled the
strip across the redraws every answered read causes. These tests run it under
node against a small stand-in for the strip, and check main.js calls it on
every draw.
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
MAIN = (APP / "main.js").read_text(encoding="utf-8")

NODE = shutil.which("node")
needs_node = unittest.skipIf(NODE is None, "node is not on PATH")

# A strip of tabs laid out left to right with a 20px gap, `width` px wide at
# x=12 on the page, like the app's phone gutter.
SCRIPT = r"""
const { revealLeft, stripPlaces, placeStrips } = await import("./app/tabstrip.js");
function strip(label, widths, current, width) {
  const tabs = [];
  let x = 0;
  for (let i = 0; i < widths.length; i++) { tabs.push({ start: x, end: x + widths[i], current: i === current }); x += widths[i] + 20; }
  const s = {
    label, scrollWidth: x - 20, clientWidth: width, _left: 0,
    get scrollLeft() { return this._left; },
    set scrollLeft(v) { this._left = Math.max(0, Math.min(v, this.scrollWidth - this.clientWidth)); },
    getAttribute: (k) => (k === "aria-label" ? label : null),
    getBoundingClientRect: () => ({ left: 12, right: 12 + width }),
    querySelector(sel) {
      const t = tabs.find((n) => n.current);
      return sel === '[aria-current="page"]' && t ? { getBoundingClientRect: () => ({ left: 12 + t.start - s._left, width: t.end - t.start }) } : null;
    },
    tab: (i) => ({ left: 12 + tabs[i].start - s._left, right: 12 + tabs[i].end - s._left }),
  };
  return s;
}
const rootOf = (strips) => ({ querySelectorAll: (sel) => (sel === "nav.tabs" ? strips : []) });
const ECON = [95, 95, 46, 69, 71]; // Bags and gold, Auction house, Trades, Skill levels, Guild bank
const out = {};

// A new page: the lit tab is brought on screen.
const bank = strip("Economy views", ECON, 4, 336);
placeStrips(rootOf([bank]), null);
out.bank = bank.tab(4);
const first = strip("Economy views", ECON, 0, 336);
placeStrips(rootOf([first]), null);
out.first = { left: first.scrollLeft, tab: first.tab(0) };
const middle = strip("Economy views", ECON, 3, 336);
placeStrips(rootOf([middle]), null);
out.middle = middle.tab(3);

// A redraw: the strip goes back where the reader left it, even off the lit tab.
const before = strip("Economy views", ECON, 0, 336);
before.scrollLeft = 60;
const kept = stripPlaces(rootOf([before]));
const after = strip("Economy views", ECON, 0, 336);
placeStrips(rootOf([after]), kept);
out.redraw = after.scrollLeft;

// A strip that fits is never scrolled.
const fits = strip("Guild views", [60, 50, 70], 2, 336);
placeStrips(rootOf([fits]), null);
out.fits = fits.scrollLeft;

out.pure = [revealLeft(0, 300, 10, 80, 16), revealLeft(200, 300, 100, 180, 16), revealLeft(0, 300, 400, 470, 16)];
console.log(JSON.stringify(out));
"""


def run():
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        shutil.copytree(APP, root / "app")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.js").write_text(SCRIPT, encoding="utf-8")
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


@needs_node
class TheLitTabIsOnScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run()

    def assertOnStrip(self, tab):
        self.assertGreaterEqual(tab["left"], 12, tab)
        self.assertLessEqual(tab["right"], 12 + 336, tab)

    def test_a_tab_past_the_right_edge_is_brought_in(self):
        self.assertOnStrip(self.out["bank"])

    def test_a_tab_in_the_middle_is_brought_in(self):
        self.assertOnStrip(self.out["middle"])

    def test_the_first_tab_leaves_the_strip_at_its_start(self):
        self.assertEqual(self.out["first"]["left"], 0)
        self.assertOnStrip(self.out["first"]["tab"])

    def test_a_redraw_keeps_where_the_reader_scrolled(self):
        self.assertEqual(self.out["redraw"], 60)

    def test_a_strip_that_fits_is_left_alone(self):
        self.assertEqual(self.out["fits"], 0)

    def test_the_scroll_rule(self):
        # In view: unchanged. Off the left: its start, less the pad. Off the
        # right: its end, plus the pad, at the right edge.
        self.assertEqual(self.out["pure"], [0, 84, 186])


class EveryDrawPlacesTheStrips(unittest.TestCase):
    def test_main_reads_the_strips_before_a_redraw_and_places_them_after(self):
        body = MAIN[MAIN.index("function draw(keepPlace)") :]
        body = body[: body.index("\n}\n")]
        read = body.index("stripPlaces(main)")
        draw = body.index("main.innerHTML")
        place = body.index("placeStrips(main, strips)")
        self.assertLess(read, draw)
        self.assertLess(draw, place)
        # Only a redraw of the same page keeps the old scroll; a new page
        # reveals its own lit tab.
        self.assertRegex(
            body, r"const strips = keepPlace \? stripPlaces\(main\) : null;"
        )
        self.assertTrue(re.search(r'from "\./tabstrip\.js"', MAIN))


if __name__ == "__main__":
    unittest.main()
