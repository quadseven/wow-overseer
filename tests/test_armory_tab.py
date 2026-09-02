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

Tickets: infra#3096 (the tab), infra#3139 (the profile).
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
        self.assertLess(self.page.index("--- the Armory tab (infra#3096, infra#3139)"),
                        self.page.index("--- the Family tab (infra#2892)"))

    def test_the_script_sits_below_the_family_slice(self):
        """TheFamilyTab slices from its banner to loadZones().then(. Armory
        code in that window is swept into the Family tab's own tests."""
        self.assertGreater(self.page.index("// --- the Armory tab (infra#3096, infra#3139)"),
                           self.page.index("loadZones().then("))


class TheArmoryTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text()
        cls.server = (HERE / "map_server.py").read_text()
        start = cls.page.index("// --- the Armory tab (infra#3096, infra#3139)")
        cls.tab = cls.page[start:cls.page.index("</script>", start)]
        css = cls.page.index("--- the Armory tab (infra#3096, infra#3139)")
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
        """Every profile draws the same cells in the same places exactly as
        long as one list decides what the slots are. The page must take
        that list from the payload and never name a slot itself."""
        for slot in armory.EQUIPPED_SLOTS:
            self.assertNotIn('"' + slot + '"', self.tab)

    def test_an_empty_slot_says_the_word(self):
        """A blank cell reads as 'nothing to report'. An empty head slot on a
        level 25 warrior is the entire reason for opening this tab."""
        self.assertIn('cell.textContent = s.cosmetic ? s.slot : "empty";', self.tab)

    def test_the_doll_layout_is_not_retyped_into_the_page(self):
        """Which slots go down which side of the character is a fact the
        payload carries (armory.DOLL_LEFT / DOLL_RIGHT); the page draws
        from it so it never names a slot itself."""
        self.assertIn("for (const spec of p.doll.left)", self.tab)
        self.assertIn("for (const spec of p.doll.right)", self.tab)

    def test_the_icon_host_is_the_one_place_the_page_leaves_the_tailnet(self):
        """The game's art is in the client's archives, not in any table this
        server has, so the icons come from the host every armory site uses.
        Exactly one host, named once, and every image has a fallback so an
        unreachable host degrades to legible rather than to blank."""
        self.assertEqual(self.tab.count("https://"), 1)
        self.assertIn('const ICON_HOST = "https://wow.zamimg.com/images/wow/icons/large/";',
                      self.tab)
        self.assertIn("img.onerror = () => { img.remove(); if (onFail) onFail(); };",
                      self.tab)
        self.assertIn('img.referrerPolicy = "no-referrer";', self.tab)

    def test_the_portrait_is_never_blank(self):
        """No character renderer here: the centre is the race portrait icon
        with the class icon, and a silhouette when the host is down."""
        self.assertIn("function silhouette(colour)", self.tab)
        self.assertIn("m.portrait.race_icon", self.tab)
        self.assertIn("m.portrait.class_icon", self.tab)

    def test_a_tooltip_opens_on_hover_and_stays_on_tap(self):
        """A phone has no hover. A tap pins the tooltip; a second tap, a tap
        elsewhere or Escape lets it go."""
        self.assertIn('e.pointerType === "mouse"', self.tab)
        self.assertIn("arm.pinned = cell;", self.tab)
        self.assertIn('if (e.key === "Escape")', self.tab)

    def test_the_tooltip_draws_the_lines_the_game_draws(self):
        """Name in quality colour, item level, binding, slot and kind, armor,
        stats, enchant, durability, classes, level, equip effects, the set
        with its pieces and bonuses, flavour text, sell price."""
        tip = self.tab[self.tab.index("function buildTip"):self.tab.index("function showTip")]
        for field in ("t.item_level", "t.binding", "t.slot", "t.kind", "t.armor",
                      "t.stats", "t.enchant", "t.durability", "t.classes",
                      "t.requires_level", "t.effects", "t.set.pieces", "t.set.bonuses",
                      "t.flavor", "t.sell_price"):
            self.assertIn(field, tip)

    def test_an_unavailable_stat_says_so(self):
        """A stat the world has not saved is not a zero. Zero attack power is
        a number a person acts on."""
        self.assertIn('s.value === null ? "unavailable" : String(s.value)', self.tab)

    def test_the_talent_grid_is_the_trainers(self):
        """Talents at their true row and column, a count only once a point
        is in, and arrows between prerequisites lit when the prerequisite is
        met."""
        self.assertIn("cell.style.gridRow = String(t.row + 1);", self.tab)
        self.assertIn("cell.style.gridColumn = String(t.col + 1);", self.tab)
        self.assertIn('r.textContent = t.rank ? t.rank + "/" + t.max_rank : "";', self.tab)
        self.assertIn("arrow(box.svg, from, t, from.rank >= reqRank);", self.tab)

    def test_every_quality_the_game_has_is_coloured(self):
        """A quality with no rule inherits body text and silently reads as
        common - an epic drop that looks like a vendor shirt."""
        for quality in armory.QUALITY_NAMES:
            self.assertIn(".q%d { color:#" % quality, self.css)

    def test_a_cosmetic_empty_slot_is_quieter_than_a_real_one(self):
        """Shirt and tabard are empty on everyone forever. An alarm that
        always fires is an alarm nobody reads, and it would drown the empty
        head slot standing next to it."""
        self.assertIn(".aslot.empty { border-style:dashed; color:#d29922; }", self.css)
        self.assertIn(".aslot.empty.cosmetic { color:var(--dim); border-color:var(--line); }",
                      self.css)

    def test_every_quality_borders_its_slot(self):
        """The quality colour is the border of the icon, as the reference
        draws it - an epic with a grey border reads as a vendor item."""
        for quality in armory.QUALITY_NAMES:
            self.assertIn(".aslot.q%d { border-color:#" % quality, self.css)

    def test_one_profile_on_a_phone_and_two_on_a_wide_desktop(self):
        """A profile is as wide as its paper doll needs, and the page must
        never scroll sideways: one column until there is room for two."""
        self.assertIn("#aprofiles { display:grid; gap:1rem; grid-template-columns:minmax(0,1fr); }",
                      self.css)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", self.css)

    def test_the_tooltip_is_a_sheet_on_a_phone(self):
        """There is no 'beside the slot' on a 390px screen."""
        self.assertIn("if (window.innerWidth <= 600) {", self.tab)

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
        self.assertIn("armory.build_armory(**_fetch_armory(), book=BOOK, items=ITEMS)",
                      handler)
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
        for book in ("items", "icons", "spells"):
            self.assertIn(f"_shared/{book}.json", self.dockerfile)
        self.assertIn("_shared/armory.py", self.dockerfile)

    def test_the_gear_query_carries_the_instance_not_just_the_template(self):
        """enchantments and randomPropertyId are what make a belt a 'Belt
        of the Tiger'. Without them half the family's stats do not exist."""
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("ii.enchantments", fetch)
        self.assertIn("ii.randomPropertyId AS random_property_id", fetch)

    def test_the_saved_stats_are_read_when_the_world_has_written_them(self):
        fetch = self.server[self.server.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _ensure_stream_store")]
        self.assertIn("JOIN character_stats s ON s.guid = c.guid", fetch)
        self.assertIn("acore_world.player_class_stats", fetch)
        self.assertIn("acore_world.player_race_stats", fetch)

    def test_the_dev_world_saves_stats_for_external_readers(self):
        """character_stats is written only when PlayerSave.Stats.MinLevel
        allows, and only on logout unless SaveOnlyOnLogout is off. The dev
        overlay turns both on; without them the stat block is derived
        forever."""
        conf = (HERE.parent.parent / "oke" / "manifests" / "wow-dev" / "config"
                / "worldserver.overrides.conf").read_text()
        self.assertIn("\nPlayerSave.Stats.MinLevel = 1\n", conf)
        self.assertIn("\nPlayerSave.Stats.SaveOnlyOnLogout = 0\n", conf)


if __name__ == "__main__":
    unittest.main()
