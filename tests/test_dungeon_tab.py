"""The Dungeons view's page contract and its endpoint, asserted against source.

Same seam as test_recap_tab.py and test_council_view.py: map_server.py imports
pymysql and index.html has no other test seam, so both are read as text and
sliced to the block being asserted about.

THREE THINGS THIS FILE IS FOR.

The first is the seam. Every sentence a reader sees must arrive written from
dungeonplan.py, because a sentence composed in JavaScript is a judgement no
Python test can reach. That is the contract test_recap_tab.ThePageDecidesNothing
established and this view is held to it rather than exempted from it: it ranks
twenty dungeons, so it has MORE to say and more chances to say something the
data does not support.

The second is the guards. This endpoint reads four world tables on two realms
running different worldserver builds, so a missing table or a missing column
must thin the view rather than blank it. Both failures have already taken a tab
down in production (infra#3172, infra#2846).

The third is the cost. It is a cross product - every dungeon's boss loot
against five characters - and the shape that kills it is a query per dungeon on
an endpoint with no auth in front of it. The reads are asserted to be
whole-world and batched.

Tickets: infra#3500, infra#2597, mod-overseer#411.
"""

import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "dungeonplan.py").read_text(encoding="utf-8")

BANNER = "// --- where to go next (infra#3500)"
CSS_BANNER = "/* --- where to go next (infra#3500)"
NEXT = "// --- the Decree console (infra#2597)"
NEXT_CSS = "/* --- the Decree console (infra#2597)"


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_recap_tab.py carries, and for the same reason: a guard
    its own explanation can trip is a guard that gets weakened until it passes.
    Several assertions below name the sentence they forbid.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    """Every other view on this page is sliced from its own banner to the next
    one, so a block dropped in the wrong window is silently asserted about by
    somebody else's suite."""

    def test_the_fetch_sits_above_the_recaps_fetch_window(self):
        """test_recap_tab slices `def _fetch_recap` to the current-goal
        banner and forbids a bare cur.execute anywhere inside it."""
        self.assertLess(
            SERVER.index("def _fetch_dungeonplan"), SERVER.index("def _fetch_recap")
        )


class TheEndpoint(unittest.TestCase):
    def test_the_families_are_read_from_the_roster(self):
        """WHO the families are belongs to the roster, exactly as /api/armory
        and /api/family refuse a name."""
        fetch = SERVER[
            SERVER.index("def _fetch_dungeonplan") : SERVER.index(
                "# --- the live dungeon recap"
            )
        ]
        self.assertIn("_PLAN_FAMILIES", fetch)

    def test_an_empty_roster_binds_no_empty_in_list(self):
        """`IN ()` is a syntax error, so no family means no character read."""
        fetch = SERVER[
            SERVER.index("def _fetch_dungeonplan") : SERVER.index(
                "# --- the live dungeon recap"
            )
        ]
        self.assertIn("if names:", fetch)
        self.assertLess(fetch.index("if names:"), fetch.index("_LINEUP_GUILD.format"))

    def test_both_families_come_from_the_roster_and_not_from_bonds(self):
        """bonds knows one family. The roster's own `family` column knows the
        Alliance family and the Horde one, so that is what the path reads."""
        self.assertIn("SELECT name, family FROM overseer_roster", SERVER)


class TheReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # To the recap's own banner and not to `def _fetch_recap`: the recap's
        # SQL constants and the shared `_wide_guarded` sit between the two, and
        # a window that swept them in would be asserting about somebody else's
        # code.
        cls.fetch = SERVER[
            SERVER.index("def _fetch_dungeonplan") : SERVER.index(
                "# --- the live dungeon recap"
            )
        ]

    def test_the_bound_map_list_is_the_modules_union(self):
        """The page draws a row per access-table map AND per map this site
        names, so binding the access table's maps alone would leave a
        site-named dungeon rendering "no boss loot" over loot that was never
        asked for."""
        self.assertIn(
            "dungeonplan.map_ids(catalogue, achievements.MAP_NAMES)", self.fetch
        )

    def test_the_dungeon_list_is_the_worlds_own_table(self):
        """A hand list cannot follow the family into a dungeon nobody
        remembered to add to it."""
        self.assertIn("dungeon_access_template", SERVER)
        self.assertIn("_PLAN_CATALOGUE", self.fetch)

    def test_the_catalogue_falls_back_to_columns_that_always_existed(self):
        """`difficulty` is what picks one row per map. A world that predates
        it must still get its dungeons."""
        self.assertIn("_PLAN_CATALOGUE_OLD", SERVER)
        old = SERVER[SERVER.index("_PLAN_CATALOGUE_OLD") :]
        self.assertNotIn("difficulty", old[: old.index(")\n")])

    def test_every_world_read_is_guarded_for_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN, and production
        lacks tables dev has. An unguarded read here is a 503 on the live
        realm for a feature it has nothing to do with."""
        for table in (
            "dungeon_access_template",
            "instance_encounters",
            "creature_loot_template",
            "characters",
            "character_inventory",
            "character_skills",
            "overseer_roster",
            "guild_member",
            "overseer_dungeon_run",
        ):
            self.assertIn('"%s"' % table, self.fetch, table)
        # Nothing in the fetch may call execute directly: the guard is the
        # only way rows come back, so a read added later cannot skip it.
        self.assertNotIn("cur.execute", self.fetch)

    def test_the_loot_is_read_once_for_every_map_and_not_once_per_dungeon(self):
        """THE COST. A query per dungeon is forty round trips for twenty
        dungeons on an endpoint with no auth in front of it."""
        self.assertEqual(self.fetch.count("_PLAN_LOOT"), 1)
        self.assertEqual(self.fetch.count("_PLAN_ENCOUNTERS"), 1)
        self.assertIn("map IN ({holes})", SERVER)
        body = self.fetch[self.fetch.index("with conn.cursor()") :]
        self.assertNotIn("for map", body)

    def test_an_empty_catalogue_does_not_bind_an_empty_in_list(self):
        """`IN ()` is a syntax error rather than an empty result, so it would
        reach the handler's 503 on a world with no access table at all."""
        self.assertIn("if maps:", self.fetch)

    def test_the_spawn_test_stays_a_subquery(self):
        """Joined, a boss with two spawn rows would multiply every one of its
        loot rows by two and count the same sword twice."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertIn("(SELECT DISTINCT id FROM acore_world.creature", sql)

    def test_loot_behind_a_reference_is_not_joined_as_an_item(self):
        """A row with a Reference points at reference_loot_template rather
        than at an item, so joining it on `it.entry = clt.Item` surfaces
        something unrelated as a boss drop."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertIn("clt.Reference = 0", sql)

    def test_a_spell_credit_is_not_read_as_a_creature(self):
        """creditType 1 is a SPELL, and without the filter the join names an
        encounter after whatever creature shares the number."""
        sql = SERVER[SERVER.index("_PLAN_ENCOUNTERS = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertIn("ie.creditType = 0", sql)
        self.assertIn("SELECT DISTINCT", sql)

    def test_where_the_family_stand_comes_back_with_them(self):
        """`map` is on the characters row already, so this is one column and
        not a second read."""
        sql = SERVER[SERVER.index("_PLAN_CHARS = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertIn("map", sql)

    def test_the_loot_read_carries_what_a_tooltip_draws(self):
        """infra#3501 built the tooltip for items nobody holds, which is every
        item on this page. Selecting a narrower list here would leave the rows
        unable to say anything a reader could act on - and this page ranks by
        item level and refuses to weight stats, so the tooltip is how the
        reader does the weighting it will not do."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = (") :]
        sql = sql[: sql.index(")" + chr(10))]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", sql)

    def test_the_chance_columns_stay_out_of_the_widened_read(self):
        """_ITEM_TEMPLATE_COLUMNS is item_template only, so the reason Chance
        and GroupId were dropped survives the widening: this page does not ask
        how likely a drop is and must not be able to start."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = (") :]
        sql = sql[: sql.index(")" + chr(10))]
        self.assertNotIn("Chance", sql)
        self.assertNotIn("GroupId", sql)

    def test_the_worn_and_skill_reads_are_the_loot_boards_own(self):
        """What a character wears and what they may hold are one question with
        one answer on this site."""
        self.assertIn("_RECAP_WORN", self.fetch)
        self.assertIn("_RECAP_SKILLS", self.fetch)


class ItShipsInTheImage(unittest.TestCase):
    def test_the_module_is_copied_into_the_container(self):
        """A module the page imports and the image does not carry is a 503 on
        a tab that worked in CI."""
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("dungeonplan.py", dockerfile)


class TheVerdictIsBorrowedAndNotCopied(unittest.TestCase):
    def test_the_module_reads_the_loot_boards_verdict(self):
        """A second definition of "upgrade" is two answers to one question
        that are free to disagree about the same drop on the same evening."""
        self.assertIn("import recap", MODULE)
        self.assertIn("recap.verdict(", MODULE)

    def test_it_does_not_keep_a_second_armour_or_proficiency_table(self):
        """mod-overseer#411 lives in recap.py, read from the core's own
        subclass-to-skill map. A copy here would go stale silently."""
        for copied in (
            "WEAPON_SKILLS = {",
            "ARMOUR_SKILLS = {",
            "ARMOUR_GRADES = {",
            "WEARABLE_SLOTS = {",
        ):
            self.assertNotIn(copied, MODULE, copied)

    def test_it_does_not_compare_item_levels_itself(self):
        """The comparison is recap.verdict's, and a second one here would be
        the divergence this module exists to avoid."""
        self.assertNotIn("item_level", MODULE)


if __name__ == "__main__":
    unittest.main()
