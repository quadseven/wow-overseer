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
import re
import unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "dungeonplan.py").read_text(encoding="utf-8")

BANNER = "// --- where to go next (infra#3500)"
CSS_BANNER = "/* --- where to go next (infra#3500)"
NEXT = "// --- the Decree console (infra#2597)"
NEXT_CSS = "/* --- the Decree console (infra#2597)"

BLOCK = PAGE[PAGE.index(BANNER):PAGE.index(NEXT, PAGE.index(BANNER))]
CSS = PAGE[PAGE.index(CSS_BANNER):PAGE.index(NEXT_CSS, PAGE.index(CSS_BANNER))]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_recap_tab.py carries, and for the same reason: a guard
    its own explanation can trip is a guard that gets weakened until it passes.
    Several assertions below name the sentence they forbid.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


CODE = code(BLOCK)
SECTION = PAGE[PAGE.index('<section id="dungeons">'):]
SECTION = SECTION[:SECTION.index("</section>")]


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    """Every other view on this page is sliced from its own banner to the next
    one, so a block dropped in the wrong window is silently asserted about by
    somebody else's suite."""

    def test_the_script_sits_in_the_one_gap_no_suite_claims(self):
        """The Family, Armory and Chronicle windows all end at
        loadZones().then(, and the Decree console's begins at its own banner."""
        start = PAGE.index(BANNER)
        self.assertGreater(start, PAGE.index("loadZones().then("))
        self.assertLess(start, PAGE.index(NEXT))

    def test_the_script_sits_below_the_routing_slice(self):
        """test_decree_tab and test_recap_tab both slice showView to
        setInterval(pollFamily. Code inside that window is read as routing."""
        self.assertGreater(PAGE.index(BANNER),
                           PAGE.index("setInterval(pollFamily"))

    def test_the_styles_sit_between_the_furniture_and_the_first_view(self):
        """The shared furniture has to stay above every view window or the
        first view to claim it takes the other four hostage; the Decree
        console's window is the first that starts at a banner."""
        self.assertLess(PAGE.index("/* --- the redesign furniture (infra#2597)"),
                        PAGE.index(CSS_BANNER))
        self.assertLess(PAGE.index(CSS_BANNER), PAGE.index(NEXT_CSS))

    def test_the_styles_sit_below_the_current_goal_banners_window(self):
        """That window runs from its own banner to the `nav` rule and sweeps in
        anything between."""
        self.assertGreater(PAGE.index(CSS_BANNER),
                           PAGE.index("  nav { display:flex"))

    def test_the_styles_sit_above_every_other_views_window(self):
        for banner in ("/* --- the Chronicle (infra#2597, mod-overseer#88,"
                       " mod-overseer#152)",
                       "/* --- the Council (infra#2597)",
                       "/* --- the Eye (infra#2597)",
                       "--- the Armory tab (infra#3096",
                       "--- the Family tab (infra#2892)"):
            self.assertLess(PAGE.index(CSS_BANNER), PAGE.index(banner), banner)

    def test_the_handler_sits_above_the_recaps_own_window(self):
        """That window runs from `def _recap` to `def _council`."""
        self.assertLess(SERVER.index("def _dungeons"), SERVER.index("def _recap"))

    def test_the_fetch_sits_above_the_recaps_fetch_window(self):
        """test_recap_tab slices `def _fetch_recap` to the current-goal
        banner and forbids a bare cur.execute anywhere inside it."""
        self.assertLess(SERVER.index("def _fetch_dungeonplan"),
                        SERVER.index("def _fetch_recap"))


class TheMarkup(unittest.TestCase):
    def test_the_section_exists_beside_the_other_views(self):
        for element in ('id="dgnhead"', 'id="dgnrunnable"', 'id="dgnorder"',
                        'id="dgnfamilies"', 'id="dgnbasis"'):
            self.assertIn(element, SECTION, element)

    def test_what_the_overseer_can_run_is_above_the_paths(self):
        """The operator's first question of every step is whether the overseer
        can run it at all, so the list of portals is read before the paths."""
        self.assertLess(SECTION.index('id="dgnrunnable"'),
                        SECTION.index('id="dgnfamilies"'))

    def test_the_rule_the_path_follows_is_above_it_and_not_below_it(self):
        """A list in an order is read as a finding. The rule that produced the
        order has to be readable before the list, not after twenty rows."""
        self.assertLess(SECTION.index('id="dgnorder"'),
                        SECTION.index('id="dgnfamilies"'))

    def test_the_basis_is_on_the_page_at_all(self):
        """The loot board's footer is the precedent: a list that does not say
        what it left out is one a reader will over-trust."""
        self.assertIn('id="dgnbasis"', SECTION)

    def test_the_markup_holds_no_sentence_of_its_own(self):
        """One furniture label and nothing else. Every other word arrives in
        the payload."""
        text = re.sub(r"<[^>]+>", " ", SECTION)
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        words = " ".join(text.split())
        self.assertIn("the path, family by family", words)
        for invented in ("upgrade", "worth", "should", "recommend", "item level"):
            self.assertNotIn(invented, words, invented)


class ThePageDecidesNothing(unittest.TestCase):
    """Every sentence arrives written. The same contract the Chronicle
    redesign established, and the reason dungeonplan.py is its own module."""

    def test_the_headline_and_the_family_lines_are_the_modules(self):
        self.assertIn("p.line", CODE)
        for key in ("f.title", "f.who_line", "f.next_line",
                    "f.family_upgrades", "f.guild_upgrades"):
            self.assertIn(key, CODE, key)
        for invented in ('" dungeons"', '" of them"', '"Next: "',
                         '"\'s family"', '"Alliance"', '"Horde"'):
            self.assertNotIn(invented, CODE, invented)

    def test_every_family_is_drawn_and_none_is_named_here(self):
        """Both factions: the page draws whatever families the payload
        carries, so the Horde family is not a second page somebody has to
        find, and no family name is written into the page."""
        self.assertIn("for (const f of p.families)", CODE)
        for name in ('"Grug"', '"Zug"', '"Cave"', '"Bonkers"'):
            self.assertNotIn(name, CODE, name)

    def test_the_rule_and_the_basis_are_printed_and_not_written(self):
        self.assertIn("p.order", CODE)
        self.assertIn("p.basis", CODE)
        for invented in ('"ranked by"', '"item level"', '"no stat weighting"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_count_on_each_row_is_the_modules_sentence(self):
        self.assertIn("d.family_line", CODE)
        self.assertIn("d.guild_line", CODE)
        for invented in ('" of the "', '" would gain"', '"nothing in here"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_place_in_the_order_is_the_modules_number(self):
        """Counted off the loop index it would agree today and disagree the
        first time this list was filtered, with nothing failing and the tie
        lines still naming the old order."""
        self.assertIn("d.rank", CODE)
        self.assertNotIn("index + 1", CODE)
        self.assertNotIn("i + 1", CODE)

    def test_what_the_overseer_can_run_is_the_modules(self):
        """Which dungeons have a portal is jobs.PORTAL_KEYWORDS's answer, read
        by dungeonpath.py; a list written here would drift the day a portal
        is added."""
        self.assertIn("p.runnable", CODE)
        self.assertIn("d.overseer.line", CODE)
        for invented in ('"deadmines"', '"portal"', '"can run"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_context_lines_are_all_the_modules(self):
        for key in ("d.state_line", "d.runs_line", "d.raid_line",
                    "f.off_path_line"):
            self.assertIn(key, CODE, key)
        for invented in ('"levels "', '"outgrown"', '"later"', '"raid"',
                         '"cleared"', '"Kalimdor"'):
            self.assertNotIn(invented, CODE, invented)

    def test_where_the_family_stands_only_picks_a_class(self):
        """`d.state` is the module's word, turned into a class name and
        nothing else; the page does not compare levels itself."""
        self.assertIn('"chr-card dgn-card dgn-" + d.state', CODE)
        for compared in (".level", "weakest", "floor"):
            self.assertNotIn(compared, CODE, compared)

    def test_each_members_line_is_printed_whole(self):
        """Not the name and the count joined here: that is a sentence about a
        character assembled where no Python test can read it."""
        self.assertIn("found.line", CODE)
        self.assertNotIn("found.who +", CODE)
        self.assertNotIn("found.gains.length +", CODE)

    def test_the_reason_the_total_skips_an_empty_slot_is_the_modules(self):
        self.assertIn("found.delta_note", CODE)
        self.assertNotIn('"empty slot"', CODE)

    def test_every_verdict_sentence_on_a_gain_is_the_modules(self):
        self.assertIn("gain.line", CODE)
        for invented in ('"replaces"', '"beats"', '"better than"', '"+"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_caveats_on_a_gain_are_printed_not_written(self):
        """A weapon nothing here can rule on has to say so beside itself."""
        self.assertIn("gain.caveats", CODE)
        self.assertNotIn("proficiency", CODE)

    def test_a_chip_is_the_modules_words_and_the_modules_tone(self):
        """`tone` is a ROLE NAME the module chose, never a colour and never a
        state this code worked out. An unknown one has to draw as a plain chip
        rather than being dropped."""
        self.assertIn("chip.text", CODE)
        self.assertIn('"chip" + (chip.tone', CODE)
        self.assertNotIn("new Map([", CODE)

    def test_an_empty_string_from_the_module_draws_nothing(self):
        """"There is nothing to say here" is a real answer, and an empty line
        under a heading reads as a broken page."""
        self.assertIn("if (text) parent.appendChild", CODE)

    def test_the_item_row_is_the_chronicles_and_not_a_second_copy(self):
        """An item is drawn in the same colour here as on the paper doll, and
        a second renderer is a second opinion about what an item looks like."""
        self.assertIn("chrItem(gain", CODE)


class TheListStaysScannableOnAPhone(unittest.TestCase):
    """Mobile is the case this is read on. Twenty dungeons times five
    characters times their gains does not fit a thumb expanded."""

    def test_a_dungeon_row_is_collapsed_until_it_is_asked_for(self):
        self.assertIn('el("details", "chr-card dgn-card dgn-" + d.state)', CODE)
        self.assertIn('document.createElement("summary")', CODE)

    def test_the_name_and_the_count_are_visible_while_it_is_collapsed(self):
        """A list of twenty closed rows that only show a name answers nothing,
        and opening all twenty is the thing this view exists to replace."""
        head = CODE[CODE.index('createElement("summary")'):
                    CODE.index("card.appendChild(head)")]
        for key in ("d.rank", "d.name", "d.state_line", "d.chips"):
            self.assertIn(key, head, key)

    def test_it_takes_the_shared_card_recipe_rather_than_a_second_one(self):
        """Four copies of the card recipe is four chances for one to drift."""
        self.assertIn("chr-card dgn-card", CODE)
        self.assertNotIn("border-radius:14px", CSS)
        self.assertNotIn("box-shadow", CSS)

    def test_nothing_sets_a_width_in_pixels(self):
        """A width in pixels is how a phone gets a sideways scrollbar."""
        found = re.search(r"[^-]width:\s*\d+px", CSS)
        self.assertIsNone(found, found.group(0) if found else "")

    def test_the_long_things_wrap_instead_of_pushing_the_page_wide(self):
        self.assertIn("flex-wrap:wrap", CSS)
        self.assertIn("overflow-wrap:anywhere", CSS)

    def test_the_one_grid_cannot_be_forced_wider_by_its_contents(self):
        """`1fr` is min-content by default, so a long dungeon name in column
        two widens the row past the viewport. minmax(0, 1fr) is the fix and it
        is invisible in a diff."""
        self.assertIn("minmax(0, 1fr)", CSS)

    def test_it_lays_out_without_a_breakpoint_of_its_own(self):
        """Mobile first: the same rules on a phone and a desktop, so nobody
        has to choose where one becomes the other."""
        self.assertNotIn("@media", CSS)

    def test_the_row_can_be_reached_by_keyboard(self):
        self.assertIn("summary:focus-visible", CSS)


class TheTabAndItsAddress(unittest.TestCase):
    def test_the_tab_button_exists_and_names_the_view(self):
        self.assertIn("gb.dataset.view = DUNGEONS_VIEW;", PAGE)
        self.assertIn('gb.textContent = "Dungeons";', PAGE)

    def test_it_sits_after_the_chronicle_and_before_the_continents(self):
        """The Chronicle says where they have been; this says which of the
        places they have not been is worth the walk."""
        self.assertLess(PAGE.index("tabs.appendChild(hb);"),
                        PAGE.index("tabs.appendChild(gb);"))
        self.assertLess(PAGE.index("tabs.appendChild(gb);"),
                        PAGE.index("for (const id of CONTINENT_ORDER)"))

    def test_the_view_is_an_address(self):
        """A *_VIEW constant missing from HASH_VIEWS gets no error and no
        warning: its deep link quietly opens the Family tab."""
        listed = PAGE[PAGE.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        self.assertIn("DUNGEONS_VIEW", listed)

    def test_showview_toggles_the_section(self):
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('dgnsection.style.display = isDgn ? "block" : "none";',
                      show)

    def test_opening_the_tab_does_not_wait_for_the_timer(self):
        """A minute of empty list under a heading is indistinguishable from a
        broken one, and this is the slowest poll on the page."""
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        head = show[show.index("if (isDgn) {"):]
        self.assertIn("pollDungeons();", head[:head.index("return;")])

    def test_opening_it_stops_the_things_that_belong_to_other_views(self):
        """The panel keeps a second player alive off screen and the broadcast
        grid keeps pulling video nobody can see."""
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        head = show[show.index("if (isDgn) {"):]
        head = head[:head.index("return;")]
        self.assertIn("closePanel();", head)
        self.assertIn("stopBroadcasts();", head)


class ThePoll(unittest.TestCase):
    def test_it_stops_when_the_tab_is_not_open(self):
        """The heaviest read on the site. Polled behind a hidden tab it is
        every dungeon's boss loot every minute for nobody."""
        self.assertIn("view !== DUNGEONS_VIEW || dgnPulling) return;", CODE)
        self.assertIn("if (view === DUNGEONS_VIEW) pollDungeons();", CODE)

    def test_only_one_pull_is_in_flight_at_a_time(self):
        """showView starts one on the way into the tab and the interval starts
        another, so two can overlap - and nothing orders their replies, so the
        slower one lands last and stamps its older ranks over the newer ones
        with the page looking freshly drawn either way."""
        self.assertIn("dgnPulling = true;", CODE)
        self.assertIn("dgnPulling) return;", CODE)

    def test_the_guard_is_released_even_when_the_read_throws(self):
        """Cleared at the end of the try it would be skipped by the very
        failure that most needs the next poll to be allowed to run."""
        poll = CODE[CODE.index("async function pollDungeons"):]
        poll = poll[:poll.index("setInterval")]
        finally_at = poll.index("} finally {")
        self.assertLess(poll.index("} catch (e) {"), finally_at)
        self.assertIn("dgnPulling = false;", poll[finally_at:])

    def test_a_world_that_never_answers_is_given_an_hourglass(self):
        """The flag above turns a hung read into a worse failure without this:
        the promise stays pending, the catch never runs, the flag is never
        cleared, and no later poll can replace "reaching the world..." ever
        again. The two are one guard."""
        self.assertIn("AbortSignal.timeout(20000)", CODE)

    def test_a_failed_poll_keeps_what_is_drawn_and_says_it_may_be_stale(self):
        """A blanked list reads as "there is nothing worth running anywhere",
        which is the one claim this view must never make by accident."""
        catch = CODE[CODE.index("} catch (e) {"):]
        self.assertIn("may be stale", catch)
        self.assertNotIn("replaceChildren", catch)

    def test_it_is_the_slowest_poll_on_the_page(self):
        """This answer moves when somebody equips something, not between two
        pulls, and it costs more than any other read here."""
        self.assertIn("DUNGEONS_VIEW) pollDungeons(); }, 60000)", CODE)


class TheEndpoint(unittest.TestCase):
    def test_it_is_routed_and_the_builder_is_pure(self):
        self.assertIn('"/api/dungeons": _dungeons,', SERVER)
        self.assertIn("dungeonplan.build_dungeonplan(", SERVER)
        self.assertIn('fetch(u("/api/dungeons"),', BLOCK)

    def test_the_handler_takes_nothing_from_the_caller(self):
        """WHO the families are belongs to the roster, exactly as /api/armory
        and /api/family refuse a name. This one asks about every dungeon at
        once, so there is no map id to steer either."""
        handler = SERVER[SERVER.index("def _dungeons"):SERVER.index("def _recap")]
        self.assertNotIn("query.get", handler)
        fetch = SERVER[SERVER.index("def _fetch_dungeonplan"):
                       SERVER.index("# --- the live dungeon recap")]
        self.assertIn("_PLAN_FAMILIES", fetch)

    def test_an_empty_roster_binds_no_empty_in_list(self):
        """`IN ()` is a syntax error, so no family means no character read."""
        fetch = SERVER[SERVER.index("def _fetch_dungeonplan"):
                       SERVER.index("# --- the live dungeon recap")]
        self.assertIn("if names:", fetch)
        self.assertLess(fetch.index("if names:"), fetch.index("_LINEUP_GUILD.format"))

    def test_both_families_come_from_the_roster_and_not_from_bonds(self):
        """bonds knows one family. The roster's own `family` column knows the
        Alliance family and the Horde one, so that is what the path reads."""
        self.assertIn("SELECT name, family FROM overseer_roster", SERVER)
        paths = SERVER[SERVER.index("def _dungeon_paths"):
                       SERVER.index("# --- the live dungeon recap")]
        self.assertIn('for head, roster in fetched["families"].items():', paths)

    def test_a_dead_database_is_a_503_that_keeps_what_is_drawn(self):
        handler = SERVER[SERVER.index("def _dungeons"):SERVER.index("def _recap")]
        self.assertIn("self._send(503", handler)


class TheReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # To the recap's own banner and not to `def _fetch_recap`: the recap's
        # SQL constants and the shared `_wide_guarded` sit between the two, and
        # a window that swept them in would be asserting about somebody else's
        # code.
        cls.fetch = SERVER[SERVER.index("def _fetch_dungeonplan"):
                           SERVER.index("# --- the live dungeon recap")]

    def test_the_bound_map_list_is_the_modules_union(self):
        """The page draws a row per access-table map AND per map this site
        names, so binding the access table's maps alone would leave a
        site-named dungeon rendering "no boss loot" over loot that was never
        asked for."""
        self.assertIn("dungeonplan.map_ids(catalogue, achievements.MAP_NAMES)",
                      self.fetch)

    def test_the_dungeon_list_is_the_worlds_own_table(self):
        """A hand list cannot follow the family into a dungeon nobody
        remembered to add to it."""
        self.assertIn("dungeon_access_template", SERVER)
        self.assertIn("_PLAN_CATALOGUE", self.fetch)

    def test_the_catalogue_falls_back_to_columns_that_always_existed(self):
        """`difficulty` is what picks one row per map. A world that predates
        it must still get its dungeons."""
        self.assertIn("_PLAN_CATALOGUE_OLD", SERVER)
        old = SERVER[SERVER.index("_PLAN_CATALOGUE_OLD"):]
        self.assertNotIn("difficulty", old[:old.index(")\n")])

    def test_every_world_read_is_guarded_for_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN, and production
        lacks tables dev has. An unguarded read here is a 503 on the live
        realm for a feature it has nothing to do with."""
        for table in ("dungeon_access_template", "instance_encounters",
                      "creature_loot_template", "characters",
                      "character_inventory", "character_skills",
                      "overseer_roster", "guild_member",
                      "overseer_dungeon_run"):
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
        body = self.fetch[self.fetch.index("with conn.cursor()"):]
        self.assertNotIn("for map", body)

    def test_an_empty_catalogue_does_not_bind_an_empty_in_list(self):
        """`IN ()` is a syntax error rather than an empty result, so it would
        reach the handler's 503 on a world with no access table at all."""
        self.assertIn("if maps:", self.fetch)

    def test_the_spawn_test_stays_a_subquery(self):
        """Joined, a boss with two spawn rows would multiply every one of its
        loot rows by two and count the same sword twice."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("(SELECT DISTINCT id FROM acore_world.creature", sql)

    def test_loot_behind_a_reference_is_not_joined_as_an_item(self):
        """A row with a Reference points at reference_loot_template rather
        than at an item, so joining it on `it.entry = clt.Item` surfaces
        something unrelated as a boss drop."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("clt.Reference = 0", sql)

    def test_a_spell_credit_is_not_read_as_a_creature(self):
        """creditType 1 is a SPELL, and without the filter the join names an
        encounter after whatever creature shares the number."""
        sql = SERVER[SERVER.index("_PLAN_ENCOUNTERS = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("ie.creditType = 0", sql)
        self.assertIn("SELECT DISTINCT", sql)

    def test_where_the_family_stand_comes_back_with_them(self):
        """`map` is on the characters row already, so this is one column and
        not a second read."""
        sql = SERVER[SERVER.index("_PLAN_CHARS = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertIn("map", sql)

    def test_the_loot_read_carries_what_a_tooltip_draws(self):
        """infra#3501 built the tooltip for items nobody holds, which is every
        item on this page. Selecting a narrower list here would leave the rows
        unable to say anything a reader could act on - and this page ranks by
        item level and refuses to weight stats, so the tooltip is how the
        reader does the weighting it will not do."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = ("):]
        sql = sql[:sql.index(")" + chr(10))]
        self.assertIn("_ITEM_TEMPLATE_COLUMNS", sql)

    def test_the_chance_columns_stay_out_of_the_widened_read(self):
        """_ITEM_TEMPLATE_COLUMNS is item_template only, so the reason Chance
        and GroupId were dropped survives the widening: this page does not ask
        how likely a drop is and must not be able to start."""
        sql = SERVER[SERVER.index("_PLAN_LOOT = ("):]
        sql = sql[:sql.index(")" + chr(10))]
        self.assertNotIn("Chance", sql)
        self.assertNotIn("GroupId", sql)

    def test_the_handler_hands_the_book_over(self):
        paths = SERVER[SERVER.index("def _dungeon_paths"):
                       SERVER.index("# --- the live dungeon recap")]
        self.assertIn('fetched["skill_rows"], ITEMS)', paths)

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
        for copied in ("WEAPON_SKILLS = {", "ARMOUR_SKILLS = {",
                       "ARMOUR_GRADES = {", "WEARABLE_SLOTS = {"):
            self.assertNotIn(copied, MODULE, copied)

    def test_it_does_not_compare_item_levels_itself(self):
        """The comparison is recap.verdict's, and a second one here would be
        the divergence this module exists to avoid."""
        self.assertNotIn("item_level", MODULE)


if __name__ == "__main__":
    unittest.main()
