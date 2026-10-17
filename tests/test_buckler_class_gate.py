"""A buckler sits in the shield slot, so only a shield class may be offered one.

Armour subclass 5 is the buckler. `wearable_armor` decided shields on subclass
6 alone and abstained on 5, so a class with no shield skill (a rogue, a
hunter) was planned a Burnt Buckler, the world refused every equip, and the
member read "Trying to wear Burnt Buckler: waiting for the game to accept it"
for as long as the piece stayed in the bags.
"""

import unittest

import gear

WARRIOR, PALADIN, HUNTER, ROGUE, SHAMAN, MAGE = 1, 2, 3, 4, 7, 8


def buckler(subclass=5):
    return gear.Holding(
        holder="Gorvash",
        guid=1,
        entry=1,
        name="Burnt Buckler",
        quality=2,
        item_level=12,
        required_level=7,
        allowable_class=-1,
        inventory_type=gear.INVTYPE_SHIELD,
        item_class=gear.ITEM_CLASS_ARMOR,
        item_subclass=subclass,
    )


def member(class_id):
    return gear.CharacterState("Gorvash", class_id, 10, {}, role=gear.ROLE_DAMAGE)


class ABucklerIsOnlyForAShieldClass(unittest.TestCase):
    def test_a_class_with_no_shield_skill_cannot_wear_it(self):
        for class_id in (HUNTER, ROGUE, MAGE):
            self.assertFalse(gear.wearable_armor(buckler(), member(class_id)))

    def test_a_shield_class_can(self):
        for class_id in (WARRIOR, PALADIN, SHAMAN):
            self.assertTrue(gear.wearable_armor(buckler(), member(class_id)))

    def test_it_is_not_planned_for_a_class_that_cannot(self):
        ok, _why = gear.would_wear(buckler(), member(ROGUE))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
