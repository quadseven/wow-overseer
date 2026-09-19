"""The Council view: council.py's judgement, and the page's contract.

Two suites in one file on purpose. The load-bearing rule of this view is that
the TRANSCRIPT'S ORDER is decided in Python and copied out by the page, and a
rule like that is only tested by asking both halves in the same breath: the
module produces the order, and the page is forbidden from having an opinion
about it.

WHY THE ORDER MATTERS. bonds.speaking_order exists because alphabetical put
the seven-year-old first every single time and the mother last, which is a
family nobody in it would recognise. That fact is already used when the bridge
writes a council's lines; this view uses the same fact rather than a second
opinion about it.

Tickets: infra#2597.
"""
import pathlib
import unittest
from datetime import datetime, timedelta

import bonds
import council

HERE = pathlib.Path(__file__).resolve().parent.parent
BANNER = "// --- the Council (infra#2597)"
CSS_BANNER = "/* --- the Council (infra#2597)"
NEXT = "// --- the Eye (infra#2597)"
NEXT_CSS = "/* --- the Eye (infra#2597)"

T0 = datetime(2026, 9, 3, 20, 0, 0)


def code(block: str) -> str:
    """`block` with its whole-line comments dropped.

    The same three lines test_chronicle_tab.py carries, and duplicated for the
    same reason the two views duplicate their strip renderer: these files slice
    the page apart by banner, and a helper imported across them would tie one
    view's window to another's. Both copies exist because a guard failed on a
    COMMENT the first time it ran - this file's banner says the word "sort" in
    the sentence forbidding it - and a guard a comment can trip is a guard that
    gets weakened until it passes.
    """
    return "\n".join(line for line in block.splitlines()
                     if not line.lstrip().startswith("//"))


def said(who, text, minutes=0):
    return {"character_name": who, "text": text,
            "created_at": T0 + timedelta(minutes=minutes)}


def goal(who, kind="level", target=12, status="active", minutes=0, quest_id=0):
    return {"character_name": who, "kind": kind, "target": target,
            "status": status, "quest_id": quest_id, "skill_name": "",
            "created_at": T0 + timedelta(minutes=minutes)}


def run_card(map_id, loot=()):
    return {"kind": "run", "map_id": map_id,
            "loot": [{"name": n, "quality": q} for n, q in loot]}


def levels(**who):
    return [{"name": name, "level": level} for name, level in who.items()]


class TheTranscriptIsInTheFamilysOrder(unittest.TestCase):

    def test_the_oldest_speaks_first_and_the_youngest_last(self):
        """THE ONE ASSERTION THIS VIEW EXISTS FOR. Grug is the father, Bork is
        seven. Any order that starts with Bork is wrong however sensible the
        rule that produced it."""
        rows = [said("Bork", "b"), said("Ugga", "u"), said("Grug", "g"),
                said("Og", "o"), said("Grog", "r")]
        who = [line["who"] for line in council.transcript(rows)]
        self.assertEqual(["Grug", "Ugga", "Og", "Grog", "Bork"], who)

    def test_alphabetical_would_be_a_different_answer(self):
        """The guard is only worth having if the wrong answer is reachable.
        Alphabetical is what overhear.audience returns and what this would be
        if anybody sorted the names on their way to the page."""
        rows = [said("Bork", "b"), said("Ugga", "u"), said("Grug", "g"),
                said("Og", "o"), said("Grog", "r")]
        who = [line["who"] for line in council.transcript(rows)]
        self.assertNotEqual(sorted(who), who)
        self.assertEqual("Bork", sorted(who)[0])

    def test_it_is_the_same_order_bonds_already_publishes(self):
        """Used twice, not decided twice. A local copy of this order could
        disagree with the one the bridge writes the lines in."""
        rows = [said(name, "x") for name in bonds.FAMILY]
        who = [line["who"] for line in council.transcript(rows)]
        self.assertEqual(bonds.speaking_order(list(bonds.FAMILY)), who)

    def test_a_speaker_who_says_two_things_keeps_them_together_in_time(self):
        """Splitting a speaker's lines by clock would interleave five
        characters into something no reader could follow."""
        rows = [said("Grug", "second", 2), said("Grug", "first", 1),
                said("Bork", "mine", 0)]
        lines = council.transcript(rows)
        self.assertEqual(["Grug", "Grug", "Bork"], [x["who"] for x in lines])
        self.assertEqual(["first", "second"], [x["text"] for x in lines[:2]])

    def test_only_the_last_sitting_is_shown(self):
        """A council is a scene. Two of them run together read as one
        conversation in which everybody changed their mind."""
        old = [said("Grug", "last week", -600), said("Ugga", "last week", -599)]
        now = [said("Grug", "tonight", 0), said("Ugga", "tonight", 1)]
        lines = council.transcript(old + now)
        self.assertEqual(["tonight", "tonight"], [x["text"] for x in lines])

    def test_a_long_pause_inside_one_council_does_not_split_it(self):
        """The bridge voices every line through a language model before it
        writes it, so a sitting takes as long as the model does."""
        rows = [said("Grug", "a", 0), said("Ugga", "b", 5),
                said("Bork", "c", 10)]
        self.assertEqual(3, len(council.transcript(rows)))

    def test_anyone_outside_the_family_is_not_in_the_council(self):
        """A council is a conversation between people who live together, and
        this module has no opinion about where a stranger stands in it."""
        rows = [said("Grug", "g"), said("Stranger", "hello")]
        self.assertEqual(["Grug"], [x["who"] for x in council.transcript(rows)])

    def test_no_rows_is_a_quiet_week_and_not_a_crash(self):
        self.assertEqual([], council.transcript([]))
        self.assertIn("quiet week", council.quiet_line([]))
        self.assertEqual("", council.quiet_line([{"who": "Grug"}]))


class EverySpeakerKeepsTheirOwnColour(unittest.TestCase):

    def test_a_hue_is_a_token_name_and_never_a_colour(self):
        """index.html owns what a colour looks like, and it owns it twice -
        once per theme."""
        for name in bonds.FAMILY:
            self.assertIn(council.speaker_hue(name), council.SPEAKER_HUES)

    def test_a_speaker_who_sat_one_out_does_not_shuffle_the_others(self):
        """Keyed on the family's own order, not on who turned up."""
        first = council.speaker_hue("Bork")
        self.assertEqual(first, council.speaker_hue("Bork"))
        self.assertNotEqual(council.speaker_hue("Grug"),
                            council.speaker_hue("Bork"))

    def test_a_stranger_gets_the_quiet_role_and_not_a_rank(self):
        self.assertEqual(council.OUTSIDER_HUE, council.speaker_hue("Stranger"))


class TheConsensusIsReadOffWhatSurvivedTheCouncil(unittest.TestCase):

    def test_the_active_goal_is_the_decision(self):
        lines = council.transcript([said("Grug", "g"), said("Ugga", "u")])
        agreed = council.consensus([goal("Bork", "level", 12)], lines)
        self.assertIn("Bork", agreed["decision"])
        self.assertIn("12", agreed["decision"])

    def test_a_quest_decision_is_named_when_the_world_can_name_it(self):
        agreed = council.consensus(
            [goal("Grog", "quest", 0, quest_id=44)], [],
            quest_titles={44: "The Defias Brotherhood"})
        self.assertIn("The Defias Brotherhood", agreed["decision"])

    def test_a_quest_with_no_title_says_so_rather_than_naming_a_number(self):
        agreed = council.consensus([goal("Grog", "quest", 0, quest_id=44)], [])
        self.assertNotIn("44", agreed["decision"])

    def test_the_newest_active_goal_wins(self):
        rows = [goal("Bork", "level", 12, minutes=0),
                goal("Grog", "level", 20, minutes=30)]
        self.assertIn("Grog", council.consensus(rows, [])["decision"])

    def test_a_cancelled_goal_is_not_a_decision(self):
        self.assertIsNone(council.consensus([goal("Bork", status="cancelled")], []))

    def test_nothing_active_is_said_out_loud_rather_than_left_blank(self):
        """A council that agrees on a quiet day has still decided something.
        An empty block with no sentence reads as a broken page."""
        self.assertIsNone(council.consensus([], []))
        self.assertIn("not written as a goal", council.undecided_line(None))
        self.assertEqual("", council.undecided_line({"decision": "x"}))

    def test_the_vote_counts_who_spoke_and_says_that_is_what_it_is(self):
        """THE TALLY IS NOT WRITTEN DOWN ANYWHERE. hold() scores the proposals
        and keeps only the winner, so a count of ayes here would be a number
        invented about a vote nothing recorded. Who turned up to argue is a
        fact this module does have."""
        lines = council.transcript([said("Grug", "g"), said("Ugga", "u")])
        agreed = council.consensus([goal("Bork")], lines)
        self.assertEqual(2, agreed["spoke"])
        self.assertEqual(len(bonds.FAMILY), agreed["family"])
        self.assertIn("SPOKE", agreed["vote"])


class TheGateIsAWordAndTheVerdictAnswersIt(unittest.TestCase):

    def test_ready_is_a_word_and_so_is_being_short(self):
        self.assertEqual("READY", council.gate_word(0))
        self.assertEqual("READY", council.gate_word(-4))
        self.assertEqual("1 LEVEL SHORT", council.gate_word(1))
        self.assertEqual("4 LEVELS SHORT", council.gate_word(4))

    def test_the_gate_is_asked_of_the_weakest_and_not_of_the_median(self):
        """A party is gated by the member who dies at the door. A median would
        report a family ready while one of them was four levels off it."""
        rows = levels(Grug=20, Ugga=20, Grog=20, Og=20, Bork=13)
        places = {p["map_id"]: p for p in council.prospects(rows, [])}
        # Deadmines wants 17; the median says go, the little one says not yet.
        self.assertEqual("4 LEVELS SHORT", places[36]["gate"])

    def test_the_gate_carries_its_own_hue_name(self):
        """"Green means they can go" is a judgement about a gate. The page's
        job is to know what green looks like on the ground it is painting,
        and it has two grounds to know that on."""
        places = {p["map_id"]: p for p in
                  council.prospects(levels(Grug=17, Bork=17), [])}
        self.assertEqual(council.READY_HUE, places[36]["hue"])
        short = {p["map_id"]: p for p in
                 council.prospects(levels(Grug=13, Bork=13), [])}
        self.assertEqual(council.SHORT_HUE, short[36]["hue"])

    def test_a_gate_always_gets_an_answer(self):
        """A gate on its own reads as a rule, and this family is not run by
        rules - they went in under-levelled once and came out with the only
        loot this view can report."""
        for short in (-2, 0, 1, 2, 5):
            self.assertTrue(council.verdict(short, False, [], "Bork").strip())

    def test_near_enough_short_is_worth_trying_and_says_who_pays_for_it(self):
        near = council.verdict(council.NEAR_ENOUGH, False, [], "Bork")
        self.assertIn("Bork", near)
        far = council.verdict(council.NEAR_ENOUGH + 1, False, [], "Bork")
        self.assertIn("Bork", far)
        self.assertNotEqual(near, far)


class TheyOnlyKnowWhatTheyHaveSeen(unittest.TestCase):

    def test_drops_come_from_runs_they_actually_did(self):
        """Not from a wiki. What a boss CAN drop is a fact about the game;
        what came out of the runs these five did is a fact about them."""
        cards = [run_card(36, [("Cruel Barb", 3), ("Buzzer Blade", 2)])]
        places = {p["map_id"]: p for p in
                  council.prospects(levels(Grug=20, Bork=20), cards)}
        self.assertIn("Cruel Barb", places[36]["drops"])
        self.assertTrue(places[36]["been"])

    def test_the_better_drop_is_named_first(self):
        cards = [run_card(36, [("a green", 2), ("a blue", 3)])]
        places = {p["map_id"]: p for p in
                  council.prospects(levels(Grug=20), cards)}
        self.assertEqual("a blue", places[36]["drops"][0])

    def test_a_place_nobody_has_been_reports_nothing_rather_than_guessing(self):
        places = {p["map_id"]: p for p in council.prospects(levels(Grug=20), [])}
        self.assertEqual([], places[36]["drops"])
        self.assertFalse(places[36]["been"])

    def test_a_place_they_have_been_is_listed_however_far_past_it_they_are(self):
        """It is the only place they know anything about, and dropping it
        would take the drops with it."""
        cards = [run_card(389, [("something", 2)])]
        far = council.prospects(levels(Grug=60, Bork=60), cards)
        self.assertIn(389, [p["map_id"] for p in far])

    def test_a_place_far_beyond_them_is_not_listed_at_all(self):
        near = [p["map_id"] for p in council.prospects(levels(Grug=10), [])]
        self.assertNotIn(47, near)

    def test_no_levels_at_all_is_no_opinion_rather_than_a_wrong_one(self):
        self.assertEqual([], council.prospects([], []))
        self.assertEqual([], council.prospects([{"name": "Grug", "level": 0}], []))

    def test_every_place_names_itself_from_the_one_table_that_names_dungeons(self):
        """A second copy of the dungeon names here would be a second answer
        able to disagree with achievements.dungeon_name."""
        import achievements
        for map_id in council.PLACES:
            self.assertIn(map_id, achievements.DUNGEONS, map_id)


class TheWholePayloadSurvivesAnEmptyWorld(unittest.TestCase):

    def test_nothing_at_all_still_builds(self):
        """A realm whose schema predates a table hands in [] for it and gets a
        thinner view, never an exception."""
        payload = council.build_council([], [], [], [], now=T0)
        self.assertEqual([], payload["transcript"])
        self.assertIsNone(payload["consensus"])
        self.assertTrue(payload["quiet"])
        self.assertTrue(payload["undecided"])

    def test_a_full_council_carries_every_key_the_page_draws(self):
        payload = council.build_council(
            [said("Grug", "we go"), said("Bork", "i want to go")],
            [goal("Bork", "level", 12)],
            levels(Grug=20, Bork=13),
            [run_card(36, [("Cruel Barb", 3)])],
            now=T0)
        self.assertEqual(["Grug", "Bork"],
                         [x["who"] for x in payload["transcript"]])
        self.assertEqual(["Bork", "Grug"], payload["spoke"])
        self.assertIn("SPOKE", payload["consensus"]["vote"])
        self.assertTrue(payload["prospects"])
        for line in payload["transcript"]:
            self.assertIn(line["hue"], council.SPEAKER_HUES)


class ThePageOnlyDraws(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.page = (HERE / "index.html").read_text(encoding="utf-8")
        cls.server = (HERE / "map_server.py").read_text(encoding="utf-8")
        start = cls.page.index(BANNER)
        cls.tab = cls.page[start:cls.page.index(NEXT, start)]
        css = cls.page.index(CSS_BANNER)
        cls.css = cls.page[css:cls.page.index(NEXT_CSS, css)]
        cls.code = code(cls.tab)

    def test_the_view_exists_and_is_an_address(self):
        self.assertIn('<section id="council">', self.page)
        self.assertIn('cb.textContent = "Council";', self.page)
        self.assertIn("cb.dataset.view = COUNCIL_VIEW;", self.page)
        listed = self.page[self.page.index("const HASH_VIEWS = ["):]
        listed = listed[:listed.index("]")]
        self.assertIn("COUNCIL_VIEW", listed)

    def test_show_view_hides_it_with_the_others(self):
        show = self.page[self.page.index("function showView"):]
        show = show[:show.index("setInterval(pollFamily")]
        self.assertIn('cnsection.style.display = isCouncil ? "block" : "none";',
                      show)
        branch = show[show.index("if (isCouncil) {"):]
        branch = branch[:branch.index("return;")]
        for line in ("closePanel();", "stopBroadcasts();", "pollCouncil();"):
            self.assertIn(line, branch)

    def test_the_page_never_sorts_the_transcript(self):
        """THE GUARD THIS FILE IS FOR. One .sort() here and the order becomes
        the page's opinion, free to drift from the family's own - and the
        wrong answer is the one a reasonable person reaches first, because
        alphabetical looks tidy."""
        for reorder in (".sort(", ".reverse(", "localeCompare"):
            self.assertNotIn(reorder, self.code, reorder)

    def test_the_hue_is_applied_as_a_class_and_not_as_a_colour(self):
        self.assertIn('"cn-who h-" + line.hue', self.code)
        self.assertNotIn(".style.color", self.code)

    def test_every_hue_the_module_can_emit_has_a_rule_in_the_page(self):
        """A hue with no rule is text in the ground colour, which on a card is
        invisible."""
        for hue in (list(council.SPEAKER_HUES)
                    + [council.OUTSIDER_HUE, council.READY_HUE,
                       council.SHORT_HUE]):
            self.assertIn(".h-%s {" % hue, self.page, hue)

    def test_the_page_does_not_pick_the_gates_colour_either(self):
        self.assertIn('"cn-gate h-" + p.hue', self.code)
        self.assertNotIn("h-green", self.code)

    def test_the_decision_and_the_vote_are_drawn_and_not_composed(self):
        self.assertIn("agreed.decision", self.code)
        self.assertIn("agreed.vote", self.code)
        self.assertNotIn("agreed.spoke +", self.code)

    def test_the_gate_and_the_verdict_come_from_the_payload(self):
        self.assertIn("p.gate", self.code)
        self.assertIn("p.verdict", self.code)
        for invented in ('"READY"', "LEVELS SHORT", "p.short +"):
            self.assertNotIn(invented, self.code, invented)

    def test_the_gate_is_a_word_before_it_is_a_colour(self):
        """A gate said only in colour is lost to a screenshot, to a
        colourblind reader and to anybody reading it out loud."""
        self.assertIn('el("span", "cn-gate ', self.code)
        self.assertIn("p.gate", self.code[self.code.index('"cn-gate '):])

    def test_nothing_from_the_payload_is_rendered_as_markup(self):
        """A council line is written by a language model into a table the
        bridge fills, which is as untrusted as text on this page gets."""
        self.assertNotIn("innerHTML", self.code)
        self.assertNotIn("insertAdjacentHTML", self.code)

    def test_a_failed_poll_keeps_the_transcript(self):
        """Blanking it reads as "the family has stopped talking", which is a
        far stronger claim than "one read failed"."""
        poll = self.code[self.code.index("async function pollCouncil"):]
        self.assertIn("may be stale", poll)
        self.assertNotIn("replaceChildren", poll)

    def test_the_endpoint_is_wired_and_the_builder_is_pure(self):
        self.assertIn('"/api/council": _council,', self.server)
        self.assertIn("council.build_council(**_fetch_council(), cards=cards)",
                      self.server)
        self.assertIn('fetch(u("/api/council"))', self.tab)

    def test_the_endpoint_takes_no_roster_from_the_caller(self):
        """WHO the family is belongs to bonds, and a roster parameter would
        make this a general character query wearing a friendly name."""
        handler = self.server[self.server.index("def _council"):]
        handler = handler[:handler.index("def _eye")]
        self.assertNotIn("query.get", handler)
        self.assertIn("503", handler)

    def test_every_overseer_table_read_goes_through_the_guard(self):
        """infra#3172 cost a whole tab on production because one read of a
        table the module creates was not guarded."""
        fetch = self.server[self.server.index("def _fetch_council"):]
        fetch = fetch[:fetch.index("def _fetch_eye")]
        for table in ("overseer_thought", "overseer_goal", "characters"):
            self.assertIn('"%s")' % table, fetch, table)

    def test_the_view_polls_only_while_it_is_open(self):
        self.assertIn("if (view === COUNCIL_VIEW) pollCouncil();", self.tab)

    def test_it_lays_out_without_a_breakpoint_of_its_own(self):
        """Mobile-first: auto-fit turns two columns into one without anybody
        choosing where that happens, and "left" becomes "first"."""
        self.assertIn("grid-template-columns:repeat(auto-fit, minmax(320px, 1fr))",
                      self.css)
        self.assertNotIn("@media", self.css)

    def test_the_module_ships_in_the_image(self):
        dockerfile = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("council.py", dockerfile)

    def test_no_em_dashes(self):
        for name in ("council.py", "tests/test_council_view.py"):
            self.assertNotIn(chr(0x2014),
                             (HERE / name).read_text(encoding="utf-8"), name)


if __name__ == "__main__":
    unittest.main()
