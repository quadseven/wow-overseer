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
import re
import unittest

import recap

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")
SERVER_MODULE = (HERE / "recap.py").read_text(encoding="utf-8")

BANNER = "// --- the live recap and the loot board (infra#2597, mod-overseer#88)"
CSS_BANNER = "/* --- the recap and the loot board, inside the Chronicle (infra#2597)"
NEXT = "// --- the Council (infra#2597)"
NEXT_CSS = "/* --- the Council (infra#2597)"
BLOCK = PAGE[PAGE.index(BANNER):PAGE.index(NEXT, PAGE.index(BANNER))]
CSS = PAGE[PAGE.index(CSS_BANNER):PAGE.index(NEXT_CSS, PAGE.index(CSS_BANNER))]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_chronicle_tab.py carries, and for the same reason: a
    guard that its own explanation can trip is a guard that gets weakened
    until it passes. Several assertions below name the sentence they forbid.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


CODE = code(BLOCK)


class WhereTheCodeIsAllowedToSit(unittest.TestCase):
    def test_the_block_is_inside_the_chronicles_window(self):
        """It renders into that tab and shares chrItem, chrSect, chrChips and
        chrWhen with it. Outside that window it would be either sweeping into
        the Armory's assertions or keeping a second copy of four helpers."""
        chron = PAGE.index("// --- the Chronicle (infra#2597, mod-overseer#88,"
                           " mod-overseer#152)")
        self.assertGreater(PAGE.index(BANNER), chron)
        self.assertLess(PAGE.index(BANNER), PAGE.index(NEXT))

    def test_the_css_is_above_the_family_banner(self):
        """The Family CSS tests slice from their banner to the end of the
        stylesheet, so rules below it are read as Family rules."""
        self.assertLess(PAGE.index(CSS_BANNER),
                        PAGE.index("--- the Family tab (infra#2892)"))

    def test_the_markup_exists_and_is_in_the_chronicle_section(self):
        section = PAGE[PAGE.index('<section id="chronicle">'):]
        section = section[:section.index("</section>")]
        for element in ('id="rcbox"', 'id="rcboard"', 'id="rcbasis"'):
            self.assertIn(element, section, element)

    def test_the_timeline_is_still_on_the_page_below_it(self):
        """The recap was added ABOVE what they have done, not instead of it."""
        section = PAGE[PAGE.index('<section id="chronicle">'):]
        section = section[:section.index("</section>")]
        self.assertLess(section.index('id="rcbox"'),
                        section.index("what they have done"))


class TheEndpoint(unittest.TestCase):
    def test_it_is_routed_and_the_builder_is_pure(self):
        self.assertIn('"/api/recap": _recap,', SERVER)
        self.assertIn("recap.build_recap(", SERVER)
        self.assertIn('fetch(u("/api/recap"))', BLOCK)

    def test_the_handler_takes_a_map_and_never_a_roster(self):
        """WHO the family is belongs to bonds, exactly as /api/armory and
        /api/family refuse a name. A map id is a fact about the world."""
        handler = SERVER[SERVER.index("def _recap"):]
        handler = handler[:handler.index("def _council")]
        self.assertIn("family.roster()", handler)
        self.assertNotIn('query.get("name"', handler)
        self.assertIn('query.get("map"', handler)

    def test_the_map_parameter_is_an_integer_or_it_is_dropped(self):
        handler = SERVER[SERVER.index("def _recap"):]
        handler = handler[:handler.index("def _council")]
        self.assertIn("isdigit()", handler)

    def test_a_dead_database_is_a_503_that_keeps_what_is_drawn(self):
        handler = SERVER[SERVER.index("def _recap"):]
        handler = handler[:handler.index("def _council")]
        self.assertIn("self._send(503", handler)
        self.assertIn("may be stale", BLOCK)

    def test_every_overseer_read_is_guarded_for_both_errors(self):
        """1146 is a missing TABLE and 1054 a missing COLUMN, and only one of
        the two guards already in this file catches both. Production lacks
        tables dev has, so an unguarded read here is a 503 on the live realm
        for a feature it has nothing to do with."""
        fetch = SERVER[SERVER.index("def _fetch_recap"):]
        fetch = fetch[:fetch.index("# --- the current-goal banner")]
        for table in ("overseer_dungeon_run", "overseer_event", "overseer_death",
                      "overseer_snapshot"):
            self.assertIn('"%s"' % table, fetch, table)
        # Nothing in the fetch may call execute directly: the guard is the
        # only way rows come back, so a read added later cannot skip it.
        self.assertNotIn("cur.execute", fetch)

    def test_the_guard_catches_the_base_class_that_covers_both(self):
        """1054 is not a ProgrammingError. pymysql has no entry for it in
        error_map, so it falls back to OperationalError, and a guard that
        catches only ProgrammingError is half a guard."""
        guard = SERVER[SERVER.index("def _wide_guarded"):]
        guard = guard[:guard.index("def _fetch_recap")]
        self.assertIn("pymysql.err.MySQLError", guard)
        self.assertIn("(1054, 1146)", guard)

    def test_anything_that_is_not_those_two_still_raises(self):
        """A guard that swallowed a network blip would render an empty recap
        and train the alarm away."""
        guard = SERVER[SERVER.index("def _wide_guarded"):]
        guard = guard[:guard.index("def _fetch_recap")]
        self.assertIn("raise", guard)

    def test_the_run_read_falls_back_to_columns_that_always_existed(self):
        """outcome and members arrived on 2026-09-02. A world that predates
        them must still get its runs."""
        self.assertIn("_RECAP_RUNS_OLD", SERVER)
        self.assertNotIn("outcome", SERVER[SERVER.index("_RECAP_RUNS_OLD"):
                                           SERVER.index("_RECAP_EQUIPS")])

    def test_the_equip_read_is_not_narrowed_to_the_run(self):
        """The earliest equip of a pair is a fortnight old for gear worn for a
        fortnight. Narrowing this to the run window would reproduce exactly
        the bug the module exists to fix."""
        sql = SERVER[SERVER.index("_RECAP_EQUIPS = ("):]
        sql = sql[:sql.index(")\n")]
        self.assertNotIn("first_seen >=", sql)
        self.assertNotIn("started_at", sql)

    def test_the_bosses_are_not_a_hand_written_list(self):
        """A hand list is what put a boss in the Chronicle that the core does
        not count. These come from the core's own encounter table."""
        self.assertIn("instance_encounters", SERVER)
        self.assertIn("creature_loot_template", SERVER)


class ThePageDecidesNothing(unittest.TestCase):
    """Every sentence arrives written. This is the contract the Chronicle
    redesign established and the reason recap.py is a separate module."""

    def test_the_headline_is_printed_and_not_composed(self):
        self.assertIn("p.headline", CODE)
        for invented in ('" in"', '"Wailing Caverns"', '" minutes in"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_party_line_is_the_modules(self):
        self.assertIn("p.party_line", CODE)
        for invented in ('" of "', '" inside"', '" standing"'):
            self.assertNotIn(invented, CODE, invented)

    def test_each_member_prints_the_whole_label_the_module_wrote(self):
        """Not the name and the note joined here: that is a sentence about a
        character assembled where no Python test can read it."""
        self.assertIn("m.label", CODE)
        self.assertNotIn("m.name +", CODE)
        for invented in ('"fighting"', '"down"', '"inside"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_progress_line_and_its_basis_are_the_modules(self):
        self.assertIn("prog.line", CODE)
        self.assertIn("prog.basis", CODE)
        self.assertNotIn('" of " + prog.total', CODE)

    def test_the_loot_header_is_the_modules_and_counts_its_own_list(self):
        """The header that overstated its list is the bug the operator saw."""
        self.assertIn("p.loot_line", CODE)
        self.assertNotIn("p.loot.length +", CODE)

    def test_the_loot_caveat_is_the_modules_string_and_not_the_pages(self):
        self.assertIn("p.loot_caveat", CODE)
        self.assertNotIn("first worn", CODE)

    def test_the_run_card_prints_the_same_caveat(self):
        """The Chronicle's own run card counts loot by the same rule now, so
        it must carry the same admission."""
        self.assertIn('el("div", "note", c.loot_caveat)', PAGE)

    def test_every_verdict_sentence_is_the_modules(self):
        self.assertIn("drop.verdict_line", CODE)
        self.assertNotIn("best.who +", CODE)
        for invented in ('"upgrade for"', '"item level"', '"better than"',
                         '"beats"'):
            self.assertNotIn(invented, CODE, invented)

    def test_the_also_wanted_list_is_trimmed_by_the_module(self):
        """The page used to take wanted_by.slice(1) as "everybody except the
        one already shown", which is true only while the module's ranking puts
        that reader first. Re-rank the verdicts and the page would start
        hiding a name or repeating one, with nothing failing."""
        self.assertIn("drop.also_line", CODE)
        self.assertNotIn("slice(1)", CODE)
        self.assertNotIn('"also wanted by"', CODE)

    def test_the_slot_and_the_chance_are_joined_by_the_module(self):
        self.assertIn("drop.meta", CODE)
        self.assertNotIn("drop.slot +", CODE)

    def test_a_progress_bar_is_only_drawn_when_the_module_says_it_knows(self):
        """With no instance record the payload is known:false, count 0 and
        total 7. An empty bar over that asserts "no bosses down", which is the
        distinction encounters_down exists to keep."""
        self.assertIn("prog.known && prog.total", CODE)

    def test_the_ending_is_a_sentence_and_not_a_column_value(self):
        """ended_reason is sometimes prose and sometimes a bare token like
        `cold_heartbeat`. The page cannot tell which it has."""
        self.assertIn("_ending(", SERVER_MODULE)
        self.assertIn("p.last.ended_reason", CODE)

    def test_the_caveats_on_a_drop_are_printed_not_written(self):
        self.assertIn("drop.caveats", CODE)
        self.assertNotIn("proficiency", CODE)

    def test_the_boss_line_is_counted_by_the_module(self):
        self.assertIn("boss.line", CODE)
        self.assertNotIn("boss.drops.length +", CODE)

    def test_the_only_thing_decided_here_is_the_tone_a_verdict_is_drawn_in(self):
        """A hue is a fact about the stylesheet, which is the one thing that
        knows this page is drawn on two grounds."""
        self.assertIn("RC_TONES", CODE)
        tones = CODE[CODE.index("const RC_TONES"):]
        tones = tones[:tones.index("]);")]
        for word in (recap.UPGRADE, recap.EMPTY, recap.LOCKED):
            self.assertIn('"%s"' % word, tones, word)

    def test_an_unknown_verdict_still_prints_rather_than_vanishing(self):
        """A word recap.py grows later must show up as plain text, not be
        dropped on the floor by a lookup that missed."""
        self.assertIn('RC_TONES.get(drop.best.verdict) || ""', CODE)

    def test_the_readers_clock_is_the_one_exception(self):
        """A timestamp has to be rendered in the reader's timezone and the
        server does not know what that is. It reuses the Chronicle's helper
        rather than keeping a second copy."""
        self.assertIn("chrWhen(", CODE)
        self.assertNotIn("function chrWhen", CODE)


class WhatThePageMustNotDo(unittest.TestCase):
    def test_nothing_from_the_payload_is_rendered_as_markup(self):
        """Item names, boss names and character names all come from tables
        this service does not write. textContent, never innerHTML."""
        self.assertNotIn("innerHTML", BLOCK)
        self.assertNotIn("insertAdjacentHTML", BLOCK)

    def test_a_failed_poll_does_not_blank_the_view(self):
        poll = BLOCK[BLOCK.index("async function pollRecap"):]
        self.assertNotIn("rcbox.replaceChildren()", poll)
        self.assertNotIn("rcboard.replaceChildren()", poll)

    def test_the_failure_says_so_through_the_banner_the_tab_already_has(self):
        """Two banners on one tab can disagree about whether the world is up."""
        poll = BLOCK[BLOCK.index("async function pollRecap"):]
        self.assertIn("chrhead.textContent", poll)

    def test_the_page_never_reorders_the_roster_or_the_bosses(self):
        """Roster order is a fact about the family (bonds.speaking_order) and
        encounter order is a fact about the dungeon. A sort here would be a
        second opinion about either."""
        self.assertNotIn(".sort(", CODE)

    def test_entering_the_view_polls_both_halves(self):
        show = PAGE[PAGE.index("function showView"):]
        branch = show[show.index("if (isChr) {"):]
        branch = branch[:branch.index("return;")]
        self.assertIn("pollChronicle();", branch)
        self.assertIn("pollRecap();", branch)

    def test_it_only_polls_while_the_view_is_open(self):
        self.assertIn("if (view === CHRONICLE_VIEW) pollRecap();", BLOCK)


class TheStylesheetKeepsTheHouseRules(unittest.TestCase):
    def test_every_property_it_reads_is_defined_somewhere(self):
        """An undefined custom property is invalid at computed-value time, so
        the declaration falls back to inherit with no console error and no
        failing test. That shipped once already (infra#3255)."""
        style = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", style))
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*\)", CSS))
        self.assertEqual(sorted(used - defined), [])

    def test_it_paints_from_on_card_roles_and_never_from_a_pigment(self):
        """A pigment is mixed for one ground and this page has two."""
        for pigment in ("--cyan", "--green", "--vermilion", "--amber",
                        "--rust", "--deep-green"):
            self.assertNotIn("var(%s)" % pigment, CSS, pigment)

    def test_it_defines_no_quality_colours_of_its_own(self):
        """One .q3 on the page. A second set here would be a second opinion
        about what rare looks like."""
        self.assertNotIn(".q3 {", CSS)

    def test_no_rule_of_its_own_sits_inside_a_theme_block(self):
        self.assertNotIn("@media", CSS)


class TheArmoryLinksBackToTheChronicle(unittest.TestCase):
    """"Can you link on their armory where they got what gear?" What the
    record supports is where it was first seen WORN, and the line says that."""

    def test_the_provenance_index_rides_on_the_armory_payload(self):
        self.assertIn("recap.provenance_index(", SERVER)
        self.assertIn("arm.provenance = p.provenance || {};", PAGE)

    def test_the_equip_read_behind_it_is_guarded(self):
        """Gear and talents are core tables that are always there;
        overseer_event is not. A realm without it must still get a paper
        doll."""
        fetch = SERVER[SERVER.index("def _fetch_armory"):]
        fetch = fetch[:fetch.index("def _fetch_standing")]
        self.assertIn("_wide_guarded(", fetch)
        self.assertIn("equip_event_rows", fetch)

    def test_the_line_is_a_link_to_the_chronicle(self):
        block = PAGE[PAGE.index("function renderProvenance"):]
        block = block[:block.index("function renderDetail")]
        self.assertIn('a.href = "#chronicle";', block)
        self.assertIn("a.textContent = p.line;", block)

    def test_an_item_with_no_record_is_shown_and_not_hidden(self):
        """Hiding it would make "no idea where this came from" look identical
        to "came from nowhere interesting"."""
        block = PAGE[PAGE.index("function renderProvenance"):]
        block = block[:block.index("function renderDetail")]
        self.assertIn("if (!p.known)", block)
        self.assertIn("row.textContent = p.line;", block)

    def test_the_sentence_is_the_modules_and_not_the_pages(self):
        block = code(PAGE[PAGE.index("function renderProvenance"):
                          PAGE.index("function renderDetail")])
        self.assertIn("p.line", block)
        for invented in ('"first worn in "', '"looted in "', '"got in "'):
            self.assertNotIn(invented, block, invented)

    def test_the_page_never_calls_it_looted(self):
        """The event says where it was WORN. A character can loot in a
        dungeon and equip in town, and the record cannot tell those apart."""
        self.assertNotIn("looted here", PAGE)
        self.assertNotIn("looted in", PAGE)


class TheModuleShipsInTheImage(unittest.TestCase):
    def test_recap_is_copied_into_the_container(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("recap.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
