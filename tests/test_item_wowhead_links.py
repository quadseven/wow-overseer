"""Every item name links to its WotLK Wowhead page.

The link is a plain anchor (no Wowhead script), opens in a new tab on desktop,
and the phone sheet carries the same link because hover does not exist there.
"""

import json
import pathlib
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"

# Just enough DOM for modules that load api.js or _model.js.
FAKE_DOM = """
globalThis.document = { querySelector: () => null, addEventListener() {}, createElement: () => ({ remove() {} }), head: { appendChild() {} } };
globalThis.window = { addEventListener() {}, matchMedia: () => ({ matches: false }) };
globalThis.sessionStorage = { getItem() {}, setItem() {} };
"""


def node_in_app(script):
    """Run `script` under node with the app directory copied next to it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "app"
        shutil.copytree(APP, root)
        (root.parent / "package.json").write_text(
            '{"type": "module"}', encoding="utf-8"
        )
        (root.parent / "dom.js").write_text(FAKE_DOM, encoding="utf-8")
        (root.parent / "run.js").write_text(
            'import "./dom.js";\n' + script, encoding="utf-8"
        )
        out = subprocess.run(
            [shutil.which("node"), str(root.parent / "run.js")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class TheHelper(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_it_builds_the_wotlk_item_url(self):
        got = node_in_app(
            'import * as M from "./app/ui.js";\n'
            "console.log(JSON.stringify(M.wowheadItemUrl(10402)));\n"
        )
        self.assertEqual(got, "https://www.wowhead.com/wotlk/item=10402")

    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_it_coerces_missing_entries_to_zero(self):
        got = node_in_app(
            'import * as M from "./app/ui.js";\n'
            "console.log(JSON.stringify(M.wowheadItemUrl(null)));\n"
        )
        self.assertEqual(got, "https://www.wowhead.com/wotlk/item=0")


class TheItemLink(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_it_is_an_anchor_to_wowhead(self):
        got = node_in_app(
            'import * as M from "./app/ui.js";\n'
            'console.log(JSON.stringify(String(M.item({entry: 10402, name: "Cape", quality: 2}))));\n'
        )
        self.assertTrue(got.startswith("<a "), got)
        self.assertIn('href="https://www.wowhead.com/wotlk/item=10402"', got)
        self.assertIn('target="_blank"', got)
        self.assertIn('rel="noopener"', got)
        self.assertIn('data-item="10402"', got)

    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_it_keeps_the_quality_colour_class(self):
        got = node_in_app(
            'import * as M from "./app/ui.js";\n'
            'console.log(JSON.stringify(String(M.item({entry: 1, name: "Common", quality: 1}))));\n'
        )
        self.assertIn('class="item q1"', got)

    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_cells_are_anchors_too(self):
        got = node_in_app(
            'import * as M from "./app/views/_members.js";\n'
            'console.log(JSON.stringify(String(M.cell({entry: 456, name: "Bag item", quality: 3, icon: "inv_misc_bag_01"}))));\n'
        )
        self.assertTrue(got.startswith("<a "), got)
        self.assertIn('href="https://www.wowhead.com/wotlk/item=456"', got)
        self.assertIn('target="_blank"', got)
        self.assertIn('rel="noopener"', got)
        self.assertIn('data-item="456"', got)


class TheUpgradesTable(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_every_item_name_links_to_its_wowhead_page(self):
        got = node_in_app(
            'import * as M from "./app/views/_members.js";\n'
            "const data = {\n"
            "  level: 20,\n"
            "  slots: [{\n"
            '    label: "Shoulder", state: "upgrade",\n'
            '    worn: {entry: 100, name: "Old Shoulders", score: 12},\n'
            '    now: {entry: 101, name: "New Shoulders", quality: 2, icon: "inv_shoulder_01", gain: 3, where: "drop"},\n'
            "    targets: {\n"
            '      preraid: [{entry: 102, name: "Pre Shoulders", score: 20, where: [{label: "Quest"}]}],\n'
            '      raid: [{entry: 103, name: "Raid Shoulders", score: 30, where: [{label: "Boss"}]}]\n'
            "    },\n"
            '    next: {entry: 104, name: "Next Shoulders", quality: 3, icon: "inv_shoulder_02", gain: 5, where: [{label: "Dungeon"}], phase: "preraid"}\n'
            "  }],\n"
            "  items: {\n"
            '    100: {quality: 1, icon: "inv_shoulder_00"},\n'
            '    102: {quality: 2, icon: "inv_shoulder_01"},\n'
            '    103: {quality: 4, icon: "inv_shoulder_03"}\n'
            "  }\n"
            "};\n"
            'const html = String(M.upgradesBody(data, "all", "slot"));\n'
            "console.log(JSON.stringify(html));\n"
        )
        for entry in (100, 101, 102, 103, 104):
            with self.subTest(entry=entry):
                self.assertIn(
                    'href="https://www.wowhead.com/wotlk/item=%d"' % entry, got
                )
        # The five named items each appear as an anchor in both the table and
        # the phone cards, so there are ten item links and no buttons.
        self.assertEqual(got.count('<a class="item q'), 10)
        self.assertNotIn('<button class="item', got)


class TheTooltipSheet(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "node is needed to run the app's modules"
    )
    def test_the_last_line_is_open_on_wowhead(self):
        got = node_in_app(
            'import * as T from "./app/tooltip.js";\n'
            "const payload = {\n"
            "  entry: 2042,\n"
            '  name: "Staff of Westfall",\n'
            '  tooltip: {name: "Staff of Westfall", quality: 3, item_level: 24}\n'
            "};\n"
            'const lines = T.lines(payload, "Staff", null).map(String);\n'
            "console.log(JSON.stringify(lines));\n"
        )
        self.assertTrue(got[-1].startswith('<div class="ln ln-sep">'), got)
        self.assertIn("Open on Wowhead", got[-1])
        self.assertIn('href="https://www.wowhead.com/wotlk/item=2042"', got[-1])
        self.assertIn('target="_blank"', got[-1])


if __name__ == "__main__":
    unittest.main()
