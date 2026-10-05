"""The family tailor sews the guild's bags (operator, 2026-10-05).

The family are the guild's master crafters: a tailor sews the biggest bag its
skill allows that beats the smallest bag anybody in the guild wears, weaving
the bolts toward it first, and the corps posts it from the next mailbox.
"""

import unittest

import bag_upgrade
import craft_rhythm
import craft_supply

TAILOR = ("tailoring",)
WOOL_BOLT = 2997
WOOL = 2592
SILK_BOLT = 4305
HEAVY_LEATHER = 4234


def errand(value, floor, held=None, bags_wanted=0):
    return craft_rhythm.errand(
        "Og", {"tailoring": value}, held or {}, TAILOR, bags_wanted, floor
    )


class TheTailorSewsForTheGuild(unittest.TestCase):
    def test_bolts_in_hand_sew_the_biggest_bag_that_beats_the_floor(self):
        chosen = errand(90, 6, {WOOL_BOLT: 3})
        self.assertEqual(chosen.spell, 3757)
        self.assertIn("Woolen Bag (8 slots) for the guild", chosen.why)

    def test_short_of_bolts_it_weaves_them(self):
        chosen = errand(90, 6, {WOOL_BOLT: 1, WOOL: 12})
        self.assertEqual(chosen.spell, 2964)
        self.assertIn("1 of the 3", chosen.why)

    def test_an_empty_bag_position_takes_a_linen_bag_at_low_skill(self):
        self.assertEqual(errand(50, 0, {2996: 3}).spell, 3755)

    def test_no_bag_beats_the_floor_and_the_ladder_goes_on(self):
        chosen = errand(50, 8)
        self.assertNotIn(chosen.spell, craft_rhythm.BAG_FEED)

    def test_a_reagent_that_is_neither_bolt_nor_thread_must_be_in_hand(self):
        held = {SILK_BOLT: 3, WOOL_BOLT: 3}
        self.assertEqual(
            errand(160, 6, held).spell,
            3757,
            "no Heavy Leather: the Small Silk Pack waits",
        )
        held[HEAVY_LEATHER] = 2
        self.assertEqual(errand(160, 6, held).spell, 3813)

    def test_an_unread_guild_keeps_the_family_rule(self):
        self.assertEqual(errand(90, None, {2996: 3}, bags_wanted=1).spell, 3755)
        self.assertNotIn(errand(90, None).spell, craft_rhythm.BAG_FEED)

    def test_the_bag_stand_is_judged_on_its_own_bolts(self):
        stand = craft_rhythm.stand("Og", 3757, {WOOL_BOLT: 6})
        self.assertEqual((stand.verdict, stand.casts), (craft_rhythm.STOCKED, 2))

    def test_every_bag_the_tailor_may_sew_has_its_thread_bought(self):
        for spell in craft_rhythm.BAG_FEED:
            self.assertIn(spell, craft_supply.REAGENTS)

    def test_the_bolts_and_cloth_are_counted_before_the_choice(self):
        wanted = craft_rhythm.reagents_to_count("Og", {"tailoring": 90}, TAILOR, 0, 6)
        self.assertTrue({WOOL_BOLT, WOOL, HEAVY_LEATHER} <= wanted)


class TheGuildFloor(unittest.TestCase):
    def test_the_smallest_worn_bag_across_the_guild(self):
        rows = [{"worn": 4, "smallest": 10}, {"worn": 4, "smallest": 6}]
        self.assertEqual(bag_upgrade.guild_floor(rows), 6)

    def test_an_empty_bag_position_is_a_floor_of_zero(self):
        rows = [{"worn": 4, "smallest": 10}, {"worn": 2, "smallest": 14}]
        self.assertEqual(bag_upgrade.guild_floor(rows), 0)

    def test_nobody_read_is_not_a_floor(self):
        self.assertIsNone(bag_upgrade.guild_floor([]))


if __name__ == "__main__":
    unittest.main()
