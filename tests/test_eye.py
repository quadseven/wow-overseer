"""The Eye: eye.py's judgement, and the page's contract.

THE THING THIS VIEW IS FOR IS THE THING IT REFUSES TO DRAW. A server rollup
over a realm with one family on it is five real numbers and a dozen invented
ones, and the invented ones are what a reader remembers. So every rung says
whether it is real, and a rung that is not says what would turn it on rather
than drawing an empty chart of itself.

Most of these assertions are therefore about ABSENCE: no guild ladder, no
population curve, no tier reported ON that was not counted. A view whose
value is its honesty needs its honesty pinned, or the first person to make it
look busier will win.

Tickets: infra#2597.
"""
import pathlib
import unittest
from datetime import datetime

import eye

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Eye (infra#2597)"
CSS_BANNER = "/* --- the Eye (infra#2597)"
NEXT = "// --- the Armory tab (infra#3096, infra#3139)"
NEXT_CSS = "/* --- the Armory tab (infra#3096, infra#3139)"

T0 = datetime(2026, 9, 3, 20, 0, 0)

FAMILY = [{"name": n} for n in ("Grug", "Ugga", "Grog", "Bork", "Og")]


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same helper test_chronicle_tab.py and test_council_view.py carry, and
    duplicated for the same reason: these files slice the page apart by
    banner, and a helper imported across them would tie one view's window to
    another's. A guard a COMMENT can trip is a guard that gets weakened until
    it passes, and this file's banner names every word its guards forbid.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


def snapshot(name, bot=1, leader=""):
    return {"name": name, "is_bot": bot, "group_leader": leader}


def tiers(payload):
    return {row["tier"]: row for row in payload["tiers"]}


class ATierThatIsNotRealSaysWhatWouldMakeItReal(unittest.TestCase):

    def test_the_guild_tier_is_off_and_names_its_condition(self):
        """THE RUNG THE WHOLE VIEW IS SHAPED AROUND. There is no guild. An
        empty guild roster with an axis on it is a picture of a server that
        does not exist; the number of signatures a charter needs is a fact."""
        rung = eye.guild_tier(0, 5)
        self.assertEqual(eye.OFF, rung["state"])
        self.assertEqual("0", rung["value"])
        self.assertIn(str(eye.CHARTER_SIGNATURES), rung["switch"])

    def test_a_realm_too_small_to_sign_a_charter_says_how_short_it_is(self):
        rung = eye.guild_tier(0, 5)
        self.assertIn("5 short", rung["switch"])

    def test_a_realm_big_enough_says_nobody_has_done_it_instead(self):
        """Two different absences. "Nobody can" and "nobody has" are not the
        same finding and must not read the same."""
        rung = eye.guild_tier(0, eye.CHARTER_SIGNATURES)
        self.assertNotIn("short", rung["switch"])
        self.assertIn("nobody has taken one round", rung["switch"])

    def test_a_guild_that_exists_turns_the_tier_on_by_itself(self):
        """No change to this module or to the page. The count is a real read."""
        rung = eye.guild_tier(2, 40)
        self.assertEqual(eye.ON, rung["state"])
        self.assertEqual("", rung["switch"])

    def test_a_tier_that_is_on_never_carries_a_switch(self):
        """A switch on a working tier reads as a suggestion to change
        something that already works."""
        rung = eye.tier("X", eye.ON, "1", "fine", "do a thing")
        self.assertEqual("", rung["switch"])

    def test_every_off_or_partial_tier_in_a_full_build_has_a_switch(self):
        payload = eye.build_eye([], FAMILY, [{"characters": 5}],
                                [{"guilds": 0}], now=T0)
        for rung in payload["tiers"]:
            if rung["state"] != eye.ON:
                self.assertTrue(rung["switch"], rung["tier"])


class TheRealmTierRefusesToCallOneFamilyAPopulation(unittest.TestCase):

    def test_an_empty_world_is_a_real_state_and_not_an_outage(self):
        """The module sweeps logged-out rows, so an empty world drains the
        table. Saying so is honest; crying outage over an empty tavern is
        the bug the map banner already had."""
        rung = eye.realm_tier(0, 0)
        self.assertEqual(eye.OFF, rung["state"])
        self.assertIn("Nobody walks the world", rung["headline"])

    def test_one_family_logged_in_is_partial_and_says_why(self):
        rung = eye.realm_tier(5, 0)
        self.assertEqual(eye.PARTIAL, rung["state"])
        self.assertIn("population IS the family", rung["switch"])

    def test_a_crowd_is_a_population(self):
        rung = eye.realm_tier(eye.CROWD, 1)
        self.assertEqual(eye.ON, rung["state"])
        self.assertEqual("", rung["switch"])

    def test_the_machine_played_characters_are_counted_as_such(self):
        self.assertIn("4 of them played by the machine",
                      eye.realm_tier(5, 1)["headline"])


class ThePartyTierIsReadOffTheLiveWorld(unittest.TestCase):

    def test_one_leader_is_one_party(self):
        rows = [snapshot("Grug", leader="Grug"), snapshot("Bork", leader="Grug")]
        rung = eye.party_tier(rows, {"Grug", "Bork"})
        self.assertEqual(eye.ON, rung["state"])
        self.assertIn("Grug", rung["headline"])

    def test_two_leaders_is_a_split_family_and_not_a_party(self):
        """Five characters behind two leaders are not one party, and calling
        that a party would be the invention this view exists to refuse."""
        rows = [snapshot("Grug", leader="Grug"), snapshot("Bork", leader="Bork")]
        rung = eye.party_tier(rows, {"Grug", "Bork"})
        self.assertEqual(eye.PARTIAL, rung["state"])
        self.assertIn("split", rung["headline"])

    def test_nobody_in_the_world_is_no_party(self):
        rung = eye.party_tier([], {"Grug"})
        self.assertEqual(eye.OFF, rung["state"])

    def test_a_stranger_leading_a_stranger_is_not_the_familys_party(self):
        """The tier reports the FAMILY. Another player's group on the same
        realm is not evidence about this one."""
        rows = [snapshot("Someone", leader="Someone")]
        self.assertEqual(eye.OFF, eye.party_tier(rows, {"Grug"})["state"])


class TheFamilyTierDoesNotBlinkOutAtBedtime(unittest.TestCase):

    def test_the_family_is_read_from_saved_rows_and_not_from_the_snapshot(self):
        """The five exist whether or not they are logged in. A FAMILY tier
        driven by the live snapshot would report "no family is in the world"
        every night, which is a claim about the wrong thing."""
        payload = eye.build_eye([], FAMILY, [{"characters": 5}],
                                [{"guilds": 0}], now=T0)
        self.assertEqual(eye.ON, tiers(payload)[eye.FAMILY]["state"])
        self.assertEqual(eye.OFF, tiers(payload)[eye.REALM]["state"])

    def test_the_family_is_named_rather_than_counted(self):
        rung = eye.family_tier(FAMILY)
        for name in ("Grug", "Ugga", "Grog", "Bork", "Og"):
            self.assertIn(name, rung["headline"])

    def test_no_saved_family_is_reported_and_not_hidden(self):
        self.assertEqual(eye.OFF, eye.family_tier([])["state"])
        self.assertEqual(eye.OFF, eye.character_tier([], 0)["state"])

    def test_a_family_that_is_the_whole_realm_says_so(self):
        self.assertIn("they are the whole realm",
                      eye.character_tier(FAMILY, 5)["headline"])

    def test_a_realm_with_other_characters_gives_the_bigger_number(self):
        self.assertIn("of 40", eye.character_tier(FAMILY, 40)["headline"])


class TheRollupAddsUpToOneHonestSentence(unittest.TestCase):

    def test_it_says_how_much_of_the_ladder_is_real(self):
        self.assertIn("2 of 5", eye.honest_line(2, 5))
        self.assertIn("names what would turn it on", eye.honest_line(2, 5))

    def test_it_does_not_congratulate_anybody(self):
        """A rollup that says "3 of 5 systems nominal" over a realm with one
        family on it is the dashboard voice this view refuses."""
        for banned in ("nominal", "healthy", "all good", "%"):
            self.assertNotIn(banned, eye.honest_line(3, 5))

    def test_a_complete_ladder_says_nothing_is_a_placeholder(self):
        self.assertIn("Nothing on this page is a placeholder",
                      eye.honest_line(5, 5))

    def test_the_strip_counts_and_never_estimates(self):
        payload = eye.build_eye([snapshot("Grug", bot=1, leader="Grug")],
                                FAMILY, [{"characters": 5}], [{"guilds": 0}],
                                now=T0)
        strip = {t["label"]: t["value"] for t in payload["strip"]}
        self.assertEqual("5", strip["CHARACTERS"])
        self.assertEqual("1", strip["IN WORLD"])
        self.assertEqual("1", strip["FAMILIES"])
        self.assertEqual("0", strip["GUILDS"])
        self.assertEqual("3/5", strip["TIERS ON"])


class ADegradedSchemaThinsTheViewRatherThanBreakingIt(unittest.TestCase):

    def test_every_input_may_be_empty(self):
        """A realm whose schema predates a table hands in [] for it, exactly
        as build_agenda's inputs may."""
        payload = eye.build_eye([], [], [], [], now=T0)
        self.assertEqual(5, len(payload["tiers"]))
        self.assertTrue(payload["honest"])

    def test_a_count_row_with_a_null_in_it_is_zero_and_not_a_crash(self):
        self.assertEqual(0, eye._count([{"guilds": None}], "guilds"))
        self.assertEqual(0, eye._count([], "guilds"))

    def test_a_tier_is_never_reported_on_without_having_been_counted(self):
        """The one failure that would make this view worse than no view."""
        payload = eye.build_eye([], [], [], [], now=T0)
        for rung in payload["tiers"]:
            self.assertNotEqual(eye.ON, rung["state"], rung["tier"])


class ThePageOnlyDraws(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.page.index(BANNER)
        cls.tab = cls.page[start:cls.page.index(NEXT, start)]
        cls.code = code(cls.tab)
        css = cls.page.index(CSS_BANNER)
        cls.css = cls.page[css:cls.page.index(NEXT_CSS, css)]

    def test_the_view_exists_and_is_an_address(self):
        self.assertIn('<section id="eye">', self.page)
        self.assertIn('eb.textContent = "The Eye";', self.page)
        self.assertIn("eb.dataset.view = EYE_VIEW;", self.page)
        listed = self.page[self.page.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        self.assertIn("EYE_VIEW", listed)

    def test_show_view_hides_it_with_the_others(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('eyesection.style.display = isEye ? "block" : "none";',
                      show)
        branch = show[show.index("if (isEye) {"):]
        branch = branch[:branch.index("return;")]
        for line in ("closePanel();", "stopBroadcasts();", "pollEye();"):
            self.assertIn(line, branch)

    def test_the_switch_sentence_is_drawn_and_never_written_here(self):
        """What turns a tier on is the most useful sentence on an off rung and
        the most judgement-shaped one on the view."""
        self.assertIn("t.switch", self.code)
        for invented in ("charter", "signatures", "logged in and saved"):
            self.assertNotIn(invented, self.code, invented)

    def test_the_state_word_and_the_headline_come_from_the_payload(self):
        self.assertIn("t.state", self.code)
        self.assertIn("t.headline", self.code)
        self.assertIn("p.honest", self.code)

    def test_the_page_invents_no_tier_of_its_own(self):
        """Five rungs, named by the module. A sixth added here would be a
        claim about the realm made by a stylesheet's neighbour."""
        for name in ("CHARACTER", "FAMILY", "GUILD", "REALM", "PARTY"):
            self.assertNotIn('"%s"' % name, self.code, name)

    def test_it_draws_no_chart_of_anything(self):
        """The refusal, stated as a test. A canvas, an svg or a bar sized from
        a number is the exact shape this view exists not to be."""
        for chart in ("<canvas", "createElement(\"canvas\")", "<svg",
                      "createElementNS", "width: \" +", "chart"):
            self.assertNotIn(chart, self.code, chart)

    def test_the_hue_is_the_modules_choice_and_the_page_only_names_a_class(self):
        """"Off is the alarming one" is a judgement about the state, not about
        the stylesheet. The page knows what vermilion looks like on the ground
        it is painting, and it has two grounds to know that on."""
        self.assertIn('"ey-state h-" + t.hue', self.code)
        self.assertNotIn("h-vermilion", self.code)

    def test_every_state_the_module_can_emit_has_a_hue_with_a_rule(self):
        """A state with no rule is text in the ground colour, which on a card
        is invisible."""
        for state in (eye.ON, eye.OFF, eye.PARTIAL):
            self.assertIn(state, eye.STATE_HUES, state)
        for hue in set(eye.STATE_HUES.values()):
            self.assertIn(".h-%s {" % hue, self.page, hue)

    def test_the_tier_name_leads_and_the_count_follows_it(self):
        """Read aloud that is "GUILD 0 OFF", which is a sentence. The other way
        round it is a number looking for a noun, which is what a screen reader
        gets handed."""
        top = self.code[self.code.index('el("div", "ey-top")'):]
        self.assertLess(top.index('"ey-name"'), top.index('"ey-count"'))

    def test_an_off_rung_is_told_apart_without_colour_too(self):
        """A state said only in colour is lost to a screenshot and to a reader
        who cannot tell the two apart. The word is there, and so is a border
        that is not a colour."""
        self.assertIn('"ey-row s-" + t.state.toLowerCase()', self.code)
        self.assertIn("border-style:dashed", self.css)

    def test_nothing_from_the_payload_is_rendered_as_markup(self):
        self.assertNotIn("innerHTML", self.code)
        self.assertNotIn("insertAdjacentHTML", self.code)

    def test_a_failed_poll_keeps_the_ladder(self):
        """A view whose whole job is to say what is NOT real, rendered empty,
        reads as a realm where nothing is real at all."""
        poll = self.code[self.code.index("async function pollEye"):]
        self.assertIn("may be stale", poll)
        self.assertNotIn("replaceChildren", poll)

    def test_the_endpoint_is_wired_and_the_builder_is_pure(self):
        self.assertIn('"/api/eye": _eye,', self.server)
        self.assertIn("eye.build_eye(**_fetch_eye())", self.server)
        self.assertIn('fetch(u("/api/eye"))', self.code)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        handler = self.server[self.server.index("def _eye"):]
        handler = handler[:handler.index("def _wealth")]
        self.assertNotIn("query.get", handler)
        self.assertIn("503", handler)

    def test_the_guild_count_is_a_real_read_and_not_a_constant(self):
        """The Eye reports no guild because the table was counted and had
        nothing in it. A hard-coded zero would keep saying so on the day one
        was made."""
        fetch = self.server[self.server.index("def _fetch_eye"):]
        fetch = fetch[:fetch.index("# --- the current-goal banner")]
        self.assertIn("SELECT COUNT(*) AS guilds FROM guild", fetch)
        self.assertIn('"guild")', fetch)

    def test_the_view_polls_only_while_it_is_open(self):
        self.assertIn("if (view === EYE_VIEW) pollEye();", self.code)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("eye.py", dockerfile)

    def test_the_one_breakpoint_is_the_one_the_handoff_names(self):
        """Mobile-first, a single breakpoint at 640px, and everything else
        auto-fit. Two queries in one view is where a layout starts having
        opinions nobody wrote down."""
        self.assertEqual(1, self.css.count("@media"))
        self.assertIn("@media (min-width:640px)", self.css)

    def test_no_em_dashes(self):
        for name in ("eye.py", "tests/test_eye.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
