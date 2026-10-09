"""The hubs, the Watch wall of heads, and the headless family cards.

Asserted against index.html as source, the way test_family_tab.py and
test_raid_tab.py do: map_server.py imports pymysql and the page has no other
test seam.

What the operator asked for, and what each class pins:

  - a scrolling tab row with More and Maps groups became five hubs (a bottom
    bar on a phone), with every address still routed by HASH_VIEWS;
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
PAGE = (HERE / "classic.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")


def between(text, start, end):
    at = text.index(start)
    return text[at : text.index(end, at)]


def routed_views():
    """The views HASH_VIEWS lists, by constant name."""
    listed = between(PAGE, "const HASH_VIEWS = [", "];")
    return set(re.findall(r"\b[A-Z]+_VIEW\b", listed[listed.index("[") :]))


def view_constants():
    """Every *_VIEW the page declares, by constant name."""
    return set(re.findall(r"^const ([A-Z]+_VIEW) = ", PAGE, re.M))


def hubs():
    """[(key, label, [view constant, ...]), ...] as hubLayout() lists them."""
    layout = between(PAGE, "function hubLayout()", "\n}\n")
    rows = re.findall(r'\[\s*(\w+|"\w+")\s*,\s*"([^"]+)"\s*,\s*\[([^\]]*)\]', layout)
    return [
        (key.strip('"'), label, re.findall(r"\b[A-Z]+_VIEW\b", views))
        for key, label, views in rows
    ]


def phone_block():
    """The shell's phone rules: the first max-width:640px block."""
    at = PAGE.index("  @media (max-width:640px) {")
    return PAGE[at : PAGE.index("\n  }\n", at)]


def rule(selector, text=PAGE):
    """The declarations of the first rule that starts with `selector {`."""
    at = text.index(selector + " {")
    return text[at : text.index("}", at)]


class TheViewsLiveInFiveHubs(unittest.TestCase):
    """The operator: "terrible layout, massive scroll nav". Eight tabs, a More
    group and a Maps group, each opening a second scrolling row, became five
    hubs with the views of the current one beside or above the content."""

    def test_there_are_five_hubs_in_the_chosen_order(self):
        self.assertEqual(
            [label for _key, label, _views in hubs()],
            ["Watch", "Families", "Guild", "Gear", "World"],
        )

    def test_each_hub_holds_the_views_the_operator_chose(self):
        self.assertEqual(
            {label: views for _key, label, views in hubs()},
            {
                "Watch": ["WATCH_VIEW"],
                "Families": ["FAMILY_VIEW", "LINEUP_VIEW", "CHRONICLE_VIEW"],
                "Guild": [
                    "GUILD_VIEW",
                    "GUILDCHAT_VIEW",
                    "DUNGEONS_VIEW",
                    "RAID_VIEW",
                    "COUNCIL_VIEW",
                    "DECREE_VIEW",
                ],
                "Gear": ["ARMORY_VIEW", "BAGS_VIEW", "UPGRADES_VIEW", "TRADES_VIEW"],
                "World": ["MAP_VIEW", "EYE_VIEW"],
            },
        )

    def test_every_view_belongs_to_exactly_one_hub(self):
        """A view in no hub has no way in; a view in two lights two hubs."""
        placed = [v for _k, _l, views in hubs() for v in views]
        self.assertEqual(sorted(placed), sorted(set(placed)), "a view is in two hubs")
        self.assertEqual(set(placed), view_constants())

    def test_every_routed_view_has_a_button(self):
        """HASH_VIEWS is what an address can name; each of them needs a
        button to light, in whichever hub it sits."""
        build = between(PAGE, "function buildViewTabs()", "\n}\n")
        for view in routed_views():
            self.assertIn(".dataset.view = " + view + ";", build, view)

    def test_routing_is_still_the_table(self):
        """Hubs show and hide buttons; they must not become a second router."""
        for fn in (
            "function hubLayout()",
            "function arrangeTabs()",
            "function syncHubs()",
            "function openHub(",
        ):
            body = between(PAGE, fn, "\n}\n")
            self.assertNotIn("location.hash", body, fn)
            self.assertNotIn("HASH_VIEWS", body, fn)
        self.assertIn("HASH_VIEWS.indexOf(name) >= 0 ? name : FAMILY_VIEW", PAGE)

    def test_the_whole_view_list_is_still_routed(self):
        self.assertEqual(routed_views(), view_constants() - {"MAP_VIEW"})

    def test_old_addresses_still_open_their_view(self):
        """Every view id an address could name before is still a routed name,
        the renamed #achievements included, and the map keeps its own route."""
        for name in (
            "family",
            "watch",
            "armory",
            "bags",
            "chronicle",
            "dungeons",
            "raid",
            "lineup",
            "guild",
            "upgrades",
            "trades",
            "council",
            "eye",
            "decree",
            "map",
        ):
            self.assertRegex(PAGE, r'const [A-Z]+_VIEW = "' + name + '";', name)
        self.assertIn('new Map([["achievements", CHRONICLE_VIEW]])', PAGE)
        self.assertIn(
            "if (name === MAP_VIEW) {", between(PAGE, "function applyHash()", "\n}\n")
        )

    def test_the_continents_are_the_world_hubs_row(self):
        load = between(PAGE, "async function loadZones()", "\n}\n")
        self.assertIn('const tabs = document.getElementById("tabs");', load)
        self.assertLess(
            load.index("for (const id of CONTINENT_ORDER)"),
            load.index("arrangeTabs();"),
        )
        self.assertIn(
            "return b.dataset.view ? hubOf(b.dataset.view) : WORLD_HUB;", PAGE
        )
        arrange = between(PAGE, "function arrangeTabs()", "\n}\n")
        self.assertIn("v === MAP_VIEW ? !b.dataset.view", arrange)

    def test_the_group_mechanics_are_gone(self):
        for gone in (
            "MORE_GROUP",
            "MAPS_GROUP",
            "function tabLayout()",
            "function tabGroupPanel(",
            "function syncTabGroups()",
            "tabGroupOpen",
            'id="tabsub"',
            ".tabpanel",
            "function revealTab(",
        ):
            self.assertNotIn(gone, PAGE, gone)

    def test_a_hub_with_one_view_shows_no_row(self):
        sync = between(PAGE, "function syncHubs()", "\n}\n")
        self.assertIn("const solo = shown < 2;", sync)
        self.assertIn("row.hidden = solo", sync)

    def test_the_realm_switcher_rides_the_world_hub(self):
        """It left the header, where it cost a phone a row on every view."""
        header = between(PAGE, "<header>", "</header>")
        self.assertNotIn('id="realmnav"', header)
        subnav = between(PAGE, '<div id="subnav">', "</div>")
        self.assertIn('<nav id="realmnav" aria-label="realm"></nav>', subnav)
        self.assertIn('<script id="realmnav-data" type="application/json">', subnav)
        sync = between(PAGE, "function syncHubs()", "\n}\n")
        self.assertIn("hub !== WORLD_HUB || !realms.childElementCount", sync)

    def test_the_watch_live_dot_is_on_the_hub(self):
        """The Watch hub has one view and so no row: a dot on a hidden button
        would say nothing."""
        self.assertIn(
            "document.querySelector('#hubs button[data-hub=\"' + hubOf(WATCH_VIEW) + '\"]')",
            PAGE,
        )
        self.assertIn("#hubs button.live::before", PAGE)


class TheHubsSitWhereAThumbIs(unittest.TestCase):
    def test_on_a_phone_the_hubs_are_fixed_to_the_bottom(self):
        hubs_rule = rule("    #hubs", phone_block())
        self.assertIn("position:fixed", hubs_rule)
        self.assertIn("bottom:0", hubs_rule)
        self.assertIn("env(safe-area-inset-bottom)", hubs_rule)

    def test_the_bar_can_reach_the_home_indicator(self):
        """Without viewport-fit=cover every safe-area inset reads as zero."""
        self.assertIn("viewport-fit=cover", between(PAGE, '<meta name="viewport"', ">"))

    def test_the_page_is_padded_clear_of_the_bar(self):
        body = rule("    body", phone_block())
        self.assertIn("padding-bottom:calc(53px + env(safe-area-inset-bottom))", body)

    def test_five_equal_cells(self):
        self.assertIn("flex:1 1 0", rule("    #hubs button", phone_block()))

    def test_on_a_wide_screen_the_hubs_ride_the_top(self):
        bar = rule("  #tabbar")
        self.assertIn("position:sticky", bar)
        self.assertIn("top:0", bar)
        self.assertLess(PAGE.index('<nav id="hubs"'), PAGE.index('<nav id="tabs"'))

    def test_no_row_scrolls_sideways(self):
        for sel in ("  #hubs", "  #tabs", "  #subnav", "  #tabbar"):
            body = rule(sel)
            self.assertNotIn("overflow-x", body, sel)
        self.assertIn("flex-wrap:wrap", rule("  #tabs"))
        self.assertIn("flex-wrap:wrap", rule("  #subnav"))
        self.assertNotIn("mask-image", phone_block())

    def test_a_view_button_never_breaks_across_two_lines(self):
        self.assertIn("white-space:nowrap", rule("  #tabs button"))
        self.assertIn("white-space:nowrap", rule("  #hubs button"))


class TheHubsWorkFromAKeyboard(unittest.TestCase):
    def test_hubs_are_buttons_that_say_where_you_are(self):
        build = between(PAGE, "function buildHubs()", "\n}\n")
        self.assertIn('b.type = "button";', build)
        sync = between(PAGE, "function syncHubs()", "\n}\n")
        self.assertIn('b.setAttribute("aria-current", "page")', sync)
        self.assertIn('b.removeAttribute("aria-current")', sync)

    def test_the_lit_view_says_so_too(self):
        mark = between(PAGE, "function markTabs()", "\n}\n")
        self.assertIn('b.setAttribute("aria-current", "page")', mark)
        self.assertIn('"#tabs button"', mark)
        self.assertIn("syncHubs();", mark)

    def test_arrows_walk_both_rows(self):
        walk = between(PAGE, "function arrowWalk(row)", "\n}\n")
        for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
            self.assertIn('"' + key + '"', walk)
        self.assertIn("!b.hidden", walk)
        build = between(PAGE, "function buildHubs()", "\n}\n")
        self.assertIn("arrowWalk(bar);", build)
        self.assertIn("arrowWalk(row);", build)

    def test_escape_goes_back_up_to_the_hub(self):
        build = between(PAGE, "function buildHubs()", "\n}\n")
        self.assertIn('e.key !== "Escape"', build)
        self.assertIn("lit.focus();", build)

    def test_a_hub_returns_to_the_view_left_there(self):
        mark = between(PAGE, "function markTabs()", "\n}\n")
        self.assertIn("hubLast.set(buttonHub(b), b);", mark)
        hub = between(PAGE, "function openHub(key)", "\n}\n")
        self.assertIn("last.click()", hub)

    def test_quiet_ticks_write_nothing(self):
        """render() calls markTabs five times a second; an unguarded write per
        button per tick is churn a screen reader hears."""
        sync = between(PAGE, "function syncHubs()", "\n}\n")
        self.assertIn("if (b.hidden === mine)", sync)
        self.assertIn("if (row.hidden !== solo)", sync)


class TheShellDrawsAtOnce(unittest.TestCase):
    def test_the_named_tabs_do_not_wait_for_the_map_files(self):
        load = between(PAGE, "async function loadZones()", "\n}\n")
        self.assertNotIn("WATCH_VIEW", load)
        self.assertNotIn("buildViewTabs", load)
        foot = PAGE[PAGE.index('window.addEventListener("hashchange", applyHash);') :]
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
        self.assertIn(
            "if (view !== (onWatch ? WATCH_VIEW : FAMILY_VIEW)) return;", self.POLL
        )
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
        self.assertIn('.filter(Boolean).join(" - ")', render)


class ThePanelsReadTheFamilyOnScreen(unittest.TestCase):
    def test_the_needs_poll_names_the_family_and_drops_stale_replies(self):
        poll = between(PAGE, "async function pollNeeds()", "\n}\n")
        self.assertIn('u("/api/needs" + familyQuery(asked))', poll)
        self.assertIn(
            "if ((p.family || asked) !== familyKey || view !== FAMILY_VIEW) return;",
            poll,
        )

    def test_a_family_tab_is_an_address(self):
        self.assertIn('return v === FAMILY_VIEW ? familyKey : "";', PAGE)
        route = between(PAGE, "function applyHash()", "\n}\n")
        self.assertIn("if (name === FAMILY_VIEW && cut >= 0)", route)
        self.assertIn("decodeURIComponent", route)


if __name__ == "__main__":
    unittest.main()
