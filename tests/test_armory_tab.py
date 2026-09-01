"""The Armory tab's page contract: the rules that cost something to learn.

Asserted against index.html as source, the same way test_family_tab.py guards
the Family tab - map_server.py imports pymysql and the page has no other test
seam. These are not "does it render": they are the handful of rules that a
refactor could quietly undo while leaving five columns on screen looking
perfectly fine.

Two of them are about where this tab's code is ALLOWED to sit. The Family
tab's tests slice the page by its own banners - CSS from its banner to
</style>, JS from its banner to loadZones().then( - so Armory code placed
inside either window silently becomes part of a slice about a different tab
and starts failing assertions that have nothing to do with it. That happened
once while this tab was being built; these two tests are so it does not
happen again to whoever adds the third one.

Ticket: infra#3096.
"""
import pathlib
import unittest

import armory
import family

HERE = pathlib.Path(__file__).resolve().parent.parent


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text()

    def test_the_styles_sit_above_the_family_banner(self):
        """ThumbSized and the broadcast-grid CSS tests both slice from a
        Family banner to </style>. Armory rules dropped into that window get
        read as Family rules."""
        self.assertLess(self.page.index("--- the Armory tab (infra#3096)"),
                        self.page.index("--- the Family tab (infra#2892)"))

    def test_the_script_sits_below_the_family_slice(self):
        """TheFamilyTab slices from its banner to loadZones().then(. Armory
        code in that window is swept into the Family tab's own tests."""
        self.assertGreater(self.page.index("// --- the Armory tab (infra#3096)"),
                           self.page.index("loadZones().then("))


class TheArmoryTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text()
        cls.server = (HERE / "map_server.py").read_text()
        start = cls.page.index("// --- the Armory tab (infra#3096)")
        cls.tab = cls.page[start:cls.page.index("</script>", start)]
        css = cls.page.index("--- the Armory tab (infra#3096)")
        cls.css = cls.page[css:cls.page.index("--- the Family tab (infra#2892)")]

    def test_the_tab_exists_beside_the_family_and_the_continents(self):
        self.assertIn('<section id="armory">', self.page)
        self.assertIn('ab.textContent = "Armory";', self.page)
        self.assertIn("ab.dataset.view = ARMORY_VIEW;", self.page)

    def test_a_third_tab_can_actually_light_up(self):
        """markTabs was a ternary hard-coded to FAMILY_VIEW: any other named
        view fell through to the continent branch, compared an undefined
        dataset.id against `current`, and could never be highlighted. The
        button worked and looked permanently unselected."""
        mark = self.page[self.page.index("function markTabs"):]
        mark = mark[:mark.index("function showView")]
        self.assertIn("view === b.dataset.view", mark)
        self.assertNotIn("FAMILY_VIEW", mark,
                         "markTabs must not know any view by name")

    def test_the_map_is_hidden_behind_every_view_that_is_not_the_map(self):
        """showView read 'not Family means map', so a third view would have
        drawn the canvas and the legend underneath itself."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('wrapEl.style.display = view === MAP_VIEW ? "block" : "none";',
                      show)
        self.assertIn('legend.style.display = view === MAP_VIEW ? "" : "none";', show)

    def test_opening_the_tab_does_not_wait_for_the_timer(self):
        """Thirty seconds of blank page is indistinguishable from a broken
        tab, and it is the first thing anybody would see."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertIn("pollArmory();", arm[:arm.index("return;")])

    def test_opening_the_tab_stops_the_broadcast_grid(self):
        """Five WHEP players kept running behind a view that shows none of
        them is 6Mbit across the tailnet for nothing."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        arm = show[show.index("if (isArm) {"):]
        self.assertIn("stopBroadcasts();", arm[:arm.index("return;")])

    def test_the_poll_is_gated_on_the_tab_being_open(self):
        """Every poll on this page guards on visibility rather than being
        started and stopped, because a timer that is only sometimes running is
        a timer somebody has to remember to restart."""
        poll = self.tab[self.tab.index("async function pollArmory"):]
        self.assertIn("if (view !== ARMORY_VIEW) return;", poll)

    def test_the_poll_is_deliberately_slower_than_every_other_poll(self):
        """The core writes gear and talents on its own save timer, so these
        rows cannot change at the 5s cadence the rest of the page uses. This
        is the one place a reviewer would 'fix' it back to 5000 for
        consistency, so the number and its reason are asserted together."""
        self.assertIn("setInterval(pollArmory, 30000);", self.tab)
        self.assertNotIn("setInterval(pollArmory, 5000)", self.page)
        self.assertIn("save timer", self.tab)

    def test_a_failed_poll_keeps_the_grid_it_has_already_drawn(self):
        """A blank Armory reads as 'they are wearing nothing', which is a
        worse lie than an old answer honestly labelled."""
        poll = self.tab[self.tab.index("async function pollArmory"):]
        poll = poll[:poll.index("setInterval(pollArmory")]
        self.assertIn("may be stale", poll)
        self.assertNotIn("textContent = \"\"", poll)

    def test_nothing_reaches_the_page_as_markup(self):
        """Item names come out of the world database. They are data, and data
        goes in through textContent."""
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)

    def test_the_roster_is_not_retyped_into_the_page(self):
        """WHO the family is belongs to bonds. A second list in the HTML is a
        second answer that can disagree with it, silently, by drawing four
        columns."""
        for name in family.roster():
            self.assertNotIn('"' + name + '"', self.tab)

    def test_the_slot_list_is_not_retyped_into_the_page(self):
        """The grid only reads ACROSS if every column has the same rows in the
        same order, which holds exactly as long as one list decides it. The
        page must take that list from the payload."""
        self.assertIn("for (const spec of p.slots)", self.tab)
        for slot in armory.EQUIPPED_SLOTS:
            self.assertNotIn('"' + slot + '"', self.tab)

    def test_an_empty_slot_says_the_word(self):
        """A blank cell reads as 'nothing to report'. An empty head slot on a
        level 25 warrior is the entire reason for opening this tab."""
        self.assertIn('r.v.textContent = "empty";', self.tab)

    def test_every_quality_the_game_has_is_coloured(self):
        """A quality with no rule inherits body text and silently reads as
        common - an epic drop that looks like a vendor shirt."""
        for quality in armory.QUALITY_NAMES:
            self.assertIn(".q%d { color:#" % quality, self.css)

    def test_a_cosmetic_empty_slot_is_quieter_than_a_real_one(self):
        """Shirt and tabard are empty on everyone forever. An alarm that
        always fires is an alarm nobody reads, and it would drown the empty
        head slot standing next to it."""
        self.assertIn(".aslot.empty .v { color:#d29922; }", self.css)
        self.assertIn(".aslot.empty.cosmetic .v { color:var(--dim); }", self.css)

    def test_five_columns_the_moment_there_is_room_for_five(self):
        """Side by side IS the feature. auto-fit alone settles into
        three-and-a-gap on a wide screen and quietly stops being one view."""
        self.assertIn("grid-template-columns:repeat(5,1fr)", self.css)
        self.assertIn("grid-template-columns:1fr", self.css)

    def test_the_page_says_the_numbers_are_a_save_rather_than_a_live_read(self):
        """The core writes these on a timer measured in minutes. Without the
        sentence, somebody equips a sword, sees no change, and concludes the
        tab is broken."""
        self.assertIn("last saved them", self.tab)


class TheEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()
        cls.dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                          / "Dockerfile").read_text()

    def test_the_endpoint_is_reachable(self):
        self.assertIn('"/api/armory": _armory,', self.server)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """WHO the family is belongs to bonds. Accepting a roster would make
        this a general character query wearing a friendly name."""
        handler = self.server[self.server.index("def _armory"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertIn("armory.build_armory(**_fetch_armory(), book=BOOK)", handler)
        self.assertNotIn("query.get", handler)

    def test_a_dead_database_is_a_503_rather_than_a_hang(self):
        handler = self.server[self.server.index("def _armory"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertIn("self._send(503", handler)

    def test_the_talent_book_is_read_once_at_import_not_per_request(self):
        """It is 117KB of JSON and it never changes. Loading it inside the
        handler would parse it again on every poll, forever."""
        self.assertIn("BOOK = armory.TalentBook.load(HERE)", self.server)
        handler = self.server[self.server.index("def _armory"):]
        handler = handler[:handler.index("def _thoughts")]
        self.assertNotIn("TalentBook.load", handler)

    def test_the_gear_query_is_not_bounded_by_a_hand_typed_slot_count(self):
        """The SQL bound and the grid's rows must come from one list. Typing
        19 here would silently drop a slot the day panel's list grows one."""
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("len(armory.EQUIPPED_SLOTS)", fetch)

    def test_the_gear_query_reaches_the_world_database_for_item_names(self):
        """Item name, quality and level are in acore_world, not the characters
        database. Without the join every item renders as a bare entry id."""
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("LEFT JOIN acore_world.item_template", fetch)

    def test_the_talent_book_ships_in_the_image(self):
        """armory.TalentBook.load runs at IMPORT time, so an image without
        talents.json does not start at all - and that failure lands at pod
        start, long after CI has gone green."""
        self.assertIn("_shared/talents.json", self.dockerfile)
        self.assertIn("_shared/armory.py", self.dockerfile)


if __name__ == "__main__":
    unittest.main()
