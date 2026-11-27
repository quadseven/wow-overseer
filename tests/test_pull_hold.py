"""The solo pull gate: a mana-class seat with no drink and low mana is held.

A seat is held only when it is a drinking (mana) class, carries no drink, sits
under the mana floor, and is not in a group run. The hold releases when it
holds drink or its mana is back at or above the floor, and it never holds a
seat in a group run.

PURE MODULE: facts in, held-or-not out. No MySQL, no clock.
"""

import unittest

import restsupply

# Class ids: 1 warrior, 4 rogue do not drink; 2 paladin, 5 priest, 8 mage, 9
# warlock, 11 druid, 3 hunter, 7 shaman drink.
WARRIOR = 1
PRIEST = 5
MAGE = 8
FLOOR = restsupply.PULL_HOLD_MANA_FLOOR_PCT


def held(class_id, mana_pct, drink, in_group_run):
    return restsupply.pull_hold(class_id, mana_pct, drink, in_group_run)


class SoloSeatHeldWhenDryAndLowMana(unittest.TestCase):
    def test_mana_class_no_drink_under_floor_is_held(self):
        self.assertTrue(held(PRIEST, FLOOR - 1, 0, False))

    def test_mana_class_no_drink_just_under_floor_is_held(self):
        self.assertTrue(held(MAGE, 1, 0, False))

    def test_warrior_never_held(self):
        self.assertFalse(held(WARRIOR, 0, 0, False))

    def test_rogue_never_held(self):
        self.assertFalse(held(4, 0, 0, False))


class DrinkReleasesTheHold(unittest.TestCase):
    def test_mana_class_with_drink_is_not_held_under_floor(self):
        self.assertFalse(held(PRIEST, FLOOR - 1, 1, False))

    def test_a_full_stack_of_drink_releases_the_hold(self):
        self.assertFalse(held(MAGE, 0, restsupply.drink_target(MAGE), False))

    def test_unread_drink_counts_as_no_drink(self):
        self.assertTrue(held(PRIEST, FLOOR - 1, None, False))


class ManaBackAboveFloorReleasesTheHold(unittest.TestCase):
    def test_at_the_floor_is_not_held(self):
        self.assertFalse(held(PRIEST, FLOOR, 0, False))

    def test_above_the_floor_is_not_held(self):
        self.assertFalse(held(MAGE, FLOOR + 1, 0, False))

    def test_full_mana_is_not_held(self):
        self.assertFalse(held(PRIEST, 100, 0, False))


class GroupRunIsNeverHeld(unittest.TestCase):
    def test_mana_class_dry_low_mana_in_a_run_is_not_held(self):
        self.assertFalse(held(PRIEST, 0, 0, True))

    def test_any_class_in_a_run_is_not_held(self):
        self.assertFalse(held(WARRIOR, 0, 0, True))


class UnreadMana(unittest.TestCase):
    def test_unread_mana_with_no_drink_is_held(self):
        self.assertTrue(held(PRIEST, None, 0, False))

    def test_unread_mana_with_drink_is_not_held(self):
        self.assertFalse(held(MAGE, None, 1, False))


if __name__ == "__main__":
    unittest.main()
