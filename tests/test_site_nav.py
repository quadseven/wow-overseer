"""The tab row, the Watch wall of heads, and the headless family cards.

Asserted against index.html as source, the way test_family_tab.py and
test_raid_tab.py do: map_server.py imports pymysql and the page has no other
test seam.

What the operator asked for, and what each class pins:

  - twenty tabs in one row became a primary row plus two groups (Maps, More),
    with every address still routed by HASH_VIEWS;
  - the Watch tab shows both families' heads, from one endpoint that reads
    every family, instead of whichever family the Family tab last looked at;
  - a family member with no game client has no empty video box and no
    "watch" button;
  - the quest board and the needs panels read the family on screen.
"""
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")


def between(text, start, end):
    at = text.index(start)
    return text[at:text.index(end, at)]


def routed_views():
    """The views HASH_VIEWS lists, by constant name."""
    listed = between(PAGE, "const HASH_VIEWS = [", "];")
    return set(re.findall(r"\b[A-Z]+_VIEW\b", listed[listed.index("["):]))


def view_constants():
    """Every *_VIEW the page declares, by constant name."""
    return set(re.findall(r"^const ([A-Z]+_VIEW) = ", PAGE, re.M))


class TheTabsAreGrouped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.LAYOUT = between(PAGE, "function tabLayout()", "\n}\n")

    def test_the_primary_row_is_the_views_asked_for(self):
        primary = between(self.LAYOUT, "primary:", "],")
        for view in ("WATCH_VIEW", "FAMILY_VIEW", "LINEUP_VIEW", "ARMORY_VIEW",
                     "BAGS_VIEW", "DUNGEONS_VIEW", "DECREE_VIEW"):
            self.assertIn(view, primary, view)
        for view in ("CHRONICLE_VIEW", "RAID_VIEW", "TRADES_VIEW",
                     "COUNCIL_VIEW", "EYE_VIEW", "MAP_VIEW"):
            self.assertNotIn(view, primary, view)

    def test_there_are_two_groups_maps_and_more(self):
        self.assertIn('[MORE_GROUP, "More"]', self.LAYOUT)
        self.assertIn('[MAPS_GROUP, "Maps"]', self.LAYOUT)

    def test_the_continents_go_into_the_maps_group(self):
        load = between(PAGE, "async function loadZones()", "\n}\n")
        self.assertIn("const tabs = tabGroupPanel(MAPS_GROUP);", load)
        self.assertLess(load.index("tabGroupPanel(MAPS_GROUP)"),
                        load.index("for (const id of CONTINENT_ORDER)"))

    def test_a_view_nobody_placed_lands_in_more_not_nowhere(self):
        arrange = between(PAGE, "function arrangeTabs()", "\n}\n")
        self.assertIn("layout.primary.indexOf(b.dataset.view) < 0", arrange)
        self.assertIn("tabGroupPanel(MORE_GROUP).appendChild(b)", arrange)

    def test_every_routed_view_has_a_button(self):
        """HASH_VIEWS is what an address can name; each of them needs a tab
        to light, wherever the grouping puts it."""
        build = between(PAGE, "function buildViewTabs()", "\n}\n")
        for view in routed_views():
            self.assertIn(".dataset.view = " + view + ";", build, view)

    def test_routing_is_still_the_table(self):
        """Grouping moves buttons; it must not become a second router."""
        for fn in ("function arrangeTabs()", "function syncTabGroups()",
                   "function tabGroupPanel("):
            body = between(PAGE, fn, "\n}\n")
            self.assertNotIn("location.hash", body, fn)
            self.assertNotIn("HASH_VIEWS", body, fn)
        self.assertIn("HASH_VIEWS.indexOf(name) >= 0 ? name : FAMILY_VIEW", PAGE)

    def test_the_whole_view_list_is_still_routed(self):
        self.assertEqual(routed_views(), view_constants() - {"MAP_VIEW"})


class TheGroupsWorkFromAKeyboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.PANEL = between(PAGE, "function tabGroupPanel(", "\n}\n")

    def test_the_toggle_is_a_disclosure_button(self):
        self.assertIn('toggle.type = "button";', self.PANEL)
        self.assertIn('toggle.setAttribute("aria-expanded", "false");', self.PANEL)
        self.assertIn('toggle.setAttribute("aria-controls", "tabs-" + key);', self.PANEL)

    def test_escape_closes_the_group_and_returns_focus(self):
        self.assertIn('e.key !== "Escape"', self.PANEL)
        self.assertIn("toggle.focus();", self.PANEL)

    def test_the_toggles_come_last_so_tab_walks_into_the_panel(self):
        arrange = between(PAGE, "function arrangeTabs()", "\n}\n")
        self.assertIn("row.appendChild(tabGroups.get(key).toggle)", arrange)
        self.assertLess(PAGE.index('<nav id="tabs">'), PAGE.index('<div id="tabsub">'))

    def test_the_expanded_state_is_kept_true(self):
        sync = between(PAGE, "function syncTabGroups()", "\n}\n")
        self.assertIn('g.toggle.setAttribute("aria-expanded", String(open));', sync)

    def test_the_lit_group_says_which_view_is_inside_it(self):
        sync = between(PAGE, "function syncTabGroups()", "\n}\n")
        self.assertIn('": " + lit.textContent', sync)

    def test_marking_tabs_reaches_into_the_groups(self):
        mark = between(PAGE, "function markTabs()", "\n}\n")
        self.assertIn('"#tabs button:not(.tabgroup), #tabsub button"', mark)
        self.assertIn("syncTabGroups();", mark)


class TheShellDrawsAtOnce(unittest.TestCase):
    def test_the_named_tabs_do_not_wait_for_the_map_files(self):
        load = between(PAGE, "async function loadZones()", "\n}\n")
        self.assertNotIn("WATCH_VIEW", load)
        self.assertNotIn("buildViewTabs", load)
        foot = PAGE[PAGE.index('window.addEventListener("hashchange", applyHash);'):]
        self.assertLess(foot.index("buildViewTabs();"), foot.index("\napplyHash();"))

    def test_the_census_does_not_wait_for_the_map_files(self):
        self.assertIn("poll();\nsetInterval(poll, 5000);\nloadZones().then(", PAGE)
        self.assertNotIn("loadZones().then(() => { poll();", PAGE)


class TheWatchWallIsBothHeads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.POLL = between(PAGE, "async function pollFamily()", "\n}\n")

    def test_the_watch_view_reads_the_wall_endpoint(self):
        self.assertIn('u("/api/wall")', self.POLL)
        self.assertIn("if (onWatch) renderHeads(payload);", self.POLL)

    def test_a_reply_for_a_view_no_longer_open_is_dropped(self):
        self.assertIn("if (view !== (onWatch ? WATCH_VIEW : FAMILY_VIEW)) return;", self.POLL)
        self.assertIn("if (!onWatch && asked !== familyKey) return;", self.POLL)

    def test_the_heads_render_touches_no_family_card(self):
        heads = between(PAGE, "function renderHeads(p)", "\n}\n")
        self.assertNotIn("familyCard", heads)
        self.assertNotIn("fheadline", heads)
        self.assertIn("renderWall(p);", heads)

    def test_the_server_reads_every_family_once(self):
        self.assertIn('"/api/wall": _wall,', SERVER)
        handler = between(SERVER, "    def _wall(", "    def _armory(")
        self.assertIn("_fetch_rosters()", handler)
        self.assertIn("_fetch_family(everyone)", handler)
        self.assertIn("watchwall.build_heads(", handler)
        self.assertNotIn("query.get", handler)
        self.assertIn("self._send(503", handler)

    def test_each_family_is_built_on_its_own_rows(self):
        """build_family finds the leader by guid among the rows it is handed;
        a merged set would crown one family's head on the other."""
        handler = between(SERVER, "    def _wall(", "    def _armory(")
        self.assertIn('mine = [r for r in rows if r["name"] in names]', handler)


class HeadlessCardsHaveNoVideoChrome(unittest.TestCase):
    def test_a_card_with_no_broadcast_is_marked_headless(self):
        self.assertIn('(m.broadcast_url ? "" : " headless")', PAGE)

    def test_headless_hides_the_video_box_and_the_watch_button(self):
        rule = between(PAGE, "  .fcard.headless .fstream", "}")
        self.assertIn(".fwatch", rule)
        self.assertIn(".fplayer", rule)
        self.assertIn("display:none", rule)

    def test_the_status_strip_is_not_hidden(self):
        self.assertNotIn(".fcard.headless .fstrip", PAGE)
        self.assertNotIn(".fcard.headless .fbar", PAGE)

    def test_an_empty_role_leaves_no_dangling_separator(self):
        """The other family has no personas, so no role: "L11 Warrior - "."""
        render = between(PAGE, "function renderFamily(p)", "\n}\n")
        self.assertNotIn('m["class"] + " - " + m.role', render)
        self.assertIn(".filter(Boolean).join(\" - \")", render)


class ThePanelsReadTheFamilyOnScreen(unittest.TestCase):
    def test_the_needs_poll_names_the_family_and_drops_stale_replies(self):
        poll = between(PAGE, "async function pollNeeds()", "\n}\n")
        self.assertIn('u("/api/needs" + familyQuery(asked))', poll)
        self.assertIn("if ((p.family || asked) !== familyKey || view !== FAMILY_VIEW) return;",
                      poll)

    def test_a_family_tab_is_an_address(self):
        self.assertIn('return v === FAMILY_VIEW ? familyKey : "";', PAGE)
        route = between(PAGE, "function applyHash()", "\n}\n")
        self.assertIn("if (name === FAMILY_VIEW && cut >= 0)", route)
        self.assertIn("decodeURIComponent", route)


if __name__ == "__main__":
    unittest.main()
