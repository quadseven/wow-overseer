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

    def test_the_card_counts_who_spoke_and_never_claims_a_vote(self):
        """THE TALLY IS NOT WRITTEN DOWN ANYWHERE. hold() scores the proposals
        and keeps only the winner, so a count of ayes here would be a number
        invented about a vote nothing recorded. Who turned up to argue is a
        fact this module does have, and the card says which it is."""
        rows = [said("Grug", "g"), said("Ugga", "u", minutes=1)]
        agreed = council.consensus([goal("Bork", minutes=1)], [],
                                   thought_rows=rows, now=T0)
        self.assertEqual(2, agreed["spoke"])
        self.assertEqual(len(bonds.FAMILY), agreed["family"])
        self.assertIn("does not record a vote", agreed["who_line"])
        self.assertNotIn("vote", agreed)


def dgoal(who, keyword, target=25, minutes=0, status="active"):
    row = goal(who, "dungeon", target, status=status, minutes=minutes)
    row["skill_name"] = keyword
    return row


class TheDecisionIsAPlainSentence(unittest.TestCase):
    """The operator could not read "Grug is to see to dungeon." Every kind
    the goal table holds has its own sentence, with a subject and a verb."""

    def test_a_dungeon_goal_names_the_place_and_the_campaign(self):
        line = council.decision_line(dgoal("Grug", "blackrock-depths"))
        self.assertEqual(
            "Grug will lead the family into Blackrock Depths, 25 runs.", line)
        self.assertNotIn("see to", line)

    def test_a_scarlet_goal_names_its_wing(self):
        line = council.decision_line(dgoal("Grog", "scarlet-cathedral"))
        self.assertIn("Scarlet Monastery (the Cathedral)", line)

    def test_every_portal_keyword_has_a_place(self):
        """A keyword the portal table can run and this sentence cannot name
        would print the raw keyword to the operator."""
        import jobs
        for keyword in jobs.PORTAL_KEYWORDS:
            self.assertIn(keyword, council.DUNGEON_KEYWORDS, keyword)

    def test_the_bare_dungeon_job_is_a_dungeon_and_not_a_blank(self):
        self.assertIn("into a dungeon",
                      council.decision_line(dgoal("Grug", "")))

    def test_a_skill_goal_names_the_skill_and_the_rank(self):
        row = goal("Grog", "skill", 50)
        row["skill_name"] = "mining"
        self.assertEqual("Grog will train mining to 50.",
                         council.decision_line(row))

    def test_a_level_goal_says_who_helps_whom(self):
        self.assertEqual("The family will help Bork reach level 12.",
                         council.decision_line(goal("Bork", "level", 12)))

    def test_no_kind_falls_into_to_see_to(self):
        for kind in ("level", "quest", "skill", "dungeon", "mystery"):
            self.assertNotIn("is to see to",
                             council.decision_line(goal("Grug", kind)), kind)


OUTSIDE = council.OUTSIDE_LABEL


class TheCardReadsTheSittingThatDecidedIt(unittest.TestCase):
    """The card used to count the speakers of the LAST sitting, which on the
    dev realm was a one-line sitting about a robe held a day after the dungeon
    decision it was printed under."""

    def setUp(self):
        self.rows = [
            said("Grug", "we go in", minutes=0),
            said("Ugga", "Ugga help Grug.", minutes=0),
            said("Grug", "Then it is settled.", minutes=1),
            # A day later, and nothing to do with the decision.
            said("Og", "Og make robe.", minutes=24 * 60),
        ]
        self.agreed = council.consensus(
            [dgoal("Grug", "blackrock-depths", minutes=1)], [],
            thought_rows=self.rows, now=T0 + timedelta(days=1, hours=2))

    def test_the_count_is_of_the_deciding_sitting(self):
        self.assertEqual(["Grug", "Ugga"], self.agreed["speakers"])
        self.assertNotIn("Og", self.agreed["speakers"])

    def test_the_proposer_is_whoever_settled_it(self):
        self.assertEqual("Grug", self.agreed["proposer"])
        self.assertTrue(self.agreed["who_line"].startswith("Grug proposed it."))
        self.assertIn("Ugga also spoke.", self.agreed["who_line"])

    def test_everyone_who_did_not_speak_is_named(self):
        for name in ("Og", "Grog", "Bork"):
            self.assertIn(name, self.agreed["silent"])
        self.assertIn("did not speak at that sitting", self.agreed["who_line"])

    def test_the_lines_shown_are_the_deciding_ones(self):
        texts = [line["text"] for line in self.agreed["sitting"]]
        self.assertIn("Ugga help Grug.", texts)
        self.assertNotIn("Og make robe.", texts)

    def test_it_says_how_long_ago(self):
        self.assertEqual("Set 25 hours ago.", self.agreed["when_line"])

    def test_a_goal_no_sitting_produced_says_so(self):
        agreed = council.consensus(
            [dgoal("Grug", "deadmines", minutes=600)], [],
            thought_rows=self.rows[:3], now=T0)
        self.assertEqual("SET OUTSIDE THE COUNCIL", agreed["label"])
        self.assertIn("Nobody voted", agreed["who_line"])
        self.assertEqual([], agreed["sitting"])

    def test_a_goal_time_that_is_not_a_time_finds_no_sitting(self):
        self.assertEqual([], council.deciding_sitting(self.rows, "2026-09-03"))

    def test_an_unreadable_line_time_is_skipped_not_raised(self):
        lines = [{"who": "Grug", "text": "g", "at": "not a time"},
                 {"who": "Ugga", "text": "u", "at": None}]
        agreed = council.consensus([goal("Bork")], lines, now=T0)
        self.assertEqual(OUTSIDE, agreed["label"])

    def test_other_open_goals_are_listed_not_hidden(self):
        agreed = council.consensus(
            [dgoal("Grug", "blackrock-depths", minutes=1),
             dgoal("Bork", "stockades", minutes=-60)], [],
            thought_rows=self.rows, now=T0)
        self.assertEqual(1, len(agreed["older"]))
        self.assertIn("The Stockade", agreed["older"][0])


class TheCardSaysWhetherItIsInEffect(unittest.TestCase):
    """A dungeon decision starts nothing until the family leader's job column
    names it: the run coordinator reads that one column. The card said nothing
    about it, so an active goal nobody was acting on read as done."""

    def _agreed(self, job):
        standing = {"leader": "Grug", "job": job, "done": 3, "wanted": 25}
        return council.consensus([dgoal("Grug", "blackrock-depths")], [],
                                 thought_rows=[], standing=standing, now=T0)

    def test_a_matching_job_is_in_effect_and_counts_runs(self):
        agreed = self._agreed("dungeon:blackrock-depths")
        self.assertIs(True, agreed["in_effect"])
        self.assertIn("3 of 25 runs done", agreed["next_line"])

    def test_a_job_that_names_something_else_is_not_in_effect(self):
        agreed = self._agreed("quest")
        self.assertIs(False, agreed["in_effect"])
        self.assertIn("still reads quest", agreed["next_line"])
        self.assertIn("dungeon:blackrock-depths", agreed["next_line"])

    def test_an_unread_roster_is_unknown_and_not_a_guess(self):
        agreed = council.consensus([dgoal("Grug", "blackrock-depths")], [],
                                   thought_rows=[], standing=None, now=T0)
        self.assertIsNone(agreed["in_effect"])
        self.assertIn("could not be read", agreed["next_line"])

    def test_a_goal_with_no_column_says_what_happens_next(self):
        agreed = council.consensus([goal("Bork", "level", 12)], [],
                                   thought_rows=[], now=T0)
        self.assertIsNone(agreed["in_effect"])
        self.assertTrue(agreed["next_line"].startswith("Next:"))


def roster_row(name, fam, lead=0, job="quest"):
    return {"name": name, "family": fam, "enabled": 1, "lead": lead,
            "job": job, "dungeon_runs_wanted": 25, "dungeon_runs_done": 0}


class BothFamiliesAreOnTheTab(unittest.TestCase):
    """The roster holds an Alliance five and a Horde five. bonds holds personas
    for one of them, so the tab only ever showed that one."""

    def setUp(self):
        roster = [roster_row(n, "Grug", lead=int(n == "Grug"))
                  for n in ("Grug", "Ugga", "Og", "Grog", "Bork")]
        roster += [roster_row(n, "Zug", lead=int(n == "Zug"))
                   for n in ("Zug", "Oz", "Uzza", "Zork", "Zrog")]
        lv = [{"name": n, "level": 60, "race": 1}
              for n in ("Grug", "Ugga", "Og", "Grog", "Bork")]
        lv += [{"name": n, "level": 12, "race": 2}
               for n in ("Zug", "Oz", "Uzza", "Zork", "Zrog")]
        self.payload = council.build_council(
            [said("Grug", "g"), said("Ugga", "u")],
            [dgoal("Grug", "blackrock-depths")], lv,
            [run_card(230, [("Ironfoe", 4)])], now=T0, roster_rows=roster)
        self.by = {f["family"]: f for f in self.payload["families"]}

    def test_there_is_one_block_per_family(self):
        self.assertEqual(["Grug", "Zug"],
                         [f["family"] for f in self.payload["families"]])

    def test_each_family_is_titled_with_its_faction(self):
        self.assertEqual("Grug's family, Alliance", self.by["Grug"]["title"])
        self.assertEqual("Zug's family, Horde", self.by["Zug"]["title"])

    def test_a_family_with_no_personas_says_it_holds_no_councils(self):
        zug = self.by["Zug"]
        self.assertFalse(zug["holds_council"])
        self.assertIn("does not hold councils", zug["note"])
        self.assertIsNone(zug["consensus"])

    def test_the_other_familys_goal_is_not_theirs(self):
        self.assertIsNotNone(self.by["Grug"]["consensus"])
        self.assertIsNone(self.by["Zug"]["consensus"])

    def test_each_family_is_gated_on_its_own_levels(self):
        zug = self.by["Zug"]["prospects"]
        self.assertTrue(zug)
        self.assertNotIn("Blackrock Depths", [p["place"] for p in zug])
        self.assertTrue(any(not p["ready"] for p in zug)
                        or all(p["wants"] <= 12 for p in zug))

    def test_drops_the_alliance_saw_are_not_credited_to_the_horde(self):
        for place in self.by["Zug"]["prospects"]:
            self.assertEqual([], place["drops"], place["place"])

    def test_no_roster_falls_back_to_the_one_family_bonds_knows(self):
        payload = council.build_council([], [], [], [], now=T0)
        self.assertEqual(1, len(payload["families"]))
        self.assertTrue(payload["families"][0]["holds_council"])


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
        for key in ("label", "decision", "who_line", "next_line", "sitting"):
            self.assertIn(key, payload["consensus"])
        self.assertTrue(payload["families"])
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

    def test_the_decision_is_drawn_as_sentences_and_not_composed(self):
        """The card was a status word over "1 OF 5 SPOKE", and the operator
        could not read it. Every line on it is now a sentence from council.py,
        drawn as it arrives."""
        for key in ("agreed.label", "agreed.decision", "agreed.who_line",
                    "agreed.when_line", "agreed.next_line", "agreed.sitting"):
            self.assertIn(key, self.code, key)
        self.assertNotIn("agreed.vote", self.code)
        self.assertNotIn("CARRIED", self.code)
        self.assertNotIn("SPOKE", self.code)

    def test_every_family_is_drawn(self):
        self.assertIn("p.families", self.code)
        self.assertIn("f.title", self.code)
        self.assertIn("f.note", self.code)

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
        for table in ("overseer_thought", "overseer_goal", "characters",
                      "overseer_roster"):
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
