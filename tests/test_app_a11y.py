"""The app's phone and accessibility rules that can be checked from source.

- Every text colour token reads at 4.5:1 or better on the ground, the
  surface and the hover row, in both themes. The ratios are computed here
  from the hex and oklch values in app/tokens.css (WCAG 2 relative luminance).
- No rule colours text with the faint end of a ramp (600 and below).
- On a touch phone an item opens its sheet on a tap, and a second tap (on
  the item, the sheet or outside it) closes it. tooltip.js runs under node
  against a small stand-in for the DOM.
- The phone sheet styles every card line the hover card does.
- A tab with a minimum width never shrinks below its label.
- A histogram whose bars link is a group of links, not an image.
- Motion a script starts (a smooth scroll, a turning model) asks for
  reduced motion first, because the CSS switch cannot reach it.
"""

import json
import math
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
APP = HERE / "app"
TOKENS = (APP / "tokens.css").read_text(encoding="utf-8")

# Text colours: what any view may paint words with.
TEXT_TOKENS = (
    "--color-text",
    "--color-neutral-100",
    "--color-neutral-200",
    "--color-neutral-300",
    "--color-neutral-400",
    "--color-neutral-500",
    "--color-accent-200",
    "--color-accent-300",
    "--ok",
    "--warn",
    "--bad",
    "--q-poor",
    "--q-common",
    "--q-uncommon",
    "--q-rare",
    "--q-epic",
    "--q-legendary",
    "--cls-warrior",
    "--cls-paladin",
    "--cls-rogue",
    "--cls-priest",
    "--cls-mage",
    "--cls-shaman",
    "--cls-druid",
    "--cls-hunter",
    "--cls-warlock",
    "--cls-death-knight",
)
# Grounds: the page, a card, and a hovered or held row.
GROUNDS = ("--color-bg", "--color-surface", "--color-neutral-900")


def block(start):
    """The declarations of the first rule that opens with `start`."""
    i = TOKENS.index(start)
    body = TOKENS[TOKENS.index("{", i) + 1 : TOKENS.index("}", i)]
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))


def themes():
    dark = block(":root {")
    light = dict(dark)
    light.update(block(':root[data-theme="light"]'))
    return {"dark": dark, "light": light}


def linear_rgb(value):
    """A token value as linear sRGB, from #rrggbb or oklch(L C H)."""
    value = value.strip()
    if value.startswith("#"):
        rgb = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        return [
            c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb
        ]
    m = re.fullmatch(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)", value)
    if not m:
        raise ValueError("not a plain colour: %s" % value)
    lightness, chroma, hue = map(float, m.groups())
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )
    return [min(1.0, max(0.0, c)) for c in rgb]


def contrast(fg, bg):
    lum = [
        0.2126 * r + 0.7152 * g + 0.0722 * b
        for r, g, b in (linear_rgb(fg), linear_rgb(bg))
    ]
    hi, lo = max(lum), min(lum)
    return (hi + 0.05) / (lo + 0.05)


class TheTokenContrast(unittest.TestCase):
    def test_the_arithmetic_matches_known_ratios(self):
        self.assertAlmostEqual(contrast("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(contrast("#777777", "#ffffff"), 4.48, places=2)
        self.assertAlmostEqual(contrast("oklch(1 0 0)", "#ffffff"), 1.0, places=2)

    def test_every_text_colour_reads_at_4_5_in_both_themes(self):
        for theme, tokens in themes().items():
            for fg in TEXT_TOKENS:
                for ground in GROUNDS:
                    ratio = contrast(tokens[fg], tokens[ground])
                    with self.subTest(theme=theme, fg=fg, ground=ground):
                        self.assertGreaterEqual(
                            ratio,
                            4.5,
                            "%s %s on %s is %.2f:1" % (theme, fg, ground, ratio),
                        )

    def test_the_system_light_theme_is_the_chosen_light_theme(self):
        # The light ramp is written twice (chosen, and from the system); a
        # fix to one that misses the other ships a failing theme.
        chosen = block(':root[data-theme="light"]')
        system = block(':root:not([data-theme="dark"])')
        self.assertEqual(chosen, system)

    def test_no_rule_colours_text_with_the_faint_end_of_a_ramp(self):
        # 600 and below are for borders, bars and rings. An icon (an <i>) may
        # use them; words may not.
        faint = re.compile(
            r"(?<![\w-])color:\s*var\(--color-(?:neutral|accent)-[6-9]00\)"
        )
        for path in sorted(APP.rglob("*.css")):
            if path.name == "tokens.css":
                continue
            css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if not faint.search(body):
                    continue
                for sel in selector.split(","):
                    with self.subTest(path=path.name, selector=sel.strip()):
                        self.assertRegex(sel.strip(), r"(^|\s)i$")


def node_dir(files, script):
    """Run `script` as an ES module in a directory holding `files`
    ({name: text}); it prints JSON on its last line."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        for name, text in files.items():
            (root / name).write_text(text, encoding="utf-8")
        (root / "run.js").write_text(script, encoding="utf-8")
        out = subprocess.run(
            [shutil.which("node"), str(root / "run.js")],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


# Just enough DOM for tooltip.js: elements with attributes, listeners and the
# two parts of the sheet it looks up; a phone's media query.
FAKE_DOM = r"""
class El {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.hidden = false; this.children = []; this.listeners = {}; this.style = {}; this.parts = {}; this.markup = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  set innerHTML(v) { this.markup = String(v); if (this.markup.includes("tip-body")) { this.parts[".tip-body"] = new El("div"); this.parts[".close"] = new El("button"); } }
  get innerHTML() { return this.markup; }
  querySelector(s) { return this.parts[s] || null; }
  closest(s) { return s === "[data-item]" && "data-item" in this.attrs ? this : null; }
  contains() { return false; }
  focus() {}
  get textContent() { return this.attrs["data-name"] || ""; }
  get offsetHeight() { return 200; }
  getBoundingClientRect() { return { left: 10, top: 300, right: 200, bottom: 321 }; }
}
const listeners = {};
globalThis.document = {
  body: new El("body"),
  createElement: (t) => new El(t),
  addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
  contains: () => true,
};
globalThis.window = { innerWidth: 390, innerHeight: 844, matchMedia: () => ({ matches: true }), addEventListener() {} };
const fire = (list, type, target) => (list[type] || []).forEach((fn) => fn({ target, pointerType: "touch", preventDefault() {} }));
const tap = (target) => fire(listeners, "click", target);
"""

API_STUB = (
    'export const peek = () => ({ data: { name: "Cape", tooltip: { name: "Cape", quality: 3 } } });\n'
    "export const load = () => Promise.resolve();\n"
)


class TheItemSheetOnTouch(unittest.TestCase):
    def run_taps(self):
        script = (
            FAKE_DOM
            + r"""
const T = await import("./tooltip.js");
T.install();
const item = new El("button");
item.setAttribute("data-item", "123");
item.setAttribute("data-name", "Cape");
const open = () => { const s = document.body.children[1]; return !!s && !s.hidden; };
const out = {};
tap(item); out.first_tap_opens = open();
out.hover_card_stays_shut = document.body.children[0].hidden;
const scrim = document.body.children[1];
fire(scrim.listeners, "click", scrim.parts[".tip-body"]); out.tap_on_sheet_closes = !open();
tap(item); tap(item); out.second_tap_on_item_closes = !open();
tap(item); fire(scrim.listeners, "click", scrim); out.tap_outside_closes = !open();
tap(item); fire(scrim.listeners, "click", scrim.parts[".close"]); out.close_button_closes = !open();
tap(item); out.opens_again = open();
console.log(JSON.stringify(out));
"""
        )
        files = {
            "tooltip.js": (APP / "tooltip.js").read_text(encoding="utf-8"),
            "ui.js": (APP / "ui.js").read_text(encoding="utf-8"),
            "api.js": API_STUB,
        }
        return node_dir(files, script)

    def test_a_tap_opens_and_a_second_tap_anywhere_closes(self):
        self.assertEqual(
            self.run_taps(),
            {
                "first_tap_opens": True,
                "hover_card_stays_shut": True,
                "tap_on_sheet_closes": True,
                "second_tap_on_item_closes": True,
                "tap_outside_closes": True,
                "close_button_closes": True,
                "opens_again": True,
            },
        )


class TheHistogram(unittest.TestCase):
    def draw(self, bins):
        script = (
            'import * as M from "./ui.js";\n'
            'console.log(JSON.stringify(String(M.histogram(%s, { label: "Levels" }))));\n'
            % json.dumps(bins)
        )
        return node_dir({"ui.js": (APP / "ui.js").read_text(encoding="utf-8")}, script)

    def test_linked_bars_are_a_group_of_links_each_its_full_column(self):
        out = self.draw(
            [
                {"label": "10-11", "n": 1, "href": "#/a"},
                {"label": "12-13", "n": 4, "href": "#/b"},
            ]
        )
        self.assertIn('class="histo" role="group"', out)
        self.assertNotIn('role="img"', out)
        self.assertEqual(out.count('<a class="hit"'), 2)
        self.assertIn('<span class="bar " style="height:25%">', out)

    def test_bars_without_links_stay_an_image(self):
        out = self.draw([{"label": "10-11", "n": 1}, {"label": "12-13", "n": 2}])
        self.assertIn('class="histo" role="img"', out)


class TheTouchTargets(unittest.TestCase):
    CSS = (APP / "app.css").read_text(encoding="utf-8")

    def test_items_and_members_are_44px_on_a_touch_screen(self):
        m = re.search(r"@media \(pointer: coarse\) \{\s*([^{}]+)\{([^{}]*)\}", self.CSS)
        self.assertIsNotNone(m)
        self.assertIn(".item", m.group(1))
        self.assertIn("a.member", m.group(1))
        self.assertIn(".chip", m.group(1))
        self.assertIn("min-height: 44px", m.group(2))

    def test_sortable_headers_are_44px_on_a_touch_screen(self):
        start = self.CSS.index("@media (pointer: coarse) {")
        block = self.CSS[start : self.CSS.index("\n}", start)]
        self.assertRegex(block, r"\.table th button \{[^}]*min-height: 44px")

    def test_the_phone_quest_holders_are_44px_wide(self):
        family = (APP / "views" / "family.css").read_text(encoding="utf-8")
        self.assertIn("width: 44px; height: 44px;", family)
        self.assertNotIn(".qwho { width: 40px; }", family)


class TheItemSheetLines(unittest.TestCase):
    def test_the_sheet_styles_every_line_the_card_draws(self):
        # The phone sheet is not a .tip, so the hover card's rules do not
        # reach it: without its own, "Item level 37" and "Rare" run together
        # and the name loses its quality colour.
        css = (APP / "app.css").read_text(encoding="utf-8")
        drawn = set(
            re.findall(
                r'class="ln ?([\w-]*)', (APP / "tooltip.js").read_text(encoding="utf-8")
            )
        )
        drawn = {c for c in drawn if c} | {"ln"} | {"tq%d" % q for q in range(6)}
        for cls in sorted(drawn):
            with self.subTest(cls=cls):
                self.assertIn(".tip .%s " % cls, css)
                self.assertIn(".item-sheet .%s " % cls, css)
        self.assertRegex(
            css, r"\.item-sheet \.ln \{[^}]*justify-content: space-between"
        )


class TheTabRow(unittest.TestCase):
    def test_a_tab_never_shrinks_below_its_label(self):
        # A min-width on a flex item drops its automatic minimum, so the row
        # would squeeze the labels into each other instead of scrolling.
        css = (APP / "app.css").read_text(encoding="utf-8")
        for body in re.findall(r"\.tabs a \{([^}]*)\}", css):
            if "min-width" in body:
                self.assertIn("flex-shrink: 0", body)


class TheReducedMotion(unittest.TestCase):
    def test_css_motion_stops_when_the_system_asks(self):
        css = (APP / "app.css").read_text(encoding="utf-8")
        block = css[css.index("@media (prefers-reduced-motion: reduce)") :]
        block = block[: block.index("}\n}") + 3]
        for rule in ("animation: none !important", "transition: none !important"):
            self.assertIn(rule, block)

    def test_script_motion_asks_the_system_first(self):
        # CSS cannot stop motion a script starts: a smooth scroll or a model
        # that turns by itself has to ask for itself.
        movers = re.compile(r'behavior:\s*"smooth"|r\.azimuth \+ TURN')
        for path in sorted(APP.rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            if movers.search(text):
                with self.subTest(path=path.name):
                    self.assertIn("prefers-reduced-motion: reduce", text)
                    self.assertNotIn('behavior: "smooth"', text)


if __name__ == "__main__":
    unittest.main()
