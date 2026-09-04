"""The current-goal banner's page contract (infra#3205).

Asserted against index.html as source, the way test_family_tab.py,
test_armory_tab.py and test_chronicle_tab.py do: map_server.py imports
pymysql and the page has no other test seam.

The first class here is about WHERE the code sits, and it is not bookkeeping.
Three tab suites slice this file by their own banners - the Family from its
banner to loadZones().then(, the Armory and the Wealth view from theirs to
</script>, the Chronicle from its to the Council's - and anything dropped
inside one of those windows silently becomes part of a contract about a
different tab. This banner is not a tab at all, so it has to sit in the one
gap none of them claim.
"""
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the current goal banner (infra#3205)"
CSS_BANNER = "/* --- the current goal banner (infra#3205)"
CHRONICLE = "// --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
CHRONICLE_CSS = "/* --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
FAMILY_CSS = "--- the Family tab (infra#2892)"


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_the_styles_sit_above_every_tabs_css_slice(self):
        """The earliest CSS window on the page starts at the redesign
        furniture the Chronicle heads, so this block goes ahead of it or it
        is swept into one."""
        self.assertLess(self.page.index(CSS_BANNER),
                        self.page.index(CHRONICLE_CSS))
        self.assertLess(self.page.index(CSS_BANNER),
                        self.page.index(FAMILY_CSS))

    def test_the_script_sits_between_the_family_slice_and_the_chronicle(self):
        start = self.page.index(BANNER)
        self.assertGreater(start, self.page.index("loadZones().then("))
        self.assertLess(start, self.page.index(CHRONICLE))

    def test_the_handler_sits_outside_the_family_and_armory_windows(self):
        """Both suites slice map_server.py to `def _thoughts`."""
        server = (HERE / "map_server.py").read_text(encoding="utf-8")
        self.assertGreater(server.index("def _agenda"),
                           server.index("def _thoughts"))


class TheBannerIsAlwaysVisible(unittest.TestCase):
    """The whole point. A goal that only shows on one tab is a goal you have
    to go and look for, which is the state this feature replaces."""

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_it_is_not_inside_any_section(self):
        agenda_at = self.page.index('<div id="agenda">')
        self.assertLess(agenda_at, self.page.index('<section id="family">'))
        self.assertLess(agenda_at, self.page.index('<section id="armory">'))
        self.assertLess(agenda_at, self.page.index('<section id="chronicle">'))
        self.assertLess(agenda_at, self.page.index('<section id="council">'))
        self.assertLess(agenda_at, self.page.index('<section id="eye">'))

    def test_it_is_above_the_tabs_and_below_the_outage_banner(self):
        """An unreachable world outranks anything this can say about a goal."""
        self.assertLess(self.page.index('<div id="stale">'),
                        self.page.index('<div id="agenda">'))
        self.assertLess(self.page.index('<div id="agenda">'),
                        self.page.index('<nav id="tabs">'))

    def test_showview_never_hides_it(self):
        """Every other view element is toggled in showView. This one must not
        be, or it becomes a tab by accident."""
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertNotIn("agenda", show)
        self.assertNotIn("agEl", show)

    def test_it_polls_unconditionally_not_per_view(self):
        """Contrast setInterval(() => { if (view === CHRONICLE_VIEW) ... }) -
        the Chronicle polls only while it is open, and this must not."""
        tab = self._tab()
        self.assertIn("setInterval(pollAgenda, 10000);", tab)
        self.assertNotIn("if (view ===", tab)

    def _tab(self):
        start = self.page.index(BANNER)
        return self.page[start:self.page.index(CHRONICLE, start)]


class TheBannerDrawsWhatItIsGiven(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        start = cls.page.index(BANNER)
        cls.tab = cls.page[start:cls.page.index(CHRONICLE, start)]
        css = cls.page.index(CSS_BANNER)
        # To the `nav` rule that follows the block, NOT to the next tab
        # banner: the Chronicle CSS is hundreds of lines further down, and
        # slicing that far would sweep the panel and player styles in here and
        # let an assertion pass on a rule belonging to something else.
        cls.css = cls.page[css:cls.page.index("  nav { display:flex", css)]

    def test_every_payload_string_is_set_as_text(self):
        """Quest titles come from the world database and the errand reason is
        LLM-written into a table the bridge fills. None of it is trusted."""
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)
        self.assertIn("textContent", self.tab)

    def test_it_decides_nothing_itself(self):
        """The payload arrives fully decided. A page that recomputed 'is this
        stalled' would be a second implementation of the rule, free to drift
        from the one the suite actually tests."""
        for invented in ("dungeon_runs", "completedEncounters", "job ===",
                         "drive_quest", "Math.max"):
            self.assertNotIn(invented, self.tab)

    def test_both_clocks_are_drawn(self):
        """'Set 40 minutes ago' is fine for a goal being worked; 'last moved
        40 minutes ago' is the stall. One without the other can be read as
        the wrong one."""
        self.assertIn("goal set", self.tab)
        self.assertIn("last moved", self.tab)
        self.assertIn("changed_seconds", self.tab)
        self.assertIn("moved_seconds", self.tab)

    def test_a_stall_is_said_in_words_and_not_only_in_colour(self):
        self.assertIn("STALLED", self.tab)
        self.assertIn("stall_after_seconds", self.tab)

    def test_a_failed_poll_keeps_the_sentence_it_has(self):
        """A blanked banner reads as 'the family has no goal', which is worse
        than an old answer honestly labelled."""
        poll = self.tab[self.tab.index("async function pollAgenda"):]
        self.assertNotIn("replaceChildren", poll)
        self.assertIn("agstale", poll)

    def test_stalled_is_drawn_on_top_of_the_activity_not_instead_of_it(self):
        """A stalled dungeon run is still a dungeon run, and losing that word
        costs the reader the number saying how far in they are."""
        self.assertIn("agEl.classList.add(p.activity);", self.tab)
        self.assertIn('if (p.stalled) agEl.classList.add("stalled");', self.tab)

    def test_a_state_change_clears_the_last_state(self):
        self.assertIn("agEl.classList.remove(...AG_STATES);", self.tab)

    def test_the_split_and_stalled_states_are_the_ones_that_stand_out(self):
        """They are the two worth interrupting a person for, so they are the
        two that are not the ordinary blue."""
        self.assertIn("#agenda.split", self.css)
        self.assertIn("#agenda.stalled", self.css)
        self.assertIn("var(--horde)", self.css)

    def test_every_activity_the_module_can_report_has_a_style(self):
        """A new activity kind with no rule would draw an unmarked banner."""
        import agenda
        for kind in (agenda.DUNGEON, agenda.TRAVEL, agenda.JOB, agenda.QUEST,
                     agenda.IDLE, agenda.SPLIT):
            self.assertIn("#agenda." + kind, self.css, kind)
            self.assertIn('"' + kind + '"', self.tab, kind)

    def test_the_headline_is_the_biggest_text_on_the_page(self):
        """Read from across a room while five streams play; half a second is
        the whole budget."""
        self.assertIn("#agline { font-size:1.35rem", self.css)
        self.assertIn("@media (max-width:600px)", self.css)


class TheEndpointIsWiredUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_route_exists(self):
        self.assertIn('"/api/agenda": _agenda,', self.server)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        handler = self.server[self.server.index("def _agenda"):]
        handler = handler[:handler.index("def do_POST")]
        self.assertIn("agenda.build_agenda(**_fetch_agenda())", handler)
        self.assertNotIn("query.get", handler)

    def test_a_failed_query_is_a_503_and_not_an_empty_banner(self):
        handler = self.server[self.server.index("def _agenda"):]
        handler = handler[:handler.index("def do_POST")]
        self.assertIn("503", handler)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                      / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("_shared/agenda.py", dockerfile)


class EveryOverseerTableReadIsGuarded(unittest.TestCase):
    """infra#3172 cost a whole tab on production because one read of a table
    the module creates was not guarded. infra#2846 cost the family their quest
    drive because one COLUMN was missing. Both classes are guarded here, and
    this is the test that says so out loud."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.server.index("def _fetch_agenda")
        cls.fetch = cls.server[start:cls.server.index("def _fetch_streams",
                                                      start)]

    def test_every_overseer_table_goes_through_the_guard(self):
        for table in ("overseer_roster", "overseer_dungeon_run",
                      "overseer_goal", "overseer_trade", "overseer_event"):
            self.assertIn('"%s")' % table, self.fetch, table)

    def test_the_guard_swallows_a_missing_column_as_well_as_a_missing_table(self):
        guard = self.server[self.server.index("def _guarded"):
                            self.server.index("def _fetch_agenda")]
        self.assertIn("(1054, 1146)", guard)

    def test_the_guard_swallows_nothing_else(self):
        """Anything but those two is a real fault and must still reach the
        handler's 503, rather than being rendered as an empty banner."""
        guard = self.server[self.server.index("def _guarded"):
                            self.server.index("def _fetch_agenda")]
        self.assertIn("raise", guard)

    def test_the_newest_columns_have_an_older_fallback(self):
        """dungeon_runs_*, campaign_id, run_number, outcome and members all
        landed on 2026-09-02. A world predating them must get a thinner
        banner, not a 503."""
        self.assertIn("_ROSTER_OLD", self.fetch)
        self.assertIn("_RUNS_OLD", self.fetch)
        self.assertNotIn("dungeon_runs_done",
                         self.server[self.server.index("_ROSTER_OLD ="):
                                     self.server.index("_RUNS_FULL =")])

    def test_the_reserved_word_lead_is_escaped_in_both_roster_reads(self):
        """`lead` is reserved in MySQL 8. An unquoted one is a syntax error,
        which no schema fallback would catch."""
        block = self.server[self.server.index("_ROSTER_FULL ="):
                            self.server.index("_RUNS_FULL =")]
        self.assertEqual(block.count("`lead`"), 2)
        self.assertNotIn(" lead,", block)


if __name__ == "__main__":
    unittest.main()
