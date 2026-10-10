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
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")

    def test_the_handler_sits_below_the_armorys_slice(self):
        """The Armory endpoint suite reads everything between `def _armory`
        and `def _thoughts` as the Armory's own contract, including its
        assertion that no handler in that window reads a query parameter."""
        self.assertGreater(
            self.server.index("def _wealth"), self.server.index("def _thoughts")
        )

    def test_the_fetch_sits_above_the_armorys_slice(self):
        """Same reasoning at the other end: `def _fetch_armory` to
        `def _ensure_stream_store` is the Armory's fetch window."""
        self.assertLess(
            self.server.index("def _fetch_wealth"),
            self.server.index("def _fetch_armory"),
        )


class TheContractWithTheBuilder(unittest.TestCase):
    """The page and the module have to agree about the words in the payload.

    A source-reading suite cannot execute the page, so this does the next best
    thing: it builds a real payload and asserts that every key the page reads
    off it exists. A renamed key is otherwise a silent undefined on a tab
    nobody has open."""

    @classmethod
    def setUpClass(cls):
        cls.built = payload()

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
            [],
            {},
        )
        for key in (
            "who",
            "room",
            "holding",
            "elsewhere_note",
            "notable_note",
            "containers",
            "class_colour",
            "money",
            "held",
        ):
            self.assertIn(key, present, key)
        for key in (
            "percent",
            "tone",
            "used_label",
            "free_label",
            "free_tone",
            "bags_label",
            "spare_label",
            "spare_tone",
        ):
            self.assertIn(key, present["room"], key)

    def test_the_guild_bank_keys_the_page_reads_all_exist(self):
        bank = self.built["guild_bank"]
        for key in ("lead", "body", "steps", "blocked"):
            self.assertIn(key, bank, key)
        for key in ("step", "state_label", "tone"):
            self.assertIn(key, bank["steps"][0], key)

    def test_the_linked_sentence_has_both_halves_and_a_ticket(self):
        for sentence in (
            self.built["guild_bank"]["blocked"],
            self.built["auctions"]["empty"]["why"],
        ):
            for key in ("before", "ticket", "after"):
                self.assertIn(key, sentence, key)


class ItReadsOnAPhone(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in (
            "wealth.py",
            "map_server.py",
            "tests/test_wealth.py",
            "tests/test_wealth_tab.py",
        ):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )


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
            cls.server.index("# --- the Wealth and Bags view") : cls.server.index(
                "# Everything a tooltip draws"
            )
        ]
        cls.sql = cls.fetch[cls.fetch.index("names = family.roster()") :]
        cls.handler = cls.server[
            cls.server.index("def _wealth") : cls.server.index("def do_POST")
        ]

    def test_the_endpoint_is_reachable(self):
        self.assertIn('"/api/wealth": _wealth,', self.server)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """WHO the family is belongs to bonds. Accepting a roster would make
        this a general character query wearing a friendly name."""
        # Both families now (#88), and still from the roster alone.
        self.assertIn("groups = _fetch_family_groups()", self.handler)
        self.assertIn(
            "wealth.build_wealth(**_fetch_wealth(names), icons=ITEMS.icons,",
            self.handler,
        )
        self.assertIn("families=groups)", self.handler)
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
