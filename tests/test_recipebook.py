"""Learning a recipe off an item, and buying one that is actually usable.

bridge.py imports discord and cannot be imported here, so the pass half is read
as text the way test_bag_handover and test_auction do. The decisions half is a
pure module and is exercised directly, against numbers measured off the live
realm on 2026-09-14.

WHAT IS PINNED HERE, and why each one is worth a case:

  - THE COMMAND GRAMMAR AGREES WITH THE PARSER THAT WILL READ IT. `use_command`
    renders the text `OverseerDecisions::ParseLearnRequest` accepts, and that
    parser's own source is read here rather than remembered - the same thing
    test_auction does for `ParseAuctionRequest`.
  - REACHABILITY IS THE CORE'S OWN TEST. `Player::CanUseItem` refuses an item
    whose RequiredSkillRank is above the character's value in RequiredSkill, so
    a pass that shopped by profession alone would buy walls. Measured: of the 72
    class-9 items on the family's own auction house that day, two were within
    anybody's reach, because the cheapest Plans wanted Blacksmithing 60 against
    a smith at 1.
  - `character_spell` IS NEVER READ. It cannot answer whether a bot knows a
    recipe, and being wrong in that direction DESTROYS AN ITEM: the core
    consumes a recipe item on use whether or not anything was learned, and asks
    no already-known question of its own. The worldserver's own refusal is what
    this pass consumes instead, and that is asserted as a seam, not just
    described.
  - A BOUGHT RECIPE ARRIVES BY MAIL, so the buy half can never feed the learn
    half in the same pass. DoAuction's own success sentence is read here,
    because if that ever changes this design gets simpler and this test is what
    should say so.
"""
import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import auction  # noqa: E402
import recipebook  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "mod-overseer/src/overseer_decisions.cpp"
DECISIONS_H = ROOT / "mod-overseer/src/overseer_decisions.h"
MODULE = ROOT / "mod-overseer/src/mod_overseer.cpp"
BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "bridge.py"
DOCKERFILE = ROOT / "docker/wow-overseer/Dockerfile"


def _source() -> str:
    return BRIDGE.read_text(encoding="utf-8")


def _block(signature: str) -> str:
    """One def's body, to the next def at the same or shallower indent."""
    src = _source()
    start = src.index(signature)
    indent = len(signature) - len(signature.lstrip())
    rest = src[start:]
    match = re.search(r"\n {0,%d}(async def |def |class )" % indent, rest[1:])
    return rest[: match.start() + 1] if match else rest


def _code(body: str) -> str:
    """The same text with its prose removed - docstrings, then `#` comments.

    WHY ANY OF THIS FILE NEEDS IT. Several of the rules below are "this pass
    must not touch X", and X is named in the very comment that explains why. A
    bare substring search over the whole body is then satisfied by DELETING THE
    EXPLANATION, which is the opposite of what the test is for. Stripping the
    prose first means the assertion is about the code and the comment is free to
    say whatever is true.
    """
    body = re.sub(r'"""(?:.|\n)*?"""', "", body)
    body = re.sub(r"'''(?:.|\n)*?'''", "", body)
    return re.sub(r"(?m)#.*$", "", body)


def _has(case, needle: str, haystack: str, what: str) -> None:
    """assertIn over a whole C++ file, without printing the file on failure.

    A failed assertIn embeds its haystack in the message, and these haystacks
    are the module's 40,000-line source: one failure writes 600KB into the CI
    log and buries the others. These eight assertions are EXPECTED to fail
    whenever the submodule pin is behind the module, so they of all things have
    to fail in one readable line.
    """
    case.assertTrue(needle in haystack,
                    "%s: not found in the deployed module source - is the "
                    "submodule pin behind mod-overseer#468? (looked for %r)"
                    % (what, needle[:80]))


def _slice(case, source: str, start_at: str, end_at: str) -> str:
    """The text between two markers, or a one-line skip-worthy failure.

    `str.index` raises ValueError with no context when the marker is absent, and
    absent is exactly what these markers are whenever the submodule pin is
    behind the module. A bare traceback there says `substring not found` and
    nothing about why.
    """
    for marker in (start_at, end_at):
        if marker not in source:
            case.fail("not found in the deployed module source - is the "
                      "submodule pin behind mod-overseer#468? (looked for %r)"
                      % marker[:80])
    start = source.index(start_at)
    return source[start:source.index(end_at, start)]


def _cpp_code(body: str) -> str:
    """The same, for a C++ body: block comments then line comments."""
    body = re.sub(r"/\*(?:.|\n)*?\*/", "", body)
    return re.sub(r"(?m)//.*$", "", body)


# ---------------------------------------------------------------------------
# Measured off the live realm, 2026-09-14. The five family members' real skill
# numbers, which are what make the reachability cases mean something: every one
# of their primaries is near the floor, so the only class-9 items they can use
# are Cooking ones at rank 1.
SKILLS = {
    "Bork": {165: 1, 393: 12, 185: 1, 129: 1},    # Leatherworking, Skinning
    "Grog": {186: 1, 202: 1, 185: 1, 129: 1},     # Mining, Engineering
    "Grug": {164: 1, 186: 8, 185: 1, 129: 1},     # Blacksmithing, Mining
    "Og": {197: 50, 333: 1, 185: 1, 129: 1},      # Tailoring, Enchanting
    "Ugga": {171: 14, 182: 133, 185: 1, 129: 1},  # Alchemy, Herbalism
}

# Real items, with their real gates out of acore_world.item_template.
TENDERLOIN = recipebook.Listing(
    auction_id=121718, entry=27686, label="Recipe: Roasted Moongraze Tenderloin",
    buyout=1049, house=2, required_skill=185, required_rank=1, recipe_spell=33277)
GINGERBREAD = recipebook.Listing(
    auction_id=122435, entry=17200, label="Recipe: Gingerbread Cookie",
    buyout=897, house=7, required_skill=185, required_rank=1, recipe_spell=21143)
KABOB = recipebook.Listing(
    auction_id=121744, entry=5482, label="Recipe: Kaldorei Spider Kabob",
    buyout=1241, house=2, required_skill=185, required_rank=10, recipe_spell=6412)
GREEN_SILK = recipebook.Listing(
    auction_id=121717, entry=7090, label="Pattern: Green Silk Armor",
    buyout=4194, house=2, required_skill=197, required_rank=165, recipe_spell=8784)
GEMMED_COPPER = recipebook.Listing(
    auction_id=121949, entry=3610, label="Plans: Gemmed Copper Gauntlets",
    buyout=3470, house=2, required_skill=164, required_rank=60, recipe_spell=3325)

PURSES = {"Bork": 1578677, "Grog": 1806127, "Grug": 1748436,
          "Og": 1734714, "Ugga": 1767877}
SLOTS = {name: 12 for name in SKILLS}


class TheCommandGrammar(unittest.TestCase):

    def test_a_guid_renders_the_guid_form(self):
        self.assertEqual(recipebook.use_command(item_guid=1339293), "use guid:1339293")

    def test_an_entry_renders_the_entry_form(self):
        self.assertEqual(recipebook.use_command(entry=27686), "use entry:27686")

    def test_exactly_one_of_the_two(self):
        with self.assertRaises(ValueError):
            recipebook.use_command()
        with self.assertRaises(ValueError):
            recipebook.use_command(item_guid=1, entry=2)

    def test_a_zero_is_refused_rather_than_rendered(self):
        """ParseLearnRequest rejects zero by name, so writing one would be a row
        whose only possible answer is a refusal."""
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                recipebook.use_command(item_guid=bad)
            with self.assertRaises(ValueError):
                recipebook.use_command(entry=bad)

    def test_a_bool_is_not_an_id(self):
        """True is an int in Python and would render `use guid:1`, naming
        whatever item happens to hold guid 1."""
        with self.assertRaises(ValueError):
            recipebook.use_command(item_guid=True)
        with self.assertRaises(ValueError):
            recipebook.use_command(entry=True)


class TheParserOnTheOtherSideAcceptsIt(unittest.TestCase):
    """Read off the deployed parser's own source, never remembered."""

    def test_the_verb_is_the_word_the_dispatch_routes_on(self):
        source = DECISIONS.read_text(encoding="utf-8", errors="ignore")
        _has(self, 'return !words.empty() && words[0] == "use";', source,
             "IsLearnRow routes on the exact word")
        for rendered in (recipebook.use_command(entry=27686),
                         recipebook.use_command(item_guid=7)):
            self.assertTrue(rendered.startswith("use "))

    def test_the_two_keys_are_the_two_this_module_renders(self):
        source = DECISIONS.read_text(encoding="utf-8", errors="ignore")
        _has(self, 'LearnKeyed(words[1], "guid", key)', source, "the guid key")
        _has(self, 'LearnKeyed(words[1], "entry", key)', source, "the entry key")

    def test_a_third_word_is_refused_so_nothing_may_be_appended(self):
        source = DECISIONS.read_text(encoding="utf-8", errors="ignore")
        _has(self, "request.error = LearnRefusal::TooManyWords;", source,
             "a third word is refused")
        for rendered in (recipebook.use_command(entry=1),
                         recipebook.use_command(item_guid=1)):
            self.assertEqual(len(rendered.split()), 2)

    def test_the_kind_it_rides_on_needs_no_new_enum_value(self):
        """The whole reason this is kind='cast'. A new ENUM value is a migration
        in mod-overseer's data/sql that reaches a world only when db-import
        runs."""
        self.assertEqual(recipebook.LEARN_KIND, "cast")
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        _has(self, 'else if (kind == "cast" && OverseerDecisions::IsLearnRow(command))',
             source, "the dispatch arm")


class TheSettledDetailsAreTheExecutorsOwnWords(unittest.TestCase):
    """If these drift, the pass re-asks a settled row for ever."""

    def test_both_literals_exist_in_the_deployed_refusal_table(self):
        source = DECISIONS_H.read_text(encoding="utf-8", errors="ignore")
        _has(self, 'constexpr char const* AlreadyKnown = "%s";' % recipebook.ALREADY_KNOWN,
             source, "the already-known literal")
        _has(self, 'constexpr char const* SkillTooLow = "%s";' % recipebook.SKILL_TOO_LOW,
             source, "the skill-too-low literal")

    def test_the_already_known_refusal_happens_before_anything_is_sent(self):
        """It is the refusal that saves the item, so it has to be upstream of
        the packet. Spell::TakeCastItem destroys a recipe item on use whether or
        not anything was learned."""
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        body = _slice(self, source, "static char const* DoLearnRecipe(",
                      "session->HandleUseItemOpcode(raw);")
        _has(self, "return refuse(Refusal::AlreadyKnown);", body,
             "the already-known refusal precedes the packet")

    def test_the_verdict_is_hasspell_and_not_character_spell(self):
        """Asserted on the code with the comments stripped, because the comment
        right above the read names character_spell in order to say it must not
        be used - and a bare substring search would reward deleting it."""
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        body = _cpp_code(_slice(self, source, "void ResolveLearnChecks(",
                                "_pendingLearns.swap(stillLearning);"))
        self.assertIn("bot->HasSpell(check.ev.recipeSpellId)", body)
        self.assertNotIn("character_spell", body)
        # And the verdict is taken from the read-back, not invented here.
        self.assertIn("check.ev.verdict = JudgeLearn(read);", body)


class WhatACharacterCanActuallyUse(unittest.TestCase):

    def test_a_cooking_recipe_at_rank_one_is_in_reach_of_everybody(self):
        for name in SKILLS:
            self.assertTrue(
                recipebook.within_reach(185, 1, SKILLS[name]), name)

    def test_the_next_cooking_recipe_up_is_not(self):
        """Rank 10 against Cooking 1. The wall is real and one rank wide."""
        for name in SKILLS:
            self.assertFalse(recipebook.within_reach(185, 10, SKILLS[name]), name)

    def test_the_tailor_cannot_use_a_pattern_needing_more_than_he_has(self):
        self.assertFalse(recipebook.within_reach(197, 165, SKILLS["Og"]))

    def test_but_could_use_one_at_or_below_his_value(self):
        self.assertTrue(recipebook.within_reach(197, 50, SKILLS["Og"]))
        self.assertTrue(recipebook.within_reach(197, 49, SKILLS["Og"]))

    def test_a_skill_the_character_does_not_hold_at_all_is_not_reach(self):
        """EQUIP_ERR_NO_REQUIRED_PROFICIENCY, and it is not the same wall as a
        low value - but it is the same answer."""
        self.assertFalse(recipebook.within_reach(333, 1, SKILLS["Bork"]))

    def test_a_zero_value_reads_as_not_holding_it(self):
        self.assertFalse(recipebook.within_reach(333, 1, {333: 0}))

    def test_an_item_that_gates_on_nothing_is_always_in_reach(self):
        self.assertTrue(recipebook.within_reach(0, 0, {}))


class LearningWhatIsAlreadyCarried(unittest.TestCase):

    def _held(self, holder, guid, entry, skill, rank, label="x"):
        return recipebook.Held(holder=holder, item_guid=guid, entry=entry,
                               label=label, required_skill=skill,
                               required_rank=rank, recipe_spell=1)

    def test_a_reachable_recipe_is_queued_by_guid(self):
        learns, _ = recipebook.plan_learns(
            [self._held("Ugga", 1647927, 6661, 185, 1)], SKILLS)
        self.assertEqual(len(learns), 1)
        self.assertEqual(learns[0].command, "use guid:1647927")
        self.assertEqual(learns[0].holder, "Ugga")

    def test_an_unreachable_one_is_skipped_with_both_numbers_in_the_sentence(self):
        learns, skipped = recipebook.plan_learns(
            [self._held("Bork", 1894435, 8397, 165, 200,
                        "Pattern: Tough Scorpid Bracers")], SKILLS)
        self.assertEqual(learns, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("165", skipped[0].why)
        self.assertIn("200", skipped[0].why)
        self.assertIn("Bork", skipped[0].why)

    def test_the_family_as_measured_can_learn_none_of_what_it_carries(self):
        """The finding this pass was written against. Every one of the 43
        class-9 items in their bags on 2026-09-14 gated above their trades, so a
        pass that queued by profession alone would have burned the lot."""
        carried = [
            self._held("Bork", 1894435, 8397, 165, 200),
            self._held("Bork", 1851923, 4298, 165, 170),
            self._held("Grug", 1507032, 3611, 164, 145),
            self._held("Og", 1787181, 10316, 197, 215),
            self._held("Ugga", 1693292, 2553, 171, 50),
        ]
        learns, skipped = recipebook.plan_learns(carried, SKILLS)
        self.assertEqual(learns, [])
        self.assertEqual(len(skipped), len(carried))

    def test_a_settled_answer_from_the_world_is_never_re_asked(self):
        held = [self._held("Ugga", 1647927, 6661, 185, 1)]
        learns, skipped = recipebook.plan_learns(
            held, SKILLS, settled={("Ugga", 6661)})
        self.assertEqual(learns, [])
        self.assertIn("worldserver", skipped[0].why)

    def test_the_settled_set_is_per_character_and_not_per_item(self):
        """Ugga knowing a recipe says nothing about whether Og does."""
        held = [self._held("Ugga", 1, 6661, 185, 1),
                self._held("Og", 2, 6661, 185, 1)]
        learns, _ = recipebook.plan_learns(held, SKILLS, settled={("Ugga", 6661)})
        self.assertEqual([x.holder for x in learns], ["Og"])

    def test_a_row_already_queued_in_the_window_is_not_queued_again(self):
        held = [self._held("Ugga", 1647927, 6661, 185, 1)]
        learns, skipped = recipebook.plan_learns(
            held, SKILLS, seen={("Ugga", "use guid:1647927")})
        self.assertEqual(learns, [])
        self.assertIn("retry window", skipped[0].why)

    def test_the_highest_reachable_rank_goes_first(self):
        """The recipe nearest the top of what the trade can do is the one most
        likely to still be worth casting."""
        held = [self._held("Og", 10, 111, 197, 5),
                self._held("Og", 11, 222, 197, 40),
                self._held("Og", 12, 333, 197, 20)]
        learns, _ = recipebook.plan_learns(held, SKILLS)
        self.assertEqual([x.entry for x in learns], [222, 333, 111])

    def test_an_empty_pass_is_not_an_error(self):
        self.assertEqual(recipebook.plan_learns([], SKILLS), ([], []))


class BuyingOneThatIsActuallyUsable(unittest.TestCase):

    def _houses(self, **kw):
        return kw

    def test_the_only_two_listings_in_reach_are_the_cooking_ones(self):
        """Measured: 72 class-9 items on the house, two usable by anybody."""
        market = [TENDERLOIN, KABOB, GREEN_SILK, GEMMED_COPPER]
        usable = recipebook.usable(market, 2, SKILLS["Og"])
        self.assertEqual([x.entry for x in usable], [27686])

    def test_a_listing_in_another_house_is_not_on_this_counter(self):
        self.assertEqual(recipebook.usable([GINGERBREAD], 2, SKILLS["Og"]), [])
        self.assertEqual(
            [x.entry for x in recipebook.usable([GINGERBREAD], 7, SKILLS["Og"])],
            [17200])

    def test_a_bid_only_listing_is_never_bought(self):
        """A bid buys nothing and DoAuction refuses one by name."""
        free = recipebook.Listing(
            auction_id=1, entry=27686, label="x", buyout=0, house=2,
            required_skill=185, required_rank=1)
        self.assertEqual(recipebook.usable([free], 2, SKILLS["Og"]), [])

    def test_an_absurdly_priced_listing_is_refused_by_the_per_item_cap(self):
        dear = recipebook.Listing(
            auction_id=1, entry=27686, label="x",
            buyout=recipebook.PER_RECIPE_CAP_COPPER + 1, house=2,
            required_skill=185, required_rank=1)
        self.assertEqual(recipebook.usable([dear], 2, SKILLS["Og"]), [])

    def test_the_best_reachable_rank_is_taken_and_not_the_cheapest_thing(self):
        """Buying the cheapest on offer fills a bag with recipes that are
        already grey."""
        cheap_low = recipebook.Listing(
            auction_id=1, entry=100, label="cheap", buyout=10, house=2,
            required_skill=197, required_rank=5)
        dearer_high = recipebook.Listing(
            auction_id=2, entry=200, label="better", buyout=900, house=2,
            required_skill=197, required_rank=45)
        buys, _ = recipebook.plan_purchases(
            ["Og"], [cheap_low, dearer_high], SKILLS, {"Og": 2}, PURSES, SLOTS)
        self.assertEqual([b.entry for b in buys], [200])

    def test_one_recipe_per_character_per_pass(self):
        buys, _ = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN, TENDERLOIN], SKILLS, {"Og": 2}, PURSES, SLOTS)
        self.assertEqual(len(buys), 1)

    def test_two_characters_at_one_counter_do_not_buy_the_same_auction(self):
        """An auction id is bought exactly once; a second row naming it can only
        be refused."""
        buys, _ = recipebook.plan_purchases(
            ["Og", "Ugga"], [TENDERLOIN], SKILLS,
            {"Og": 2, "Ugga": 2}, PURSES, SLOTS)
        self.assertEqual(len(buys), 1)

    def test_the_command_is_the_auction_modules_own_rendering(self):
        buys, _ = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN], SKILLS, {"Og": 2}, PURSES, SLOTS)
        self.assertEqual(buys[0].command, auction.buy_command(121718))

    def test_an_empty_purse_buys_nothing_and_says_so(self):
        buys, skipped = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN], SKILLS, {"Og": 2}, {"Og": 3}, SLOTS)
        self.assertEqual(buys, [])
        self.assertIn("carries 3", skipped[0].why)

    def test_full_bags_buy_nothing_and_say_so(self):
        buys, skipped = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN], SKILLS, {"Og": 2}, PURSES,
            {"Og": recipebook.SLOTS_KEPT_FREE})
        self.assertEqual(buys, [])
        self.assertIn("free bag slots", skipped[0].why)

    def test_the_pass_spend_cap_stops_the_second_buyer(self):
        """The cap is across the whole pass, not per character, so the second
        shopper is refused by what the first one already spent."""
        dear_a = recipebook.Listing(
            auction_id=1, entry=100, label="a", buyout=6000, house=2,
            required_skill=185, required_rank=1)
        dear_b = recipebook.Listing(
            auction_id=2, entry=200, label="b", buyout=6000, house=2,
            required_skill=185, required_rank=1)
        buys, skipped = recipebook.plan_purchases(
            ["Og", "Ugga"], [dear_a, dear_b], SKILLS,
            {"Og": 2, "Ugga": 2}, PURSES, SLOTS, cap=7000)
        self.assertEqual(len(buys), 1)
        self.assertTrue(any("already spent" in s.why for s in skipped))

    def test_and_the_same_two_both_sell_when_the_cap_allows_it(self):
        """The control for the case above: without it, a cap test passes just as
        well against a planner that never buys anything at all."""
        dear_a = recipebook.Listing(
            auction_id=1, entry=100, label="a", buyout=6000, house=2,
            required_skill=185, required_rank=1)
        dear_b = recipebook.Listing(
            auction_id=2, entry=200, label="b", buyout=6000, house=2,
            required_skill=185, required_rank=1)
        buys, _ = recipebook.plan_purchases(
            ["Og", "Ugga"], [dear_a, dear_b], SKILLS,
            {"Og": 2, "Ugga": 2}, PURSES, SLOTS, cap=20000)
        self.assertEqual(len(buys), 2)

    def test_a_recipe_already_in_the_bag_is_not_bought_again(self):
        """A recipe teaches once and is destroyed doing it, so a second copy is
        worth nothing. The overlap is the NORMAL case: a character holds an
        unlearned Pattern precisely because the trade is too low, and the moment
        it is high enough this pass would find the same one on the house."""
        buys, _ = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN], SKILLS, {"Og": 2}, PURSES, SLOTS,
            carried={("Og", 27686)})
        self.assertEqual(buys, [])

    def test_but_somebody_else_holding_it_does_not_stop_this_one_buying(self):
        """The control. Keyed per character, because Ugga's copy is in Ugga's
        bag and teaches nobody else."""
        buys, _ = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN], SKILLS, {"Og": 2}, PURSES, SLOTS,
            carried={("Ugga", 27686)})
        self.assertEqual([b.entry for b in buys], [27686])

    def test_the_pass_feeds_it_from_the_same_read_the_learning_half_used(self):
        body = _code(_block("    async def _recipebook_once("))
        self.assertIn("carried = {(item.holder, int(item.entry)) for item in held}",
                      body)
        self.assertIn("settled, seen, carried)", body)

    def test_an_unreachable_house_buys_nothing(self):
        buys, skipped = recipebook.plan_purchases(
            ["Og"], [TENDERLOIN], SKILLS, {"Og": 0}, PURSES, SLOTS)
        self.assertEqual(buys, [])
        self.assertIn("no auction house", skipped[0].why)

    def test_nobody_at_a_counter_buys_nothing(self):
        self.assertEqual(
            recipebook.plan_purchases([], [TENDERLOIN], SKILLS, {}, PURSES, SLOTS),
            ([], []))


class ReadingTheWorldserversAnswerBack(unittest.TestCase):

    def test_an_already_known_row_settles_that_character_and_entry(self):
        rows = [{"target_name": "Ugga", "detail": recipebook.ALREADY_KNOWN,
                 "entry": 6661}]
        self.assertEqual(recipebook.settled_from_rows(rows), {("Ugga", 6661)})

    def test_a_skill_too_low_row_settles_it_too(self):
        rows = [{"target_name": "Og", "detail": recipebook.SKILL_TOO_LOW,
                 "entry": 7090}]
        self.assertEqual(recipebook.settled_from_rows(rows), {("Og", 7090)})

    def test_a_transient_refusal_settles_nothing(self):
        """`character is moving` ends by itself, and a pass that treated it as
        final would never try that item again."""
        rows = [{"target_name": "Og", "detail": "character is moving",
                 "entry": 7090},
                {"target_name": "Og", "detail": "", "entry": 7090}]
        self.assertEqual(recipebook.settled_from_rows(rows), set())

    def test_a_row_with_no_entry_settles_nothing(self):
        """A refusal taken before the item was resolved carries entry 0, and
        (name, 0) would match nothing while looking like an answer."""
        rows = [{"target_name": "Og", "detail": recipebook.ALREADY_KNOWN,
                 "entry": 0}]
        self.assertEqual(recipebook.settled_from_rows(rows), set())

    def test_no_rows_is_not_an_error(self):
        self.assertEqual(recipebook.settled_from_rows([]), set())
        self.assertEqual(recipebook.settled_from_rows(None), set())


class TheBridgeDecidesNothing(unittest.TestCase):

    def test_the_plan_comes_from_the_pure_module(self):
        body = _code(_block("    async def _recipebook_once("))
        self.assertIn("recipebook.plan_learns(", body)
        self.assertIn("recipebook.plan_purchases(", body)
        self.assertIn("recipebook.settled_from_rows(", body)

    def test_no_skill_arithmetic_in_the_bridge(self):
        """Which recipe is in reach is recipebook's rule. A comparison here
        would be a second copy of it."""
        body = _code(_block("    async def _recipebook_once("))
        self.assertNotIn("required_rank", body)
        self.assertNotIn("RequiredSkillRank", body)
        self.assertNotIn("within_reach", body)

    def test_the_pass_never_reads_character_spell(self):
        """THE ONE THAT MATTERS. Being wrong in that direction destroys an item:
        the core consumes a recipe item on use whether or not anything was
        learned, and asks no already-known question of its own."""
        for signature in ("    async def _recipebook_once(",
                          "def _fetch_held_recipes(",
                          "def _fetch_recipe_skills(",
                          "def _fetch_recipe_listings("):
            self.assertNotIn("character_spell", _code(_block(signature)), signature)

    def test_the_verdict_reader_says_why_character_spell_cannot_be_used(self):
        """THE ONE TEST HERE THAT IS DELIBERATELY ABOUT THE PROSE. The next
        person to read this pass will reach for `character_spell` unless the
        reader that replaced it says why not, in the place they will be
        standing. Not wrapped in _code() for exactly that reason."""
        body = _block("def _fetch_recipe_verdicts(")
        self.assertIn("character_spell", body)
        self.assertIn("_SaveSpells", body)

    def test_the_learn_row_carries_the_kind_and_source_the_module_routes_on(self):
        body = _code(_block("def _insert_learn("))
        self.assertIn("(target_name, command, kind, target_arg, source)", body)
        self.assertIn("recipebook.LEARN_KIND", body)
        self.assertIn("recipebook.LEARN_SOURCE", body)

    def test_a_world_without_the_enum_warns_instead_of_raising(self):
        """PROSE STRIPPED FIRST, and this one is not hypothetical: _insert_learn's
        own docstring explains why the 1265 guard is kept, so asserting over the
        whole block passed against a version with the guard deleted."""
        for signature in ("def _insert_learn(", "def _insert_recipe_buy("):
            body = _code(_block(signature))
            self.assertIn("1265", body, signature)
            self.assertIn("return 0", body, signature)

    def test_every_reader_degrades_rather_than_raising(self):
        for signature in ("def _fetch_recipe_skills(", "def _fetch_held_recipes(",
                          "def _fetch_recipe_listings(",
                          "def _fetch_recipe_verdicts(",
                          "def _recent_recipe_keys("):
            body = _code(_block(signature))
            self.assertIn("1146", body, signature)

    def test_the_same_row_is_not_queued_twice_inside_the_window(self):
        body = _code(_block("    async def _recipebook_once("))
        self.assertIn("_recent_recipe_keys, GIVE_RETRY_MINUTES", body)

    def test_the_pass_stands_down_mid_dungeon(self):
        body = _code(_block("    async def _recipebook_once("))
        self.assertIn("self._mid_run(names)", body)

    def test_it_writes_no_travel_errand_of_its_own(self):
        """A second writer of travel_npc is the collision infra#3712 records.
        The shopping half only acts where the auction pass already put
        somebody.

        ASSERTED ON CODE AND NOT ON THE WORD, because the docstring explains
        exactly this and a bare substring search would be satisfied by deleting
        the explanation."""
        body = _code(_block("    async def _recipebook_once("))
        self.assertNotIn("travel_npc", body)
        self.assertNotIn("_claim_town_slot", body)
        self.assertNotIn("overseer_roster", body)
        self.assertIn("_fetch_auctioneer", body)

    def test_the_buy_goes_through_the_existing_auction_executor(self):
        body = _code(_block("def _insert_recipe_buy("))
        self.assertIn("auction.AUCTION_KIND", body)

    def test_the_held_query_reads_the_carried_side_only(self):
        """The `use` verb reaches worn gear, the backpack and equipped bags and
        deliberately not the bank, so a banked recipe is not drivable."""
        src = _source()
        sql = src[src.index("_RECIPE_HELD_SQL = ("):src.index("def _fetch_held_recipes(")]
        self.assertIn("character_inventory", sql)
        self.assertNotIn("character_bank", sql)
        self.assertIn("it.spellid_2 > 0", sql)

    def test_the_listing_query_only_takes_buyouts(self):
        src = _source()
        sql = src[src.index("_RECIPE_LISTINGS_SQL = ("):
                  src.index("def _fetch_recipe_listings(")]
        self.assertIn("a.buyoutprice > 0", sql)
        self.assertIn("it.spellid_2 > 0", sql)


class TheLoopIsRegisteredInBothPlaces(unittest.TestCase):
    """test_headless_bridge holds the two lists to differ by exactly
    HEADLESS_SKIP, so a loop added to one and not the other fails CI. Asserted
    here as well, because the failure there names the wrong thing."""

    def test_both_lists_carry_it(self):
        self.assertEqual(_source().count("self._recipebook_loop,"), 2)

    def test_it_has_its_own_clock(self):
        body = _code(_block("    async def _recipebook_loop("))
        self.assertIn("RECIPEBOOK_CYCLE_SECONDS", body)
        self.assertIn("self._recipebook_once()", body)


class TheExecutorContractThisPassDependsOn(unittest.TestCase):

    def test_a_bought_recipe_arrives_by_mail_and_not_in_the_bags(self):
        """Which is why the buy half can never feed the learn half in one pass.
        If this stops being true the design gets simpler, and this test is what
        should say so."""
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        _has(self, 'describe("bought", "", "the item arrives by mail', source,
             "DoAuction still says a bought item arrives by mail")

    def test_the_use_row_is_never_reported_as_delivered(self):
        """Spell 483 is a 3000ms cast, so a `delivered` would be a postmark and
        not a delivery."""
        source = MODULE.read_text(encoding="utf-8", errors="ignore")
        body = _slice(self, source, "static char const* DoLearnRecipe(",
                      "void ResolveLearnChecks(")
        _has(self, 'status = "verifying";', body, "the row waits out the cast")
        self.assertNotIn('status = "delivered";', body)


class TheModuleShips(unittest.TestCase):

    def test_recipebook_is_in_the_image(self):
        self.assertIn("_shared/recipebook.py",
                      DOCKERFILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
