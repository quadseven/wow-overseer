"""A routed armor piece goes to the member whose own material it is (Refs #2133).

`gear.rank_receivers` only asked whether a member CAN wear a piece, so an epic
mail chest could go to a plate tank that wore a worse chest in the slot, ahead
of the mail shaman it was made for. The ranking now puts the members whose own
armor material the piece is ahead of the ones who would wear it down.
"""

import unittest

import gear

WARRIOR, SHAMAN, MAGE = 1, 7, 8


def mail_chest(**over):
    base = dict(
        holder="Avenah",
        guid=4910001,
        entry=19000,
        name="Breastplate of the Storm",
        quality=4,
        item_level=62,
        required_level=55,
        allowable_class=-1,
        inventory_type=5,
        item_class=gear.ITEM_CLASS_ARMOR,
        item_subclass=gear.ARMOR_MAIL,
    )
    base.update(over)
    return gear.Holding(**base)


def member(name, class_id, chest, level=60, role=gear.ROLE_DAMAGE):
    return gear.CharacterState(
        name=name, class_id=class_id, level=level, equipped={"chest": chest}, role=role
    )


def cands(*states):
    return [gear.Candidate(character=s, family=True) for s in states]


class TheOwnMaterialRanksFirst(unittest.TestCase):
    def test_a_mail_shaman_ranks_ahead_of_a_plate_tank_with_a_bigger_gain(self):
        shaman = member("Thrall", SHAMAN, 50)
        tank = member("Grug", WARRIOR, 20, role=gear.ROLE_TANK)
        ranked = gear.rank_receivers(mail_chest(), cands(tank, shaman))
        self.assertEqual(["Thrall", "Grug"], [r.name for r in ranked])
        self.assertTrue(ranked[0].native)
        self.assertFalse(ranked[1].native)

    def test_proficiency_still_gates_absolutely(self):
        mage = member("Jaina", MAGE, 10)
        ranked = gear.rank_receivers(mail_chest(), cands(mage))
        self.assertEqual((), ranked)

    def test_a_plate_tank_is_still_ranked_when_nobody_wears_the_piece_as_own(self):
        tank = member("Grug", WARRIOR, 20, role=gear.ROLE_TANK)
        ranked = gear.rank_receivers(mail_chest(), cands(tank))
        self.assertEqual(["Grug"], [r.name for r in ranked])

    def test_gain_orders_members_of_the_same_fit(self):
        a = member("Thrall", SHAMAN, 50)
        b = member("Rehgar", SHAMAN, 30)
        ranked = gear.rank_receivers(mail_chest(), cands(a, b))
        self.assertEqual(["Rehgar", "Thrall"], [r.name for r in ranked])

    def test_a_piece_with_no_material_is_nobodys_step_down(self):
        ring = mail_chest(inventory_type=11, item_subclass=0)
        warrior = member("Grug", WARRIOR, 0)
        self.assertTrue(gear.is_own_material(ring, warrior))
        weapon = mail_chest(item_class=gear.ITEM_CLASS_WEAPON, inventory_type=13)
        self.assertTrue(gear.is_own_material(weapon, warrior))

    def test_a_heavier_piece_is_its_wearers_own(self):
        plate = mail_chest(item_subclass=gear.ARMOR_PLATE)
        self.assertTrue(gear.is_own_material(plate, member("Grug", WARRIOR, 0)))
        self.assertFalse(gear.is_own_material(mail_chest(), member("Grug", WARRIOR, 0)))
