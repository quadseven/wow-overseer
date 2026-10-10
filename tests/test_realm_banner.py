"""The realm banner's page and wiring contract (quadseven/mod-overseer#184).

Asserted against index.html and map_server.py as source, the way
test_agenda_banner.py, test_family_tab.py, test_armory_tab.py and
test_chronicle_tab.py do: map_server.py imports pymysql and the page has no
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
ACH_CSS = "/* --- the redesign furniture (infra#2597)"
FAMILY_CSS = "--- the Family tab (infra#2892)"

# The C++ module that writes the table this banner reads, through the submodule
# infra pins it at.
MODULE_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "mod-overseer/src/overseer_decisions.h"
)


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_handler_sits_outside_every_window_in_map_server(self):
        """The Family and Armory suites slice to `def _thoughts`, the
        current-goal banner's from `def _agenda` to `def do_POST`. This handler
        is above all of them, which is also where it belongs: it answers which
        world, and the rest only mean something inside that answer."""
        realm_at = self.server.index("    def _realm(")
        for later in (
            "def _map",
            "def _family",
            "def _armory",
            "def _thoughts",
            "def _agenda",
            "def do_POST",
        ):
            self.assertLess(realm_at, self.server.index(later), later)

    def test_the_fetch_sits_above_every_fetch_window(self):
        """The earliest fetch window any suite slices starts at
        `def _fetch_armory`; the modelviewer's ends at `MODELS = `, which is
        above _connect."""
        fetch_at = self.server.index("def _fetch_realm")
        self.assertGreater(fetch_at, self.server.index("def _connect"))
        for later in (
            "def _fetch_rows",
            "def _fetch_armory",
            "def _fetch_achievements",
            "def _fetch_agenda",
            "def _guarded",
        ):
            self.assertLess(fetch_at, self.server.index(later), later)


class TheEndpointIsWiredUp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_route_exists(self):
        self.assertIn('"/api/realm": _realm,', self.server)

    def test_the_builder_is_pure_and_takes_nothing_from_the_caller(self):
        handler = self.server[self.server.index("    def _realm(") :]
        handler = handler[: handler.index("def _healthz")]
        self.assertIn("realm.build_realm(**_fetch_realm())", handler)
        self.assertNotIn("query.get", handler)

    def test_a_failed_query_is_a_503_and_not_a_wrong_banner(self):
        handler = self.server[self.server.index("    def _realm(") :]
        handler = handler[: handler.index("def _healthz")]
        self.assertIn("503", handler)

    def test_the_pure_module_imports_no_database(self):
        source = (HERE / "realm.py").read_text(encoding="utf-8")
        self.assertNotIn("pymysql", source)
        self.assertNotIn("import os", source)

    def test_the_module_ships_in_the_image(self):
        """The build's shared-dir copy names every file explicitly, so a new
        module is one forgotten line away from a pod that crashes on import."""
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("realm.py", dockerfile)


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
        cls.guard = cls.server[start : cls.server.index("def _fetch_rows", start)]

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
        fetch = self.server[self.server.index("def _fetch_realm") :]
        fetch = fetch[: fetch.index("def _fetch_rows")]
        self.assertEqual(fetch.count("_realm_guarded("), 3)
        for table in ("overseer_build", "acore_world.version", "acore_auth.realmlist"):
            self.assertIn(table, self.server, table)

    def test_the_read_names_no_column_that_could_go_missing_on_an_older_realm(self):
        """overseer_build is name/value rows rather than a column per fact,
        precisely so a newer module adds rows and never columns. That is what
        leaves 1146 as the only way this read can fail on an old realm, and it
        only holds while the SELECT stays this narrow."""
        select = re.search(r'_BUILD_SQL = "([^"]+)"', self.server).group(1)
        self.assertEqual(
            select, "SELECT name, value, source, reported_at FROM overseer_build"
        )


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
        cls.source = (
            MODULE_SRC.read_text(encoding="utf-8") if MODULE_SRC.exists() else ""
        )
        cls.has_feature = "REALM_PRODUCTION" in cls.source

    def test_the_three_realm_kinds_are_spelled_the_same_on_both_sides(self):
        if not self.has_feature:
            self.skipTest("the pinned module predates the build report")
        import realm

        for constant, value in (
            ("REALM_PRODUCTION", realm.PRODUCTION),
            ("REALM_NON_PRODUCTION", realm.NON_PRODUCTION),
            ("REALM_UNKNOWN", realm.UNKNOWN),
        ):
            declaration = r'%s\[\]\s*=\s*"%s"' % (re.escape(constant), re.escape(value))
            self.assertRegex(self.source, declaration, constant)

    def test_the_pin_verdicts_are_spelled_the_same_on_both_sides(self):
        if not self.has_feature:
            self.skipTest("the pinned module predates the build report")
        import realm

        for constant, value in (
            ("PINS_MATCH", realm.PINS_MATCH),
            ("PINS_STALE", realm.PINS_STALE),
            ("PINS_UNKNOWN", realm.PINS_UNKNOWN),
        ):
            declaration = r'%s\[\]\s*=\s*"%s"' % (re.escape(constant), re.escape(value))
            self.assertRegex(self.source, declaration, constant)


if __name__ == "__main__":
    unittest.main()
