"""The Trades view's page contract and its endpoint, asserted against source.

Same seam as test_dungeon_tab.py and test_recap_tab.py: map_server.py imports
pymysql and index.html has no other test seam, so both are read as text and
sliced to the block being asserted about.

FOUR THINGS THIS FILE IS FOR.

The first is the seam. Every sentence a reader sees must arrive written from
guildcraft.py, because a sentence composed in JavaScript is a judgement no
Python test can reach. That is the contract test_recap_tab.ThePageDecidesNothing
established and this view is held to it rather than exempted from it: it says
what a guild cannot do, which is the kind of sentence somebody acts on.

The second is the guards. This endpoint reads nine world and overseer tables on
two realms running different worldserver builds, so a missing table or a
missing column must thin the view rather than blank it. Both failures have
already taken a tab down in production (infra#3172, infra#2846).

The third is the cost. It is a cross product of characters against trades
against recipes, and the shape that kills it is a query per recipe on an
endpoint with no auth in front of it. The reads are asserted to be whole-set
and batched, and the roster the two per-character reads bind is asserted to be
the MODULE's answer rather than one this file works out for itself.

The fourth is where each block is allowed to sit. Every other view on this page
is sliced from its own banner to the next one, so a block dropped in the wrong
window is silently asserted about by somebody else's suite.

Tickets: infra#3507, infra#3500, infra#2597.
"""

import pathlib
import re
import unittest

import guildcraft

HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "guildcraft.py").read_text(encoding="utf-8")

BANNER = "// --- what the guild can make (infra#3507)"
CSS_BANNER = "/* --- what the guild can make (infra#3507)"
NEXT = "// --- where to go next (infra#3500)"
NEXT_CSS = "/* --- where to go next (infra#3500)"


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_dungeon_tab.py carries, and for the same reason: a
    guard its own explanation can trip is a guard that gets weakened until it
    passes. Several assertions below name the sentence they forbid.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


FETCH = SERVER[
    SERVER.index("_TRADE_SKILL_LIST = ") : SERVER.index(
        "# --- which dungeon is worth running next"
    )
]
HANDLER = SERVER[SERVER.index("def _trades") : SERVER.index("def _run_timeline")]


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    def test_the_fetch_sits_above_both_fetch_windows_that_forbid_a_bare_read(self):
        """test_dungeon_tab slices `def _fetch_dungeonplan` onward and
        test_recap_tab slices `def _fetch_recap` onward, and both forbid a bare
        cur.execute anywhere inside. A section dropped in either would be
        asserted about by a suite that knows nothing of it."""
        self.assertLess(
            SERVER.index("def _fetch_guildcraft"),
            SERVER.index("def _fetch_dungeonplan"),
        )
        self.assertLess(
            SERVER.index("def _fetch_guildcraft"), SERVER.index("def _fetch_recap")
        )

    def test_the_handler_sits_in_the_gap_between_two_claimed_windows(self):
        """The Armory, Family and Wealth handler windows all END at
        `def _thoughts`; this one ends at `def _run_timeline`."""
        self.assertGreater(SERVER.index("def _trades"), SERVER.index("def _thoughts"))
        self.assertLess(SERVER.index("def _trades"), SERVER.index("def _run_timeline"))


class TheEndpoint(unittest.TestCase):
    def test_the_handler_takes_nothing_from_the_caller(self):
        """WHO the guild is belongs to the roster and to the world's own
        guild table, exactly as /api/armory and /api/family refuse a name.
        One guild per family, every family from the roster (#198)."""
        self.assertIn("sides = _faction_sides()", HANDLER)
        self.assertNotIn("query.get", HANDLER)

    def test_a_dead_database_is_a_503_that_keeps_what_is_drawn(self):
        self.assertIn("self._send(503", HANDLER)

    def test_the_tooltip_book_and_the_icons_are_handed_over(self):
        """This page ranks nothing on stats, so the tooltip is how a reader
        weighs a recipe's product for themselves."""
        self.assertIn("book=ITEMS", HANDLER)
        self.assertIn("icons=ITEMS.icons", HANDLER)

    def test_the_geometry_is_handed_over_so_a_vendor_can_be_placed(self):
        self.assertIn("geo=GEO", HANDLER)


class TheReads(unittest.TestCase):
    def test_every_world_read_is_guarded_for_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN, and production
        lacks tables dev has. An unguarded read here is a 503 on the live realm
        for a feature it has nothing to do with."""
        for table in (
            "guild_member",
            "characters",
            "character_skills",
            "character_spell",
            "overseer_roster",
            "item_template",
            "trainer_spell",
            "npc_vendor",
            "creature_loot_template",
            "quest_template",
        ):
            self.assertIn('"%s"' % table, FETCH, table)
        # Nothing in the fetch may call execute directly: the guard is the
        # only way rows come back, so a read added later cannot skip it.
        self.assertNotIn("cur.execute", FETCH)

    def test_the_roster_the_two_per_character_reads_bind_is_the_modules(self):
        """A name the page draws a row for but never read spells for renders
        as "knows nothing", which is a claim rather than a gap."""
        self.assertIn("guildcraft.covered_names(names, guild)", FETCH)
        body = FETCH[FETCH.index("with conn.cursor()") :]
        self.assertIn("_TRADE_SPELLS.format(holes=choles)", body)
        self.assertIn("_TRADE_SKILLS.format(holes=choles)", body)

    def test_nothing_is_read_once_per_trade_or_once_per_recipe(self):
        """THE COST. A query per recipe is thousands of round trips on an
        endpoint with no auth in front of it."""
        body = FETCH[FETCH.index("with conn.cursor()") :]
        for once in (
            "_TRADE_RECIPES",
            "_TRADE_VENDORS",
            "_TRADE_DROPS",
            "_TRADE_QUESTS",
            "_TRADE_TRAINER",
        ):
            self.assertEqual(body.count(once), 1, once)
        self.assertNotIn("for skill", body)
        self.assertNotIn("for recipe", body)

    def test_the_source_reads_filter_by_subquery_and_not_by_a_bound_id_list(self):
        """Binding the recipe entries would mean reading them once to build
        the list and once more to use it, which is the same rows twice."""
        for sql in ("_TRADE_VENDORS", "_TRADE_DROPS"):
            block = SERVER[SERVER.index("%s = (" % sql) :]
            block = block[: block.index(")\n")]
            self.assertIn("_TRADE_RECIPE_ITEMS", block, sql)

    def test_the_drop_read_declines_to_follow_reference_loot(self):
        """The same filter the loot board and the dungeon plan both carry, and
        the page's own basis says what it costs."""
        block = SERVER[SERVER.index("_TRADE_DROPS = (") :]
        block = block[: block.index(")\n")]
        self.assertIn("clt.Reference = 0", block)

    def test_one_spawn_per_creature_and_the_basis_says_so(self):
        """Joined plainly, a vendor with twelve spawn rows is twelve copies of
        the same sentence."""
        for sql in ("_TRADE_VENDORS", "_TRADE_DROPS"):
            block = SERVER[SERVER.index("%s = (" % sql) :]
            block = block[: block.index(")\n")]
            self.assertIn("SELECT MIN(guid) FROM acore_world.creature", block)
        self.assertIn("ONE of its spawn rows", MODULE)

    def test_the_quest_read_covers_every_reward_column(self):
        """Four fixed rewards and six choices. A recipe handed over as the
        fourth choice is not a recipe with no source."""
        block = SERVER[SERVER.index("_TRADE_QUEST_COLUMNS = (") :]
        block = block[: block.index(")\n")]
        for column in ("RewardItem4", "RewardChoiceItemID6"):
            self.assertIn(column, block, column)
        self.assertEqual(len(re.findall(r'"Reward', block)), 10)

    def test_the_recipe_read_only_takes_rows_that_teach_something(self):
        """The taught craft spell is the only bridge back to character_spell
        this database has, so a recipe row without one can never be matched
        against what anybody knows."""
        block = SERVER[SERVER.index("_TRADE_RECIPES = (") :]
        block = block[: block.index(")\n")]
        self.assertIn("it.spellid_2 > 0", block)
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", block)

    def test_the_skill_read_takes_the_ceiling_and_not_only_the_value(self):
        """1 of 75 and 1 of 300 are different characters, and the ceiling is
        also what bounds which missing recipes get listed."""
        block = SERVER[SERVER.index("_TRADE_SKILLS = (") :]
        block = block[: block.index(")\n")]
        self.assertIn("cs.`max`", block)

    def test_the_bound_skill_ids_are_the_modules_and_are_not_user_input(self):
        """The list is ints from goals.SKILL_IDS, and /api/trades takes no
        parameters at all, so nothing a caller can reach touches it."""
        self.assertIn("guildcraft.recipe_skills()", FETCH)
        self.assertEqual(sorted(guildcraft.recipe_skills()), guildcraft.recipe_skills())

    def test_a_missing_roster_column_is_reported_and_not_swallowed(self):
        """An empty list is either "nobody is assigned anything" or "the
        column is not in this world yet", and those are different admissions."""
        self.assertIn('"roster_read": bool(roster_rows)', FETCH)
        self.assertIn("roster_read", MODULE)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in (
            "map_server.py",
            "guildcraft.py",
            "tests/test_trades_tab.py",
        ):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )

    def test_the_module_ships_in_the_image(self):
        """A module the page imports and the image does not carry is a 503 on
        a tab that was green in CI."""
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("guildcraft.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
