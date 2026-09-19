"""The Bags tab's page contract, asserted against index.html as source, the way
test_family_tab.py, test_armory_tab.py and test_achievements_tab.py do:
map_server.py imports pymysql and the page has no other test seam.

WHAT THIS SUITE IS MOSTLY ABOUT is infra#2597, the seam rule: every judgement
lives in a pure Python module the stdlib suite can import with no database and
no browser, and the page draws what it is handed. That is not a style
preference here - it is the difference between a threshold somebody can find
and a threshold buried in a ternary in a 5,500 line HTML file. The previous
version of this tab decided three things in JavaScript (when a bag meter turns
amber, what an empty purse is called, what the auction panel says when it is
empty), and none of the three was reachable from a test. So a large part of
what follows is the inverse assertion: those sentences must NOT appear in the
page, because they now come from wealth.py.

TWO OF THESE ARE ABOUT WHERE THE CODE SITS. Three tab suites slice index.html
by their own banners - the Family tests from theirs to the end of the
stylesheet and to loadZones().then(, the Armory tests from theirs to the
Family's - so code dropped into any of those windows is swept into assertions
about a different feature. This tab's CSS therefore sits in the Armory's
window (the last one above the Family banner) and its script below the
Armory's poll, and neither is a statement that Bags belongs to the Armory: it
has been its own tab since the redesign.

Tickets: quadseven/mod-overseer#88, quadseven/mod-overseer#147, infra#2831.
"""
import pathlib
import unittest

import family
import wealth

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Bags tab (quadseven/mod-overseer#88, infra#2597)"
CSS_BANNER = "/* --- the Bags tab (quadseven/mod-overseer#88, infra#2597)"
FRONT_DOOR = "// --- the front door (infra#3110)"


def payload():
    """A live-shaped payload, built the way the endpoint builds one.

    No rows: an empty realm is the payload shape the page has to survive on
    the very first paint anyway, and every key the page reads is present in
    it. The cases with rows in them are test_wealth.py's job.
    """
    return wealth.build_wealth([], [], [], [], {})


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_styles_sit_inside_the_armorys_window_and_above_the_familys(self):
        """Not because Bags is part of the Armory - it is its own tab - but
        because the Family tests read everything from their banner to the end
        of the stylesheet as a Family rule, and the Armory's window is the
        last place above it."""
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


class ItIsATabOfItsOwn(unittest.TestCase):
    """It used to be a div at the bottom of the Armory reachable by a jump
    link, on the theory that "what is he wearing" and "what is he carrying"
    are one question. They are not: the Armory is opened when something went
    wrong in a fight, and this is opened when nothing is happening at all,
    because a character with no room stops questing and stands still."""

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_the_section_exists_and_the_armory_no_longer_contains_it(self):
        self.assertIn('<section id="bags">', self.page)
        section = self.page[self.page.index('<section id="armory">'):]
        section = section[:section.index("</section>")]
        self.assertNotIn('id="wcards"', section)
        self.assertNotIn('id="wauction"', section)

    def test_the_jump_link_into_the_armorys_nav_is_gone(self):
        """A jump link is not a tab, and leaving one behind would send a
        reader of the Armory to a block that is no longer under it."""
        self.assertNotIn("wjump", self.page)

    def test_the_button_sits_between_the_armorys_and_the_achievements(self):
        """Next to the Armory because it is the same five and the next
        question about them; before Achievements because that one is read the
        evening after rather than while something is wrong."""
        self.assertIn('bb.textContent = "Bags";', self.page)
        self.assertIn("bb.dataset.view = BAGS_VIEW;", self.page)
        self.assertLess(self.page.index("tabs.appendChild(ab);"),
                        self.page.index("tabs.appendChild(bb);"))
        self.assertLess(self.page.index("tabs.appendChild(bb);"),
                        self.page.index("tabs.appendChild(hb);"))

    def test_the_view_is_an_address(self):
        """#bags opens straight onto the tab. Asked of the routing TABLE
        rather than of a branch: the chain of ifs this replaced silently
        swallowed #watch when the Watch wall was added."""
        listed = self.page[self.page.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        self.assertIn("BAGS_VIEW", listed)

    def test_show_view_hides_it_with_the_others(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('bagsection.style.display = isBags ? "block" : "none";', show)
        branch = show[show.index("if (isBags) {"):]
        branch = branch[:branch.index("return;")]
        for line in ("closePanel();", "stopBroadcasts();", "pollWealth();"):
            self.assertIn(line, branch)

    def test_opening_the_armory_no_longer_fetches_the_bags(self):
        """Two tabs, two polls. Leaving the fetch on the Armory branch would
        pull every inventory row the family owns every thirty seconds behind a
        view that does not draw one of them."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertNotIn("pollWealth();", arm[:arm.index("return;")])

    def test_the_poll_stops_when_the_tab_is_not_open(self):
        """A thirty-second fetch of every inventory row the family owns, run
        forever behind the map, is a query nobody is reading."""
        poll = self.page[self.page.index("async function pollWealth"):]
        self.assertIn("if (view !== BAGS_VIEW) return;", poll)

    def test_the_poll_matches_the_armorys_cadence_and_not_the_maps(self):
        """Money and bags are written by the core's save timer. Polling them
        at the map's five seconds would refetch an identical payload a
        hundred and eighty times per actual change."""
        self.assertIn("setInterval(pollWealth, 30000);", self.page)
        self.assertNotIn("setInterval(pollWealth, 5000)", self.page)


class NothingOnThisTabDecidesAnything(unittest.TestCase):
    """infra#2597, stated as the absence of the sentences.

    Every one of the strings below is a verdict, a threshold or a status word,
    and every one of them used to be typed into index.html. They are asserted
    ABSENT because their presence would mean a second copy exists - and a
    second copy of "no room left" is a second answer to "what does full mean"
    that no test can reach."""

    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(FRONT_DOOR, start)]
        cls.built = payload()

    def test_the_thresholds_left_the_page(self):
        """`cap.full ? " full" : pct >= 90 ? " tight" : ""` was a decision
        about when a person is warned that a bag is filling up, written where
        no test could see it. Ninety per cent is wealth.TIGHT_PERCENT now."""
        self.assertNotIn("pct >= 90", self.tab)
        self.assertNotIn("cap.full", self.tab)
        self.assertNotIn("empty_bag_slots", self.tab)
        self.assertEqual(wealth.TIGHT_PERCENT, 90)

    def test_the_status_words_left_the_page(self):
        for word in ('"nothing"', '"none"', '"no room left"', '"worn"',
                     '"full"', '"out of room"', '"free"'):
            self.assertNotIn(word, self.tab, word + " is composed in the page")

    def test_the_composed_sentences_left_the_page(self):
        """Asserted against the LIVE payload rather than a list typed here, so
        a sentence added to wealth.py and then also pasted into the page is
        caught without anybody remembering to extend this test."""
        f = self.built["family"]["finding"]
        for text in (f["lead"], f["detail"], f["because"],
                     self.built["saved_note"],
                     self.built["auctions"]["caveat"],
                     self.built["auctions"]["empty"]["lead"],
                     self.built["guild_bank"]["lead"],
                     wealth.SPARE_NOTE, wealth.NOTABLE_NOTE, wealth.ABSENT_NOTE):
            self.assertNotIn(text, self.tab, "duplicated in the page: " + text)

    def test_the_section_labels_come_from_the_payload_too(self):
        """A section rule carries an index and a label, and both are words on
        a screen. The page reads them; it does not name them."""
        for header in self.built["sections"].values():
            self.assertNotIn('"' + header["label"] + '"', self.tab)
        self.assertIn("wrule(wcardshead, p.sections.cards);", self.tab)
        self.assertIn("wrule(wauchead, p.sections.auction);", self.tab)
        self.assertIn("wrule(wguildhead, p.sections.guild);", self.tab)

    def test_the_one_sentence_the_page_owns_says_why_it_is_here(self):
        """The unreachable notice cannot come from a payload: there is no
        payload during the failure it exists for. It is the only string on
        this tab that is allowed to be here, and the comment above it says
        so."""
        self.assertIn("const WSTALE =", self.tab)
        self.assertEqual(self.tab.count("const WSTALE"), 1)
        self.assertIn("there is no payload during the failure it exists for",
                      self.tab)

    def test_a_tone_becomes_a_class_and_nothing_else(self):
        """wealth.py decides what counts as an alarm; the page decides what an
        alarm looks like. The whole of that seam is one function."""
        self.assertIn('return base ? base + " t-" + tone : "t-" + tone;', self.tab)
        for tone in (wealth.ALARM, wealth.CAUTION, wealth.GOOD):
            self.assertNotIn('"' + tone + '"', self.tab)

    def test_the_roster_is_not_retyped_into_the_page(self):
        """WHO the family is belongs to bonds. A second list in the HTML is a
        second answer that can disagree with it, silently."""
        for name in family.roster():
            self.assertNotIn('"' + name + '"', self.tab)

    def test_nothing_reaches_the_page_as_markup(self):
        """Item names come out of the world database. They are data, and data
        goes in through textContent."""
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)

    def test_no_outside_host_is_named_here(self):
        """The page holds itself to naming exactly two outside hosts (the icon
        CDN and the model viewer). The item links and both ticket links are
        built server side, where the module that knows the reason for a link
        also holds the URL."""
        self.assertNotIn("https://", self.tab)
        self.assertIn("a.href = it.wowhead;", self.tab)
        self.assertIn("a.href = s.ticket.url;", self.tab)


class TheFindingOpensTheTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(FRONT_DOOR, start)]
        css = page.index(CSS_BANNER)
        cls.css = page[css:page.index("/* --- the Family tab (infra#2892)")]

    def test_it_is_the_first_thing_rendered(self):
        """A chart of 189 out of 190 is a full bar, and a full bar is what a
        healthy inventory looks like too until somebody reads the axis."""
        render = self.tab[self.tab.index("function renderWealth(p)"):]
        self.assertLess(render.index("renderFinding(p.family.finding);"),
                        render.index("renderStats(p.family.stats);"))

    def test_it_carries_the_lead_the_detail_and_the_reason(self):
        fn = self.tab[self.tab.index("function renderFinding"):]
        fn = fn[:fn.index("\n}")]
        for line in ('el("p", "wlead", f.lead)', 'el("p", "wdetail", f.detail)',
                     'el("p", "wbecause", f.because)'):
            self.assertIn(line, fn)
        self.assertIn("if (f.who_label)", fn)

    def test_the_lead_is_the_widest_thing_on_the_tab(self):
        self.assertIn(".wlead { font-family:var(--display);", self.css)
        self.assertIn("font-size:clamp(1.3rem,4.6vw,2rem);", self.css)

    def test_the_tone_colours_it_from_the_named_text_roles(self):
        """Never a raw pigment for text. --warn-text and --caution-text are
        darker than the swatches they are named after because a pigment picked
        for a bar fails as words."""
        self.assertIn("#wfinding.t-alarm .wlead { color:var(--warn-text); }", self.css)
        self.assertIn("#wfinding.t-caution .wlead { color:var(--caution-text); }",
                      self.css)


class TheBagGrid(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(FRONT_DOOR, start)]
        css = page.index(CSS_BANNER)
        cls.css = page[css:page.index("/* --- the Family tab (infra#2892)")]

    def test_an_empty_square_is_drawn_rather_than_left_out(self):
        """A bag rendered as only the things in it makes a full bag and a
        half-empty one the same shape, and which of those is true is the
        entire finding this view exists for."""
        self.assertIn('if (!it) return el("span", "wslot free");', self.tab)
        self.assertIn("const cells = new Array(bag.slots).fill(null);", self.tab)

    def test_an_item_sits_in_its_own_square_and_not_packed_to_the_front(self):
        """The grid is the game's own: slot four is slot four whether or not
        slots one to three hold anything."""
        self.assertIn("cells[at] = it;", self.tab)

    def test_a_square_is_eleven_pixels_ink_or_hairline(self):
        """The whole point of the redesign here. A 44px icon per slot is the
        game's bag window, which is the right shape for browsing a bag and the
        wrong one for "is he full" - that had to be read off a number beside a
        picture of forty-four things."""
        self.assertIn("  .wslot { width:11px; height:11px;", self.css)
        self.assertIn("background:var(--on-card); }", self.css)
        self.assertIn(".wslot.free { background:transparent;", self.css)
        self.assertIn("box-shadow:inset 0 0 0 1px var(--line); }", self.css)

    def test_a_square_is_not_a_control(self):
        """Eleven pixels is a third of the 44px this page allows anywhere
        else, so a square is a span with a title and never a link. The item
        behind it is named properly in the list below, on a 44px row."""
        cell = self.tab[self.tab.index("function wslotCell"):]
        cell = cell[:cell.index("\n}")]
        self.assertNotIn('createElement("a")', cell)
        self.assertIn("cell.title = it.tip;", cell)
        row = self.css[self.css.index(".witem {"):]
        self.assertIn("min-height:44px", row[:row.index("}")])

    def test_the_tooltip_line_is_composed_in_the_module(self):
        """"no vendor value" is a sentence about what a SellPrice of 0 means,
        which is the same judgement stack_value() already makes."""
        self.assertIn("a.title = it.tip;", self.tab)
        self.assertNotIn("no vendor value", self.tab)

    def test_the_bag_is_named_in_its_own_quality_colour(self):
        """The row has no icon on purpose - four more requests per character
        for a picture of a bag nobody identifies by its art - so the name in
        the quality colour is what makes the row identifiable. The colours are
        the Armory's .q0-.q7 and not a second set."""
        self.assertIn('head.appendChild(el("span", "n " + wquality(bag.quality),'
                      " bag.name));", self.tab)
        self.assertNotIn(".q3 {", self.css)

    def test_the_container_says_how_full_it_is_in_the_modules_words(self):
        """A container of unknown size says so rather than rendering "3 of 0",
        and which of those it is was decided where the LEFT JOIN miss is
        understood."""
        self.assertIn('el("span", "of", bag.room_label)', self.tab)


class ThePurseCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(FRONT_DOOR, start)]
        css = page.index(CSS_BANNER)
        cls.css = page[css:page.index("/* --- the Family tab (infra#2892)")]

    def test_money_is_drawn_in_the_games_own_three_coins(self):
        self.assertIn('n.append(el("span", "g", m.gold + "g "));', self.tab)
        self.assertIn('n.append(el("span", "s", m.silver + "s "));', self.tab)
        self.assertIn('n.append(el("span", "c", m.copper + "c"));', self.tab)
        self.assertIn(".wpurse .g, .wcoins .g { color:#e6c200; }", self.css)

    def test_the_word_for_an_empty_purse_comes_from_the_module(self):
        """A quest item is worth nothing to a vendor. "nothing", "0c" and a
        blank space are three different claims about that, and the page used
        to pick one of them."""
        self.assertIn('n.append(el("span", "zero", m.text)); return n;', self.tab)

    def test_a_full_inventory_is_drawn_loud_because_it_stops_a_bot_questing(self):
        self.assertIn('c.meter.className = wtone("wmeter", r.tone);', self.tab)
        self.assertIn(".wmeter.t-alarm span { background:var(--vermilion); }", self.css)

    def test_empty_bag_positions_are_called_out_separately_and_in_amber(self):
        """Out of room with three empty bag positions is "find him a bag".
        Out of room with four full bags is "sell something". Two different
        fixes, so two different lines and two different colours."""
        self.assertIn("if (r.spare_label) {", self.tab)
        self.assertIn(".wspare .t-caution { color:var(--caution-text); }", self.css)

    def test_a_bagged_item_is_amber_and_a_worn_one_is_not(self):
        """An item on a body is where it belongs; the same item loose in a bag
        is a spare, a mistake, or gold nobody has banked. Which of those a
        thing is was decided in the module, and the page reads the tone."""
        self.assertIn('el("span", wtone("w", it.place_tone), it.place)', self.tab)
        self.assertIn(".witem .w.t-caution { color:var(--caution-text); }", self.css)

    def test_the_cards_are_built_once_and_updated_in_place(self):
        """Five cards rebuilt every poll would throw away the scroll position
        mid-read on a phone, which is the one device this is checked from."""
        self.assertIn("const wlth = { cards: new Map(), note: \"\" };", self.tab)
        self.assertIn("let c = wlth.cards.get(name);", self.tab)

    def test_a_failed_poll_keeps_the_bags_it_has_and_says_they_are_old(self):
        """An empty bag grid reads as "he has plenty of room", which is the
        precise opposite of what this view exists to report."""
        poll = self.tab[self.tab.index("async function pollWealth"):]
        poll = poll[:poll.index("setInterval(pollWealth")]
        self.assertIn("wsaved.append(el(\"span\", \"\", WSTALE));", poll)
        self.assertIn("if (wlth.note)", poll)
        self.assertNotIn("wcards.replaceChildren()", poll)
        self.assertNotIn("wfinding.replaceChildren()", poll)

    def test_the_page_says_the_numbers_are_a_save_rather_than_a_live_read(self):
        """Without the sentence somebody sells a sword, sees no change, and
        concludes the view is broken. It is the payload's, because it is a
        fact about the data."""
        self.assertIn("as the world last saved them", wealth.SAVED_NOTE)
        self.assertIn("wsaved.replaceChildren(el(\"span\", \"\", p.saved_note));",
                      self.tab)


class TheEmptyPanelsSayWhyTheyAreEmpty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(FRONT_DOOR, start)]
        cls.built = payload()

    def test_the_auction_panel_draws_the_reason_rather_than_a_blank(self):
        """A blank panel and a broken query look identical. Nobody has wired
        auction behaviour yet, so an empty auction house is the CORRECT
        reading and the panel has to say which of the two it is."""
        render = self.tab[self.tab.index("function renderAuctions"):]
        render = render[:render.index("\n}")]
        self.assertIn('el("p", "wplead", a.empty.lead)', render)
        self.assertIn('el("p", "wbody", a.empty.body)', render)
        self.assertIn("wlinked(a.empty.why)", render)

    def test_the_panel_says_a_completed_sale_leaves_no_trace(self):
        """The core deletes an auction the moment it finishes and mails the
        gold, so an empty `sold` can never honestly read as "nothing has ever
        sold"."""
        render = self.tab[self.tab.index("function renderAuctions"):]
        render = render[:render.index("\n}")]
        self.assertIn("if (!a.tracked)", render)
        self.assertIn('el("p", "wbody", a.caveat)', render)

    def test_the_guild_bank_lists_the_road_rather_than_an_empty_vault(self):
        """Same reasoning one panel down. There is no guild, so there is no
        guild bank - and what is useful is not the empty vault, it is which
        parts of the road to one the module can already drive."""
        render = self.tab[self.tab.index("function renderGuild"):]
        render = render[:render.index("\n}")]
        self.assertIn('el("p", "wplead", g.lead)', render)
        self.assertIn("for (const s of g.steps)", render)
        self.assertIn('el("span", wtone("v", s.tone), s.state_label)', render)
        self.assertIn("wlinked(g.blocked)", render)

    def test_both_tickets_are_links_the_module_supplied(self):
        for ticket in (wealth.AUCTION_TICKET, wealth.GUILD_TICKET):
            self.assertNotIn(ticket["label"], self.tab)
            self.assertNotIn(ticket["url"], self.tab)
        self.assertIn("a.textContent = s.ticket.label;", self.tab)


class TheContractWithTheBuilder(unittest.TestCase):
    """The page and the module have to agree about the words in the payload.

    A source-reading suite cannot execute the page, so this does the next best
    thing: it builds a real payload and asserts that every key the page reads
    off it exists. A renamed key is otherwise a silent undefined on a tab
    nobody has open."""

    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(BANNER)
        cls.tab = page[start:page.index(FRONT_DOOR, start)]
        cls.built = payload()

    def test_the_top_level_keys_the_page_reads_all_exist(self):
        for key in ("members", "family", "auctions", "guild_bank", "sections",
                    "saved_note"):
            self.assertIn(key, self.built, key)
            self.assertIn("p." + key, self.tab, key)

    def test_the_family_keys_the_page_reads_all_exist(self):
        for key in ("finding", "stats"):
            self.assertIn(key, self.built["family"], key)

    def test_the_finding_keys_the_page_reads_all_exist(self):
        for key in ("lead", "detail", "because", "tone", "who_label"):
            self.assertIn(key, self.built["family"]["finding"], key)

    def test_the_member_keys_the_page_reads_all_exist(self):
        absent = self.built["members"][0]
        for key in ("name", "present", "who", "absent_note"):
            self.assertIn(key, absent, key)
        present = wealth.build_member(
            family.roster()[0],
            {"name": family.roster()[0], "level": 25, "class": 1, "money": 0},
            [], {})
        for key in ("who", "room", "holding", "elsewhere_note", "notable_note",
                    "containers", "class_colour", "money", "held"):
            self.assertIn(key, present, key)
        for key in ("percent", "tone", "used_label", "free_label", "free_tone",
                    "bags_label", "spare_label", "spare_tone"):
            self.assertIn(key, present["room"], key)

    def test_the_guild_bank_keys_the_page_reads_all_exist(self):
        bank = self.built["guild_bank"]
        for key in ("lead", "body", "steps", "blocked"):
            self.assertIn(key, bank, key)
        for key in ("step", "state_label", "tone"):
            self.assertIn(key, bank["steps"][0], key)

    def test_the_linked_sentence_has_both_halves_and_a_ticket(self):
        for sentence in (self.built["guild_bank"]["blocked"],
                         self.built["auctions"]["empty"]["why"]):
            for key in ("before", "ticket", "after"):
                self.assertIn(key, sentence, key)


class ItReadsOnAPhone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        css = cls.page.index(CSS_BANNER)
        cls.css = cls.page[css:cls.page.index("/* --- the Family tab (infra#2892)")]

    def test_one_card_on_a_phone_and_more_only_when_there_is_room(self):
        """One breakpoint, at 640, so the tab does not change shape twice on
        the way to a desktop and the page never scrolls sideways."""
        self.assertIn("#wcards { display:grid; gap:1rem; "
                      "grid-template-columns:minmax(0,1fr); }", self.css)
        self.assertIn("@media (min-width:640px) {\n"
                      "    #wcards { grid-template-columns:"
                      "repeat(auto-fit,minmax(330px,1fr)); }\n  }", self.css)

    def test_the_strip_is_two_columns_on_a_phone_rather_than_seven_rows(self):
        """Seven readings stacked is a screen and a half of scrolling before
        the first card, and these are glanced at rather than read."""
        self.assertIn("#wstats { display:grid; gap:.55rem; margin-top:1rem;\n"
                      "            grid-template-columns:repeat(2,minmax(0,1fr)); }",
                      self.css)

    def test_the_only_breakpoint_is_the_one_the_handoff_names(self):
        self.assertNotIn("min-width:1400px", self.css)
        self.assertNotIn("min-width:2100px", self.css)
        self.assertEqual(self.css.count("@media"), self.css.count("min-width:640px"))

    def test_the_section_rule_is_the_index_the_line_and_the_label(self):
        self.assertIn(".bline { flex:1 1 auto; height:2px; "
                      "background:var(--on-card); }", self.css)
        self.assertIn(".bidx { font-family:var(--mono);", self.css)
        self.assertIn(".blab { font-family:var(--mono);", self.css)

    def test_every_row_that_can_be_tapped_is_a_finger_tall(self):
        for rule in (".witem {", ".wauc {", ".wstep {"):
            block = self.css[self.css.index(rule):]
            block = block[:block.index("}")]
            self.assertIn("min-height:44px", block, rule)

    def test_the_page_carries_no_framework(self):
        """No framework, no bundler, no external CSS of our own, one stylesheet
        link and it goes to the font host. What this guard is actually for is a
        framework arriving by the back door: a CSS kit, a component library, a
        bundle. A font is none of those, and the check still fails if one shows
        up, because it counts the links rather than deleting the rule."""
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
        cls.dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
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

    def test_whether_there_is_a_guild_is_asked_rather_than_assumed(self):
        """The guild bank panel says there is no guild bank because there is
        no guild. That sentence has to stop being drawn the day somebody makes
        one, which a constant in the builder could never do."""
        self.assertIn("g.name AS guild_name", self.fetch)
        self.assertIn("JOIN guild_member gm ON gm.guid = c.guid", self.fetch)
        self.assertIn('"guild_rows": guild_rows', self.fetch)

    def test_the_guild_bank_snapshot_is_read_only_and_old_realms_fail_closed(self):
        self.assertIn("g.guildid AS guild_id", self.fetch)
        self.assertIn("FROM guild_bank_tab t", self.fetch)
        self.assertIn("guild_bank_item i", self.fetch)
        self.assertIn("guild_bank_rows", self.fetch)
        self.assertIn("guild_bank_right", self.fetch)
        self.assertIn("guild_bank_right_rows", self.fetch)
        self.assertIn("1146", self.fetch)

    def test_the_module_ships_in_the_image(self):
        """map_server imports wealth at module scope, so an image without it
        does not start at all - and that failure lands at pod start, long
        after CI has gone green."""
        self.assertIn("wealth.py", self.dockerfile)

    def test_the_builder_is_the_only_thing_that_decides_anything(self):
        """Same seam rule as every other endpoint here (infra#2597): rows in,
        payload out, bytes over HTTP."""
        self.assertNotIn("build_capacity", self.server)
        self.assertNotIn("build_finding", self.server)
        self.assertNotIn("split_inventory", self.handler)
        self.assertEqual(self.server.count("wealth.build_wealth"), 1)


if __name__ == "__main__":
    unittest.main()
