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
STYLE = PAGE[PAGE.index("<style>") : PAGE.index("</style>")]
HEAD = PAGE[: PAGE.index("</head>")]


def _theme_blocks():
    """The three places a reader can be: nothing chosen and a light system, a
    dark system, and an explicit choice. A token has to be in all three."""
    blocks = []
    for marker in (
        ":root {\n    --ink:",
        ':root:not([data-theme="light"]) {',
        ':root[data-theme="dark"] {',
    ):
        start = STYLE.index(marker)
        blocks.append(STYLE[start : STYLE.index("}", start)])
    return blocks


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
        self.assertIn("prefers-color-scheme: dark", STYLE)
        block = STYLE[STYLE.index("@media (prefers-color-scheme: dark)") :]
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
                STYLE.count(token + ":"),
                3,
                token + " is not defined in all three theme states",
            )


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
        root = STYLE[STYLE.index(":root {") : STYLE.index(":root {") + 400]
        self.assertIn("--panel:#FFFFFF", root)
        self.assertIn("--text:#0B1A10", root)
        self.assertNotIn("--panel:#161b22", root)
        self.assertNotIn("--text:#e6edf3", root)

    def test_the_dark_surfaces_are_the_ones_that_draw_items_and_say_why(self):
        """Not a stylistic exception. Item quality is a COLOUR in this game and
        the values are canonical: #1eff00 uncommon-green on white is close to
        invisible. Re-tinting them would invent new quality colours; leaving
        them on paper would ship ones nobody can read. So the sections that
        draw items keep the ground those colours were designed for, by
        overriding the same tokens.

        TWO SCOPES SINCE BAGS BECAME ITS OWN TAB. It used to be a div inside
        #armory and was covered by that scope for free; the day it moved out
        it needed its own, and a redesign that moved the markup without moving
        the scope would have left every uncommon-green item name at about
        1.3:1 on a white card. That is the same bug the Family tab shipped
        with priests, which is what the class below is about."""
        for section in ("#armory {", "#bags {"):
            scope = STYLE[STYLE.index(section) :]
            scope = scope[: scope.index("}")]
            for token in ("--bg:", "--panel:", "--line:", "--text:", "--dim:"):
                self.assertIn(token, scope, token + " is not overridden for " + section)

    def test_the_bags_scope_also_overrides_the_text_roles(self):
        """The five legacy tokens are not enough on their own any more. The
        redesign draws with --on-card, --warn-text, --caution-text and
        --accent-text, and every one of those resolves to a colour chosen for
        a WHITE card. Inside a section that is dark in both themes they have
        to be overridden too, or the finding at the top of the tab is ink on
        near-black."""
        scope = STYLE[STYLE.index("#bags {") :]
        scope = scope[: scope.index("}")]
        for token in (
            "--on-card:",
            "--on-card-dim:",
            "--warn-text:",
            "--caution-text:",
            "--accent-text:",
        ):
            self.assertIn(token, scope, token + " is not overridden for #bags")

    def test_the_new_text_roles_exist_in_every_theme_state(self):
        """Same rule as the shell tokens: a role defined only inside a media
        query is invisible to a reader whose system preference does not match,
        and the symptom is unstyled text rather than an error.

        ASKED OF THE THREE BLOCKS, NOT OF A COUNT. Counting the token across
        the whole stylesheet was the first version of this, and it passed with
        the bug live: #bags overrides both roles in its own scope, so deleting
        one from the explicit-dark block still left three occurrences and
        three was the bar. A count cannot tell you WHERE, which is the only
        thing this test is about."""
        for block in _theme_blocks():
            for token in ("--caution-text:", "--accent-text:"):
                self.assertIn(token, block, token + " missing from " + block[:40])

    def test_the_canonical_quality_colours_are_untouched(self):
        """Changing these would be changing what the game means, not what the
        page looks like."""
        for canonical in ("#1eff00", "#a335ee", "#ff8000", "#e6cc80"):
            self.assertIn(canonical, STYLE, canonical)


class ClassColourDoesNotSurviveAWhiteCard(unittest.TestCase):
    """MEASURED ON THE LIVE PAGE, by a contrast audit over every rendered text
    node after the light conversion:

        Ugga   priest   rgb(255,255,255) on white   1.0:1   invisible
        Bork   rogue    rgb(255,245,105)            1.1:1
        Og     mage     rgb(105,204,240)            1.8:1
        Grog   paladin  rgb(245,140,186)            2.2:1
        Grug   warrior  rgb(199,156,110)            2.5:1

    This is the same problem as item quality, which the Armory solves by
    keeping a dark ground, and that fix was scoped too narrowly: class colours
    are canonical too, chosen for a dark game UI, and a priest is literally
    white. The Armory, Standing and Wealth all sit inside the dark section and
    keep their class-coloured names; the broadcast tile's name sits on video.
    The Family card was the one light surface drawing names in class colour."""

    def test_the_family_name_is_ink_and_not_the_class_colour(self):
        rule = STYLE[STYLE.index(".fname {") :]
        rule = rule[: rule.index("}")]
        self.assertIn("color:var(--text)", rule)

    def test_the_family_card_no_longer_paints_the_name_from_the_class(self):
        """The assignment that made a priest invisible."""
        self.assertNotIn('c.nm.style.color = m.class_colour || "";', PAGE)

    def test_the_class_survives_as_a_swatch(self):
        """The information does not move, it lands on a shape where colour
        costs nothing to read."""
        self.assertIn('el("span", "fclass")', PAGE)
        self.assertIn('sw.style.setProperty("--cc"', PAGE)

    def test_the_swatch_has_a_border_or_a_priest_is_an_invisible_hole(self):
        """A priest's colour IS #ffffff. Without a hairline the swatch is a
        white square on a white card, which is the same bug in a new shape."""
        rule = STYLE[STYLE.index(".fclass {") :]
        rule = rule[: rule.index("}")]
        self.assertIn("border:", rule)

    def test_the_dark_surfaces_keep_their_class_colours(self):
        """Not a retreat from class colour. Where the ground is dark the
        canonical colours are exactly right, and three views still use them."""
        self.assertGreaterEqual(PAGE.count("c.nm.style.color = m.class_colour;"), 2)


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
        head_script = HEAD[HEAD.index("<script>") :]
        self.assertIn("try {", head_script)
        self.assertIn("catch", head_script)
        setter = PAGE[
            PAGE.index("localStorage.setItem") - 200 : PAGE.index(
                "localStorage.setItem"
            )
            + 200
        ]
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
        band = STYLE[STYLE.index("#realm.rk-production") :]
        self.assertIn("background:var(--ink)", band[:200])
        self.assertIn("border-bottom-color:var(--vermilion)", band[:300])

    def test_unverified_is_vermilion_and_not_a_quiet_amber(self):
        band = STYLE[STYLE.index("#realm.rk-unknown") :]
        self.assertIn("background:var(--vermilion)", band[:200])

    def test_the_quiet_state_keeps_a_fallback_before_color_mix(self):
        """color-mix is declared second so a browser without it still gets a
        green band rather than no background at all."""
        band = STYLE[STYLE.index("#realm.rk-non-production") :]
        head = band[:400]
        self.assertLess(
            head.index("background:var(--deep-green)"),
            head.index("background:color-mix"),
        )


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in ("index.html", "tests/test_theme.py"):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )

    def test_the_typefaces_have_real_fallbacks(self):
        """A blocked font host must cost the page its typography and nothing
        else."""
        for stack in ("--display:", "--body:", "--mono:"):
            line = STYLE[STYLE.index(stack) : STYLE.index(stack) + 160]
            self.assertIn(",", line, stack + " has no fallback")
            self.assertTrue(
                any(g in line for g in ("sans-serif", "monospace", "system-ui")),
                stack + " ends without a generic family",
            )


if __name__ == "__main__":
    unittest.main()
