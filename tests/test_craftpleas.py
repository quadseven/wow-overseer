"""A need becomes a name, and only when it is unambiguous (infra#2829).

Same bar kin.py's plea parsing sets for itself: the near-misses are worth as
much as the hits, because a false positive here is a fabricated voice line in
party chat and not a dropped feature.
"""
import unittest

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
        cases = {
            "bag": "Og", "robe": "Og", "cloth": "Og",
            "potion": "Ugga", "elixir": "Ugga", "flask": "Ugga",
            "armor": "Grug", "plate": "Grug", "sword": "Grug",
            "leathers": "Bork",
            "enchant": "Og",
            "glyph": "Grog",
            "gem": "Grog", "ring": "Grog",
        }
        for product, crafter in cases.items():
            with self.subTest(product=product):
                ask = craftpleas.parse_ask("Grug", f"we need a {product}")
                self.assertIsNotNone(ask, f"{product} produced no ask")
                self.assertEqual(ask.crafter, crafter)

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
        """Deliberately no opinion, same as professions.UNASSIGNED - engineering
        has no crafter, and craftpleas has no idea what a "widget" is either."""
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


class AnswerTest(unittest.TestCase):
    def test_the_crafter_speaks_in_first_person_about_their_own_trade(self):
        ask = craftpleas.parse_ask("Grug", "I need a bag")
        said = craftpleas.answer(ask)
        self.assertIn("Og", said)
        self.assertIn("tailoring", said)
        self.assertIn("bag", said)


if __name__ == "__main__":
    unittest.main()
