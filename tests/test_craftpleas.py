"""A need becomes a name, and only when it is unambiguous (infra#2829).

Same bar kin.py's plea parsing sets for itself: the near-misses are worth as
much as the hits, because a false positive here is a fabricated voice line in
party chat and not a dropped feature.
"""

import unittest

import chat
import craftpleas


class ParseAskTest(unittest.TestCase):
    def test_a_plain_need_names_the_crafter(self):
        ask = craftpleas.parse_ask("Grug", "I need a bag")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.asker, "Grug")
        self.assertEqual(ask.product, "bag")
        self.assertEqual(ask.skill, "tailoring")
        self.assertEqual(ask.crafter, "Og")

    def test_the_caveman_form_is_understood(self):
        """Evan's own example, and professions.py's own `said` text, are both
        this grammar - no "need", just "make"."""
        ask = craftpleas.parse_ask("Grug", "Ugga make bag?")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.product, "bag")
        self.assertEqual(ask.crafter, "Og")

    def test_who_can_make_is_a_query_too(self):
        ask = craftpleas.parse_ask("Evan", "who can make potions around here")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.skill, "alchemy")
        self.assertEqual(ask.crafter, "Ugga")

    def test_every_product_resolves_to_its_assigned_crafter(self):
        """Asked by somebody who is not the crafter, every time.

        This used to ask as Grug for all fourteen products, which since
        infra#3197 is Grug asking Grug for a sword - self-address, and now
        correctly no ask at all. The asker moved rather than the assertion:
        who makes what is the thing under test, and it has not changed.
        """
        cases = {
            "bag": "Og",
            "robe": "Og",
            "cloth": "Og",
            "potion": "Ugga",
            "elixir": "Ugga",
            "flask": "Ugga",
            "armor": "Grug",
            "plate": "Grug",
            "sword": "Grug",
            "leathers": "Bork",
            "enchant": "Og",
        }
        for product, crafter in cases.items():
            with self.subTest(product=product):
                asker = "Ugga" if crafter != "Ugga" else "Grug"
                ask = craftpleas.parse_ask(asker, f"we need a {product}")
                self.assertIsNotNone(ask, f"{product} produced no ask")
                self.assertEqual(ask.crafter, crafter)

    def test_a_product_of_an_unassigned_trade_asks_nobody(self):
        """Glyphs and gems were Grog's until #2831's update moved him to
        mining + engineering. Inscription and jewelcrafting are now in
        professions.UNASSIGNED, so these words must resolve to no ask at all
        rather than keep naming him."""
        for product in ("glyph", "gem", "ring"):
            with self.subTest(product=product):
                ask = craftpleas.parse_ask("Ugga", f"we need a {product}")
                self.assertIsNone(ask, f"{product} should have no crafter")

    def test_leather_armor_is_not_shadowed_by_bare_armor(self):
        ask = craftpleas.parse_ask("Grug", "I need leather armor")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.product, "leather armor")
        self.assertEqual(ask.skill, "leatherworking")
        self.assertEqual(ask.crafter, "Bork")

    def test_no_speaker_is_none(self):
        self.assertIsNone(craftpleas.parse_ask("", "I need a bag"))

    def test_no_text_is_none(self):
        self.assertIsNone(craftpleas.parse_ask("Grug", ""))

    def test_an_unlisted_product_is_none(self):
        """Deliberately no opinion, same as professions.UNASSIGNED - inscription
        and jewelcrafting have no crafter, and craftpleas has no idea what a
        "widget" is either."""
        self.assertIsNone(craftpleas.parse_ask("Grug", "I need a widget"))

    def test_a_line_with_no_trigger_word_is_none(self):
        """Merely mentioning the noun is not a request."""
        self.assertIsNone(craftpleas.parse_ask("Grug", "my bag is heavy"))

    def test_a_negated_need_is_none(self):
        self.assertIsNone(craftpleas.parse_ask("Grug", "I don't need a bag"))

    def test_nobody_needs_is_none(self):
        self.assertIsNone(craftpleas.parse_ask("Grug", "nobody needs a bag right now"))

    def test_an_offer_to_make_something_for_someone_else_still_resolves(self):
        """Not a near-miss this module has to catch - unlike kin's "offering
        help to someone else", naming the crafter is correct here even when
        it is not who is speaking."""
        ask = craftpleas.parse_ask("Bork", "Og can make bags for everyone")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.crafter, "Og")


class SelfAddressTest(unittest.TestCase):
    """Nobody answers themselves (infra#3197).

    The captured loop, verbatim from `overseer_chat`: one sentence, 58 times
    in three minutes, because Og's own answer parsed as a fresh ask whose
    crafter was Og.
    """

    ANSWER = (
        "Og need cloth? Og know tailoring. Og make it, family just bring the stuff."
    )

    def test_the_crafters_own_answer_is_not_a_new_ask(self):
        self.assertIsNone(craftpleas.parse_ask("Og", self.ANSWER))

    def test_the_same_sentence_from_somebody_else_still_asks(self):
        """The guard is about WHO is speaking, not about the words. Grog
        saying he needs cloth is a real question with a real answer."""
        ask = craftpleas.parse_ask("Grog", "Grog need cloth")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.crafter, "Og")

    def test_a_crafter_asking_for_their_own_trade_is_silence(self):
        self.assertIsNone(craftpleas.parse_ask("Grug", "Grug need a sword"))

    def test_the_guard_ignores_how_a_name_is_capitalised(self):
        self.assertIsNone(craftpleas.parse_ask("og", self.ANSWER))

    def test_a_crafter_may_still_be_asked_about_somebody_elses_trade(self):
        """Og is the tailor and is not the smith; asking for plate is a
        question he cannot answer himself, so it is not self-address."""
        ask = craftpleas.parse_ask("Og", "Og need plate armor")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.crafter, "Grug")


class HandoverIsNotARequestTest(unittest.TestCase):
    """materials.py's own line carries both trigger words (infra#3197)."""

    def test_a_character_narrating_its_own_handover_asks_nothing(self):
        self.assertIsNone(
            craftpleas.parse_ask(
                "Grog", "Grog give Og 20 Linen Cloth. Og need it for tailoring."
            )
        )

    def test_the_other_stack_of_the_same_handover_asks_nothing_either(self):
        """The two lines that read as a loop: 20 and then 19."""
        self.assertIsNone(
            craftpleas.parse_ask(
                "Grug", "Grug give Og 19 Linen Cloth. Og need it for tailoring."
            )
        )

    def test_asking_somebody_else_to_give_you_something_is_still_an_ask(self):
        """Anchored on the SPEAKER's own name, so only a character narrating
        its own handover is silenced."""
        ask = craftpleas.parse_ask("Grug", "Og give Grug cloth please, Grug need it")
        self.assertIsNotNone(ask)
        self.assertEqual(ask.crafter, "Og")


class AskKeyTest(unittest.TestCase):
    """The say-it-once key is the intent, never the sentence."""

    def test_the_key_is_crafter_skill_and_asker(self):
        ask = craftpleas.parse_ask("Grug", "Grug need a bag")
        self.assertEqual(craftpleas.ask_key(ask), ("og", "tailoring", "grug"))

    def test_two_products_of_one_trade_are_one_conversation(self):
        """ "bag" and "robe" are the same thing to say to the same person."""
        bag = craftpleas.parse_ask("Grug", "Grug need a bag")
        robe = craftpleas.parse_ask("Grug", "Grug need a robe")
        self.assertEqual(craftpleas.ask_key(bag), craftpleas.ask_key(robe))

    def test_two_different_askers_are_two_conversations(self):
        grug = craftpleas.parse_ask("Grug", "Grug need a bag")
        bork = craftpleas.parse_ask("Bork", "Bork need a bag")
        self.assertNotEqual(craftpleas.ask_key(grug), craftpleas.ask_key(bork))

    def test_the_key_ignores_how_the_names_are_spelled(self):
        upper = craftpleas.parse_ask("GRUG", "GRUG need a bag")
        lower = craftpleas.parse_ask("grug", "grug need a bag")
        self.assertEqual(craftpleas.ask_key(upper), craftpleas.ask_key(lower))


class SkillStateTest(unittest.TestCase):
    """What the named crafter can actually do, right now."""

    def _ask(self):
        return craftpleas.parse_ask("Grug", "Grug need a bag")

    def test_a_trade_in_character_skills_is_held(self):
        self.assertEqual(
            craftpleas.state(self._ask(), {"Og": {"tailoring": 1}}), chat.HELD
        )

    def test_the_live_family_reads_as_learning_not_as_held(self):
        """Og as `character_skills` actually has him, read 2026-09-02:
        herbalism 30/75 and nothing else. ROSTER assigns him tailoring, so
        the honest word for it is "learning"."""
        self.assertEqual(
            craftpleas.state(self._ask(), {"Og": {"herbalism": 30}}),
            chat.LEARNING,
        )

    def test_a_trade_nobody_planned_or_holds_is_neither(self):
        ask = craftpleas.parse_ask("Grug", "Grug need a bag")
        self.assertEqual(ask.crafter, "Og")
        self.assertEqual(
            chat.skill_state(
                "Og",
                "cooking",
                held={"Og": {"herbalism": 1}},
                planned={"Og": ("tailoring",)},
            ),
            chat.UNSKILLED,
        )
        self.assertEqual(craftpleas.state(ask, {"Og": {}}), chat.LEARNING)

    def test_an_empty_reading_never_reads_as_held(self):
        """A failed skills read must not become a boast. Nothing known about
        anybody is not the same as everybody being able to do everything."""
        self.assertNotEqual(craftpleas.state(self._ask(), {}), chat.HELD)


class AnswerTest(unittest.TestCase):
    def test_the_crafter_speaks_in_first_person_about_their_own_trade(self):
        ask = craftpleas.parse_ask("Grug", "I need a bag")
        said = craftpleas.answer(ask, held={"Og": {"tailoring": 1}})
        self.assertIn("Og", said)
        self.assertIn("tailoring", said)
        self.assertIn("bag", said)

    def test_a_trade_that_is_only_planned_is_never_claimed(self):
        """The line Evan watched, and the one that replaces it. Og does not
        know tailoring; the learn has been 'planned' since 2026-08-26."""
        ask = craftpleas.parse_ask("Grug", "I need a bag")
        said = craftpleas.answer(ask, held={"Og": {"herbalism": 30}})
        self.assertNotIn("Og know tailoring", said)
        self.assertIn("learning", said)
        self.assertTrue(chat.honest_claim(said, skill="tailoring", state=chat.LEARNING))

    def test_a_trade_nobody_is_getting_says_nothing_at_all(self):
        """Silence is a real answer. A sentence a viewer cannot tell is false
        is worse than a question that goes unanswered."""
        ask = craftpleas.Ask(
            asker="Grug", product="bag", skill="cooking", crafter="Bork"
        )
        self.assertEqual(craftpleas.answer(ask, held={"Bork": {}}), "")

    def test_every_answer_it_does_give_passes_its_own_honesty_gate(self):
        ask = craftpleas.parse_ask("Grug", "I need a bag")
        for held, state in (
            ({"Og": {"tailoring": 1}}, chat.HELD),
            ({"Og": {"herbalism": 30}}, chat.LEARNING),
        ):
            with self.subTest(state=state):
                said = craftpleas.answer(ask, held=held)
                self.assertTrue(said)
                self.assertTrue(chat.honest_claim(said, skill=ask.skill, state=state))

    def test_the_answer_never_addresses_the_crafter_as_the_asker(self):
        """parse_ask refuses the self case, so no answer can ever be built
        that has Og asking Og - the assertion is on the pair, not on words."""
        for line in ("Og need cloth", "Og need a bag", "who can make cloth"):
            with self.subTest(line=line):
                self.assertIsNone(craftpleas.parse_ask("Og", line))


if __name__ == "__main__":
    unittest.main()
