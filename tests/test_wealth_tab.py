"""The Wealth and Bags view's page contract, asserted against index.html as
source, the way test_family_tab.py, test_armory_tab.py and
test_achievements_tab.py do: map_server.py imports pymysql and the page has
no other test seam.

TWO OF THESE ARE ABOUT WHERE THE CODE SITS, and they are the reason this file
exists at all. The Family tests slice the page from their banner to
loadZones().then( (script) and to the end of the stylesheet (CSS); the Armory
tests slice from their banner to </script>; the Armory ENDPOINT tests slice
map_server from `def _armory` to `def _thoughts` and from `def _fetch_armory`
to `def _ensure_stream_store`. Code dropped into any of those windows is
swept into assertions about a different feature. So this view's CSS sits
inside the Armory's own window (it belongs to that tab) and above the Family
banner, its script sits below the Armory's poll, its handler sits BELOW
`def _thoughts`, and its fetch sits ABOVE `def _fetch_armory`.

Tickets: quadseven/mod-overseer#88, quadseven/mod-overseer#147.
"""
import pathlib
import unittest

import armory
import family
import wealth

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Wealth and Bags view (quadseven/mod-overseer#88)"
CSS_BANNER = "/* --- the Wealth and Bags view (quadseven/mod-overseer#88)"


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_styles_sit_inside_the_armorys_window_and_above_the_familys(self):
        css = self.page.index(CSS_BANNER)
        self.assertGreater(css, self.page.index("--- the Armory tab (infra#3096"))
        self.assertLess(css, self.page.index("--- the Family tab (infra#2892)"))

    def test_the_script_sits_below_the_armorys_own_poll(self):
        self.assertGreater(self.page.index(BANNER),
                           self.page.index("setInterval(pollArmory, 30000);"))

    def test_the_handler_sits_below_the_armorys_slice(self):
        """The Armory endpoint suite reads everything between `def _armory`
        and `def _thoughts` as the Armory's own contract, including its
        assertion that no handler in that window reads a query parameter."""
        self.assertGreater(self.server.index("def _wealth"),
                           self.server.index("def _thoughts"))

    def test_the_fetch_sits_above_the_armorys_slice(self):
        """Same reasoning at the other end: `def _fetch_armory` to
        `def _ensure_stream_store` is the Armory's fetch window."""
        self.assertLess(self.server.index("def _fetch_wealth"),
                        self.server.index("def _fetch_armory"))


class TheWealthView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        start = cls.page.index(BANNER)
        cls.tab = cls.page[start:cls.page.index("</script>", start)]
        css = cls.page.index(CSS_BANNER)
        cls.css = cls.page[css:cls.page.index("--- the Family tab (infra#2892)")]

    def test_the_view_lives_inside_the_armory_section(self):
        """It is one more view of the same five saved characters, not a
        seventh tab: the same rows, the same save timer, the same poll."""
        section = self.page[self.page.index('<section id="armory">'):]
        section = section[:section.index("</section>")]
        self.assertIn('<div id="wealth">', section)
        self.assertIn('<div id="wcards"></div>', section)
        self.assertIn('<div id="wauction"></div>', section)

    def test_opening_the_armory_tab_fetches_the_bags_too(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertIn("pollWealth();", arm[:arm.index("return;")])

    def test_the_poll_stops_when_the_tab_is_not_open(self):
        """A thirty-second fetch of every inventory row the family owns, run
        forever behind the map, is a query nobody is reading."""
        poll = self.tab[self.tab.index("async function pollWealth"):]
        self.assertIn("if (view !== ARMORY_VIEW) return;", poll)

    def test_the_poll_matches_the_armorys_cadence_and_not_the_maps(self):
        """Money and bags are written by the core's save timer. Polling them
        at the map's five seconds would refetch an identical payload a
        hundred and eighty times per actual change."""
        self.assertIn("setInterval(pollWealth, 30000);", self.tab)
        self.assertNotIn("setInterval(pollWealth, 5000)", self.page)

    def test_a_failed_poll_keeps_the_bags_it_has_and_says_they_are_old(self):
        """An empty bag grid reads as 'he has plenty of room', which is the
        precise opposite of what this view exists to report."""
        poll = self.tab[self.tab.index("async function pollWealth"):]
        poll = poll[:poll.index("setInterval(pollWealth")]
        self.assertIn("wsaved.textContent = WSAVED + WSTALE;", poll)
        self.assertNotIn("wcards.replaceChildren()", poll)
        self.assertNotIn("wheadline.replaceChildren()", poll)

    def test_nothing_reaches_the_page_as_markup(self):
        """Item names come out of the world database. They are data, and data
        goes in through textContent."""
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)

    def test_the_roster_is_not_retyped_into_the_page(self):
        """WHO the family is belongs to bonds. A second list in the HTML is a
        second answer that can disagree with it, silently."""
        for name in family.roster():
            self.assertNotIn('"' + name + '"', self.tab)

    def test_an_empty_bag_square_is_drawn_rather_than_left_out(self):
        """A bag rendered as only the things in it makes a full bag and a
        half-empty one the same shape, and which of those is true is the
        entire finding this view exists for."""
        self.assertIn('if (!it) return el("div", "wslot free");', self.tab)
        self.assertIn("const cells = new Array(bag.slots).fill(null);", self.tab)
        self.assertIn(".wslot.free { border-style:dashed;", self.css)

    def test_an_item_sits_in_its_own_square_and_not_packed_to_the_front(self):
        """The grid is the game's own: slot four is slot four whether or not
        slots one to three hold anything."""
        self.assertIn("cells[at] = it;", self.tab)

    def test_every_quality_borders_its_square(self):
        """The quality colour is the border of the icon, exactly as the paper
        doll above draws it. A rare with a grey border reads as a vendor
        item."""
        for quality in armory.QUALITY_NAMES:
            self.assertIn(".wslot.q%d { border-color:#" % quality, self.css)

    def test_the_icons_come_from_the_armorys_own_loader(self):
        """One approach to item art on this page, not two: the same host, the
        same lazy load, the same fallback when it is unreachable."""
        self.assertIn("iconImg(it.icon, it.name, fallback)", self.tab)
        self.assertIn("const fallback = () => { a.prepend(el(", self.tab)
        self.assertIn(".wslot .nm { align-self:flex-start;", self.css)

    def test_the_item_links_come_from_the_payload_rather_than_a_typed_host(self):
        """The page holds itself to naming exactly two outside hosts (the
        icon CDN and the model viewer). Every other link is built server
        side, the way the Achievements tab's already are."""
        self.assertIn("a.href = it.wowhead;", self.tab)
        self.assertIn("link.href = a.ticket.url;", self.tab)
        self.assertNotIn("https://", self.tab)

    def test_money_is_drawn_in_the_games_own_three_coins(self):
        self.assertIn('n.append(el("span", "g", m.gold + "g "));', self.tab)
        self.assertIn('n.append(el("span", "s", m.silver + "s "));', self.tab)
        self.assertIn('n.append(el("span", "c", m.copper + "c"));', self.tab)
        self.assertIn(".wpurse .g, .wcoins .g { color:#e6c200; }", self.css)

    def test_nothing_is_said_out_loud_rather_than_drawn_as_a_blank(self):
        """A quest item is worth nothing to a vendor. An empty space where
        its price should be reads as a missing number."""
        self.assertIn('n.append(el("span", "none", "nothing")); return n;', self.tab)

    def test_a_full_inventory_is_drawn_loud_because_it_stops_a_bot_questing(self):
        self.assertIn('c.meter.className = "wmeter" + (cap.full ? " full"'
                      ' : pct >= 90 ? " tight" : "");', self.tab)
        self.assertIn(".wmeter.full span { background:var(--horde); }", self.css)
        self.assertIn('wheadline.appendChild(wchip("alarm", "out of room",', self.tab)

    def test_empty_bag_slots_are_reported_because_the_fix_is_different(self):
        """Out of room with three empty bag slots is 'find him a bag'. Out of
        room with four full bags is 'sell something'."""
        self.assertIn("if (cap.empty_bag_slots) {", self.tab)
        self.assertIn('wchip("alarm", "empty bag slots"', self.tab)

    def test_the_page_says_the_numbers_are_a_save_rather_than_a_live_read(self):
        """The core writes money and bags on a timer measured in minutes.
        Without the sentence somebody sells a sword, sees no change, and
        concludes the view is broken."""
        self.assertIn("as the world last saved them", self.tab)

    def test_the_empty_auction_state_says_why_it_is_empty(self):
        """A blank panel and a broken query look identical. Nobody has wired
        auction behaviour yet, so an empty auction house is the CORRECT
        reading and the panel has to say which of the two it is."""
        render = self.tab[self.tab.index("function renderAuctions"):]
        render = render[:render.index("function renderWealth")]
        self.assertIn("Nothing listed, nothing sold, nothing bid on", render)
        self.assertIn("That is an empty auction house, not an empty ", render)
        self.assertIn("link.textContent = a.ticket.label;", render)

    def test_the_panel_says_a_completed_sale_leaves_no_trace(self):
        """The core deletes an auction the moment it finishes and mails the
        gold, so an empty `sold` can never honestly read as 'nothing has ever
        sold'."""
        render = self.tab[self.tab.index("function renderAuctions"):]
        render = render[:render.index("function renderWealth")]
        self.assertIn("if (!a.tracked) {", render)
        self.assertIn("Completed sales leave no trace to read", render)

    def test_the_jump_link_scrolls_rather_than_navigating(self):
        """location.hash is this page's router. An href that actually fired
        would send the reader to a different view."""
        self.assertIn("wjump.onclick = (e) => {", self.tab)
        self.assertIn("e.preventDefault();", self.tab)
        self.assertIn("#ajump a.wjump { order:1;", self.css)

    def test_one_card_on_a_phone_and_more_only_when_there_is_room(self):
        """Same stops as the profiles above, so the tab does not change shape
        halfway down, and the page never scrolls sideways."""
        self.assertIn("#wcards { display:grid; gap:1rem; "
                      "grid-template-columns:minmax(0,1fr); }", self.css)
        self.assertIn("@media (min-width:1400px) { #wcards { "
                      "grid-template-columns:repeat(2,minmax(0,1fr)); } }", self.css)

    def test_the_cards_are_built_once_and_updated_in_place(self):
        """Five cards rebuilt every poll would throw away the scroll position
        mid-read on a phone, which is the one device this is checked from."""
        self.assertIn("const wlth = { cards: new Map() };", self.tab)
        self.assertIn("let c = wlth.cards.get(name);", self.tab)

    def test_the_page_carries_no_framework(self):
        """No framework, no bundler, no external CSS of our own.

        NARROWED FOR THE TYPEFACES, AND ONLY FOR THEM. The redesign is set in
        three faces the page cannot supply itself, and self-hosting them as
        base64 would add most of a megabyte to a file that is already one
        document. So exactly one stylesheet link is permitted, to the font
        host, and every other one is still refused.

        WHAT THIS GUARD IS ACTUALLY FOR is a framework arriving by the back
        door: a CSS kit, a component library, a bundle. A font is none of
        those, and the check below still fails if one shows up, because it
        counts the links rather than deleting the rule.

        `<script src=` stays absolutely forbidden. The one external script
        this page runs, the model viewer, is created at runtime with a failure
        path, and that is the pattern anything external has to follow."""
        links = [ln for ln in self.page.splitlines()
                 if '<link rel="stylesheet"' in ln]
        for ln in links:
            self.assertIn("fonts.googleapis.com", ln,
                          "only the font host may be linked: " + ln.strip())
        self.assertLessEqual(len(links), 1, "one font stylesheet, no more")
        self.assertNotIn("<script src=", self.page)

    def test_no_em_dashes(self):
        for name in ("index.html", "wealth.py", "map_server.py",
                     "tests/test_wealth.py", "tests/test_wealth_tab.py"):
            self.assertNotIn(chr(0x2014), (HERE / name).read_text(encoding="utf-8"),
                             name)


class TheEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        cls.dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                          / "Dockerfile").read_text(encoding="utf-8")
        # From the adapter's own banner (which is where the column list
        # lives) to the Armory's, and the SQL half separately: the docstring
        # QUOTES the Armory's slot-bounded query to explain why this one is
        # not bounded, so an assertion about what the SQL does must not be
        # able to read the prose about what it deliberately does not do.
        cls.fetch = cls.server[
            cls.server.index("# --- the Wealth and Bags view"):
            cls.server.index("# Everything a tooltip draws")]
        cls.sql = cls.fetch[cls.fetch.index("names = family.roster()"):]
        cls.handler = cls.server[cls.server.index("def _wealth"):
                                 cls.server.index("def do_POST")]

    def test_the_endpoint_is_reachable(self):
        self.assertIn('"/api/wealth": _wealth,', self.server)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """WHO the family is belongs to bonds. Accepting a roster would make
        this a general character query wearing a friendly name."""
        self.assertIn("wealth.build_wealth(**_fetch_wealth(), icons=ITEMS.icons)",
                      self.handler)
        self.assertNotIn("query.get", self.handler)
        self.assertIn("names = family.roster()", self.fetch)

    def test_a_dead_database_is_a_503_rather_than_a_hang(self):
        self.assertIn("self._send(503", self.handler)

    def test_the_icon_book_is_read_once_at_import_not_per_request(self):
        """It is the same frozen book the Armory already loads. Reading it
        inside the handler would parse it again on every poll, forever."""
        self.assertIn("ITEMS = armory.ItemBook.load(HERE)", self.server)
        self.assertNotIn("ItemBook.load", self.handler)

    def test_the_inventory_query_is_not_filtered_by_slot(self):
        """Which (bag, slot) pair is a bag, the backpack or the bank is the
        judgement this feature is made of, and it lives in wealth.py where
        the suite can reach it. Filtering here would move it into SQL that
        nothing tests."""
        self.assertNotIn("ci.slot <", self.sql)
        self.assertNotIn("ci.bag = 0", self.sql)
        self.assertIn("JOIN character_inventory ci ON ci.guid = c.guid", self.sql)

    def test_the_query_carries_the_container_guid(self):
        """`character_inventory.item` is the item_instance guid, and it is
        what the rows INSIDE a bag name in their own `bag` column. Without it
        there is no way to tell which container an item is in."""
        self.assertIn("ci.item AS item_guid", self.fetch)
        self.assertIn("ci.bag, ci.slot", self.fetch)

    def test_the_query_reaches_the_world_database_for_prices_and_bag_sizes(self):
        """Name, quality, sell price and container size are in acore_world,
        not the characters database. Without the join every bag renders as an
        unsized box of bare entry ids."""
        self.assertIn("LEFT JOIN acore_world.item_template", self.fetch)
        self.assertIn("it.SellPrice AS sell_price", self.fetch)
        self.assertIn("it.ContainerSlots AS container_slots", self.fetch)

    def test_the_auction_query_resolves_both_sides_to_names(self):
        """auctionhouse keys owner and bidder by character guid. Leaving them
        as numbers would make the builder resolve them, which needs a second
        query it has no connection for."""
        self.assertIn("o.name AS owner_name", self.fetch)
        self.assertIn("b.name AS buyer_name", self.fetch)
        self.assertIn("FROM auctionhouse a", self.fetch)

    def test_the_module_ships_in_the_image(self):
        """map_server imports wealth at module scope, so an image without it
        does not start at all - and that failure lands at pod start, long
        after CI has gone green."""
        self.assertIn("_shared/wealth.py", self.dockerfile)

    def test_the_builder_is_the_only_thing_that_decides_anything(self):
        """Same seam rule as every other endpoint here (infra#2597): rows in,
        payload out, bytes over HTTP."""
        self.assertNotIn("build_capacity", self.server)
        self.assertNotIn("split_inventory", self.handler)
        self.assertEqual(self.server.count("wealth.build_wealth"), 1)


class TheContractWithTheBuilder(unittest.TestCase):
    """The page and the module have to agree about the words in the payload."""

    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index("</script>", start)]

    def test_the_page_uses_the_builders_own_word_for_a_worn_item(self):
        self.assertIn('const WORN = "%s";' % wealth.EQUIPPED, self.tab)

    def test_the_backpack_is_never_named_by_the_page(self):
        """Its name is the builder's, so the label under an icon and the
        label in a notable item's '(in X)' can never disagree."""
        self.assertNotIn('"%s"' % wealth.BACKPACK_NAME, self.tab)


if __name__ == "__main__":
    unittest.main()
