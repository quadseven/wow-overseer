"""The Achievements tab's page contract, asserted against index.html as source
the way test_family_tab.py and test_armory_tab.py do - map_server.py imports
pymysql and the page has no other test seam.

Two of these are about WHERE the code sits. The Family tests slice the page
from their banner to loadZones().then( (script) and to the end of the
stylesheet (CSS); the Armory tests slice from their banner to </script>.
Code dropped into either window is swept into assertions about a different
tab, so this tab's block lives between the map's intervals and the Armory
banner, and its CSS above the Family banner.

Tickets: mod-overseer#88, mod-overseer#152.
"""
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Achievements tab (mod-overseer#88, mod-overseer#152)"
CSS_BANNER = "/* --- the Achievements tab (mod-overseer#88, mod-overseer#152)"


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


class TheAchievementsTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.page.index(BANNER)
        cls.tab = cls.page[start:cls.page.index("// --- the Armory tab", start)]
        css = cls.page.index(CSS_BANNER)
        cls.css = cls.page[css:cls.page.index("/* --- the Armory tab", css)]

    def test_the_tab_exists_beside_family_and_armory(self):
        self.assertIn('<section id="achievements">', self.page)
        self.assertIn('hb.textContent = "Achievements";', self.page)
        self.assertIn("hb.dataset.view = ACH_VIEW;", self.page)
        # Beside them, not among the continents: the button is appended after
        # the Armory's and before the continent loop.
        self.assertLess(self.page.index("tabs.appendChild(ab);"),
                        self.page.index("tabs.appendChild(hb);"))
        self.assertLess(self.page.index("tabs.appendChild(hb);"),
                        self.page.index("for (const id of CONTINENT_ORDER)"))

    def test_the_view_is_an_address(self):
        """#achievements opens straight onto the tab, like #armory does."""
        apply = self.page[self.page.index("function applyHash"):]
        apply = apply[:apply.index("window.addEventListener(\"hashchange\"")]
        self.assertIn("showView(ACH_VIEW)", apply)

    def test_show_view_hides_it_with_the_others(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('achsection.style.display = isAch ? "block" : "none";', show)
        # Entering it is a read: panel closed, broadcasts stopped, one poll.
        branch = show[show.index("if (isAch) {"):]
        branch = branch[:branch.index("return;")]
        for line in ("closePanel();", "stopBroadcasts();", "pollAchievements();"):
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
        poll = self.tab[self.tab.index("async function pollAchievements"):]
        self.assertIn("may be stale", poll)
        self.assertNotIn("achline.replaceChildren()", poll)

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

    def test_one_column_timeline(self):
        """Mobile-first: the line and the cards are one column; only the
        loot grid inside a card is allowed to go wide, and it is auto-fill."""
        self.assertIn("#achline { position:relative; padding-left:1.4rem; }", self.css)
        self.assertIn("grid-template-columns:repeat(auto-fill, minmax(230px, 1fr))", self.css)

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
        for name in ("index.html", "achievements.py", "map_server.py",
                     "tests/test_achievements.py", "tests/test_achievements_tab.py"):
            self.assertNotIn(chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
