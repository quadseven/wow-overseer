"""A family member casts the bandage rung it has bought (#2432).

The learn errand buys Heavy Linen Bandage (3276) at First Aid 40. Linen
Bandage (3275) is grey at 60, so a member that holds 3276 and is never aimed
at it sits at 60 for ever. A rung in the spellbook the caller read is
answered; one that is absent, or a book that was not read, is refused as
before.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import craft  # noqa: E402
import craft_rhythm  # noqa: E402

LINEN_BANDAGE = 3275
HEAVY_LINEN_BANDAGE = 3276
WOOL_BANDAGE = 3277
LINEN_CLOTH = 2589


class TheErrandAnswersAHeldSecondaryRung(unittest.TestCase):
    def test_first_aid_60_answers_3276_when_the_book_holds_it(self):
        self.assertEqual(
            craft.craft_errand(
                "Grug",
                {"first aid": 60},
                primaries=(),
                known=frozenset({HEAVY_LINEN_BANDAGE}),
            ),
            HEAVY_LINEN_BANDAGE,
        )

    def test_first_aid_60_is_refused_when_the_book_lacks_it(self):
        self.assertEqual(
            craft.craft_errand(
                "Grug", {"first aid": 60}, primaries=(), known=frozenset()
            ),
            0,
        )

    def test_an_unread_book_is_refused_as_before(self):
        self.assertEqual(craft.craft_errand("Grug", {"first aid": 60}, primaries=()), 0)
        self.assertEqual(
            craft.craft_errand("Grug", {"first aid": 60}, primaries=(), known=None),
            0,
        )

    def test_only_the_rung_the_skill_has_reached_is_answered(self):
        """Holding 3276 answers nothing at 80, where the rung is Wool Bandage."""
        known = frozenset({HEAVY_LINEN_BANDAGE})
        self.assertEqual(
            craft.craft_errand("Grug", {"first aid": 80}, primaries=(), known=known),
            0,
        )
        self.assertEqual(
            craft.craft_errand(
                "Grug",
                {"first aid": 80},
                primaries=(),
                known=known | {WOOL_BANDAGE},
            ),
            WOOL_BANDAGE,
        )

    def test_a_held_cooking_rung_is_still_not_answered(self):
        """Smoked Bear Meat (8607) is the Cooking rung at 75; only First Aid
        rungs are answered from the book."""
        self.assertEqual(
            craft.recipe_for(craft.SKILL_IDS["cooking"], 75).spell_id, 8607
        )
        self.assertEqual(
            craft.craft_errand(
                "Grug", {"cooking": 75}, primaries=(), known=frozenset({8607})
            ),
            0,
        )
        self.assertFalse(craft.secondary_held(8607, frozenset({8607})))

    def test_linen_bandage_is_answered_whatever_the_book_says(self):
        for known in (None, frozenset(), frozenset({HEAVY_LINEN_BANDAGE})):
            with self.subTest(known=known):
                self.assertEqual(
                    craft.craft_errand(
                        "Grug", {"first aid": 59}, primaries=(), known=known
                    ),
                    LINEN_BANDAGE,
                )

    def test_a_primary_rung_is_unchanged_by_the_book(self):
        skills = {"tailoring": 1, "first aid": 60}
        for known in (None, frozenset(), frozenset({HEAVY_LINEN_BANDAGE})):
            with self.subTest(known=known):
                self.assertEqual(
                    craft.craft_errand("Og", skills, ("tailoring",), known=known),
                    craft.craft_errand("Og", skills, ("tailoring",)),
                )


class TheRhythmBandagesWithAHeldRung(unittest.TestCase):
    """Grug is a smith with nothing to cast and Linen Cloth in its bags."""

    SKILLS = {"blacksmithing": 1, "first aid": 60}
    PRIMARIES = ("blacksmithing",)
    HELD = {LINEN_CLOTH: 20}

    def errand(self, known, skills=None, held=None):
        return craft_rhythm.errand(
            "Grug",
            self.SKILLS if skills is None else skills,
            self.HELD if held is None else held,
            self.PRIMARIES,
            known=known,
        )

    def idle(self):
        return craft.craft_errand("Grug", self.SKILLS, self.PRIMARIES)

    def test_the_idle_craft_is_a_primary_rung_with_nothing_in_hand(self):
        self.assertTrue(self.idle())
        self.assertEqual(craft_rhythm.casts_in_hand(self.idle(), self.HELD), 0)

    def test_first_aid_60_bandages_3276_when_the_book_holds_it(self):
        got = self.errand(frozenset({self.idle(), HEAVY_LINEN_BANDAGE}))
        self.assertEqual(got.spell, HEAVY_LINEN_BANDAGE)
        self.assertIn("Heavy Linen Bandage", got.why)

    def test_first_aid_60_keeps_the_idle_craft_when_the_book_lacks_it(self):
        got = self.errand(frozenset({self.idle()}))
        self.assertEqual(got.spell, self.idle())

    def test_an_unread_book_keeps_the_idle_craft(self):
        self.assertEqual(self.errand(None).spell, self.idle())

    def test_one_cloth_is_not_a_cast_of_the_heavy_rung(self):
        got = self.errand(
            frozenset({self.idle(), HEAVY_LINEN_BANDAGE}), held={LINEN_CLOTH: 1}
        )
        self.assertEqual(got.spell, self.idle())

    def test_linen_bandage_below_60_is_unchanged(self):
        skills = dict(self.SKILLS, **{"first aid": 59})
        for known in (None, frozenset({self.idle()})):
            with self.subTest(known=known):
                self.assertEqual(self.errand(known, skills=skills).spell, LINEN_BANDAGE)

    def test_the_cloth_of_a_bought_rung_is_counted(self):
        """The counts are fetched before the book is read, so the rung's cloth
        is counted whether or not it turns out to be held."""
        wanted = craft_rhythm.reagents_to_count("Grug", self.SKILLS, self.PRIMARIES)
        self.assertIn(LINEN_CLOTH, wanted)


if __name__ == "__main__":
    unittest.main()
