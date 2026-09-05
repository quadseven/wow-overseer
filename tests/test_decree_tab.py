"""The Decree console's page contract, asserted against index.html as source,
the way test_family_tab.py, test_armory_tab.py and test_wealth_tab.py do:
map_server.py imports pymysql and the page has no other test seam.

TWO OF THESE ARE ABOUT WHERE THE CODE SITS, and they are the reason a file
like this exists at all. Seven suites slice this page by their own banners:
the Family tests take their banner to loadZones().then( (script) and to
</style> (CSS); the Armory's and the Bags view's take theirs to </script>; the
Chronicle's, the Council's and the Eye's each run to the next view's banner;
the current-goal banner's CSS window ends at the `nav` rule. Code dropped
inside any of those windows is swept into assertions about a feature it has
nothing to do with. So this view's CSS sits between the shared redesign
furniture and the Chronicle banner, its script sits between the map's
intervals and the realm banner, its handler sits BELOW the chat one, and its
fetch sits BELOW `_ask_llm`.

THE FURNITURE STAYS ABOVE IT. The section rule, the stat strip and the hue
vocabulary belong to no single view (infra#2597), so this block sits after
them and never wraps them.

THE REST ARE THE TWO HONESTY MECHANISMS, seen from the page's side. This is
the only view in the redesign that WRITES, and the failure it must not have is
the one the whole epic is named after: a control that reports success while
doing nothing. So every judgement is asserted to be ABSENT from the page - the
list of wired job modes, the vocabulary of travel roles, the meaning of a
status word - and every control that cannot reach the world is asserted to be
disabled with the reason beside it.

Ticket: infra#2597.
"""
import pathlib
import re
import unittest

import decree
import jobs
import travel

HERE = pathlib.Path(__file__).resolve().parent.parent
PAGE = (HERE / "index.html").read_text(encoding="utf-8")
SERVER = (HERE / "map_server.py").read_text(encoding="utf-8")

JS_BANNER = "// --- the Decree console (infra#2597)"
CSS_BANNER = "/* --- the Decree console (infra#2597)"
CHRONICLE_CSS = "/* --- the Chronicle (infra#2597, mod-overseer#88, mod-overseer#152)"
FURNITURE_CSS = "/* --- the redesign furniture (infra#2597)"
REALM_JS = "// --- which world this is (quadseven/mod-overseer#184)"

VIEW = PAGE[PAGE.index(JS_BANNER):PAGE.index(REALM_JS)]
CSS = PAGE[PAGE.index(CSS_BANNER):PAGE.index(CHRONICLE_CSS)]


def rule(selector: str) -> str:
    """The declarations of the rule whose selector LIST contains `selector`.

    A group, not a literal match: several of these declarations are shared by
    two or five selectors and written once, and a test that could only read
    `.dcrword {` would push the next person back into five copies of the same
    four lines to keep it passing.
    """
    # Comments first: this block's prose carries commas, and a comment left
    # in front of a selector becomes part of it.
    bare = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", bare):
        heads = [h.strip() for h in block.group(1).split(",")]
        if selector in heads:
            return block.group(2)
    raise AssertionError("no rule selects %r" % selector)
SECTION = PAGE[PAGE.index('<section id="decree">'):]
SECTION = SECTION[:SECTION.index("</section>")]


class WhereTheCodeIsAllowedToSit(unittest.TestCase):

    def test_the_styles_sit_above_every_view_window(self):
        """Every other view's CSS window starts at its own banner, and all of
        them are below this one."""
        css = PAGE.index(CSS_BANNER)
        for banner in (CHRONICLE_CSS,
                       "/* --- the Council (infra#2597)",
                       "/* --- the Eye (infra#2597)",
                       "--- the Armory tab (infra#3096",
                       "--- the Bags tab (quadseven/mod-overseer#88",
                       "--- the Family tab (infra#2892)"):
            self.assertLess(css, PAGE.index(banner), banner)

    def test_the_shared_furniture_is_above_this_view_and_not_inside_it(self):
        """The section rule, the stat strip and the hue vocabulary are used by
        three other views. Defined inside this window they would become this
        view's contract, and redrawing this view would take the others with
        it."""
        self.assertLess(PAGE.index(FURNITURE_CSS), PAGE.index(CSS_BANNER))

    def test_the_styles_sit_below_the_current_goal_banners_window(self):
        """That window runs from its own banner to the `nav` rule, and sweeps
        in anything between."""
        self.assertGreater(PAGE.index(CSS_BANNER), PAGE.index("  nav { display:flex"))

    def test_the_script_sits_below_the_family_slice(self):
        """TheFamilyTab slices from its banner to loadZones().then(."""
        self.assertGreater(PAGE.index(JS_BANNER), PAGE.index("loadZones().then("))

    def test_the_script_sits_above_the_realm_banners_own_window(self):
        """The realm banner's suite slices from its comment to the
        current-goal banner's."""
        self.assertLess(PAGE.index(JS_BANNER), PAGE.index(REALM_JS))

    def test_the_handler_sits_below_every_other_endpoints_window(self):
        """The Family, Armory and Wealth windows end at `def _thoughts` or
        `def do_POST`; the watch window starts at `def _watch_state`."""
        at = SERVER.index("    def _decree(self")
        self.assertGreater(at, SERVER.index("    def do_POST(self"))
        self.assertGreater(at, SERVER.index("    def _chat(self"))
        self.assertLess(at, SERVER.index("    def _watch_state(self"))

    def test_the_fetch_sits_below_every_other_fetch_window(self):
        """`def _fetch_armory`, `_fetch_achievements` and `_fetch_questlog`
        all run to `def _ensure_stream_store`, and `_fetch_agenda` runs to
        `_fetch_streams`."""
        at = SERVER.index("def _fetch_decree")
        self.assertGreater(at, SERVER.index("def _fetch_streams"))
        self.assertGreater(at, SERVER.index("def _ask_llm"))
        self.assertLess(at, SERVER.index("class Handler"))


class TheTabIsReachable(unittest.TestCase):

    def test_the_tab_exists_beside_the_others(self):
        self.assertIn('<section id="decree">', PAGE)
        self.assertIn('db.textContent = "Decree";', PAGE)
        self.assertIn("db.dataset.view = DECREE_VIEW;", PAGE)

    def test_it_is_the_last_named_view_and_before_the_continents(self):
        """Every tab before it answers a question about the family. This one
        changes what they are doing, and it must not be the thing under the
        thumb of somebody who opened the site to check whether anybody died."""
        self.assertLess(PAGE.index("tabs.appendChild(hb);"),
                        PAGE.index("tabs.appendChild(db);"))
        self.assertLess(PAGE.index("tabs.appendChild(db);"),
                        PAGE.index("for (const id of CONTINENT_ORDER)"))

    def test_the_view_is_an_address(self):
        """A *_VIEW constant missing from HASH_VIEWS gets no error and no
        warning: its deep link quietly opens the Family tab."""
        listed = PAGE[PAGE.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        self.assertIn("DECREE_VIEW", listed)

    def test_showview_toggles_the_section(self):
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('dcrSection.style.display = isDec ? "block" : "none";', show)

    def test_opening_the_tab_does_not_wait_for_the_timer(self):
        """Ten seconds of a blank console under a heading is
        indistinguishable from a broken one."""
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        dec = show[show.index("if (isDec) {"):]
        self.assertIn("pollDecree();", dec[:dec.index("return;")])

    def test_opening_it_stops_the_things_that_belong_to_other_views(self):
        """The panel keeps a second player alive off screen and the broadcast
        grid keeps pulling video nobody can see."""
        show = PAGE[PAGE.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        dec = show[show.index("if (isDec) {"):]
        head = dec[:dec.index("return;")]
        self.assertIn("closePanel();", head)
        self.assertIn("stopBroadcasts();", head)

    def test_the_poll_stops_when_the_tab_is_not_open(self):
        poll = VIEW[VIEW.index("async function pollDecree"):]
        self.assertIn("if (view !== DECREE_VIEW) return;", poll)

    def test_the_poll_matches_the_cadence_of_a_saved_column(self):
        """These are roster columns and finished command rows, not a stream."""
        self.assertIn("const DECREE_POLL_MS = 10000;", VIEW)
        self.assertIn("setInterval(pollDecree, DECREE_POLL_MS);", PAGE)


class NothingIsDecidedInJavaScript(unittest.TestCase):
    """THE ONE RULE (infra#2597). Every judgement lives in a pure module the
    stdlib suite can import with no database and no browser; the page sets
    textContent. These assert the judgements are ABSENT here, which is the
    only version of the rule a refactor cannot quietly undo."""

    def test_the_page_never_names_a_job_mode(self):
        """Which modes exist, and which of them are wired, is jobs.py's
        answer. A copy in the page would go on saying FARM works for as long
        as nobody happened to try it."""
        for mode in jobs.MODES:
            self.assertNotIn('"' + mode + '"', VIEW, mode)

    def test_the_page_never_names_a_travel_role(self):
        """The keywords are already duplicated in C++ and compared line for
        line by test_travel_npc. A third copy here is the one nobody checks."""
        for role in travel.ROLES:
            self.assertNotIn('"' + role + '"', VIEW, role)

    def test_the_page_never_names_a_command_status(self):
        """`delivered` reading as success is the defect this view exists to
        prevent. The page must not be able to match on the word at all - it
        draws the tone the module handed it."""
        for status in decree.OUTCOMES:
            self.assertNotIn('"' + status + '"', VIEW, status)

    def test_the_verdict_arrives_on_the_row(self):
        self.assertIn('(o.success ? " ok" : "")', VIEW)

    def test_the_page_never_names_a_section_key(self):
        """It looks each card up by the key that card's own payload carries."""
        for section in decree.SECTIONS:
            self.assertNotIn('"' + section.key + '"', VIEW, section.key)

    def test_the_page_never_composes_a_refusal(self):
        """A refusal is a claim about this system. The page chooses between
        sentences the module wrote; it never writes one."""
        ladder = VIEW[VIEW.index("function dcrShowWill"):]
        ladder = ladder[:ladder.index("async function dcrSpeak")]
        for line in ladder.splitlines():
            if "refusal =" in line and "let refusal" not in line:
                self.assertTrue(
                    "p.will.refusals." in line or "t.why_not" in line, line)

    def test_the_page_never_names_the_family(self):
        """WHO the family is belongs to bonds, and in what order they answer
        belongs to bonds too. The audience arrives sorted."""
        import family
        for name in family.roster():
            self.assertNotIn('"' + name + '"', VIEW, name)

    def test_nothing_reaches_the_page_as_markup(self):
        """A command a bot was given and a detail a worldserver wrote are
        both data, and both land here."""
        self.assertNotIn("innerHTML", VIEW)
        self.assertNotIn("insertAdjacentHTML", VIEW)

    def test_the_markup_carries_no_sentence_the_module_owns(self):
        """Two headings the module does not name are allowed; a mode, a role
        or a status word in the HTML is not - it would be a second copy of a
        vocabulary that is free to change under it."""
        for word in list(jobs.MODES) + list(travel.ROLES) + list(decree.OUTCOMES):
            self.assertIsNone(
                re.search(r"\b%s\b" % re.escape(word), SECTION.lower()), word)


class TheHonestyMechanisms(unittest.TestCase):

    def test_picking_a_mode_prints_the_modules_own_sentence(self):
        """Selecting an unwired mode must SAY that it stands the quest drive
        down. The sentence is jobs.describe, riding on the chip."""
        show = VIEW[VIEW.index("function dcrShowJob"):]
        show = show[:show.index("function dcrShowRole")]
        self.assertIn("dcrJobSays.textContent = c ? c.says", show)

    def test_an_unwired_mode_is_drawn_as_a_warning_and_not_a_caption(self):
        show = VIEW[VIEW.index("function dcrShowJob"):]
        show = show[:show.index("function dcrShowRole")]
        self.assertIn('dcrJobSays.classList.toggle("warn", !!c && !c.wired);', show)
        self.assertIn("var(--warn-bg)", rule(".dcrsays.warn"))
        self.assertIn("color:var(--warn-text)", rule(".dcrsays.warn"))

    def test_the_dot_never_carries_the_state_alone(self):
        """A dot is not readable. The chip's title says the same thing in the
        module's words, for anybody who cannot use the colour."""
        build = VIEW[VIEW.index("function dcrBuildChips"):]
        self.assertIn("b.title = c.says;", build)

    def test_delivered_is_not_drawn_in_the_success_colour(self):
        """The tone classes are all styled, and the one `delivered` carries is
        the amber rule and the caution text, never the green."""
        self.assertIn("border-left-color:var(--amber)", rule(".dcrout.unverified"))
        self.assertIn("color:var(--caution-text)", rule(".dcrword.unverified"))
        self.assertIn("border-left-color:var(--green)", rule(".dcrout.verified"))
        self.assertIn("color:var(--accent-text)", rule(".dcrword.verified"))
        self.assertNotIn("green", rule(".dcrword.unverified"))

    def test_every_tone_the_module_can_emit_is_drawn(self):
        """A tone with no rule renders as the default hairline, which is the
        quietest thing on the card - and `delivered` reaching it would be the
        original bug wearing a stylesheet."""
        tones = {read.tone for read in decree.OUTCOMES.values()} | {decree.UNSEEN}
        for tone in tones:
            self.assertIn("color:var(--", rule(".dcrword." + tone), tone)

    def test_the_row_id_and_the_evidence_are_both_drawn(self):
        draw = VIEW[VIEW.index("function dcrOutcome"):]
        draw = draw[:draw.index("function renderDecree")]
        self.assertIn('"row " + o.id', draw)
        self.assertIn("o.evidence", draw)
        self.assertIn("o.means", draw)


class ControlsThatCannotReachTheWorld(unittest.TestCase):
    """A button that silently does nothing is the failure this epic is named
    after. Every card writes now (infra#3345), so the rule turns into its
    other half: nothing is drawn sendable that the payload has not said is
    sendable, and every card still says what it does to the world."""

    def test_every_send_control_starts_disabled_in_the_markup(self):
        """Disabled until a payload says otherwise: a button that is live
        before the first poll is a button pressed against a console that has
        not read the world yet."""
        for control in ("dcrcampup", "dcrcampdown", "dcrjobsend",
                        "dcrcampsend", "dcrcampreset", "dcrtravelsend",
                        "dcrtravelstop", "dcrsend"):
            button = SECTION[SECTION.index('id="' + control + '"'):]
            self.assertIn("disabled", button[:button.index(">")], control)

    def test_the_campaign_steppers_only_draft_and_never_write(self):
        """A thumb resting on `+` must not walk the live campaign upwards one
        write at a time. The steppers move a number on the page; the send is
        the only control that reaches the column."""
        # The whole handler, pinned as a literal rather than searched for an
        # absent word: "no dcrOrder in the next N characters" passes for a
        # window that stopped one character early.
        self.assertIn("dcrCampUp.onclick = () => { dcr.wanted += 1; dcrShowCamp(); };",
                      VIEW)
        self.assertIn("dcrCampDown.onclick = () => { dcr.wanted -= 1; dcrShowCamp(); };",
                      VIEW)

    def test_the_campaign_bounds_are_the_payloads_and_not_this_files(self):
        """`floor` is the value that stops a campaign outright and `ceiling`
        is the column's own. A page holding either would be a second copy of a
        fact the database decides."""
        show = VIEW[VIEW.index("function dcrShowCamp"):]
        show = show[:show.index("dcrCampUp.onclick")]
        self.assertIn("dcr.wanted >= p.campaign.ceiling", show)
        self.assertIn("dcr.wanted <= p.campaign.floor", show)
        self.assertNotIn(str(decree.CAMPAIGN_CEILING), PAGE)

    def test_the_drafted_number_is_not_rewritten_by_the_poll(self):
        """Seeded once from the world, then owned by the page. A poll that
        reset the counter every ten seconds would change the subject under a
        reader about to press send."""
        render = VIEW[VIEW.index("function renderDecree"):]
        self.assertIn("if (dcr.wanted === null) dcr.wanted = p.campaign.wanted;",
                      render)
        self.assertNotIn("dcrCampNum.textContent = String(p.campaign.wanted);",
                         render)

    def test_they_are_exactly_44px(self):
        self.assertIn("width:44px", rule(".dcrstepbtn"))
        self.assertIn("height:44px", rule(".dcrstepbtn"))

    def test_an_unwired_mode_refuses_the_send_and_prints_the_modules_reason(self):
        """The chip stays pressable so the stand-down warning can be read; it
        is the SEND that is refused. `sendable` is the payload's word - this
        file never compares a mode against a list of the wired ones."""
        show = VIEW[VIEW.index("function dcrShowJob"):]
        show = show[:show.index("dcrJobSend.onclick")]
        self.assertIn("dcrJobSend.disabled = dcr.busy || !(c && c.sendable);", show)
        build = VIEW[VIEW.index("function dcrBuildChips"):]
        build = build[:build.index("async function dcrOrder")]
        self.assertIn(
            "dcrJobNote.textContent = c.sendable ? \"\" : c.why_not;", build)
        for mode in decree.unwired_modes():
            self.assertNotIn('"%s"' % mode, VIEW, mode)

    def test_the_render_pass_never_writes_a_note_it_would_wipe(self):
        """The note under each card carries two different answers - why an
        order cannot go, and what became of one that did - written by the pick
        and by the send. A render that wrote either would blank the result the
        moment the poll that follows a send came back, which is a console
        reporting nothing about a write that happened."""
        render = VIEW[VIEW.index("function renderDecree"):]
        show = VIEW[VIEW.index("function dcrShowJob"):VIEW.index("dcrJobSend.onclick")]
        for note in ("dcrJobNote", "dcrCampNote", "dcrTravelNote"):
            self.assertNotIn(note + ".textContent", render, note)
            self.assertNotIn(note + ".textContent", show, note)

    def test_a_card_says_what_it_does_to_the_world_either_way(self):
        refusal = VIEW[VIEW.index("function dcrRefusal"):]
        refusal = refusal[:refusal.index("function dcrBuildChips")]
        self.assertIn('if (sec.can_send) { node.appendChild(el("div", "dcrev", sec.does)); return; }',
                      refusal)
        self.assertIn("sec.why_not", refusal)
        self.assertIn("sec.instead", refusal)

    def test_an_unreachable_target_is_disabled_and_carries_its_reason(self):
        chip = VIEW[VIEW.index("function dcrChip"):]
        chip = chip[:chip.index("function dcrPress")]
        self.assertIn("if (why) { b.disabled = true; b.title = why; }", chip)
        self.assertIn("else b.onclick = onPick;", chip)


class TheOnlyThingItSends(unittest.TestCase):

    def test_the_decree_goes_down_the_chat_path_that_already_existed(self):
        """Not a second endpoint and not a second grammar. The character
        panel's chat box has posted here since infra#2604."""
        self.assertIn('fetch(u("/api/chat")', VIEW)

    def test_there_are_exactly_two_write_paths_and_no_more(self):
        """The chat path for the will, and one decree path for the other
        three. A third would be a second grammar for the same table."""
        self.assertEqual(VIEW.count('method: "POST"'), 2)
        self.assertEqual(VIEW.count('fetch(u("/api/decree"), {'), 1)

    def test_one_post_per_character_and_never_a_fan_out_endpoint(self):
        speak = VIEW[VIEW.index("async function dcrSpeak"):]
        speak = speak[:speak.index("dcrSend.onclick")]
        self.assertIn("for (const name of names)", speak)
        self.assertIn("JSON.stringify({ name: name, text: text })", speak)

    def test_a_logged_out_member_is_reported_and_not_dropped(self):
        """/api/chat composes `say` for both cases, so a member who is not in
        the world is reported in the server's own words."""
        speak = VIEW[VIEW.index("async function dcrSpeak"):]
        speak = speak[:speak.index("dcrSend.onclick")]
        self.assertIn("said.textContent = a.say;", speak)

    def test_a_queued_row_is_called_queued(self):
        """A row on the queue has not been handed over, and a handed-over row
        has not been applied. The word on the line is the weakest of the
        three on purpose."""
        speak = VIEW[VIEW.index("async function dcrSpeak"):]
        speak = speak[:speak.index("dcrSend.onclick")]
        self.assertIn('"queued command row " + a.command_id', speak)

    def test_the_row_id_comes_back_from_the_endpoint(self):
        """Without it the console could say an order was sent and never say
        what became of it."""
        self.assertIn('"command_id": row_id,', SERVER)
        self.assertIn("row_id = None", SERVER)

    def test_the_send_is_disabled_while_it_is_speaking(self):
        speak = VIEW[VIEW.index("async function dcrSpeak"):]
        speak = speak[:speak.index("dcrSend.onclick")]
        self.assertIn("dcr.busy = true;", speak)
        self.assertIn("dcrSend.disabled = true;", speak)

    def test_what_became_of_it_is_read_off_the_queue(self):
        """Not taken from the send's own reply. The queue is the only thing
        that knows, and it knows later."""
        speak = VIEW[VIEW.index("async function dcrSpeak"):]
        speak = speak[:speak.index("dcrSend.onclick")]
        self.assertIn("pollDecree();", speak)


class TheEndpointIsAnAdapter(unittest.TestCase):
    """THE ONE RULE at the other end: the HTTP adapter fetches rows and does
    nothing else."""

    def test_it_is_in_the_route_table(self):
        table = SERVER[SERVER.index("GET_ROUTES = {"):]
        self.assertIn('"/api/decree": _decree,', table[:table.index("}")])

    def test_the_write_endpoint_is_in_the_post_table(self):
        post = SERVER[SERVER.index("POST_ROUTES = {"):]
        self.assertIn('"/api/decree": _decree_post,', post[:post.index("}")])

    def test_the_handler_only_fetches_and_serves(self):
        handler = SERVER[SERVER.index("    def _decree(self"):]
        handler = handler[:handler.index("    def _watch_state(self")]
        self.assertIn("decree.build_console(**_fetch_decree())", handler)
        self.assertNotIn("query.get", handler)

    def test_a_failed_query_is_a_503_and_never_a_blank_console(self):
        handler = SERVER[SERVER.index("    def _decree(self"):]
        handler = handler[:handler.index("    def _watch_state(self")]
        self.assertIn("self._send(503", handler)
        self.assertIn("log.exception", handler)

    def test_a_degraded_schema_thins_the_console_rather_than_breaking_it(self):
        """A realm whose worldserver predates a table must get an empty list,
        not a 503 on every poll."""
        fetch = SERVER[SERVER.index("def _fetch_decree"):]
        fetch = fetch[:fetch.index("class Handler")]
        self.assertIn("_guarded(", fetch)

    def test_the_orders_it_reads_back_are_its_own(self):
        """Scoped by `source`. A console showing the bridge's traffic would
        report somebody else's orders as if the operator had given them."""
        fetch = SERVER[SERVER.index("def _fetch_decree"):]
        fetch = fetch[:fetch.index("class Handler")]
        self.assertIn("WHERE source = %s", fetch)
        self.assertIn("WEB_SOURCE", fetch)
        self.assertIn("decree.OUTCOME_ROWS", fetch)

    def test_the_source_is_one_constant_and_not_two_literals(self):
        """A second spelling would hand the console an empty page while the
        orders themselves went through perfectly."""
        self.assertIn('WEB_SOURCE = "web:overseer"', SERVER)
        self.assertEqual(SERVER.count('"web:overseer"'), 1)

    def test_the_page_keeps_what_is_drawn_when_the_poll_fails(self):
        """A blanked console reads as "no job is set, nobody is aimed
        anywhere, nothing is stopping them", which is the opposite of every
        fact on it."""
        poll = VIEW[VIEW.index("async function pollDecree"):]
        catch = poll[poll.index("} catch"):]
        self.assertIn('dcrHead.classList.add("stale");', catch)
        self.assertNotIn("replaceChildren", catch)


class TheDesignTokens(unittest.TestCase):

    def test_no_pigment_is_ever_set_as_text(self):
        """--amber as text on paper is 2.5:1 and --green is 3.0:1. Both are
        fine as a 10px dot and neither is legible as a sentence, which is what
        the text roles exist for.

        THE SIGNAL COLOURS ONLY. --ink and --pale-green are the inverted
        surface pair this page already uses for an active chip (see .rn-pill
        and the wall's toolbar), and pale-green ON ink is the high-contrast
        half of it rather than a pigment used as body text.

        The `color` property only, too: border-color and background still take
        a pigment, because a 4px rule and a 10px dot are shapes."""
        for pigment in ("--rust", "--amber", "--green", "--vermilion",
                        "--deep-green", "--cyan"):
            hit = re.search(r"(?<![-\w])color:var\(%s\)" % pigment, CSS)
            self.assertIsNone(hit, pigment)

    def test_the_text_roles_it_uses_are_defined_in_all_three_theme_states(self):
        """A token defined only inside the dark media query is invisible to a
        reader whose system preference does not match."""
        style = PAGE[PAGE.index("<style>"):PAGE.index("</style>")]
        for token in ("--caution-text", "--accent-text", "--warn-text"):
            self.assertGreaterEqual(style.count(token + ":"), 3, token)

    def test_the_chips_are_pills_and_ink_when_active(self):
        self.assertIn("border-radius:999px", rule(".dcrchip"))
        self.assertIn("background:var(--ink)",
                      rule('.dcrchip[aria-pressed="true"]'))

    def test_every_hit_target_is_at_least_44px(self):
        for selector in (".dcrchip", ".dcrstepbtn", "#dcrsend"):
            self.assertTrue(
                re.search(r"(min-)?height:44px", rule(selector)), selector)

    def test_numbers_labels_and_status_words_are_set_in_the_mono(self):
        """Every number, label and machine word. Mono is what this whole page
        sets DATA in, and a status word is data."""
        for selector in (".dcrnum", ".dcrword", ".dcrid", ".dcrlabel",
                         ".dcrchip", ".dcrnow", ".dcrtag", ".dcrnumlabel",
                         "#dcrhead"):
            self.assertIn("font-family:var(--mono)", rule(selector), selector)

    def test_there_is_one_breakpoint_and_it_is_640px(self):
        self.assertEqual(CSS.count("@media"), 1)
        self.assertIn("@media (min-width:640px)", CSS)

    def test_the_grid_is_on_a_wrapper_and_not_on_the_toggled_section(self):
        """showView sets display inline on the section, and an inline style
        beats a media query - so a grid declared on #decree would silently
        never apply."""
        block = CSS[CSS.index("@media (min-width:640px)"):]
        self.assertIn("#dcrgrid { display:grid", block)
        self.assertNotIn("#decree {", block)

    def test_the_section_is_hidden_until_the_router_shows_it(self):
        self.assertIn("#decree { display:none;", CSS)


class TheHouseRules(unittest.TestCase):

    def test_no_em_dashes(self):
        for name in ("index.html", "tests/test_decree_tab.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)

    def test_no_framework_arrived_with_the_view(self):
        """No bundler, no component library, no CSS kit. The whole frontend is
        this one file and it stays that way."""
        self.assertNotIn("<script src=", PAGE)
        self.assertNotIn("import ", VIEW)
        self.assertNotIn("require(", VIEW)

    def test_the_view_reaches_nothing_off_this_server(self):
        """This page is tailnet-only and must not gain a new way to look
        broken. Every URL it fetches goes through u(), which is what makes a
        realm mounted under a path prefix ask its own server rather than
        production's (basepath.py)."""
        self.assertNotIn("http", VIEW)
        for call in re.findall(r"fetch\((.{0,12})", VIEW):
            self.assertTrue(call.startswith("u("), call)


if __name__ == "__main__":
    unittest.main()
