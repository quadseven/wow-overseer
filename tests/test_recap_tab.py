"""The recap's page contract and its endpoint, asserted against source.

Same seam as test_chronicle_tab.py and test_armory_tab.py: map_server.py
imports pymysql and index.html has no other test seam, so the page is read as
text and sliced to the block being asserted about.

TWO THINGS THIS FILE IS FOR. The first is the seam: every sentence a reader
sees must arrive written from recap.py, because a sentence composed in
JavaScript is a judgement no Python test can reach, which is the whole reason
the Chronicle was redesigned (infra#2597). The second is the guards: this
endpoint reads five overseer_* tables and four world tables, on two realms
running different worldserver builds, so a missing table or a missing column
must thin the view rather than blank it. Both failures have already taken a
tab down in production (infra#3172, infra#2846).

Tickets: infra#2597, infra#3172, mod-overseer#88.
"""

import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
SERVER_MODULE = (HERE / "recap.py").read_text(encoding="utf-8")

BANNER = "// --- the live recap and the loot board (infra#2597, mod-overseer#88)"
CSS_BANNER = "/* --- the recap and the loot board, inside the Chronicle (infra#2597)"
NEXT = "// --- the Council (infra#2597)"
NEXT_CSS = "/* --- the Council (infra#2597)"


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_chronicle_tab.py carries, and for the same reason: a
    guard that its own explanation can trip is a guard that gets weakened
    until it passes. Several assertions below name the sentence they forbid.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


class TheEndpoint(unittest.TestCase):
    def test_the_handler_takes_a_map_and_never_a_roster(self):
        """WHO the family is belongs to the roster, exactly as /api/armory
        and /api/family refuse a name. A map id is a fact about the world.
        One recap per family, every family from the roster (#198)."""
        handler = SERVER[SERVER.index("def _recap") :]
        handler = handler[: handler.index("def _council")]
        self.assertIn("for side in _faction_sides():", handler)
        self.assertNotIn('query.get("name"', handler)
        self.assertIn('query.get("map"', handler)

    def test_the_map_parameter_is_an_integer_or_it_is_dropped(self):
        handler = SERVER[SERVER.index("def _recap") :]
        handler = handler[: handler.index("def _council")]
        self.assertIn("isdigit()", handler)

    def test_every_overseer_read_is_guarded_for_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN, and only one of
        the two guards already in this file catches both. Production lacks
        tables dev has, so an unguarded read here is a 503 on the live realm
        for a feature it has nothing to do with."""
        fetch = SERVER[SERVER.index("def _fetch_recap") :]
        fetch = fetch[: fetch.index("# --- the current-goal banner")]
        for table in (
            "overseer_dungeon_run",
            "overseer_event",
            "overseer_death",
            "overseer_snapshot",
        ):
            self.assertIn('"%s"' % table, fetch, table)
        # Nothing in the fetch may call execute directly: the guard is the
        # only way rows come back, so a read added later cannot skip it.
        self.assertNotIn("cur.execute", fetch)

    def test_the_guard_catches_the_base_class_that_covers_both(self):
        """1054 is not a ProgrammingError. pymysql has no entry for it in
        error_map, so it falls back to OperationalError, and a guard that
        catches only ProgrammingError is half a guard."""
        guard = SERVER[SERVER.index("def _wide_guarded") :]
        guard = guard[: guard.index("def _fetch_recap")]
        self.assertIn("pymysql.err.MySQLError", guard)
        self.assertIn("(1054, 1146)", guard)

    def test_anything_that_is_not_those_two_still_raises(self):
        """A guard that swallowed a network blip would render an empty recap
        and train the alarm away."""
        guard = SERVER[SERVER.index("def _wide_guarded") :]
        guard = guard[: guard.index("def _fetch_recap")]
        self.assertIn("raise", guard)

    def test_the_run_read_falls_back_to_columns_that_always_existed(self):
        """outcome and members arrived on 2026-09-02. A world that predates
        them must still get its runs."""
        self.assertIn("_RECAP_RUNS_OLD", SERVER)
        self.assertNotIn(
            "outcome",
            SERVER[SERVER.index("_RECAP_RUNS_OLD") : SERVER.index("_RECAP_EQUIPS")],
        )

    def test_the_equip_read_is_not_narrowed_to_the_run(self):
        """The earliest equip of a pair is a fortnight old for gear worn for a
        fortnight. Narrowing this to the run window would reproduce exactly
        the bug the module exists to fix."""
        sql = SERVER[SERVER.index("_RECAP_EQUIPS = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertNotIn("first_seen >=", sql)
        self.assertNotIn("started_at", sql)

    def test_the_bosses_are_not_a_hand_written_list(self):
        """A hand list is what put a boss in the Chronicle that the core does
        not count. These come from the core's own encounter table."""
        self.assertIn("instance_encounters", SERVER)
        self.assertIn("creature_loot_template", SERVER)


class TheArmoryLinksBackToTheChronicle(unittest.TestCase):
    """ "Can you link on their armory where they got what gear?" What the
    record supports is where it was first seen WORN, and the line says that."""

    def test_the_equip_read_behind_it_is_guarded(self):
        """Gear and talents are core tables that are always there;
        overseer_event is not. A realm without it must still get a paper
        doll."""
        fetch = SERVER[SERVER.index("def _fetch_armory") :]
        fetch = fetch[: fetch.index("_QUESTLOG_SQL = (")]
        self.assertIn("_wide_guarded(", fetch)
        self.assertIn("equip_event_rows", fetch)


class TheModuleShipsInTheImage(unittest.TestCase):
    def test_recap_is_copied_into_the_container(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("recap.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
