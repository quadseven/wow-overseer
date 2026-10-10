"""The Family tab's page contract: the rules that cost something to learn.

Asserted against index.html as source, the same way test_stream.py guards the
player - map_server.py imports pymysql and the page has no other test seam.
These are deliberately not "does it render": they are the handful of rules
that were each paid for by a real failure, and that a refactor could quietly
undo while leaving five cards on screen looking perfectly fine.

Ticket: infra#2892.
"""

import unittest


class TheFamilyTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pathlib

        here = pathlib.Path(__file__).resolve().parent.parent
        cls.server = (here / "map_server.py").read_text()

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """A caller may choose a FAMILY. It may never supply a NAME.

        This used to forbid `query.get` outright, which was the simplest way
        to say "no roster from the request" while there was one family. There
        are two now - an Alliance five and a Horde five - so the tab has to be
        able to ask for one of them, and a flat ban on reading the query would
        have meant hard-coding a second roster in the page instead. That is
        the very thing test_the_roster_is_not_retyped_into_the_page forbids.

        So the invariant is enforced where it actually lives: whatever the
        caller sends is matched against the set of families the DATABASE
        reports, and the names handed to _fetch_family come from that lookup.
        A request cannot name a character, which is what this has always been
        about.
        """
        handler = self.server[self.server.index("def _family") :]
        handler = handler[: handler.index("def _thoughts")]
        # the roster reaching the query comes from the lookup, not the request
        self.assertIn("self._family_scope(query)", handler)
        # Every reader here is handed `names`, the list that lookup produced.
        # Matched as a call ARGUMENT rather than as one exact line, because
        # pinning the whole spelling makes this fail on any rewording of the
        # call - which it did, the first time the call gained an argument.
        for reader in ("_fetch_family(", "_fetch_profiles("):
            self.assertIn(
                reader + "names)",
                handler,
                reader + " must be given the looked-up roster",
            )
        self.assertIn("family.build_family(", handler)
        # nothing is taken from the request here: the family key is read by
        # _family_scope, below
        self.assertNotIn("query.get", handler)
        # and nothing from the request is passed to a reader
        self.assertNotIn("_fetch_family(query", handler)
        self.assertNotIn("build_family(query", handler)

        lookup = self.server[self.server.index("def _family_scope") :]
        lookup = lookup[: lookup.index("def _chat_post")]
        # the only thing taken from the request is the family key, and an
        # unrecognised key falls back rather than reaching SQL
        self.assertIn('which = query.get("family", [""])[0]', lookup)
        self.assertIn("which if which in rosters else FAMILIES.default()", lookup)
        self.assertNotIn('query.get("name', lookup)


if __name__ == "__main__":
    unittest.main()


class TheQuestBoard(unittest.TestCase):
    """infra#88: one shared quest board under all five feeds, in place of
    the five per-character lists infra#3110 put inside the cards.

    The judgements - who is on it, helping, done, leading; how the rows
    sort; where the fold is - all live in questlog.py, with their own suite.
    These are the page rules: the ones a refactor could undo while leaving a
    perfectly plausible list on screen."""

    @classmethod
    def setUpClass(cls):
        import pathlib

        here = pathlib.Path(__file__).resolve().parent.parent
        cls.server = (here / "map_server.py").read_text()
        # The block without its opening essay, for the assertions that are
        # about what the CODE says rather than what the comments explain.

    def test_the_server_reads_turn_ins_and_the_party_for_the_board(self):
        """DONE needs character_queststatus_rewarded per quest, and HELPING
        needs the snapshot's group_leader; a board built without either
        would draw every row as "on it" and nothing else."""
        fetch = self.server[self.server.index("def _fetch_questlog") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("character_queststatus_rewarded", fetch)
        self.assertIn("group_leader", fetch)
        self.assertIn('"done_rows": done_rows', fetch)
        self.assertIn('"party_rows": party_rows', fetch)

    def test_the_endpoint_takes_a_family_and_never_a_roster(self):
        """The rule /api/family follows: a caller may choose a FAMILY and may
        never supply a NAME. The board used to take no key at all, so the
        Horde tab was handed the Alliance board. The names reaching the reader
        are the ones _family_scope looked up, and the key is its only input."""
        handler = self.server[self.server.index("def _questlog") :]
        handler = handler[: handler.index("def _family_scope")]
        self.assertIn("self._family_scope(query)", handler)
        self.assertIn(
            "questlog.build_questlog(**_fetch_questlog(names), roster=names)", handler
        )
        self.assertNotIn("query.get", handler)
        scope = self.server[self.server.index("def _family_scope") :]
        scope = scope[: scope.index("def _chat_post")]
        self.assertIn('which = query.get("family", [""])[0]', scope)
        self.assertIn("rosters = FAMILIES.families()", scope)
        self.assertNotIn('query.get("name', scope)

    def test_the_endpoint_is_wired_into_the_route_table(self):
        """do_GET is a lookup and nothing else, so a handler that is never
        named in the table is a 404 with a docstring."""
        self.assertIn('"/api/questlog": _questlog,', self.server)

    def test_the_query_reads_the_statuses_the_module_named(self):
        """The status filter is the difference between a slot count that fits
        in 25 and one that does not (see questlog.IN_LOG). Spelling it into
        the SQL by hand is how it drifts from the module that explains it."""
        fetch = self.server[self.server.index("def _fetch_questlog") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("questlog.IN_LOG", fetch)
        self.assertIn("questlog.objective_entries", fetch)


class TheNeedsTheHandoversAndTheBonds(unittest.TestCase):
    """infra#2597 on the Family view. The card answered "is my family alive"
    and nothing under it, and alive has never been the interesting question:
    they have spent whole sessions alive, standing still, with full bags, gear
    at a quarter durability, and a stack of linen four of them keep trying to
    hand to the fifth whose bags are full. Every one of those facts already
    existed in a module and none of them was on a surface.

    THE RULES THAT COST SOMETHING. These are not "does it render" - they are
    the handful that a refactor could undo while leaving three perfectly
    plausible panels on screen. The load-bearing one is
    test_the_page_decides_nothing: the moment a threshold or a status word is
    spelled in this file, the page has an opinion about the family that can
    disagree with the module, and both will render."""

    @classmethod
    def setUpClass(cls):
        import pathlib

        here = pathlib.Path(__file__).resolve().parent.parent
        cls.server = (here / "map_server.py").read_text(encoding="utf-8")
        cls.dockerfile = (here / "Dockerfile").read_text(encoding="utf-8")

    # --- the page decides nothing -----------------------------------------

    # --- nothing near a card is ever rebuilt -------------------------------

    # --- what is on the page ----------------------------------------------

    # --- the poll ----------------------------------------------------------

    # --- the endpoint ------------------------------------------------------

    def test_the_endpoint_takes_a_family_and_never_a_roster(self):
        """Same rule as the quest board: the family key through _family_scope
        and nothing else. Without it the Horde tab drew the Alliance's bags."""
        handler = self.server[self.server.index("def _needs") :]
        handler = handler[: handler.index("def _agenda")]
        self.assertIn("self._family_scope(query)", handler)
        self.assertIn("needs.build_needs(**_fetch_needs(names), roster=names)", handler)
        self.assertNotIn("query.get", handler)
        self.assertIn("self._send(503", handler)

    def test_the_handler_sits_outside_every_other_suites_window(self):
        """The Armory suite reads `def _armory` to `def _thoughts` as its own
        contract; the Wealth handler is below _thoughts for exactly that
        reason and so is this one."""
        self.assertGreater(
            self.server.index("def _needs"), self.server.index("def _thoughts")
        )

    def test_the_fetch_sits_outside_the_wealth_suites_window(self):
        """That window is read as the Wealth view's SQL, and it asserts the
        inventory query is NOT bounded by slot. The durability read here IS
        bounded by slot, because a paper doll is exactly what it wants."""
        self.assertGreater(
            self.server.index("def _fetch_needs"),
            self.server.index("# Everything a tooltip draws"),
        )
        self.assertLess(
            self.server.index("def _fetch_needs"),
            self.server.index("def _ensure_stream_store"),
        )

    def test_the_window_is_the_modules_number_and_not_one_typed_into_sql(self):
        """A window is a decision about what counts as recent, and a 24 in a
        query nothing tests is a decision nobody can find."""
        fetch = self.server[self.server.index("def _fetch_needs") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        # BOTH reads, counted rather than merely present. Two queries take the
        # window and one of them going back to a literal would leave the other
        # holding the name - the assertion would pass and the two reads would
        # be looking at different amounts of history.
        self.assertEqual(fetch.count("needs.HISTORY_HOURS"), 2)
        self.assertIn("needs.HISTORY_MAX", fetch)

    def test_the_two_reads_that_can_be_missing_are_guarded(self):
        """A world whose image predates the give machinery has refused nothing.
        infra#3172 cost a whole tab on production because one read of a table
        the module creates was not guarded."""
        fetch = self.server[self.server.index("def _fetch_needs") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertEqual(fetch.count("1054, 1146"), 2)
        self.assertIn("give_rows = []", fetch)
        self.assertIn("thought_rows = []", fetch)

    def test_the_inventory_read_is_the_same_columns_the_bag_view_uses(self):
        """Two views counting the same bags off two column lists is two
        answers to how full a bag is, and one of them drifts."""
        fetch = self.server[self.server.index("def _fetch_needs") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("_WEALTH_ITEM_COLUMNS", fetch)

    def test_the_gear_read_is_bounded_by_the_module_and_not_by_a_typed_19(self):
        fetch = self.server[self.server.index("def _fetch_needs") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("len(armory.EQUIPPED_SLOTS)", fetch)
        self.assertIn("it.MaxDurability AS max_durability", fetch)

    def test_the_skills_are_sieved_in_python_and_not_in_sql(self):
        """character_skills also holds languages, Defence and every weapon
        skill. Which of them is a profession is needs.held_skills' decision,
        and an IN list of ids here would be that decision in SQL nothing
        tests."""
        fetch = self.server[self.server.index("def _fetch_needs") :]
        fetch = fetch[: fetch.index("def _ensure_stream_store")]
        self.assertIn("JOIN character_skills k ON k.guid = c.guid", fetch)
        self.assertNotIn("k.skill IN", fetch)

    def test_the_module_ships_in_the_image(self):
        """The build's shared-dir copy takes top-level files only and the
        Dockerfile names them explicitly, so a new module is one forgotten line
        away from a pod that crashes at start, long after CI went green."""
        self.assertIn("needs.py", self.dockerfile)
