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
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
MODULE = (HERE / "guildcraft.py").read_text(encoding="utf-8")

BANNER = "// --- what the guild can make (infra#3507)"
CSS_BANNER = "/* --- what the guild can make (infra#3507)"
NEXT = "// --- where to go next (infra#3500)"
NEXT_CSS = "/* --- where to go next (infra#3500)"

BLOCK = PAGE[PAGE.index(BANNER) : PAGE.index(NEXT, PAGE.index(BANNER))]
CSS = PAGE[PAGE.index(CSS_BANNER) : PAGE.index(NEXT_CSS, PAGE.index(CSS_BANNER))]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_dungeon_tab.py carries, and for the same reason: a
    guard its own explanation can trip is a guard that gets weakened until it
    passes. Several assertions below name the sentence they forbid.
    """
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("//")
    )


CODE = code(BLOCK)
SECTION = PAGE[PAGE.index('<section id="trades">') :]
SECTION = SECTION[: SECTION.index("</section>")]
FETCH = SERVER[
    SERVER.index("_TRADE_SKILL_LIST = ") : SERVER.index(
        "# --- which dungeon is worth running next"
    )
]
HANDLER = SERVER[SERVER.index("def _trades") : SERVER.index("def _dungeons")]


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    def test_the_script_sits_between_the_tooltip_and_the_dungeon_plan(self):
        """The dungeon plan's window runs from its own banner to the Decree
        console's, so a block dropped below that banner would be read as part
        of it and judged by its assertions."""
        start = PAGE.index(BANNER)
        self.assertGreater(start, PAGE.index("// --- the item tooltip"))
        self.assertLess(start, PAGE.index(NEXT))

    def test_the_script_sits_below_the_routing_slice(self):
        """test_decree_tab and test_recap_tab both slice showView to
        setInterval(pollFamily. Code inside that window is read as routing."""
        self.assertGreater(PAGE.index(BANNER), PAGE.index("setInterval(pollFamily"))

    def test_the_styles_sit_between_the_furniture_and_the_dungeon_plans(self):
        """The shared furniture has to stay above every view window or the
        first view to claim it takes the others hostage."""
        self.assertLess(
            PAGE.index("/* --- the redesign furniture (infra#2597)"),
            PAGE.index(CSS_BANNER),
        )
        self.assertLess(PAGE.index(CSS_BANNER), PAGE.index(NEXT_CSS))

    def test_the_styles_sit_below_the_current_goal_banners_window(self):
        """That window runs from its own banner to the `nav` rule and sweeps in
        anything between."""
        self.assertGreater(PAGE.index(CSS_BANNER), PAGE.index("  nav { display:flex"))

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
        `def _thoughts`, and the dungeon plan's BEGINS at `def _dungeons`."""
        self.assertGreater(SERVER.index("def _trades"), SERVER.index("def _thoughts"))
        self.assertLess(SERVER.index("def _trades"), SERVER.index("def _dungeons"))


class TheMarkup(unittest.TestCase):
    def test_the_section_exists_beside_the_other_views(self):
        for element in (
            'id="gcrhead"',
            'id="gcrguild"',
            'id="gcrcoverage"',
            'id="gcrgapsline"',
            'id="gcrgaps"',
            'id="gcrorder"',
            'id="gcrlist"',
            'id="gcrbasis"',
        ):
            self.assertIn(element, SECTION, element)

    def test_the_gaps_are_above_the_list_and_not_below_it(self):
        """A trade nobody holds is the finding. Twenty rows below a list of
        fourteen trades is where a reader never reaches it."""
        self.assertLess(SECTION.index('id="gcrgaps"'), SECTION.index('id="gcrlist"'))

    def test_the_coverage_count_is_above_the_list_too(self):
        """It is the answer to "why is the character I care about not in
        here", and that question is asked while scanning rather than after
        reaching the bottom."""
        self.assertLess(
            SECTION.index('id="gcrcoverage"'), SECTION.index('id="gcrlist"')
        )

    def test_the_rule_it_was_ordered_by_is_above_the_list(self):
        """A list in an order is read as a finding. The rule that produced the
        order has to be readable before the list, not after fourteen rows."""
        self.assertLess(SECTION.index('id="gcrorder"'), SECTION.index('id="gcrlist"'))

    def test_the_basis_is_below_the_list_it_describes(self):
        self.assertGreater(
            SECTION.index('id="gcrbasis"'), SECTION.index('id="gcrlist"')
        )

    def test_the_markup_holds_no_sentence_of_its_own_about_a_trade(self):
        """The two `ds-rule` labels are the page's own furniture, exactly as
        the Chronicle's and the dungeon plan's are: they name a part of the
        page and say nothing about any trade. Everything else that judges a
        trade has to arrive from the module, so the labels are cut out and the
        rest is checked for a sentence somebody would act on."""
        rest = re.sub(r'<div class="ds-rule">.*?</div>', "", SECTION)
        for invented in (
            "engineering",
            "recipe items",
            "in reach",
            "short",
            "trainer",
            "vendor",
        ):
            self.assertNotIn(invented, rest, invented)


class ThePageDecidesNothing(unittest.TestCase):
    """Every sentence arrives written. The contract test_recap_tab established,
    and the reason guildcraft.py is a separate module."""

    def test_the_headline_and_the_guild_line_are_printed_and_not_composed(self):
        self.assertIn("p.line", CODE)
        self.assertIn("p.guild_line", CODE)
        for invented in ('"the guild"', '" of "', '" trades"', '" held"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_coverage_and_the_order_are_the_modules(self):
        self.assertIn("p.coverage", CODE)
        self.assertIn("p.order", CODE)
        self.assertNotIn("p.trades.length +", CODE)

    def test_the_gap_sentence_is_the_modules_and_so_is_its_count(self):
        """ "Engineering is missing" is a claim about a decision the family
        made on purpose, and it is not the page's to make."""
        self.assertIn("p.gaps_line", CODE)
        self.assertIn("gap.line", CODE)
        self.assertNotIn("p.gaps.length +", CODE)
        self.assertNotIn('"engineering"', CODE)

    def test_each_trade_prints_the_whole_sentence_the_module_wrote(self):
        self.assertIn("t.line", CODE)
        self.assertNotIn("t.name +", CODE)
        for invented in ('"holds"', '"at"', '" of 75"', '"nobody"'):
            self.assertNotIn(invented, CODE, invented)

    def test_every_holder_line_is_the_modules(self):
        self.assertIn("t.holder_lines", CODE)
        self.assertNotIn("holder.value", CODE)
        self.assertNotIn("holder.max", CODE)

    def test_the_two_list_headings_are_the_modules_and_not_the_pages(self):
        """A heading is a sentence, and it is also the one place a trimmed
        list would stop admitting it was trimmed."""
        self.assertIn("t.missing_head", CODE)
        self.assertIn("t.known_head", CODE)
        for invented in ('"already known"', '"missing"', '"to find"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_recipe_counts_are_counted_by_the_module(self):
        self.assertIn("t.recipes_line", CODE)
        self.assertNotIn("t.missing.length", CODE)
        self.assertNotIn("t.known.length", CODE)

    def test_the_skill_arithmetic_is_the_modules(self):
        """ "35 short" computed here is a number no Python test can check."""
        self.assertIn("recipe.reach_line", CODE)
        self.assertNotIn("recipe.rank -", CODE)
        self.assertNotIn("recipe.required_level", CODE)

    def test_the_source_sentence_and_its_count_are_the_modules(self):
        self.assertIn("recipe.source_line", CODE)
        self.assertIn("source.line", CODE)
        self.assertNotIn("recipe.sources.length", CODE)
        for invented in ('"sold by"', '"drops from"', '"rewarded by"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_trainer_admission_is_printed_rather_than_reasoned_about(self):
        """That a trainer craft cannot be NAMED is a fact about this realm's
        database, and the page must not be the thing that knows it."""
        self.assertIn("t.trainer_line", CODE)
        self.assertNotIn("skilllineability", CODE)

    def test_the_bound_on_what_is_listed_is_printed(self):
        self.assertIn("t.beyond_line", CODE)

    def test_the_assignment_line_is_the_modules(self):
        self.assertIn("t.assigned_line", CODE)
        self.assertNotIn("t.assigned.join", CODE)

    def test_the_place_in_the_order_is_the_modules_and_not_a_loop_index(self):
        """The page would agree with it today and disagree the first time this
        list was filtered, with nothing failing."""
        self.assertIn('el("span", "gcr-rank", String(t.rank))', CODE)
        self.assertNotIn("index + 1", CODE)

    def test_the_only_thing_decided_here_is_the_tone_a_chip_is_drawn_in(self):
        """A hue is a fact about the stylesheet, which is the one thing that
        knows this page is drawn on two grounds."""
        self.assertIn('"chip" + (chip.tone ? " " + chip.tone : "")', CODE)

    def test_an_unknown_tone_still_prints_rather_than_vanishing(self):
        """A tone added to the module later must show up as a plain chip, not
        disappear off the page with nothing failing."""
        chips = CODE[CODE.index("function gcrChips") :]
        chips = chips[: chips.index("\n}")]
        self.assertNotIn("if (chip.tone ===", chips)

    def test_the_basis_stands_down_when_there_was_no_list(self):
        """A basis describes how a list was built, so it must not stand over
        one that was not built at all."""
        self.assertIn("p.empty_note || p.basis", CODE)


class ThePoll(unittest.TestCase):
    def test_it_stops_when_the_tab_is_not_open(self):
        """The heaviest read on the site. Polled behind a hidden tab it is
        every recipe in the world every two minutes for nobody."""
        self.assertIn("if (view !== TRADES_VIEW || gcrPulling) return;", CODE)
        self.assertIn("if (view === TRADES_VIEW) pollTrades(); }, 120000)", CODE)

    def test_two_pulls_cannot_be_in_flight_at_once(self):
        """Nothing orders two replies: the slower one lands last and stamps
        its older counts over the newer ones, with the page looking freshly
        drawn either way."""
        self.assertIn("let gcrPulling = false;", CODE)
        self.assertIn("AbortSignal.timeout(20000)", CODE)

    def test_the_flag_is_released_in_a_finally(self):
        """Cleared at the end of the try it would be skipped by the very
        failure that most needs the next poll to be allowed to run."""
        poll = CODE[CODE.index("async function pollTrades") :]
        self.assertIn("} finally {", poll)
        self.assertIn("gcrPulling = false;", poll[poll.index("} finally {") :])

    def test_a_failed_poll_keeps_what_is_drawn(self):
        """A blanked list reads as "the guild can make nothing and needs
        nothing", which is the one claim this view must never make."""
        catch = CODE[CODE.index("} catch (e) {") :]
        self.assertIn("may be stale", catch)
        self.assertNotIn("replaceChildren", catch)


class TheTabAndItsAddress(unittest.TestCase):
    def test_the_tab_button_exists_and_names_the_view(self):
        self.assertIn("tb.dataset.view = TRADES_VIEW;", PAGE)
        self.assertIn('tb.textContent = "Trades";', PAGE)

    def test_it_sits_after_the_dungeon_plan_and_before_the_continents(self):
        """Both read about the same five: one says where to walk for a drop,
        this one says where to walk for a recipe."""
        self.assertLess(
            PAGE.index("tabs.appendChild(gb);"), PAGE.index("tabs.appendChild(tb);")
        )
        self.assertLess(
            PAGE.index("tabs.appendChild(tb);"),
            PAGE.index("for (const id of CONTINENT_ORDER)"),
        )

    def test_the_view_is_an_address(self):
        """A *_VIEW constant missing from HASH_VIEWS gets no error and no
        warning: its deep link quietly opens the Family tab."""
        listed = PAGE[PAGE.index("const HASH_VIEWS = [") :]
        listed = listed[: listed.index("]")]
        self.assertIn("TRADES_VIEW", listed)

    def test_showview_toggles_the_section(self):
        show = PAGE[PAGE.index("function showView") :]
        show = show[: show.index("setInterval(pollFamily")]
        self.assertIn('gcrsection.style.display = isTrd ? "block" : "none";', show)

    def test_opening_the_tab_does_not_wait_for_the_timer(self):
        """Two minutes of empty list under a heading is indistinguishable from
        a broken one."""
        show = PAGE[PAGE.index("function showView") :]
        show = show[: show.index("setInterval(pollFamily")]
        head = show[show.index("if (isTrd) {") :]
        self.assertIn("pollTrades();", head[: head.index("return;")])

    def test_opening_it_stops_the_things_that_belong_to_other_views(self):
        """The panel keeps a second player alive off screen and the broadcast
        grid keeps pulling video nobody can see."""
        show = PAGE[PAGE.index("function showView") :]
        show = show[: show.index("setInterval(pollFamily")]
        head = show[show.index("if (isTrd) {") :]
        head = head[: head.index("return;")]
        self.assertIn("closePanel();", head)
        self.assertIn("stopBroadcasts();", head)


class TheEndpoint(unittest.TestCase):
    def test_it_is_routed_and_the_builder_is_pure(self):
        self.assertIn('"/api/trades": _trades,', SERVER)
        self.assertIn("guildcraft.build_guildcraft(", SERVER)
        self.assertIn('fetch(u("/api/trades"),', BLOCK)

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


class TheMobileRules(unittest.TestCase):
    """The page is read on a phone. No horizontal scrolling, and a long list
    has to stay scannable."""

    def test_nothing_in_the_block_sets_a_width_in_pixels(self):
        self.assertIsNone(re.search(r"width:\s*\d+px", CSS))

    def test_the_only_grid_cannot_be_pushed_wider_than_its_column(self):
        """A grid column defaults to min-content, so a long recipe name would
        widen the row and take the whole page sideways with it."""
        self.assertIn("minmax(0, 1fr)", CSS)

    def test_long_names_break_rather_than_scroll(self):
        for rule in (".gcr-name", ".gcr-sum", ".gcr-why", ".gcr-src"):
            block = CSS[CSS.index(rule + " {") :]
            block = block[: block.index("}")]
            self.assertIn("overflow-wrap:anywhere", block, rule)

    def test_the_chips_wrap(self):
        block = CSS[CSS.index(".gcr-chips {") :]
        block = block[: block.index("}")]
        self.assertIn("flex-wrap:wrap", block)

    def test_a_trade_is_collapsed_until_it_is_asked_for(self):
        """Fourteen trades with a dozen recipes each is not a list a thumb
        scrolls, so the row is a <details> and opens to the whole card."""
        self.assertIn('el("details", "chr-card gcr-card")', CODE)

    def test_the_summary_marker_is_hidden_in_both_engines(self):
        """Safari draws its own triangle from a pseudo-element list-style does
        not reach."""
        self.assertIn("list-style:none", CSS)
        self.assertIn("::-webkit-details-marker", CSS)

    def test_the_row_can_be_reached_from_a_keyboard(self):
        self.assertIn("summary:focus-visible", CSS)

    def test_the_block_declares_no_breakpoint_of_its_own(self):
        """Mobile first: this view has one column at every width, so a media
        query here would be a second opinion about what small means."""
        self.assertNotIn("@media", CSS)


class TheHouseRules(unittest.TestCase):
    def test_no_em_dashes(self):
        for name in (
            "index.html",
            "map_server.py",
            "guildcraft.py",
            "tests/test_trades_tab.py",
        ):
            self.assertNotIn(
                chr(0x2014), (HERE / name).read_text(encoding="utf-8"), name
            )

    def test_the_page_reaches_no_new_outside_host(self):
        """This page is tailnet only and must not gain a new way to look
        broken. The icon CDN and the model viewer are the two it already
        names, and neither is named here."""
        self.assertNotIn("http", BLOCK)

    def test_nothing_from_a_payload_is_parsed_as_markup(self):
        """Recipe names, vendor names and quest titles come from the world
        database and are not trusted."""
        for parsed in ("innerHTML", "insertAdjacentHTML"):
            self.assertNotIn(parsed, BLOCK, parsed)

    def test_the_module_ships_in_the_image(self):
        """A module the page imports and the image does not carry is a 503 on
        a tab that was green in CI."""
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("guildcraft.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
