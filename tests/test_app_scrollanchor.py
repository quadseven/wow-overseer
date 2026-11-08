"""Scroll anchoring: a redraw keeps the reader's line, not their pixels.

app/scrollanchor.js is a pure module: captureAnchor names the element at
the reader's line as a child-index path plus an offset, resolveAnchor
finds it again after the redraw, and scrollShift says how far the scroll
must move to put the line back where it was inside that element. The
elements here are plain fakes with children and rects, which is all the
module reads.
"""

import pathlib
import shutil
import unittest

from test_app_shell import node_module

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

NODE = unittest.skipUnless(
    shutil.which("node"), "node is needed to run the app's modules"
)

# A page: root with three sections; the second holds two cards.
PAGE = """
function el(top, bottom, children) {
  return { children: children || [], getBoundingClientRect: () => ({ top, bottom }) };
}
const page = el(0, 900, [
  el(0, 100),
  el(100, 500, [el(100, 300), el(300, 500)]),
  el(500, 900),
]);
"""


def run(body):
    # node_module logs JSON.stringify(<script>) with the script as one
    # expression, so the page setup and the statements ride inside an IIFE
    # whose last line returns the value under test.
    return node_module(
        "scrollanchor.js",
        "console.log(JSON.stringify((() => {\n" + PAGE + "\n" + body + "\n})()));",
    )


@NODE
class CaptureAnchor(unittest.TestCase):
    def test_it_names_the_deepest_element_at_the_line(self):
        got = run("return M.captureAnchor(page, 350);")
        self.assertEqual(got, {"path": [1, 1], "offset": 50})

    def test_it_stops_at_a_section_with_no_containing_child(self):
        got = run("return M.captureAnchor(page, 50);")
        self.assertEqual(got, {"path": [0], "offset": 50})

    def test_a_line_below_everything_has_no_anchor(self):
        self.assertIsNone(run("return M.captureAnchor(page, 950);"))

    def test_an_empty_page_has_no_anchor(self):
        got = run(
            "return M.captureAnchor({children: [], getBoundingClientRect: () => ({top: 0, bottom: 0})}, 10);"
        )
        self.assertIsNone(got)


@NODE
class ResolveAndShift(unittest.TestCase):
    def test_the_anchor_resolves_to_the_same_element(self):
        got = run(
            "const a = M.captureAnchor(page, 350);"
            "return M.resolveAnchor(page, a) === page.children[1].children[1];"
        )
        self.assertTrue(got)

    def test_a_path_that_no_longer_resolves_is_null(self):
        got = run("return M.resolveAnchor(page, {path: [1, 7], offset: 0});")
        self.assertIsNone(got)

    def test_no_movement_means_no_shift(self):
        got = run(
            "const a = M.captureAnchor(page, 350);"
            "return M.scrollShift(M.resolveAnchor(page, a), a, 350);"
        )
        self.assertEqual(got, 0)

    def test_content_growing_above_shifts_the_scroll_by_the_growth(self):
        # The same page after a redraw in which the first section grew by
        # 120px: the anchored card now starts at 420 instead of 300.
        script = """
        const a = M.captureAnchor(page, 350);
        const grown = el(0, 1020, [
          el(0, 220),
          el(220, 620, [el(220, 420), el(420, 620)]),
          el(620, 1020),
        ]);
        return M.scrollShift(M.resolveAnchor(grown, a), a, 350);
        """
        self.assertEqual(run(script), 120)
