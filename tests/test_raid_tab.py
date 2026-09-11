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
import re
import unittest

import raidgoals

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "raidgoals.py").read_text(encoding="utf-8")
DOCKERFILE = (HERE.parent.parent / "docker" / "wow-overseer"
              / "Dockerfile").read_text(encoding="utf-8")

BANNER = "// --- what the guild still needs before it can raid (infra#3508)"
CSS_BANNER = "/* --- what the guild still needs before it can raid (infra#3508)"
NEXT = "// --- the item tooltip, on every gear name (infra#3501)"
NEXT_CSS = "/* --- the item tooltip, on every gear name (infra#3501)"

BLOCK = PAGE[PAGE.index(BANNER):PAGE.index(NEXT, PAGE.index(BANNER))]
CSS = PAGE[PAGE.index(CSS_BANNER):PAGE.index(NEXT_CSS, PAGE.index(CSS_BANNER))]
SECTION = PAGE[PAGE.index('<section id="raid">'):]
SECTION = SECTION[:SECTION.index("</section>")]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_recap_tab.py and test_dungeon_tab.py carry, and for
    the same reason: a guard that its own explanation can trip is a guard that
    gets weakened until it passes. Several assertions below name the sentence
    they forbid.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


CODE = code(BLOCK)


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    """Every other view on this page is sliced from its own banner to the next
    one, so a block dropped in the wrong window is silently asserted about by
    somebody else's suite, and takes their assertions with it when it changes.
    """

    def test_the_script_sits_in_the_one_gap_no_suite_claims(self):
        """The routing slice ends at setInterval(pollFamily, and the item
        tooltip's, the dungeon plan's and the console's windows all begin at
        their own banners below this one."""
        start = PAGE.index(BANNER)
        self.assertGreater(start, PAGE.index("setInterval(pollFamily"))
        self.assertLess(start, PAGE.index(NEXT))

    def test_the_script_sits_above_the_armorys_window(self):
        """test_armory_tab slices from its banner to `</script>`, which is the
        end of the file, so anything below it is read as Armory code."""
        self.assertLess(PAGE.index(BANNER),
                        PAGE.index("// --- the Armory tab (infra#3096, infra#3139)"))

    def test_the_styles_sit_between_the_furniture_and_the_first_view(self):
        """The shared furniture has to stay above every view window or the
        first view to claim it takes the others hostage; the item tooltip's is
        the first window that starts at a banner."""
        self.assertLess(PAGE.index("/* --- the redesign furniture (infra#2597)"),
                        PAGE.index(CSS_BANNER))
        self.assertLess(PAGE.index(CSS_BANNER), PAGE.index(NEXT_CSS))

    def test_the_fetch_sits_above_the_dungeon_plans_fetch_window(self):
        """test_dungeon_tab slices its fetch from its own function to the
        recap's banner and forbids an unguarded read inside it."""
        self.assertLess(SERVER.index("def _fetch_raidgoals"),
                        SERVER.index("def _fetch_dungeonplan"))

    def test_the_handler_sits_outside_the_dungeon_plans_handler_window(self):
        """That window runs from `def _dungeons` to the recap's handler."""
        self.assertLess(SERVER.index("    def _raidgoals"),
                        SERVER.index("    def _dungeons"))

    def test_the_section_sits_before_the_council(self):
        self.assertLess(PAGE.index('<section id="raid">'),
                        PAGE.index('<section id="council">'))


class TheTabIsReachable(unittest.TestCase):
    def test_it_has_a_button_and_it_sits_next_to_the_dungeons(self):
        """The Dungeons tab says which five-man is worth the walk; this says
        what is still missing before the raid above them. Same subject, one
        rung up."""
        self.assertIn("rb.dataset.view = RAID_VIEW;", PAGE)
        self.assertLess(PAGE.index("tabs.appendChild(gb);"),
                        PAGE.index("tabs.appendChild(rb);"))
        self.assertLess(PAGE.index("tabs.appendChild(rb);"),
                        PAGE.index("tabs.appendChild(db);"))

    def test_the_view_is_in_the_routing_table(self):
        """A view missing from HASH_VIEWS falls through to the unrecognised
        branch and silently opens the Family tab, which is exactly the failure
        the routing TABLE replaced a ladder of ifs to prevent."""
        listed = PAGE[PAGE.index("const HASH_VIEWS = ["):]
        self.assertIn("RAID_VIEW", listed[:listed.index("]")])

    def test_show_view_shows_and_hides_the_section(self):
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("// Read once, at startup")]
        self.assertIn("const isRaid = v === RAID_VIEW;", show)
        self.assertIn('rgsection.style.display = isRaid ? "block" : "none";',
                      show)

    def test_it_fetches_on_the_way_in_rather_than_waiting_for_the_timer(self):
        """A minute of empty goal list under a heading is indistinguishable
        from a broken one."""
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("// Read once, at startup")]
        branch = show[show.index("  if (isRaid) {"):]
        self.assertIn("pollRaid();", branch[:branch.index("  }")])

    def test_it_stops_the_grid_and_closes_the_panel_like_every_read_view(self):
        """Both are map and Family things that would go on running behind a
        view that does not show them, keeping a second player alive off
        screen."""
        show = PAGE[PAGE.index("function showView"):]
        branch = show[show.index("  if (isRaid) {"):]
        branch = branch[:branch.index("  }")]
        self.assertIn("closePanel();", branch)
        self.assertIn("stopBroadcasts();", branch)

    def test_the_markup_exists_and_every_box_the_script_fills_is_in_it(self):
        for element in ('id="rghead"', 'id="rgroster"', 'id="rgraid"',
                        'id="rgstrip"', 'id="rgorder"', 'id="rglist"',
                        'id="rgothers"', 'id="rgotherlist"', 'id="rgbasis"'):
            self.assertIn(element, SECTION, element)

    def test_the_markup_holds_no_sentence_of_its_own(self):
        """Two section labels and the loading word, and nothing else: every
        other word on this tab arrives from the module."""
        text = re.sub(r"<[^>]+>", " ", SECTION)
        words = [w for w in text.split() if w not in
                 ("reaching", "the", "world...", "01", "02", "before",
                  "molten", "core", "rest", "of", "tier")]
        self.assertEqual(words, [], words)


class ThePageDecidesNothing(unittest.TestCase):
    """Every sentence arrives written. This is the contract the Chronicle
    redesign established and the reason raidgoals.py is a separate module. It
    matters more here than anywhere else on the site: this is the one view
    carrying numbers no table on this realm states, so a sentence composed in
    JavaScript would be a made-up requirement nothing can test."""

    def test_the_headline_is_printed_and_not_composed(self):
        self.assertIn("p.line", CODE)
        for invented in ('"Molten Core"', '" goals"', '" of "', '" ready"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_roster_and_raid_lines_are_the_modules(self):
        self.assertIn("p.roster_line", CODE)
        self.assertIn("p.raid_line", CODE)
        for invented in ('" members"', '" guild"', '"no guild"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_order_and_the_basis_are_both_rendered(self):
        """A list in an order is read as a finding whether or not anybody
        meant it to be, and this page's footer is the only thing separating a
        measurement from a convention."""
        self.assertIn("p.order", CODE)
        self.assertIn("p.basis", CODE)

    def test_the_basis_yields_to_the_modules_empty_note(self):
        """The basis describes how a list was built, so it must not stand over
        one that was not built at all."""
        self.assertIn("p.empty_note || p.basis", CODE)

    def test_every_goal_sentence_is_the_modules(self):
        self.assertIn("goal.line", CODE)
        self.assertIn("goal.need_line", CODE)
        self.assertIn("goal.recipes_line", CODE)
        for invented in ('" short"', '" needed"', '" held"', '"blocked"',
                         '"unreachable"', '" enough"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_status_is_never_worked_out_on_the_page(self):
        """Whether a goal is short, blocked or unreachable is the whole
        finding, and the module carries it as a chip with a tone on it."""
        self.assertNotIn("goal.status", CODE)
        self.assertNotIn("goal.short >", CODE)
        self.assertNotIn("goal.held <", CODE)

    def test_the_member_and_product_lines_are_printed_whole(self):
        """Not the name and the count joined here: that is a sentence about a
        character assembled where no Python test can read it."""
        self.assertIn("m.line", CODE)
        self.assertIn("p.line", CODE)
        self.assertNotIn("m.who +", CODE)
        self.assertNotIn("m.held +", CODE)

    def test_every_recipe_sentence_is_the_modules(self):
        self.assertIn("recipe.line", CODE)
        self.assertIn("recipe.who_line", CODE)
        self.assertIn("recipe.rank_line", CODE)
        for invented in ('"needs "', '"known by"', '" casts"'):
            self.assertNotIn(invented, CODE, invented)

    def test_a_blocker_and_an_unknown_are_both_printed_and_kept_apart(self):
        """A blocker is something the module knows stops the craft; an unknown
        is something it cannot answer. Painting the second like the first
        reports the page's own blind spot as the guild's problem."""
        self.assertIn("recipe.blocked", CODE)
        self.assertIn("recipe.unknown", CODE)
        self.assertIn('"rg-block"', CODE)
        self.assertIn('"rg-unknown"', CODE)

    def test_every_reagent_sentence_is_the_modules(self):
        self.assertIn("reagent.line", CODE)
        self.assertIn("reagent.source", CODE)
        self.assertIn("reagent.made_line", CODE)
        for invented in ('" short"', '"gathered"', '"vendor"', '" per cast"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_strip_prints_the_modules_label_and_value(self):
        self.assertIn("tile.value", CODE)
        self.assertIn("tile.label", CODE)
        self.assertNotIn("p.goals.length", CODE)

    def test_a_tone_is_a_class_and_never_a_colour(self):
        """`tone` is a ROLE NAME the module chose. The stylesheet decides what
        it looks like on each of the two grounds this page is drawn on."""
        self.assertIn('"chip" + (chip.tone ? " " + chip.tone : "")', CODE)
        self.assertNotIn("#", CODE.split("function rgChips")[1][:400])

    def test_an_empty_string_draws_nothing_rather_than_an_empty_line(self):
        """An empty string is a real answer from the module and means "there
        is nothing to say here"."""
        self.assertIn("if (text) parent.appendChild", CODE)


class TheEndpoint(unittest.TestCase):
    def test_it_is_routed_and_the_builder_is_pure(self):
        self.assertIn('"/api/raidgoals": _raidgoals,', SERVER)
        self.assertIn("raidgoals.build_raidgoals(", SERVER)
        self.assertIn('fetch(u("/api/raidgoals"),', BLOCK)

    def test_the_handler_takes_nothing_from_the_caller(self):
        """WHO the roster is belongs to bonds and to the world's own guild
        tables, exactly as /api/armory and /api/family refuse a name. This one
        asks a single question about a single raid, so there is nothing to
        steer either."""
        handler = SERVER[SERVER.index("def _raidgoals"):
                         SERVER.index("def _achievements")]
        self.assertIn("family.roster()", handler)
        self.assertNotIn("query.get", handler)

    def test_a_dead_database_is_a_503_that_keeps_what_is_drawn(self):
        handler = SERVER[SERVER.index("def _raidgoals"):
                         SERVER.index("def _achievements")]
        self.assertIn("self._send(503", handler)
        self.assertIn("may be stale", BLOCK)

    def test_the_module_ships_in_the_image(self):
        """A module the page imports and the image does not carry is a crash
        at pod start, long after CI went green."""
        self.assertIn("_shared/raidgoals.py", DOCKERFILE)


class TheReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # To the dungeon plan's own banner and not to its function: that
        # section's SQL constants sit between the two, and a window that swept
        # them in would be asserting about somebody else's code.
        cls.fetch = SERVER[SERVER.index("def _fetch_raidgoals"):
                           SERVER.index("# --- which dungeon is worth running")]

    def test_every_read_goes_through_the_guard_that_catches_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN. Production lacks
        tables dev has, and two of these tables are read by nothing else in
        this service, so an unguarded read here is a 503 on the live realm."""
        self.assertNotIn("cur.execute", self.fetch)
        for table in ("guild_member", "item_template", "trainer_spell",
                      "characters", "character_skills", "character_spell",
                      "character_inventory", "npc_vendor",
                      "creature_loot_template", "gameobject_loot_template"):
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
        for sql in ("_RAID_ITEMS", "_RAID_VENDOR", "_RAID_CREATURE",
                    "_RAID_OBJECT", "_RAID_HOLDINGS"):
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
        sql = SERVER[SERVER.index("_RAID_GUILD = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("SELECT gm2.guildid FROM guild_member gm2", sql)

    def test_the_reserved_word_is_aliased_rather_than_selected_bare(self):
        """`rank` is reserved in MySQL 8, so `AS rank` is a syntax error and
        would have taken this tab down on a realm running a newer server than
        the one it was written on."""
        for name in ("_RAID_RECIPES = (", "_RAID_TRAINER = ("):
            sql = SERVER[SERVER.index(name):]
            sql = sql[:sql.index(")\n")]
            self.assertIn("AS skill_rank", sql)
            self.assertNotIn("AS rank", sql)

    def test_the_holdings_read_is_the_bags_tabs_own_columns(self):
        """bank.members_from_rows reads exactly these keys, and a thinner read
        would be a second answer to "where is that stack", free to disagree
        with the Bags tab about the same stack on the same evening."""
        sql = SERVER[SERVER.index("_RAID_HOLDINGS = ("):]
        sql = sql[:sql.index(")\n")]
        for column in ("holder", "item_guid", "container_slots", "bonding",
                       "item_class", "ci.bag", "ci.slot"):
            self.assertIn(column, sql, column)

    def test_the_worn_read_selects_the_resistance_and_nothing_else(self):
        """Five more resistance columns would invite the five sentences this
        view has not earned: it asks about Molten Core, which is fire."""
        sql = SERVER[SERVER.index("_RAID_WORN = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("it.fire_res", sql)
        for other in ("frost_res", "nature_res", "shadow_res", "arcane_res"):
            self.assertNotIn(other, sql, other)

    def test_the_loot_source_reads_ignore_reference_rows(self):
        """A loot row with a Reference holds a reference id in `Item`, not an
        item entry, so matching against one reports that a herb drops off a
        creature because an unrelated reference shares its number. The loot
        board and the dungeon plan both carry this filter."""
        for name in ("_RAID_CREATURE = (", "_RAID_OBJECT = ("):
            sql = SERVER[SERVER.index(name):]
            self.assertIn("Reference = 0",
                          sql[:sql.index(")\n")], name)

    def test_the_three_source_reads_are_distinct(self):
        """A vial sold by ninety vendors is ninety rows and one answer."""
        for name in ("_RAID_VENDOR = (", "_RAID_CREATURE = (", "_RAID_OBJECT = ("):
            sql = SERVER[SERVER.index(name):]
            self.assertIn("SELECT DISTINCT", sql[:sql.index(")\n")])

    def test_the_module_never_goes_back_to_the_database(self):
        """The whole view is eleven reads on one connection, and a module that
        could query would make that untrue without anything failing."""
        for forbidden in ("pymysql", "_connect", "cursor", "execute"):
            self.assertNotIn(forbidden, MODULE, forbidden)


class TheMobileRules(unittest.TestCase):
    """The page is read on a phone. A goal, every way of finishing it and
    every line of every one is three levels of list, and drawn flat it is a
    wall nobody reads."""

    def test_nothing_in_the_block_sets_a_width_in_pixels(self):
        self.assertNotIn("width:", CSS.replace("max-width:72ch", ""))

    def test_the_long_names_break_rather_than_scrolling_the_page(self):
        self.assertIn("overflow-wrap:anywhere", CSS)

    def test_the_only_grid_column_cannot_overflow_its_track(self):
        """minmax(0, 1fr) and not 1fr: a grid track's default minimum is
        auto, which a long unbroken item name pushes wider than the screen."""
        self.assertIn("minmax(0, 1fr)", CSS)

    def test_the_chips_wrap(self):
        self.assertIn("flex-wrap:wrap", CSS)

    def test_it_declares_no_media_query_of_its_own(self):
        """The shell already has one and a second breakpoint in here is a
        second opinion about where a phone stops being a phone."""
        self.assertNotIn("@media", CSS)

    def test_a_goal_and_a_recipe_are_both_collapsed_by_default(self):
        """Six goals times three recipes times ten reagents is far more than a
        thumb can scan, so the row is a details and the recipe inside it is
        another."""
        self.assertIn('el("details", "chr-card rg-card")', CODE)
        self.assertIn('el("details", "rg-recipe")', CODE)

    def test_the_native_marker_is_hidden_in_safari_too(self):
        """Safari draws its own triangle from a pseudo-element `list-style`
        does not reach."""
        self.assertEqual(CSS.count("::-webkit-details-marker"), 2)

    def test_a_summary_keeps_a_visible_focus_ring(self):
        """It is the only control on this tab, and list-style:none on a
        summary is where a focus ring usually goes missing."""
        self.assertEqual(CSS.count(":focus-visible"), 2)

    def test_it_draws_no_item_quality_colour(self):
        """A quality colour is designed for the dark ground the Armory and the
        Bags tab override their tokens to keep; #1eff00 on a white card is
        about 1.3:1, which is the bug test_theme exists to stop. There are no
        icons for these items either: icons.json freezes them for displayids
        the client marks equippable, and a flask has no inventory type."""
        self.assertNotIn("quality", CODE)
        self.assertNotIn("chrItem", CODE)
        self.assertNotIn("icon", CODE)


class ThePollIsGuarded(unittest.TestCase):
    def test_one_pull_at_a_time_and_a_clock_on_it(self):
        """These are one guard and not two. Started from showView and from the
        interval, two can be in flight at once; and a server that accepts the
        connection and never answers leaves the promise pending for ever, so
        the flag would never be cleared and no later poll could replace the
        loading line."""
        self.assertIn("rgPulling", CODE)
        self.assertIn("AbortSignal.timeout(20000)", CODE)

    def test_the_flag_is_released_in_a_finally(self):
        """Cleared at the end of the try it would be skipped by the very
        failure that most needs the next poll to be allowed to run."""
        block = CODE[CODE.index("async function pollRaid"):]
        self.assertIn("finally", block[:block.index("\n}")])

    def test_it_polls_only_while_the_tab_is_open(self):
        """It is a wide read: every roster member's whole inventory plus three
        source tables."""
        self.assertIn("if (view === RAID_VIEW) pollRaid();", CODE)
        self.assertIn("60000);", CODE)

    def test_a_failed_poll_keeps_what_is_drawn(self):
        """A blanked list here reads as "there is nothing left to farm", which
        is the one claim this view must never make by accident."""
        block = CODE[CODE.index("async function pollRaid"):]
        self.assertNotIn("replaceChildren()", block[:block.index("\n}")])


class TheModuleAndThePageAgree(unittest.TestCase):
    """A key the page reads and the module does not write is an undefined on a
    phone, which renders as a blank line rather than as an error."""

    def test_every_payload_key_the_script_reads_is_one_the_module_writes(self):
        payload = raidgoals.build_raidgoals(
            item_rows=[], recipe_rows=[], trainer_rows=[], char_rows=[],
            skill_rows=[], spell_rows=[], holding_rows=[], worn_rows=[],
            vendor_rows=[], creature_rows=[], object_rows=[], guild_rows=[],
            roster=["Ugga"])
        for key in ("line", "roster_line", "raid_line", "strip", "order",
                    "goals", "others", "others_line", "basis", "empty_note"):
            self.assertIn("p." + key, CODE, key)
            self.assertIn(key, payload, key)

    def test_every_goal_key_the_script_reads_is_one_the_module_writes(self):
        payload = raidgoals.build_raidgoals(
            item_rows=[], recipe_rows=[], trainer_rows=[], char_rows=[],
            skill_rows=[], spell_rows=[], holding_rows=[], worn_rows=[],
            vendor_rows=[], creature_rows=[], object_rows=[], guild_rows=[],
            roster=["Ugga"])
        goal = payload["goals"][0]
        for key in ("name", "line", "chips", "need_line", "recipes_line",
                    "members", "products", "recipes"):
            self.assertIn("goal." + key, CODE, key)
            self.assertIn(key, goal, key)


if __name__ == "__main__":
    unittest.main()
