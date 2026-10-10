"""Added to an iPhone's home screen, the app opens full screen in the colors
of the theme in use, with its own icon, and never from a stale copy.

test_basepath.py holds the half of this that depends on the mount: the
manifest's URLs resolve under the prefix the page was served from.
"""

import json
import pathlib
import re
import struct
import sys
import types
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.modules.setdefault("pymysql", types.ModuleType("pymysql"))

import map_server  # noqa: E402
from tests.test_app_shell import get  # noqa: E402

PAGE = (HERE / "index.html").read_text(encoding="utf-8")
MANIFEST = json.loads((HERE / "manifest.webmanifest").read_text(encoding="utf-8"))
TOKENS = (HERE / "app" / "tokens.css").read_text(encoding="utf-8")


def background(block_start):
    """--color-bg in the first token block that opens with `block_start`."""
    block = TOKENS[TOKENS.index(block_start) :]
    found = re.search(r"--color-bg:\s*(#[0-9a-fA-F]{6})", block)
    if found is None:
        raise AssertionError("no --color-bg after " + block_start)
    return found.group(1).lower()


DARK = background(":root {")
LIGHT = background(':root[data-theme="light"] {')


def png_size(body):
    if body[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return "%dx%d" % struct.unpack(">II", body[16:24])


class TheManifest(unittest.TestCase):
    def test_it_opens_standalone_as_the_overseer(self):
        self.assertEqual(MANIFEST["display"], "standalone")
        self.assertEqual(MANIFEST["short_name"], "Overseer")

    def test_its_colors_are_the_dark_theme_background(self):
        # The default theme is dark; the manifest has one color for both
        # the splash and the bar, so it takes the default's background.
        self.assertEqual(DARK, "#161826")
        self.assertEqual(MANIFEST["theme_color"].lower(), DARK)
        self.assertEqual(MANIFEST["background_color"].lower(), DARK)

    def test_it_is_served_as_a_manifest(self):
        h = get("/manifest.webmanifest")
        self.assertEqual(h.status(), 200)
        self.assertEqual(h.header("Content-Type"), "application/manifest+json")
        self.assertEqual(json.loads(h.body()), MANIFEST)

    def test_every_icon_is_a_png_of_the_size_it_claims(self):
        icons = [{"src": "apple-touch-icon.png", "sizes": "180x180"}] + MANIFEST[
            "icons"
        ]
        for icon in icons:
            h = get("/" + icon["src"])
            self.assertEqual(h.status(), 200, icon["src"])
            self.assertEqual(h.header("Content-Type"), "image/png", icon["src"])
            self.assertEqual(png_size(h.body()), icon["sizes"], icon["src"])


class ThePage(unittest.TestCase):
    def test_the_bar_takes_the_background_of_each_theme(self):
        metas = dict(
            re.findall(
                r'<meta name="theme-color" media="\(prefers-color-scheme: (dark|light)\)" content="(#[0-9a-fA-F]{6})">',
                PAGE,
            )
        )
        self.assertEqual(
            {k: v.lower() for k, v in metas.items()}, {"dark": DARK, "light": LIGHT}
        )
        self.assertEqual(len(re.findall(r'name="theme-color"', PAGE)), 2)

    def test_a_picked_theme_moves_the_bar_with_it(self):
        # The operator's own pick overrides the system's, so main.js sets
        # every theme-color meta to the background the page is drawn in.
        main = (HERE / "app" / "main.js").read_text(encoding="utf-8")
        self.assertIn("""querySelectorAll('meta[name="theme-color"]')""", main)
        self.assertIn('getPropertyValue("--color-bg")', main)

    def test_the_iphone_home_screen_tags(self):
        for tag in (
            '<meta name="apple-mobile-web-app-capable" content="yes">',
            '<meta name="apple-mobile-web-app-title" content="Overseer">',
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
            'rel="apple-touch-icon" href="__OVERSEER_BASE__/apple-touch-icon.png"',
        ):
            self.assertIn(tag, PAGE)

    def test_no_service_worker_keeps_a_stale_copy(self):
        # A cached app would show an old realm as if it were now. Nothing
        # registers a worker; adding one means network first for every read.
        for path in [HERE / "index.html", *sorted((HERE / "app").rglob("*.js"))]:
            self.assertNotIn(
                "serviceWorker", path.read_text(encoding="utf-8"), path.name
            )
        self.assertNotIn("/sw.js", map_server.Handler.GET_ROUTES)


if __name__ == "__main__":
    unittest.main()
