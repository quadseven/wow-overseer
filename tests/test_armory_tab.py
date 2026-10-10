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


HERE = pathlib.Path(__file__).resolve().parent.parent


class TheEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()
        cls.dockerfile = (HERE / "Dockerfile").read_text()

    def test_the_endpoint_is_reachable(self):
        self.assertIn('"/api/armory": _armory,', self.server)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """WHO the family is belongs to bonds. Accepting a roster would make
        this a general character query wearing a friendly name.

        THE TWO LINES PINNED HERE CHANGED SHAPE AND THE GUARD DID NOT. This
        used to assert the single expression
        `armory.build_armory(**_fetch_armory(), book=BOOK, items=ITEMS)`,
        which stopped being one line when the handler grew the provenance
        index: the fetch is now bound so its equip rows can be lifted off
        before the splat. What the guard is FOR is that the fetch takes
        nothing from the request and that the roster reaches the builder
        whole, and both halves are still asserted, splat included. The
        assertNotIn below is the load-bearing one and it is untouched."""
        handler = self.server[self.server.index("def _armory") :]
        handler = handler[: handler.index("def _thoughts")]
        # Both families now, and still from the roster: the names reach the
        # fetch from FAMILIES (families.py) and nowhere else.
        self.assertIn("groups = list(FAMILIES.families().items())", handler)
        self.assertIn("fetched = _fetch_armory(names)", handler)
        self.assertIn("armory.build_armory(**fetched, book=BOOK, items=ITEMS,", handler)
        self.assertIn("families=groups,", handler)
        self.assertNotIn("query.get", handler)

    def test_a_file_the_model_host_has_not_got_is_logged_and_not_only_answered(self):
        """The 502 was logged and the 404 was not, which left the failure
        that actually happens with no witness anywhere: the viewer drops the
        piece it could not fetch and draws the rest, so the only evidence was
        somebody looking at the picture. The reason is logged with it because
        the two 404s are different problems - a path THIS server refuses is a
        bug here, a file the model host has not got is not."""
        handler = self.server[self.server.index("def _modelviewer") :]
        handler = handler[: handler.index("def _index")]
        self.assertIn("elif r.status == 404:", handler)
        self.assertIn(
            'log.warning("model viewer: %s for %s", r.body.decode(), path)', handler
        )

    def test_a_dead_database_is_a_503_rather_than_a_hang(self):
        handler = self.server[self.server.index("def _armory") :]
        handler = handler[: handler.index("def _thoughts")]
        self.assertIn("self._send(503", handler)

    def test_the_talent_book_is_read_once_at_import_not_per_request(self):
        """It is 117KB of JSON and it never changes. Loading it inside the
        handler would parse it again on every poll, forever."""
        self.assertIn("BOOK = armory.TalentBook.load(HERE)", self.server)
        handler = self.server[self.server.index("def _armory") :]
        handler = handler[: handler.index("def _thoughts")]
        self.assertNotIn("TalentBook.load", handler)

    def test_the_gear_query_is_not_bounded_by_a_hand_typed_slot_count(self):
        """The SQL bound and the grid's rows must come from one list. Typing
        19 here would silently drop a slot the day panel's list grows one."""
        fetch = self.server[self.server.index("def _fetch_armory") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("len(armory.EQUIPPED_SLOTS)", fetch)

    def test_the_gear_query_reaches_the_world_database_for_item_names(self):
        """Item name, quality and level are in acore_world, not the characters
        database. Without the join every item renders as a bare entry id."""
        fetch = self.server[self.server.index("def _fetch_armory") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("LEFT JOIN acore_world.item_template", fetch)

    def test_the_talent_book_ships_in_the_image(self):
        """armory.TalentBook.load runs at IMPORT time, so an image without
        talents.json does not start at all - and that failure lands at pod
        start, long after CI has gone green."""
        self.assertIn("talents.json", self.dockerfile)
        for book in ("items", "icons", "spells", "viewerdisplays"):
            self.assertIn(f"{book}.json", self.dockerfile)
        self.assertIn("armory.py", self.dockerfile)

    def test_the_gear_query_carries_the_instance_not_just_the_template(self):
        """enchantments and randomPropertyId are what make a belt a 'Belt
        of the Tiger'. Without them half the family's stats do not exist."""
        fetch = self.server[self.server.index("def _fetch_armory") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("ii.enchantments", fetch)
        self.assertIn("ii.randomPropertyId AS random_property_id", fetch)

    def test_the_saved_stats_are_read_when_the_world_has_written_them(self):
        fetch = self.server[self.server.index("def _fetch_armory") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("JOIN character_stats s ON s.guid = c.guid", fetch)
        self.assertIn("acore_world.player_class_stats", fetch)
        self.assertIn("acore_world.player_race_stats", fetch)

    # test_the_dev_world_saves_stats_for_external_readers removed here: it
    # read quadseven/infra's production/oke/manifests/wow-dev/config/
    # worldserver.overrides.conf, which this repo does not carry. An
    # equivalent check should live in infra's own wow-dev render-test suite
    # instead - see the tracking issue for this split.


class TheTwoFamiliesAndTheGuilds(unittest.TestCase):
    """Both families side by side by party role, guilds collapsed and lazy (#88)."""

    @classmethod
    def setUpClass(cls):
        cls.server = (HERE / "map_server.py").read_text()

    def test_the_member_route_is_reachable(self):
        self.assertIn('"/api/armory/member": _armory_member,', self.server)

    def test_a_name_is_only_ever_matched_against_the_families(self):
        """The route takes a parameter; what makes it safe is that the
        parameter is compared against the families' own guildmates, and
        refused otherwise."""
        member = self.server[self.server.index("def _armory_member") :]
        member = member[: member.index("def _read_json_body")]
        self.assertIn("if not FAMILIES.may_answer(wanted):", member)
        self.assertIn("self._send(404", member)


if __name__ == "__main__":
    unittest.main()
