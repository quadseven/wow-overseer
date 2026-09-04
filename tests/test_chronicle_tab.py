"""The Chronicle's page contract, asserted against index.html as source the
way test_family_tab.py and test_armory_tab.py do - map_server.py imports
pymysql and the page has no other test seam.

THIS SUITE WAS test_achievements_tab.py. The view was renamed rather than
duplicated: same endpoint, same module, a stat strip and cards in place of a
rail with dots on it. The assertions that moved with it are the ones about
WHERE the code sits and about the page deciding nothing; the ones that are
new are about the four things a card no longer composes for itself.

Three of these are about placement. The Family tests slice the page from
their banner to loadZones().then( (script) and to the end of the stylesheet
(CSS); the Armory tests slice from their banner to </script>. Code dropped
into either window is swept into assertions about a different view, so this
view's block lives between the map's intervals and the Council banner, and
its CSS above the Family banner.

Tickets: infra#2597, mod-overseer#88, mod-overseer#152.
"""
import pathlib
import unittest

import achievements

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
CSS_BANNER = "/* --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
NEXT = "// --- the Council (infra#2597)"
NEXT_CSS = "/* --- the Council (infra#2597)"


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    THE GUARDS BELOW HAD TO BE ASKED OF THE CODE AND NOT OF THE FILE, and
    finding that out is the reason this exists: the first run of
    test_the_body_and_the_line_are_not_composed_here failed on the block's own
    banner, which quotes "led by Grug, 21m in the instance" as the example of
    the sentence that moved into Python. A guard that a comment can trip is a
    guard that gets weakened until it passes.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_the_styles_sit_above_the_family_banner(self):
        self.assertLess(self.page.index(CSS_BANNER),
                        self.page.index("--- the Family tab (infra#2892)"))

    def test_the_script_sits_below_the_family_slice_and_above_the_armorys(self):
        start = self.page.index(BANNER)
        self.assertGreater(start, self.page.index("loadZones().then("))
        self.assertLess(start, self.page.index("// --- the Armory tab (infra#3096, infra#3139)"))

    def test_the_shared_furniture_is_above_this_view_and_not_inside_it(self):
        """The section rule, the stat strip and the hue vocabulary are used by
        all three redesigned views. Defined inside any one of their windows
        they would belong to that view's contract, and the next person to
        redraw that view would take the other two with them."""
        self.assertLess(self.page.index("/* --- the redesign furniture (infra#2597)"),
                        self.page.index(CSS_BANNER))


class TheChronicle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.page.index(BANNER)
        cls.tab = cls.page[start:cls.page.index(NEXT, start)]
        css = cls.page.index(CSS_BANNER)
        cls.css = cls.page[css:cls.page.index(NEXT_CSS, css)]

    def test_the_view_exists_beside_family_and_armory(self):
        self.assertIn('<section id="chronicle">', self.page)
        self.assertIn('hb.textContent = "Chronicle";', self.page)
        self.assertIn("hb.dataset.view = CHRONICLE_VIEW;", self.page)
        # Beside them, not among the continents: the button is appended after
        # the Armory's and before the continent loop.
        self.assertLess(self.page.index("tabs.appendChild(ab);"),
                        self.page.index("tabs.appendChild(hb);"))
        self.assertLess(self.page.index("tabs.appendChild(hb);"),
                        self.page.index("for (const id of CONTINENT_ORDER)"))

    def test_the_view_is_an_address(self):
        """#chronicle opens straight onto the view, like #armory does.

        ASKED OF THE ROUTING TABLE, not of a branch. This used to look for
        `showView(ACH_VIEW)` inside applyHash, which was true only while the
        router was a chain of ifs. That chain silently swallowed #watch when
        the Watch wall was added, so the router became a list; being in that
        list is now what "reachable by hash" means."""
        listed = self.page[self.page.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        self.assertIn("CHRONICLE_VIEW", listed)

    def test_the_old_achievements_address_still_opens_this_view(self):
        """A RENAME IS NOT A REASON TO BREAK AN ADDRESS, and this is the exact
        failure the routing table was introduced to prevent: an unrecognised
        hash falls through to the Family tab with no error and no warning, so
        every #achievements link anybody has already sent would quietly open
        the wrong page."""
        self.assertIn('const HASH_ALIASES = new Map([["achievements", CHRONICLE_VIEW]]);',
                      self.page)
        self.assertIn("const name = HASH_ALIASES.get(asked) || asked;", self.page)

    def test_the_alias_table_cannot_be_confused_by_a_typed_hash(self):
        """The name comes out of the URL bar. On a plain object literal
        #constructor and #__proto__ both find something truthy on the
        prototype, and the router would read a function where it expected a
        view name."""
        self.assertNotIn("const HASH_ALIASES = {", self.page)

    def test_show_view_hides_it_with_the_others(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('chrsection.style.display = isChr ? "block" : "none";', show)
        # Entering it is a read: panel closed, broadcasts stopped, one poll.
        branch = show[show.index("if (isChr) {"):]
        branch = branch[:branch.index("return;")]
        for line in ("closePanel();", "stopBroadcasts();", "pollChronicle();"):
            self.assertIn(line, branch)

    def test_the_endpoint_is_routed_and_the_builder_is_pure(self):
        self.assertIn('"/api/achievements": _achievements,', self.server)
        self.assertIn("achievements.build_achievements(**_fetch_achievements())", self.server)
        self.assertIn('fetch(u("/api/achievements"))', self.tab)

    def test_a_missing_run_table_degrades_rather_than_failing(self):
        """The live realm's schema predates overseer_dungeon_run. Error 1146
        on that one query must leave quests and levels standing."""
        fetch = self.server[self.server.index("def _fetch_achievements"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("1146", fetch)
        self.assertIn("run_rows = []", fetch)

    def test_nothing_from_the_payload_is_rendered_as_markup(self):
        """Item names, quest titles and character names come from tables the
        module and the world database write. textContent, never innerHTML."""
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)
        self.assertIn(".textContent = ", self.tab)

    def test_outbound_links_do_not_hand_over_the_opener(self):
        self.assertIn('a.rel = "noopener";', self.tab)
        self.assertIn("wow.zamimg.com/images/wow/icons/large/", self.tab)

    def test_a_failed_poll_keeps_the_cards_and_says_so(self):
        poll = self.tab[self.tab.index("async function pollChronicle"):]
        self.assertIn("may be stale", poll)
        self.assertNotIn("chrline.replaceChildren()", poll)

    def test_the_boss_note_is_tied_to_how_not_to_a_constant(self):
        """The 'inferred from loot' sentence must go away on its own the day
        boss_kill events arrive - it is keyed on the payload's `how`."""
        self.assertIn('if (b.how === "loot")', self.tab)

    def test_quality_colours_are_the_armorys_not_a_second_copy(self):
        """One .q3 on the page. A second set here would be a second opinion
        about what rare looks like, and the Armory's was lifted for
        contrast on purpose."""
        self.assertEqual(self.page.count("\n  .q3 {"), 1)
        self.assertNotIn(".q3 {", self.css)
        self.assertIn('"q" + item.quality', self.tab)

    def test_the_page_carries_no_framework(self):
        """No framework, no bundler, no external CSS of our own.

        NARROWED FOR THE TYPEFACES, AND ONLY FOR THEM. The redesign is set in
        three faces the page cannot supply itself, and self-hosting them as
        base64 would add most of a megabyte to a file that is already one
        document. So exactly one stylesheet link is permitted, to the font host,
        and every other one is still refused.

        WHAT THIS GUARD IS ACTUALLY FOR is a framework arriving by the back
        door: a CSS kit, a component library, a bundle. A font is none of those,
        and the check below still fails if one shows up, because it counts the
        links rather than deleting the rule.

        `<script src=` stays absolutely forbidden. The one external script this
        page runs, the model viewer, is created at runtime with a failure path,
        and that is the pattern anything external has to follow."""
        links = [ln for ln in self.page.splitlines()
                 if "<link rel=\"stylesheet\"" in ln]
        for ln in links:
            self.assertIn("fonts.googleapis.com", ln,
                          "only the font host may be linked: " + ln.strip())
        self.assertLessEqual(len(links), 1, "one font stylesheet, no more")
        self.assertNotIn("<script src=", self.page)

    def test_no_em_dashes(self):
        for name in ("index.html", "achievements.py", "council.py", "eye.py",
                     "map_server.py", "tests/test_achievements.py",
                     "tests/test_chronicle_tab.py"):
            self.assertNotIn(chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name)


class TheCardSaysNothingThePageWrote(unittest.TestCase):
    """THE POINT OF THE REDESIGN, and the reason it is not only a restyle.

    Every sentence a reader sees on a card used to be assembled in JavaScript:
    "led by Grug, 21m in the instance (the run row stayed open 34m)" was three
    ternaries in a function called achHeader. That is judgement, it was in the
    page, and the Python suite could not see it (infra#2597). It now arrives
    on the card, and these assertions are what stops it drifting back.
    """

    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(NEXT, start)]
        cls.code = code(cls.tab)

    def test_the_kind_word_comes_from_the_module(self):
        """"DUNGEON RUN" and "ATTEMPT" are status words, and which one a run
        gets is a judgement about whether anything came of it."""
        self.assertIn("c.word", self.code)
        for invented in ('"DUNGEON RUN"', '"ATTEMPT"', '"QUEST"', '"FIRST"'):
            self.assertNotIn(invented, self.code, invented)

    def test_the_hue_is_a_name_the_module_chose(self):
        """The page turns a name into a class and the stylesheet says what the
        class looks like. A hue picked here would be picked once, for one of
        the two grounds this page is drawn on."""
        self.assertIn('"chr-kind h-" + c.hue', self.code)

    def test_the_body_and_the_line_are_not_composed_here(self):
        self.assertIn("c.body", self.code)
        self.assertIn("c.line.who", self.code)
        self.assertIn("c.line.text", self.code)
        for invented in ("led by ", "finished the objectives",
                         " in the instance", "the run row stayed open"):
            self.assertNotIn(invented, self.code, invented)

    def test_the_character_is_named_beside_their_own_line(self):
        """An unattributed quote reads as the site talking."""
        said = self.code[self.code.index("if (c.line) {"):]
        said = said[:said.index("}")]
        self.assertIn('el("span", "who", c.line.who)', said)

    def test_the_stat_strip_is_counted_by_the_module(self):
        """A number with a word beside it is a claim. The page is handed
        label/value pairs and lays them out."""
        self.assertIn("renderChrStrip(p.strip)", self.code)
        for invented in ("p.runs +", "p.attempts +", "p.visits +",
                         "p.firsts.length +"):
            self.assertNotIn(invented, self.code, invented)

    def test_the_provenance_sentence_is_the_modules_and_not_a_ternary(self):
        """"boss kills inferred from loot" is a caveat about how a number was
        arrived at, which is the most judgement-shaped sentence on the view."""
        self.assertIn("p.provenance", self.code)
        self.assertNotIn("boss_kills_recorded ?", self.code)

    def test_the_one_thing_still_decided_here_is_the_readers_clock(self):
        """A timestamp has to be rendered in the reader's timezone and the
        server does not know what that is. It is the only exception, and it
        is not a judgement about the family."""
        self.assertIn("function chrWhen(iso)", self.code)
        self.assertIn("toLocaleTimeString", self.code)


class TheModuleOwnsTheWordsAndTheHues(unittest.TestCase):
    """The other half of the same contract, asked of achievements.py."""

    def test_every_kind_has_a_word_and_a_hue(self):
        for kind in (achievements.RUN, achievements.QUEST, achievements.LEVEL,
                     achievements.FIRST):
            self.assertIn(kind, achievements.KIND_WORDS, kind)
            self.assertIn(kind, achievements.KIND_HUES, kind)

    def test_every_hue_the_module_can_emit_has_a_rule_in_the_page(self):
        """A hue with no rule is text in the ground colour, which on a card is
        invisible. This is the guard that makes the token vocabulary a
        contract rather than a convention."""
        page = (HERE / "index.html").read_text(encoding="utf-8")
        hues = set(achievements.KIND_HUES.values())
        hues.add(achievements.ATTEMPT_HUE)
        for hue in sorted(hues):
            self.assertIn(".h-%s {" % hue, page, hue)

    def test_a_hue_rule_never_names_a_pigment(self):
        """A pigment is mixed for ONE ground and this page has two. --cyan is
        3.2:1 on white, under the 4.5:1 a label needs, and the wrong colour
        entirely on the dark theme. The roles carry a value per theme."""
        page = (HERE / "index.html").read_text(encoding="utf-8")
        for hue in ("ink", "muted", "green", "cyan", "amber", "vermilion"):
            rule = page[page.index(".h-%s {" % hue):]
            rule = rule[:rule.index("}")]
            for pigment in ("--rust", "--cyan", "--green", "--vermilion",
                            "--amber", "--ink", "--deep-green"):
                self.assertNotIn("var(%s)" % pigment, rule,
                                 ".h-%s paints from the pigment %s" % (hue, pigment))

    def test_every_text_role_is_defined_in_all_three_theme_states(self):
        """A role defined only inside a media query is invisible to a reader
        whose system preference does not match, and the symptom is one
        theme's text on the other theme's ground."""
        page = (HERE / "index.html").read_text(encoding="utf-8")
        style = page[page.index("<style>"):page.index("</style>")]
        for role in ("--accent-text", "--caution-text", "--info-text",
                     "--warn-text"):
            self.assertGreaterEqual(
                style.count(role + ":"), 3,
                role + " is not defined in all three theme states")


if __name__ == "__main__":
    unittest.main()
