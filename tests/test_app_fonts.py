"""The page's fonts are local, licensed, complete, and within its byte budget."""

import json
import pathlib
import re
import sys
import tempfile
import unittest

from test_app_shell import get

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
FONT_CSS = APP / "fonts.css"
BUDGETS = HERE / "tests" / "fixtures" / "app_budgets.json"
sys.path.insert(0, str(HERE))
from scripts.app_font_glyphs import icons_in_sources  # noqa: E402

ICON_RULE = re.compile(
    r"\.(ph-fill|ph)\.ph-([a-z0-9-]+):before\s*"
    r"\{\s*content:\s*\"\\([0-9a-f]+)\";\s*\}",
    re.IGNORECASE,
)


class ThePageUsesItsOwnFonts(unittest.TestCase):
    def test_the_served_page_has_no_external_font_or_stylesheet(self):
        page = get("/").body().decode("utf-8")
        tags = re.findall(r"<(?:link|script)\b[^>]*>", page)
        for tag in tags:
            attrs = dict(re.findall(r'([a-z-]+)="([^"]*)"', tag))
            rels = set(attrs.get("rel", "").split())
            if tag.startswith("<script") or rels.intersection(
                {"stylesheet", "preconnect"}
            ):
                url = attrs.get("src", attrs.get("href", ""))
                self.assertFalse(url.startswith(("http://", "https://")), url)
        self.assertRegex(page, r'href="/app/[0-9a-f]{12}/fonts\.css"')

    def test_inter_and_icon_fonts_use_local_files_and_swap(self):
        css = FONT_CSS.read_text(encoding="utf-8")
        self.assertIn('font-family: "Inter"', css)
        self.assertIn("font-weight: 400 500", css)
        self.assertIn('font-family: "Phosphor"', css)
        self.assertIn('font-family: "Phosphor Fill"', css)
        self.assertIn("font-display: swap", css)
        self.assertNotRegex(css, r"url\([\"']?https?://")

    def test_every_used_icon_has_a_rule_in_the_subset(self):
        css = FONT_CSS.read_text(encoding="utf-8")
        present = {(weight, name) for weight, name, _code in ICON_RULE.findall(css)}
        missing = {
            (weight, name)
            for weight, names in icons_in_sources(HERE).items()
            for name in names
            if (weight, name) not in present
        }
        self.assertEqual(missing, set())
        self.assertEqual(len(present), sum(map(len, icons_in_sources(HERE).values())))

    def test_glyph_scanner_ignores_the_generated_font_stylesheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            app = root / "app"
            app.mkdir()
            (app / "fonts.css").write_text(
                ".ph.ph-unused:before { color: red; }",
                encoding="utf-8",
            )
            (app / "main.js").write_text('const icon = "ph ph-used";', encoding="utf-8")

            self.assertEqual(icons_in_sources(root), {"ph": {"used"}, "ph-fill": set()})

    def test_font_license_texts_ship_beside_the_assets(self):
        inter = (APP / "fonts" / "LICENSE.Inter.txt").read_text(encoding="utf-8")
        phosphor = (APP / "fonts" / "LICENSE.Phosphor.txt").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE", inter)
        self.assertIn("MIT License", phosphor)

    def test_now_page_font_bytes_stay_under_the_budget(self):
        budget = json.loads(BUDGETS.read_text(encoding="utf-8"))["now_font_bytes"]
        total = sum((APP / path).stat().st_size for path in budget["files"])
        self.assertLess(total, budget["limit"])
