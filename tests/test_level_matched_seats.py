"""A seat in a levelling run is level-matched: nobody makes the door's mobs gray.

The core gives no experience to a member above the highest member the victim is
not gray to, halves everyone's when the victim is gray to the highest member,
and splits a kill by level share. A level 54 tank, or a lent level 60 healer, in
a door for levels 35 to 44 therefore costs the four members who are levelling
half their experience. These tests hold the seat rule at the public seam
(guildsocial.stance_of) and the cutoff itself (guildrun.gray_cutoff).
"""

import unittest

import guildrun
import guildsocial as gs
from test_guildsocial import mate

DOORS = {d.keyword: d for d in guildrun.doors()}
ARMORY = DOORS["scarlet-armory"]  # levels 36 to 41
ZULFARRAK = DOORS["zulfarrak"]  # levels 36 to 54
LOWER_SPIRE = DOORS["lower-blackrock-spire"]  # levels 55 to 60
PRIEST, WARRIOR = 5, 1


class GrayCutoff(unittest.TestCase):
    def test_the_core_formula_at_the_known_levels(self):
        # AzerothCore Gray level: <=5 none, <40 lvl-5-lvl/10, <60 lvl-1-lvl/5, else lvl-9.
        self.assertEqual(0, guildrun.gray_cutoff(5))
        self.assertEqual(28, guildrun.gray_cutoff(36))  # 36 - 5 - 3
        self.assertEqual(35, guildrun.gray_cutoff(44))  # 44 - 1 - 8
        self.assertEqual(43, guildrun.gray_cutoff(54))  # 54 - 1 - 10
        self.assertEqual(51, guildrun.gray_cutoff(60))

    def test_a_door_is_gray_to_a_member_when_its_mobs_sit_at_or_under_the_cutoff(self):
        self.assertTrue(guildrun.kills_gray(54, ARMORY))
        self.assertTrue(guildrun.kills_gray(60, ARMORY))
        self.assertFalse(guildrun.kills_gray(44, ARMORY))
        self.assertFalse(guildrun.kills_gray(60, LOWER_SPIRE))


class TheSeatRule(unittest.TestCase):
    def stance(self, level, door, asker_level, class_id=WARRIOR):
        m = mate("Seat", level, class_id)
        return gs.stance_of(m, door, asker_level, "Alliance", [])[0]

    def test_a_54_tank_carrying_a_door_for_the_30s_is_refused(self):
        self.assertEqual("", self.stance(54, ARMORY, 38))

    def test_a_lent_60_healer_for_a_door_in_the_40s_is_refused(self):
        self.assertEqual("", self.stance(60, DOORS["scarlet-cathedral"], 42, PRIEST))

    def test_a_60_healer_for_lower_blackrock_spire_is_still_welcome(self):
        self.assertNotEqual("", self.stance(60, LOWER_SPIRE, 57, PRIEST))

    def test_a_helper_just_over_the_door_that_does_not_gray_it_still_helps(self):
        # 45 against a door topping at 41: cutoff 35, under the Armory's mobs (36 and up).
        self.assertEqual(gs.HELPS, self.stance(45, ARMORY, 38))

    def test_a_member_inside_the_band_is_unchanged(self):
        self.assertEqual(gs.NEED, self.stance(40, ARMORY, 38))


if __name__ == "__main__":
    unittest.main()
