"""The page loads no third-party font or icon host: both fonts are vendored.

WHY. The page used to load a font stylesheet from one host and two icon
stylesheets from another, then the font files themselves, about 175 KB that
blocked first paint behind three extra connections. The icon fonts hold
thousands of glyphs and the app uses a few dozen. app/fonts/ now holds the
text font cut to the text the app draws and each icon font cut to the glyphs
the sources name, all served from the app's own mount like any other file of
the build. tools/vendor_icons.py writes it.

Ticket: #2315 (epic #2309).
"""

import pathlib
import re
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import appbuild
    import map_server

from test_app_shell import get  # noqa: E402
from tools import vendor_icons  # noqa: E402

FONTS = HERE / "app" / "fonts"
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
BUDGET_BYTES = 60 * 1024
BUILD = appbuild.fingerprint(str(HERE))


class NoThirdPartyHost(unittest.TestCase):
    def test_the_page_names_no_other_host(self):
        self.assertNotRegex(PAGE, r"https?://")

    def test_the_served_page_names_no_other_host(self):
        body = get("/").body().decode("utf-8")
        self.assertNotRegex(body, r"https?://")
        self.assertIn("/app/%s/fonts/fonts.css" % BUILD, body)

    def test_the_fonts_the_page_preloads_exist_and_match_the_stylesheet(self):
        css = (FONTS / "fonts.css").read_text(encoding="utf-8")
        preloaded = re.findall(
            r'<link rel="preload" as="font"[^>]*href="[^"]*/fonts/([a-z-]+\.woff2)"',
            PAGE,
        )
        self.assertEqual(
            sorted(preloaded),
            ["inter-latin.woff2", "phosphor-fill.woff2", "phosphor.woff2"],
        )
        for name in preloaded:
            self.assertTrue((FONTS / name).is_file(), name)
            self.assertIn("url(%s)" % name, css)

    def test_every_vendored_font_has_its_license_beside_it(self):
        self.assertTrue((FONTS / "LICENSE-Inter.txt").is_file())
        self.assertTrue((FONTS / "LICENSE-Phosphor.txt").is_file())

    def test_the_fonts_stay_small(self):
        total = sum(p.stat().st_size for p in FONTS.glob("*.woff2"))
        self.assertLess(total, BUDGET_BYTES, "font bytes: %d" % total)


class EveryUsedIconIsThere(unittest.TestCase):
    CSS = (FONTS / "fonts.css").read_text(encoding="utf-8")

    def test_every_icon_the_sources_name_has_a_glyph(self):
        have = set(re.findall(r"\.ph\.ph-([a-z0-9-]+):before", self.CSS))
        have_fill = set(re.findall(r"\.ph-fill\.ph-([a-z0-9-]+):before", self.CSS))
        # An icon is drawn in the regular or the fill style, so it must be in
        # at least one; the nav draws both (shell.js), so those are in both.
        missing = sorted(
            n for n in vendor_icons.used_icons() if n not in have and n not in have_fill
        )
        # A name followed by a template hole (`ph-caret-${...}`) is a prefix,
        # not an icon; its real names appear elsewhere in the sources.
        self.assertEqual(
            [m for m in missing if m != "caret"], [], "run tools/vendor_icons.py"
        )

    def test_the_nav_icons_exist_in_both_styles(self):
        nav = re.findall(
            r'icon: "([a-z-]+)"',
            (HERE / "app" / "shell.js").read_text(encoding="utf-8"),
        )
        self.assertGreaterEqual(len(nav), 6)
        for name in nav:
            self.assertIn(".ph.ph-%s:before" % name, self.CSS, name)
            self.assertIn(".ph-fill.ph-%s:before" % name, self.CSS, name)

    def test_the_stylesheet_names_only_local_files(self):
        self.assertNotRegex(
            self.CSS, r"url\((?!(?:inter-latin|phosphor|phosphor-fill)\.woff2\))"
        )


class TheScanner(unittest.TestCase):
    def test_it_finds_literal_and_nav_icons_and_ignores_style_words(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "app").mkdir()
            (root / "tests").mkdir()
            (root / "app" / "a.js").write_text(
                '<i class="ph-fill ph-star"></i><i class="ph ph-arrow-up-right"></i>'
            )
            (root / "app" / "shell.js").write_text('{ icon: "pulse" }')
            (root / "app" / "other.js").write_text('{ icon: "not-an-icon" }')
            (root / "x.py").write_text('"ph ph-coins"')
            (root / "tests" / "t.py").write_text('"ph-ignored"')
            self.assertEqual(
                vendor_icons.used_icons(root),
                {"star", "arrow-up-right", "pulse", "coins"},
            )

    def test_it_reads_codepoints_by_style(self):
        css = '.ph.ph-a:before {\n  content: "\\e001";\n}\n.ph-fill.ph-a:before {\n  content: "\\e002";\n}\n'
        self.assertEqual(vendor_icons.codepoints(css, "ph"), {"a": 0xE001})
        self.assertEqual(vendor_icons.codepoints(css, "ph-fill"), {"a": 0xE002})


class Served(unittest.TestCase):
    def test_a_font_is_served_typed_and_immutable_under_the_build(self):
        r = get("/app/%s/fonts/phosphor.woff2" % BUILD)
        self.assertEqual(r.status(), 200)
        self.assertEqual(r.header("Content-Type"), "font/woff2")
        self.assertEqual(r.header("Cache-Control"), map_server.APP_IMMUTABLE)
        self.assertEqual(r.body(), (FONTS / "phosphor.woff2").read_bytes())
        self.assertIsNone(r.header("Content-Encoding"))

    def test_the_font_stylesheet_is_served_under_the_build(self):
        r = get("/app/%s/fonts/fonts.css" % BUILD)
        self.assertEqual(r.status(), 200)
        self.assertEqual(r.header("Content-Type"), "text/css; charset=utf-8")

    def test_nothing_else_in_the_font_folder_is_served(self):
        for name in (
            "LICENSE-Inter.txt",
            "LICENSE-Inter",
            "inter-latin.woff",
            "inter-latin.ttf",
            "Inter-latin.woff2",
        ):
            self.assertEqual(
                get("/app/%s/fonts/%s" % (BUILD, name)).status(), 404, name
            )

    def test_a_changed_font_changes_the_build(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "app" / "fonts").mkdir(parents=True)
            (pathlib.Path(tmp) / "index.html").write_text("<html>")
            f = pathlib.Path(tmp) / "app" / "fonts" / "a.woff2"
            f.write_bytes(b"one")
            first = appbuild.fingerprint(tmp)
            f.write_bytes(b"two")
            os.utime(f, (1, 1))
            self.assertNotEqual(first, appbuild.fingerprint(tmp))


if __name__ == "__main__":
    unittest.main()
