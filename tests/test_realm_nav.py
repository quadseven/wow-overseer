"""The realm switcher, and the design actually being applied.

BOTH HALVES OF THIS FILE WERE WRITTEN AFTER THE OPERATOR SAID THE LIVE SITE
LOOKED NOTHING LIKE THE DESIGN, AND HE WAS RIGHT. Measured on the live page at
the time:

  document.fonts   Archivo, Space Mono, Zen Kaku Gothic New: all "loaded"
  every element    ui-monospace, SFMono-Regular, Menlo, monospace

Three typefaces were being downloaded on every load and rendered in none of
them. The stylesheet link had shipped, the --display/--body/--mono tokens had
shipped, and a test asserting those tokens carried fallback stacks had shipped
and passed. Not one rule used them. A token nobody references is a token that
tests green and changes nothing on screen, which is the failure this file
exists to make impossible.

The other half is the switcher: three realms have been served from one hostname
for weeks and nothing on the page said so, so moving between them meant editing
the URL by hand.
"""
import json
import os
import re
import unittest

import basepath
import realmnav

LF = chr(10)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(HERE, "index.html"), encoding="utf-8") as _fh:
    PAGE = _fh.read()
STYLE = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]


def strip_comments(text, style):
    """`text` with its comments removed.

    THE SAME MISTAKE HAS NOW BEEN MADE FIVE TIMES IN THIS WORK: a test greps
    for the bad pattern it just removed, and matches the comment that explains
    why it was removed. A comment naming #0d1117 while saying that colour is
    gone is not that colour coming back, and a test that cannot tell the
    difference punishes writing the explanation. Every assertion of the form
    "this must be absent" reads through here.
    """
    if style == "css":
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return LF.join(l for l in text.splitlines()
                   if not l.strip().startswith("//"))


CODE = strip_comments(STYLE, "css")


def _theme_block(selector):
    """The declarations inside one theme selector, and nothing else.

    Scoped overrides elsewhere in the sheet (the Armory sets the same token
    names for its own section) must not be able to stand in for a theme
    definition, which is exactly the confusion a whole-stylesheet count fell
    into.
    """
    out = []
    at = 0
    while True:
        i = CODE.find(selector, at)
        if i < 0:
            break
        start = i + len(selector)
        out.append(CODE[start:CODE.index("}", start)])
        at = start
    # EVERY block with that selector, joined. A theme state is the UNION of
    # its rules, and this page splits the light one across two `:root` blocks:
    # the legacy names in the first, the design tokens in the second. Reading
    # only the first reports the design tokens missing from a state they are
    # plainly in.
    return chr(10).join(out)


def rules_using(token):
    """Every DECLARATION that references a token, ignoring where it is defined.

    The distinction is the whole point: `--body:...` inside :root is a
    definition and proves nothing, `font-family:var(--body)` is a use.
    """
    return re.findall(r"[a-z-]+\s*:[^;{}]*var\(" + re.escape(token) + r"\)",
                      CODE)


class TheTypefacesAreActuallyApplied(unittest.TestCase):
    """Declaring a font token is not using it, and the difference is invisible
    to every test that only reads :root."""

    def test_each_face_is_referenced_by_at_least_one_rule(self):
        for token in ("--display", "--body", "--mono"):
            self.assertTrue(rules_using(token),
                            token + " is defined but no rule uses it, so the "
                            "face downloads and renders nowhere")

    def test_the_body_text_is_the_body_face_and_not_the_old_monospace(self):
        """The page was set in ui-monospace top to bottom. Body copy in a
        monospace face is the single loudest signal that no design happened."""
        body = CODE[CODE.index("body {"):]
        body = body[:body.index("}")]
        self.assertIn("var(--body)", body)
        self.assertNotIn("ui-monospace", body)

    def test_the_mark_is_set_in_the_display_face(self):
        h1 = STYLE[STYLE.index("h1 {"):]
        h1 = h1[:h1.index("}")]
        self.assertIn("var(--display)", h1)

    def test_mono_is_kept_for_data(self):
        """Not banished. Counts, hashes and timestamps are what it is for, and
        the build line is unreadable in anything else."""
        uses = " ".join(rules_using("--mono"))
        self.assertTrue(uses)
        for data in ("#census", "#rkbuild"):
            self.assertIn(data, STYLE)


class DarkIsTheSameDesignAndNotTheOldSite(unittest.TestCase):
    """The first version of the dark theme reused the previous palette, so a
    reader on a dark-preferring phone saw the OLD site with a new banner and no
    sign the redesign had happened. That is exactly what was reported."""

    def test_the_dark_ground_is_not_the_old_grey(self):
        for block in re.findall(r"(?:prefers-color-scheme: dark|data-theme=\"dark\")"
                                r"[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", CODE):
            self.assertNotIn("#0d1117", block,
                             "the dark theme is still the pre-redesign grey")
            self.assertNotIn("#161b22", block)

    def test_every_surface_token_is_defined_in_each_theme_block(self):
        """A token defined only in light renders the dark theme's text on the
        light theme's card, and that shipped: with data-theme="dark" the shell
        went dark, the cards stayed white, and .fline measured 1.1:1 on the
        live page.

        COUNTING WAS NOT ENOUGH, AND THE FIRST VERSION OF THIS TEST PROVED IT.
        It asserted each token appeared three or more times anywhere in the
        stylesheet, which the Armory's own scoped override satisfied on its
        own: deleting the entire dark media query left the count at three and
        the test still passed. Verified by deleting it. So this reads the
        three theme blocks BY SELECTOR and asks each one directly."""
        blocks = {
            "bare :root": _theme_block(":root {"),
            "prefers-color-scheme: dark": _theme_block(
                ':root:not([data-theme="light"]) {'),
            'data-theme="dark"': _theme_block(':root[data-theme="dark"] {'),
        }
        for token in ("--card", "--card-line", "--on-card", "--on-card-dim",
                      "--bg", "--panel", "--line", "--text", "--dim",
                      "--shell-bg", "--shell-text", "--shell-dim",
                      "--shell-line"):
            for where, block in blocks.items():
                self.assertIn(token + ":", block,
                              "%s is not defined in %s" % (token, where))

    def test_no_component_is_styled_inside_a_theme_block(self):
        """Only tokens move between themes. A component rule inside a media
        query is one that silently does not apply in the un-stamped state."""
        for block in re.findall(r"@media \(prefers-color-scheme: dark\)"
                                r"[^{]*\{((?:[^{}]|\{[^{}]*\})*)\}", CODE):
            for selector in re.findall(r"([^{};]+)\{", block):
                self.assertIn(":root", selector,
                              "component styled inside a theme block: " + selector)


class EveryCustomPropertyUsedIsAlsoDefined(unittest.TestCase):
    """SHIPPED TO PRODUCTION, and nothing anywhere reported it.

    The mobile wall wrote `color:var(--accent-text)` and `var(--caution-text)`
    into the tile rules. The change that DEFINED those two tokens was a
    separate pull request that had not merged yet, and the wall merged first.

    An undefined custom property is invalid at computed-value time, so `color`
    falls back to INHERIT. Every status word on the wall - LIVE, DEAD,
    FIGHTING, HURT - quietly took the caption's ink instead of its own tone.
    No console error, no failing test, and the page looked plausible: the
    words were there, just the wrong colour.

    This is the general form. A var() with no definition and no fallback is
    always a silent nothing, and the failure is invisible in a diff because
    the two halves live in different files or different branches."""

    def test_no_rule_reads_a_property_that_is_never_defined(self):
        # ONLY uses with NO FALLBACK. `var(--cc, transparent)` is a
        # deliberate optional: the class swatch is painted from a value the
        # script sets per character, and the fallback is what it looks like
        # before that happens. A var() with a fallback cannot silently
        # inherit, which is the entire failure this guards against.
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*\)", CODE))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", CODE))
        missing = sorted(used - defined)
        self.assertEqual(missing, [],
                         "used but never defined, so they silently inherit: %s"
                         % missing)

    def test_the_two_that_shipped_undefined_are_defined_everywhere(self):
        """Named explicitly as well as covered by the sweep above, because
        these two are the ones that actually reached a browser."""
        for token in ("--accent-text", "--caution-text"):
            for where, block in (("bare :root", _theme_block(":root {")),
                                 ("dark media", _theme_block(
                                     ':root:not([data-theme="light"]) {')),
                                 ("dark stamp", _theme_block(
                                     ':root[data-theme="dark"] {'))):
                self.assertIn(token + ":", block,
                              "%s missing from %s" % (token, where))


class TheSwitcherKnowsWhichWorldsExist(unittest.TestCase):

    def test_all_three_realms_are_offered(self):
        nav = realmnav.build_nav("")
        self.assertEqual([r["label"] for r in nav], ["PROD", "DEV", "HC"])

    def test_exactly_one_is_current(self):
        for mount in ("", "/dev", "/hardcore"):
            nav = realmnav.build_nav(mount)
            self.assertEqual([r["current"] for r in nav].count(True), 1, mount)
            self.assertTrue(next(r for r in nav if r["mount"] == mount)["current"])

    def test_an_unknown_mount_marks_nothing_current(self):
        """Guessing production would be the most dangerous of the three to be
        wrong about, and a switcher with no active pill is the honest
        rendering of not knowing."""
        nav = realmnav.build_nav("/somewhere-else")
        self.assertEqual([r["current"] for r in nav].count(True), 0)

    def test_hardcore_is_shown_but_not_linked(self):
        """It has no site at all, deliberately (infra#2912): its map
        Deployment and Service are excluded and nothing routes to it. A link
        would send a reader to a 404 that reads as an outage."""
        hc = next(r for r in realmnav.build_nav("") if r["mount"] == "/hardcore")
        self.assertFalse(hc["reachable"])
        self.assertEqual(hc["href"], "")
        self.assertTrue(hc["note"], "a disabled control must say why")

    def test_the_other_two_are_linked_with_a_trailing_slash(self):
        """A link to "/dev" is a redirect away from "/dev/", and a proxy that
        answers it with the root would hand back production while the switcher
        showed dev as active."""
        for r in realmnav.build_nav(""):
            if r["reachable"]:
                self.assertTrue(r["href"].endswith("/"), r["href"])

    def test_it_is_json_serialisable(self):
        """It is substituted into the page as JSON, so anything that is not
        serialisable here is a page that will not parse its own header."""
        json.dumps(realmnav.build_nav("/dev"))


class TheSwitcherReachesThePageWithTheMountPoint(unittest.TestCase):
    """Substituted in the same pass as the mount, because it is a function of
    it: the pill that is lit and the realm the page reads cannot then differ."""

    def test_the_page_carries_the_token(self):
        self.assertIn(basepath.NAV_PLACEHOLDER, PAGE)

    def test_apply_substitutes_real_json(self):
        out = basepath.apply(
            b"<x>__OVERSEER_BASE__</x><y>__OVERSEER_NAV__</y>", "/dev")
        blob = out.decode().split("<y>")[1].split("</y>")[0]
        nav = json.loads(blob)
        self.assertTrue(next(r for r in nav if r["mount"] == "/dev")["current"])

    def test_a_page_without_the_token_is_still_served(self):
        """A missing mount point is refused, because it makes every realm read
        production. A missing switcher is a visible absence somebody reports,
        so refusing to serve would turn a cosmetic loss into an outage."""
        self.assertEqual(basepath.apply(b"__OVERSEER_BASE__", "/dev"), b"/dev")

    def test_it_lives_in_a_json_island_not_in_the_script(self):
        """Bare in the script, the UNSUBSTITUTED file is invalid JavaScript,
        which breaks every parser pointed at the source, including the
        node --check gate that has caught two real bugs in this work."""
        self.assertIn('<script id="realmnav-data" type="application/json">',
                      PAGE)
        self.assertIn("JSON.parse(data.textContent)", PAGE)

    def test_the_page_draws_pills_and_makes_no_judgement(self):
        block = PAGE[PAGE.index('var nav = [];'):]
        block = strip_comments(block[:block.index("})();")], "js")
        for judged in ("hardcore", "PROD", "no page"):
            self.assertNotIn(judged, block,
                             judged + " is decided in realmnav.py, not here")

    def test_it_is_drawn_after_the_markup_it_draws_into(self):
        """SHIPPED BROKEN ONCE, LOCALLY. The first version ran beside u(), in a
        script block ABOVE the header: getElementById returned null, the guard
        returned early exactly as written, and the switcher silently never
        appeared. No error, no failing test, just a missing control."""
        self.assertLess(PAGE.index('<nav id="realmnav"'),
                        PAGE.index("var nav = [];"),
                        "the switcher is drawn before its markup exists")

    def test_the_current_realm_is_marked_for_a_screen_reader(self):
        self.assertIn('setAttribute("aria-current", "page")', PAGE)
        self.assertIn('.rn-pill[aria-current="page"]', STYLE)


class TheHouseRules(unittest.TestCase):

    def test_no_em_dashes(self):
        for name in ("index.html", "realmnav.py", "basepath.py",
                     "tests/test_realm_nav.py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                self.assertNotIn(chr(0x2014), fh.read(), name)


if __name__ == "__main__":
    unittest.main()
