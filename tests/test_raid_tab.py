"""The Raid view's page contract and its endpoint, asserted against source.

Same seam as test_dungeon_tab.py and test_recap_tab.py: map_server.py imports
pymysql and index.html has no other test seam, so both are read as text and
sliced to the block being asserted about.

THREE THINGS THIS FILE IS FOR.

The first is the seam. Every sentence a reader sees must arrive written from
raidgoals.py, because a sentence composed in JavaScript is a judgement no
Python test can reach. That is the contract test_recap_tab.ThePageDecidesNothing
established, and this view is held to it rather than exempted: it carries the
only numbers on this site the world database did not hand over, so a sentence
invented here would be a made-up requirement on a page people farm to.

The second is the guards. This endpoint reads eleven tables, two of which
nothing else in this service has ever read (`trainer_spell` and
`gameobject_loot_template`), on two realms running different worldserver
builds. A missing table or a missing column must thin the view rather than
blank it; both failures have already taken a tab down in production
(infra#3172, infra#2846).

The third is the cost. It is the widest read on the site after the dungeon
plan: every roster member's whole inventory plus three source tables. The
reads are asserted to be bound to the roster or to the module's own item list,
and never to be per goal or per reagent.

Tickets: infra#3508, infra#3500, infra#2597.
"""

import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent.parent
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "raidgoals.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE / "Dockerfile").read_text(encoding="utf-8")

BANNER = "// --- what the guild still needs before it can raid (infra#3508)"
CSS_BANNER = "/* --- what the guild still needs before it can raid (infra#3508)"
NEXT = "// --- the item tooltip, on every gear name (infra#3501)"
NEXT_CSS = "/* --- the item tooltip, on every gear name (infra#3501)"


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_recap_tab.py and test_dungeon_tab.py carry, and for
    the same reason: a guard that its own explanation can trip is a guard that
    gets weakened until it passes. Several assertions below name the sentence
    they forbid.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    """Every other view on this page is sliced from its own banner to the next
    one, so a block dropped in the wrong window is silently asserted about by
    somebody else's suite, and takes their assertions with it when it changes.
    """

    def test_the_fetch_sits_above_the_dungeon_plans_fetch_window(self):
        """test_dungeon_tab slices its fetch from its own function to the
        recap's banner and forbids an unguarded read inside it."""
        self.assertLess(
            SERVER.index("def _fetch_raidgoals"), SERVER.index("def _fetch_dungeonplan")
        )


class TheEndpoint(unittest.TestCase):
    def test_the_handler_takes_nothing_from_the_caller(self):
        """WHO the roster is belongs to bonds and to the world's own guild
        tables, exactly as /api/armory and /api/family refuse a name. This one
        asks a single question about a single raid, so there is nothing to
        steer either."""
        handler = SERVER[SERVER.index("def _raidgoals") : SERVER.index("def _loot")]
        self.assertIn("_fetch_raidgoals()", handler)
        self.assertNotIn("query.get", handler)

    def test_the_module_ships_in_the_image(self):
        """A module the page imports and the image does not carry is a crash
        at pod start, long after CI went green."""
        self.assertIn("raidgoals.py", DOCKERFILE)


class TheReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # To the dungeon plan's own banner and not to its function: that
        # section's SQL constants sit between the two, and a window that swept
        # them in would be asserting about somebody else's code.
        cls.fetch = SERVER[
            SERVER.index("def _fetch_raidgoals") : SERVER.index(
                "# --- which dungeon is worth running"
            )
        ]

    def test_every_read_goes_through_the_guard_that_catches_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN. Production lacks
        tables dev has, and two of these tables are read by nothing else in
        this service, so an unguarded read here is a 503 on the live realm."""
        self.assertNotIn("cur.execute", self.fetch)
        for table in (
            "guild_member",
            "item_template",
            "trainer_spell",
            "characters",
            "character_skills",
            "character_spell",
            "character_inventory",
            "npc_vendor",
            "creature_loot_template",
            "gameobject_loot_template",
        ):
            self.assertIn('"%s' % table, self.fetch, table)

    def test_the_bound_item_list_is_the_modules_own(self):
        """Deriving it here would let the reads fall behind the plan, and a
        reagent the reads did not bind renders as one this realm does not
        carry: a wrong sentence rather than a missing one."""
        self.assertIn("raidgoals.plan_item_names()", self.fetch)
        self.assertIn("raidgoals.craft_spells()", self.fetch)

    def test_the_reads_are_bound_to_the_roster_and_never_per_goal(self):
        """A query per reagent is twenty-seven times three round trips on an
        endpoint with no auth in front of it."""
        for sql in (
            "_RAID_ITEMS",
            "_RAID_VENDOR",
            "_RAID_CREATURE",
            "_RAID_OBJECT",
            "_RAID_HOLDINGS",
        ):
            self.assertEqual(self.fetch.count(sql + ".format"), 1, sql)
        self.assertNotIn("for recipe in", self.fetch)
        self.assertNotIn("for reagent in", self.fetch)

    def test_the_guild_widens_the_roster_that_every_other_read_binds(self):
        """A guild of forty counted against five characters' bags would report
        a guild that holds almost nothing."""
        self.assertIn("roster = sorted(", self.fetch)
        self.assertIn("_RAID_HOLDINGS.format(holes=rholes)", self.fetch)

    def test_no_entries_binds_nothing_rather_than_producing_in_nothing(self):
        """`IN ()` is a syntax error, not an empty result, so it would 503 the
        tab on a realm carrying none of these items."""
        self.assertIn("if entries:", self.fetch)

    def test_the_guild_read_is_narrowed_to_the_familys_own_guild(self):
        """The random population has guilds of its own, and counting those
        would be a raid group nobody is in."""
        sql = SERVER[SERVER.index("_RAID_GUILD = (") :]
        sql = sql[: sql.index(")\n")]
        self.assertIn("SELECT gm2.guildid FROM guild_member gm2", sql)

    def test_the_reserved_word_is_aliased_rather_than_selected_bare(self):
        """`rank` is reserved in MySQL 8, so `AS rank` is a syntax error and
        would have taken this tab down on a realm running a newer server than
        the one it was written on."""
        for name in ("_RAID_RECIPES = (", "_RAID_TRAINER = ("):
            sql = SERVER[SERVER.index(name) :]
            sql = sql[: sql.index(")\n")]
            self.assertIn("AS skill_rank", sql)
            self.assertNotIn("AS rank", sql)

    def test_the_holdings_read_is_the_bags_tabs_own_columns(self):
        """bank.members_from_rows reads exactly these keys, and a thinner read
        would be a second answer to "where is that stack", free to disagree
        with the Bags tab about the same stack on the same evening."""
        sql = SERVER[SERVER.index("_RAID_HOLDINGS = (") :]
        sql = sql[: sql.index(")\n")]
        for column in (
            "holder",
            "item_guid",
            "container_slots",
            "bonding",
            "item_class",
            "ci.bag",
            "ci.slot",
        ):
            self.assertIn(column, sql, column)

    def test_the_worn_read_carries_what_pre_raid_readiness_scores(self):
        """Seats and the gate score gearscore's stats on every worn item
        (#542), so the read carries the entry, the inventory type, the stat
        columns and fire resistance, and no item level average is computed."""
        self.assertIn("_RAID_WORN = raidgear.WORN_SQL", SERVER)
        import raidgear

        sql = raidgear.WORN_SQL
        for column in (
            "it.fire_res",
            "itemEntry AS entry",
            "stat_type1",
            "stat_value10",
        ):
            self.assertIn(column, sql, column)

    def test_the_loot_source_reads_ignore_reference_rows(self):
        """A loot row with a Reference holds a reference id in `Item`, not an
        item entry, so matching against one reports that a herb drops off a
        creature because an unrelated reference shares its number. The loot
        board and the dungeon plan both carry this filter."""
        for name in ("_RAID_CREATURE = (", "_RAID_OBJECT = ("):
            sql = SERVER[SERVER.index(name) :]
            self.assertIn("Reference = 0", sql[: sql.index(")\n")], name)

    def test_the_three_source_reads_are_distinct(self):
        """A vial sold by ninety vendors is ninety rows and one answer."""
        for name in ("_RAID_VENDOR = (", "_RAID_CREATURE = (", "_RAID_OBJECT = ("):
            sql = SERVER[SERVER.index(name) :]
            self.assertIn("SELECT DISTINCT", sql[: sql.index(")\n")])

    def test_the_module_never_goes_back_to_the_database(self):
        """The whole view is eleven reads on one connection, and a module that
        could query would make that untrue without anything failing."""
        for forbidden in ("pymysql", "_connect", "cursor", "execute"):
            self.assertNotIn(forbidden, MODULE, forbidden)


class BothGuildsGetAReadinessCard(unittest.TestCase):
    """The operator called the old tab pointless: one guild's shopping list and
    no verdict. It now opens on one readiness card per guild, both factions,
    each saying whether its first raid can happen and what stops it."""

    def test_the_guild_reads_are_bound_to_every_family_not_bonds_five(self):
        """family.roster() is bonds' one family, so a guild read bound to it
        can only ever find the Alliance guild. That is why the Horde guild
        was missing from the Raid tab."""
        body = SERVER[SERVER.index("def _fetch_raidgoals") :]
        body = body[: body.index("\ndef ")]
        self.assertNotIn("names = family.roster()", body)

    def test_the_new_reads_are_guarded(self):
        fetch = SERVER[
            SERVER.index("def _fetch_raidgoals") : SERVER.index(
                "# --- which dungeon is worth running"
            )
        ]
        self.assertIn('"character_queststatus_rewarded")', fetch)
        self.assertIn('"dungeon_access_template")', fetch)
        self.assertIn("raidready.ATTUNEMENT_QUESTS", fetch)
        self.assertIn("_RAID_WORN_OLD.format(holes=rholes)", fetch)

    def test_the_module_ships_in_the_image(self):
        self.assertIn("raidready.py", DOCKERFILE)


if __name__ == "__main__":
    unittest.main()
