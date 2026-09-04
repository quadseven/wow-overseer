"""The page has a light mode and a dark mode, and neither can go missing.

WHY THIS IS A SOURCE-READING SUITE rather than a rendering one. A theme is
almost entirely CSS, and the failure it has is not "the wrong colour" but "a
colour that only exists in one branch". A token defined only inside a media
query is invisible to a reader whose system preference does not match, and the
symptom is one theme's text on the other theme's ground, which no unit test that
imports Python would ever see. So these assert the SHAPE of the cascade, which
is the part that breaks silently.
"""
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
STYLE = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
HEAD = PAGE[:PAGE.index("</head>")]


class TheThemeResolvesInAllThreeStates(unittest.TestCase):
    """A reader is in one of three states, not two: they chose light, they chose
    dark, or they chose nothing and the operating system decides. The third is
    the default and the one most likely to be forgotten."""

    def test_the_bare_root_defines_the_shell(self):
        """With no attribute and no media query matched, the shell must still
        have every colour it needs. This is the state an un-stamped document is
        in, and a token missing here renders unstyled rather than light."""
        root = re.search(r":root \{[^}]*--shell-bg[^}]*\}", STYLE, re.S)
        self.assertIsNotNone(root, "no bare :root defines --shell-bg")
        for token in ("--shell-bg", "--shell-text", "--shell-dim", "--shell-line"):
            self.assertIn(token, root.group(0), token)

    def test_the_dark_media_query_yields_to_an_explicit_light_choice(self):
        """Guarded, or a reader who picked light on a dark machine gets dark
        anyway and the button appears broken."""
        self.assertIn('prefers-color-scheme: dark', STYLE)
        block = STYLE[STYLE.index('@media (prefers-color-scheme: dark)'):]
        self.assertIn(':root:not([data-theme="light"])', block[:200])

    def test_an_explicit_dark_choice_beats_a_light_system(self):
        """The other direction of the same rule, and the one a media query alone
        cannot express."""
        self.assertIn(':root[data-theme="dark"]', STYLE)

    def test_every_shell_token_is_defined_in_all_three_places(self):
        """The classic unreadable-page bug is a token defined in only one of
        them. Counting is enough to catch it."""
        for token in ("--shell-bg", "--shell-text", "--shell-dim", "--shell-line"):
            self.assertGreaterEqual(
                STYLE.count(token + ":"), 3,
                token + " is not defined in all three theme states")


class TheShellTakesTheThemeAndSoDoesTheContent(unittest.TestCase):
    """THIS CLASS USED TO PIN THE OPPOSITE, and the change that flipped it is
    the point rather than an accident. It asserted that --panel and --text
    stayed dark while only the shell themed, and its own docstring named the
    condition for reversing it: "if these ever become theme-aware, every bare
    hex inside those views has to move in the same change".

    That is what happened. The five legacy tokens now carry the design, which
    converts 188 rules at once, and the literals that assumed a dark ground
    moved with them. So the assertion inverts: the content tokens must be the
    LIGHT palette, and the one surface that stays dark must stay dark for a
    stated reason rather than by omission."""

    def test_the_body_is_painted_from_a_shell_token(self):
        """An unpainted body borrows whatever ground the host draws, which is
        how a page ends up with light text on white."""
        self.assertIn("background:var(--shell-bg)", STYLE)
        self.assertIn("color:var(--shell-text)", STYLE)

    def test_the_content_tokens_now_carry_the_light_palette(self):
        """The old dark values are the thing being asserted GONE. A page whose
        shell is the design and whose cards are the previous site is what got
        reported as "this looks nothing like the handoff"."""
        root = STYLE[STYLE.index(":root {"):STYLE.index(":root {") + 400]
        self.assertIn("--panel:#FFFFFF", root)
        self.assertIn("--text:#0B1A10", root)
        self.assertNotIn("--panel:#161b22", root)
        self.assertNotIn("--text:#e6edf3", root)

    def test_the_armory_is_the_one_dark_surface_and_says_why(self):
        """Not a stylistic exception. Item quality is a COLOUR in this game and
        the values are canonical: #1eff00 uncommon-green on white is close to
        invisible. Re-tinting them would invent new quality colours; leaving
        them on paper would ship ones nobody can read. So that section keeps
        the ground they were designed for, by overriding the same tokens."""
        scope = STYLE[STYLE.index("#armory {"):]
        scope = scope[:scope.index("}")]
        for token in ("--bg:", "--panel:", "--line:", "--text:", "--dim:"):
            self.assertIn(token, scope, token + " is not overridden for the Armory")
        # The bags and the purse live inside that same section, which is what
        # makes one scope enough to cover every surface that draws an item.
        self.assertLess(PAGE.index('<section id="armory">'),
                        PAGE.index('<div id="wealth">'))

    def test_the_canonical_quality_colours_are_untouched(self):
        """Changing these would be changing what the game means, not what the
        page looks like."""
        for canonical in ("#1eff00", "#a335ee", "#ff8000", "#e6cc80"):
            self.assertIn(canonical, STYLE, canonical)


class TheStoredChoiceSurvivesAReload(unittest.TestCase):

    def test_it_is_applied_before_the_first_paint(self):
        """In the body it would run after the browser has drawn one theme and
        the reader would watch the page change colour on every load."""
        self.assertIn("overseer-theme", HEAD)
        self.assertIn("data-theme", HEAD)

    def test_every_storage_access_is_wrapped(self):
        """localStorage THROWS rather than returning null in a private window or
        with site data blocked. An unwrapped read in the head would stop the
        page rendering at all, which is a far worse outcome than forgetting a
        preference."""
        for call in ("localStorage.getItem", "localStorage.setItem"):
            self.assertIn(call, PAGE, call)
        head_script = HEAD[HEAD.index("<script>"):]
        self.assertIn("try {", head_script)
        self.assertIn("catch", head_script)
        setter = PAGE[PAGE.index("localStorage.setItem") - 200:
                      PAGE.index("localStorage.setItem") + 200]
        self.assertIn("try {", setter)

    def test_the_button_names_where_it_goes_not_where_it_is(self):
        """A label naming the current state reads as a claim and gets clicked by
        someone trying to reach the state it names."""
        self.assertIn('currentTheme() === "dark" ? "light" : "dark"', PAGE)

    def test_it_follows_the_system_only_while_nothing_is_chosen(self):
        self.assertIn('if (!document.documentElement.getAttribute("data-theme"))', PAGE)


class TheRealmBandsUseTheDesignTokens(unittest.TestCase):
    """The banner is the one surface already converted, and its three states are
    the page's loudest signal. Pinning the tokens keeps a later edit from
    quietly returning production to a colour nobody chose."""

    def test_production_is_ink_with_the_alarm_rule_beneath(self):
        band = STYLE[STYLE.index("#realm.rk-production"):]
        self.assertIn("background:var(--ink)", band[:200])
        self.assertIn("border-bottom-color:var(--vermilion)", band[:300])

    def test_unverified_is_vermilion_and_not_a_quiet_amber(self):
        band = STYLE[STYLE.index("#realm.rk-unknown"):]
        self.assertIn("background:var(--vermilion)", band[:200])

    def test_the_quiet_state_keeps_a_fallback_before_color_mix(self):
        """color-mix is declared second so a browser without it still gets a
        green band rather than no background at all."""
        band = STYLE[STYLE.index("#realm.rk-non-production"):]
        head = band[:400]
        self.assertLess(head.index("background:var(--deep-green)"),
                        head.index("background:color-mix"))


class TheHouseRules(unittest.TestCase):

    def test_no_em_dashes(self):
        for name in ("index.html", "tests/test_theme.py"):
            self.assertNotIn(chr(0x2014), (HERE / name).read_text(encoding="utf-8"),
                             name)

    def test_the_typefaces_have_real_fallbacks(self):
        """A blocked font host must cost the page its typography and nothing
        else."""
        for stack in ("--display:", "--body:", "--mono:"):
            line = STYLE[STYLE.index(stack):STYLE.index(stack) + 160]
            self.assertIn(",", line, stack + " has no fallback")
            self.assertTrue(
                any(g in line for g in ("sans-serif", "monospace", "system-ui")),
                stack + " ends without a generic family")


if __name__ == "__main__":
    unittest.main()
