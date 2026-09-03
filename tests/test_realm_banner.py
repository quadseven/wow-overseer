"""The realm banner's page and wiring contract (quadseven/mod-overseer#184).

Asserted against index.html and map_server.py as source, the way
test_agenda_banner.py, test_family_tab.py, test_armory_tab.py and
test_achievements_tab.py do: map_server.py imports pymysql and the page has no
other test seam.

WHAT IS ACTUALLY BEING PROTECTED HERE. This is the only element on the site that
says which world the reader is looking at, and it exists because the hostnames
that used to say it are being collapsed into one. Almost everything below is
about a way this element could stop being trustworthy without anything failing:
a poll that quietly blanks it, a markup default that renders as safe, an
unguarded read that takes the page down on the one realm that most needs a
label, or a second copy of the "is this production" rule written in JavaScript.

The first class is about WHERE the code sits, and it is not bookkeeping. Four
suites slice these two files by their own banners, and code dropped inside one
of those windows silently becomes part of a contract about something else.
"""
import pathlib
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent

CSS_BANNER = "/* --- which world this is (quadseven/mod-overseer#184)"
JS_BANNER = "// --- which world this is (quadseven/mod-overseer#184)"
AGENDA_CSS = "/* --- the current goal banner (infra#3205)"
AGENDA_JS = "// --- the current goal banner (infra#3205)"
ACH_CSS = "/* --- the Achievements tab (mod-overseer#88, mod-overseer#152)"
FAMILY_CSS = "--- the Family tab (infra#2892)"

# The C++ module that writes the table this banner reads, through the submodule
# infra pins it at.
MODULE_SRC = (
    pathlib.Path(__file__).resolve().parents[3]
    / "docker/azerothcore-playerbots/mod-overseer/src/overseer_decisions.h"
)


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_styles_sit_above_every_other_css_slice(self):
        """The earliest CSS windows on the page start at the current-goal
        banner and the Achievements banner, so this block goes ahead of both or
        it is swept into one of them."""
        self.assertLess(self.page.index(CSS_BANNER), self.page.index(AGENDA_CSS))
        self.assertLess(self.page.index(CSS_BANNER), self.page.index(ACH_CSS))
        self.assertLess(self.page.index(CSS_BANNER), self.page.index(FAMILY_CSS))

    def test_the_script_sits_in_the_one_gap_no_suite_claims(self):
        """The Family tab's window ends at loadZones().then(, the current-goal
        banner's begins at its own comment, and the Achievements and Armory
        windows are further down again."""
        start = self.page.index(JS_BANNER)
        self.assertGreater(start, self.page.index("loadZones().then("))
        self.assertLess(start, self.page.index(AGENDA_JS))

    def test_the_handler_sits_outside_every_window_in_map_server(self):
        """The Family and Armory suites slice to `def _thoughts`, the
        current-goal banner's from `def _agenda` to `def do_POST`, and the
        Standing suite from `def _standing` to `def _questlog`. This handler is
        above all of them, which is also where it belongs: it answers which
        world, and the rest only mean something inside that answer."""
        realm_at = self.server.index("    def _realm(")
        for later in ("def _map", "def _family", "def _armory", "def _standing",
                      "def _thoughts", "def _agenda", "def do_POST"):
            self.assertLess(realm_at, self.server.index(later), later)

    def test_the_fetch_sits_above_every_fetch_window(self):
        """The earliest fetch window any suite slices starts at
        `def _fetch_armory`; the modelviewer's ends at `MODELS = `, which is
        above _connect."""
        fetch_at = self.server.index("def _fetch_realm")
        self.assertGreater(fetch_at, self.server.index("def _connect"))
        for later in ("def _fetch_rows", "def _fetch_armory",
                      "def _fetch_achievements", "def _fetch_agenda",
                      "def _guarded"):
            self.assertLess(fetch_at, self.server.index(later), later)


class TheBannerIsAlwaysVisible(unittest.TestCase):
    """The whole point. A label that only shows on one tab, or that a view
    switch can hide, is not a label."""

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_it_is_not_inside_any_section(self):
        realm_at = self.page.index('<div id="realm"')
        for section in ('<section id="family">', '<section id="armory">',
                        '<section id="achievements">', '<div id="wrap">'):
            self.assertLess(realm_at, self.page.index(section), section)

    def test_it_is_the_first_thing_in_the_body_and_above_every_other_banner(self):
        """WHICH world outranks both "the world is unreachable" and what the
        family wants, because neither of those sentences means anything until
        you know which realm they are about."""
        realm_at = self.page.index('<div id="realm"')
        self.assertLess(self.page.index("<body>"), realm_at)
        self.assertLess(realm_at, self.page.index("<header>"))
        self.assertLess(realm_at, self.page.index('<div id="stale">'))
        self.assertLess(realm_at, self.page.index('<div id="agenda">'))
        self.assertLess(realm_at, self.page.index('<nav id="tabs">'))

    def test_showview_never_hides_it(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        for name in ("realm", "rklabel", "realmEl"):
            self.assertNotIn(name, show, name)

    def test_it_polls_unconditionally_and_not_per_view(self):
        tab = self._tab()
        self.assertIn("setInterval(pollRealm, 60000);", tab)
        self.assertNotIn("if (view ===", tab)

    def _tab(self):
        start = self.page.index(JS_BANNER)
        return self.page[start:self.page.index(AGENDA_JS, start)]


class TheMarkupShipsTheAlarmState(unittest.TestCase):
    """THE LOAD-BEARING DETAIL OF THE WHOLE ELEMENT, and the one thing here that
    is not like any other banner on this page.

    Every other banner starts empty and is filled in by its first poll. If this
    one did that, a page whose very first /api/realm call failed would sit there
    unlabelled - which is exactly the state the reader must never be in, and
    exactly the state they are most likely to be in when something is already
    wrong. So the static markup IS the unverified state, and the script only
    ever replaces it with something the server actually said.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        start = cls.page.index('<div id="realm"')
        cls.markup = cls.page[start:cls.page.index("</div>", cls.page.index(
            'id="rkbuild"'))]

    def test_the_default_class_is_the_unverified_one(self):
        self.assertIn('class="rk-unknown"', self.markup)
        self.assertNotIn("rk-non-production", self.markup)

    def test_the_default_text_is_the_alarm_and_not_a_placeholder(self):
        self.assertIn("REALM NOT VERIFIED", self.markup)
        self.assertIn("Treat what you are seeing as live", self.markup)

    def test_the_default_never_says_anything_reassuring(self):
        for calm in ("NOT PRODUCTION", "development", "dev", "test", "safe"):
            self.assertNotIn(calm, self.markup, calm)

    def test_the_three_states_all_have_styles(self):
        """The page sets className to "rk-" + kind. A kind with no rule would
        render as an unstyled strip, which reads as no warning at all."""
        for kind in ("production", "non-production", "unknown"):
            self.assertIn("#realm.rk-%s" % kind, self.page, kind)

    def test_production_does_not_depend_on_colour_alone(self):
        """A colourblind reader, a monochrome screenshot, or a stylesheet that
        failed to load all have to leave the word standing."""
        self.assertIn("REALM NOT VERIFIED", self.page)
        self.assertIn('rkLabel.textContent = d.label;', self.page)


class TheBannerDrawsWhatItIsGiven(unittest.TestCase):
    """The payload arrives fully decided. A second copy of "is this production"
    written in JavaScript is a second copy free to drift, and not drifting is
    the only thing this banner is for."""

    @classmethod
    def setUpClass(cls):
        page = (HERE / "index.html").read_text(encoding="utf-8")
        start = page.index(JS_BANNER)
        cls.tab = page[start:page.index(AGENDA_JS, start)]

    def test_every_string_it_shows_is_set_as_text(self):
        self.assertNotIn("innerHTML", self.tab)
        self.assertNotIn("insertAdjacentHTML", self.tab)
        self.assertIn("textContent", self.tab)

    def test_it_decides_no_realm_kind_of_its_own(self):
        """No comparison against a kind, no label text, no name-to-kind map.
        Everything it draws was named by realm.py."""
        for decided in ('"production"', "'production'", '"NOT PRODUCTION"',
                        "REALM NOT VERIFIED", '"stale"', "Homelab"):
            self.assertNotIn(decided, self.tab, decided)

    def test_it_composes_no_sentence_of_its_own(self):
        """realm.py returns realm_line, build_line and warning_text already
        written, precisely so the suite can assert on what a reader sees."""
        for field in ("d.label", "d.realm_line", "d.build_line",
                      "d.warning_text"):
            self.assertIn(field, self.tab, field)

    def test_a_failed_poll_leaves_the_banner_exactly_as_it_was(self):
        """The realm has not changed because a query timed out. Blanking a
        correct PRODUCTION label over a network blip would be the page throwing
        away the one fact it is here to hold on to."""
        catch = self.tab[self.tab.index("catch (e)"):]
        catch = catch[:catch.index("pollRealm();")]
        for wipe in ("textContent", "className", "renderRealm"):
            self.assertNotIn(wipe, catch, wipe)


class TheEndpointIsWiredUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")

    def test_the_route_exists(self):
        self.assertIn('"/api/realm": _realm,', self.server)

    def test_the_builder_is_pure_and_takes_nothing_from_the_caller(self):
        handler = self.server[self.server.index("    def _realm("):]
        handler = handler[:handler.index("def _healthz")]
        self.assertIn("realm.build_realm(**_fetch_realm())", handler)
        self.assertNotIn("query.get", handler)

    def test_a_failed_query_is_a_503_and_not_a_wrong_banner(self):
        handler = self.server[self.server.index("    def _realm("):]
        handler = handler[:handler.index("def _healthz")]
        self.assertIn("503", handler)

    def test_the_page_asks_for_it(self):
        self.assertIn('fetch(u("/api/realm"))', self.page)

    def test_the_pure_module_imports_no_database(self):
        source = (HERE / "realm.py").read_text(encoding="utf-8")
        self.assertNotIn("pymysql", source)
        self.assertNotIn("import os", source)

    def test_the_module_ships_in_the_image(self):
        """The build's shared-dir copy names every file explicitly, so a new
        module is one forgotten line away from a pod that crashes on import."""
        dockerfile = (HERE.parent.parent / "docker" / "wow-overseer"
                      / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("_shared/realm.py", dockerfile)


class EveryReadIsGuardedWithTheClassThatActuallyFires(unittest.TestCase):
    """infra#3172 cost a whole tab on the live realm because one read of a table
    the in-world module creates was not guarded. This banner reads the NEWEST
    such table, so on the day it ships every realm answers 1146 to it, and the
    live realm will answer 1146 for longer than the others because it is rolled
    least often. A banner that 503s there has told the reader nothing at all
    about what they are looking at, which is worse than the state it replaced.

    THE CATCH CLASS IS THE POINT OF THIS CLASS, not the presence of a try. It
    was verified against pymysql 1.4.6 as deployed, by asking the live realm's
    own database for a table and a column that do not exist:

        MISSING TABLE  -> pymysql.err.ProgrammingError 1146
        MISSING COLUMN -> pymysql.err.OperationalError  1054

    1054 is absent from pymysql's error_map, so raise_mysql_exception falls back
    to OperationalError for it. A guard that catches ProgrammingError - which is
    the obvious thing to copy from the helper three functions down - would
    compile, read correctly, pass review, and never once fire on half of what it
    names.
    """

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.server.index("def _realm_guarded")
        cls.guard = cls.server[start:cls.server.index("def _fetch_rows", start)]

    def test_the_guard_catches_the_base_class_and_not_programmingerror(self):
        self.assertIn("except pymysql.err.MySQLError", self.guard)
        self.assertNotIn("except pymysql.err.ProgrammingError", self.guard)

    def test_it_swallows_both_a_missing_table_and_a_missing_column(self):
        self.assertIn("(1054, 1146)", self.guard)

    def test_it_swallows_nothing_else(self):
        """Anything but those two is a real fault and must still reach the
        handler's 503. A banner that silently reported "not verified" for a
        network blip would train the alarm away."""
        self.assertIn("raise", self.guard)

    def test_every_one_of_the_three_reads_goes_through_it(self):
        """Including the two core tables, which nothing else on this page
        bothers to guard. That rule is right elsewhere and wrong here: this is
        the one banner whose whole job is to be trustworthy when something is
        already wrong."""
        fetch = self.server[self.server.index("def _fetch_realm"):]
        fetch = fetch[:fetch.index("def _fetch_rows")]
        self.assertEqual(fetch.count("_realm_guarded("), 3)
        for table in ("overseer_build", "acore_world.version",
                      "acore_auth.realmlist"):
            self.assertIn(table, self.server, table)

    def test_the_read_names_no_column_that_could_go_missing_on_an_older_realm(self):
        """overseer_build is name/value rows rather than a column per fact,
        precisely so a newer module adds rows and never columns. That is what
        leaves 1146 as the only way this read can fail on an old realm, and it
        only holds while the SELECT stays this narrow."""
        select = re.search(r'_BUILD_SQL = "([^"]+)"', self.server).group(1)
        self.assertEqual(
            select, "SELECT name, value, source, reported_at FROM overseer_build")


class TheTwoSidesAgreeOnTheStrings(unittest.TestCase):
    """The worldserver writes realm_kind and the site styles on it, so the two
    have to spell the three answers identically. A disagreement is silent and
    lands on the safe side of nothing: an unrecognised kind reads as UNKNOWN,
    so the failure is a permanently alarming banner on a realm that is fine,
    which is exactly the way to train the alarm away.

    WHEN THIS STARTS RUNNING. It reads the C++ through the mod-overseer
    submodule, which infra pins by SHA. The pin still names a commit from before
    the module gained this file, so these cases skip today and begin asserting
    the moment AC_OVERSEER_SHA and the submodule gitlink move - which has to
    happen before the banner can show anything but "not reported" anyway. This
    is a ratchet on a change that is already required, not a test waiting for
    somebody to remember it.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = (MODULE_SRC.read_text(encoding="utf-8")
                      if MODULE_SRC.exists() else "")
        cls.has_feature = "REALM_PRODUCTION" in cls.source

    def test_the_three_realm_kinds_are_spelled_the_same_on_both_sides(self):
        if not self.has_feature:
            self.skipTest("the pinned module predates the build report")
        import realm
        for constant, value in (("REALM_PRODUCTION", realm.PRODUCTION),
                                ("REALM_NON_PRODUCTION", realm.NON_PRODUCTION),
                                ("REALM_UNKNOWN", realm.UNKNOWN)):
            self.assertIn('%s[] = "%s"' % (constant, value), self.source,
                          constant)

    def test_the_pin_verdicts_are_spelled_the_same_on_both_sides(self):
        if not self.has_feature:
            self.skipTest("the pinned module predates the build report")
        import realm
        for constant, value in (("PINS_MATCH", realm.PINS_MATCH),
                                ("PINS_STALE", realm.PINS_STALE),
                                ("PINS_UNKNOWN", realm.PINS_UNKNOWN)):
            self.assertIn('%s[] = "%s"' % (constant, value), self.source,
                          constant)


if __name__ == "__main__":
    unittest.main()
