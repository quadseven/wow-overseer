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

    def test_the_card_surface_is_themed_in_all_three_states(self):
        """A card token defined only in light renders dark text on a dark card
        for every reader whose system prefers dark, which is most of them."""
        for token in ("--card", "--card-line", "--on-card", "--on-card-dim"):
            self.assertGreaterEqual(
                STYLE.count(token + ":"), 3,
                token + " is not defined in all three theme states")

    def test_no_component_is_styled_inside_a_theme_block(self):
        """Only tokens move between themes. A component rule inside a media
        query is one that silently does not apply in the un-stamped state."""
        for block in re.findall(r"@media \(prefers-color-scheme: dark\)"
                                r"[^{]*\{((?:[^{}]|\{[^{}]*\})*)\}", CODE):
            for selector in re.findall(r"([^{};]+)\{", block):
                self.assertIn(":root", selector,
                              "component styled inside a theme block: " + selector)


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
