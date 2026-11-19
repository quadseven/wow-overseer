"""The armor term prices only armor that fits the wearer (Refs #2132).

equipscore priced armor as weight x armor / 10 in every slot and for every
material, so a mail caster piece with a high armor value could outrank a plate
piece with a tank's stats, and a finger slot's 50 armor could outrank nine
stamina. The armor term now counts where the slot normally carries armor and
the piece is the wearer's own material, or carries no stat the role wants.
"""

import unittest

import equipscore as es
from tests.test_equip_score import (
    DEFENSE,
    INT,
    PROTECTION,
    SPI,
    STA,
    STR,
    WARRIOR,
    WARRIOR_SKILLS,
    member,
    piece,
)

PLATE_SKILLS = WARRIOR_SKILLS + ",293"


def tank():
    return es.wearer_from_row(
        member(
            "Grug",
            WARRIOR,
            60,
            talents=PROTECTION,
            tree="Protection",
            skills=PLATE_SKILLS,
        )
    )


class ThePlateTankKeepsItsOwnArmor(unittest.TestCase):
    def test_a_plate_piece_with_tank_stats_beats_a_mail_caster_piece_with_more_armor(
        self,
    ):
        plate = piece(
            "Plate Chest",
            5,
            4,
            4,
            level=55,
            req=50,
            stats=((STR, 8), (STA, 20), (DEFENSE, 6)),
            armor=400,
            holder="Grug",
        )
        mail = piece(
            "Robe of Insight",
            5,
            4,
            3,
            level=58,
            req=50,
            stats=((INT, 25), (SPI, 12), (STA, 4)),
            armor=900,
            holder="Grug",
        )
        picked = [e.name for e in es.choose(tank(), [], [mail, plate])]
        self.assertEqual(["Plate Chest"], picked)

    def test_a_worn_plate_piece_is_not_stripped_for_the_mail_caster_piece(self):
        worn = piece(
            "Plate Chest",
            5,
            4,
            4,
            level=55,
            req=50,
            stats=((STR, 8), (STA, 20), (DEFENSE, 6)),
            armor=400,
            slot=4,
            holder="Grug",
        )
        mail = piece(
            "Robe of Insight",
            5,
            4,
            3,
            level=58,
            req=50,
            stats=((INT, 25), (SPI, 12), (STA, 4)),
            armor=900,
            holder="Grug",
        )
        self.assertEqual((), es.choose(tank(), [worn], [mail]))

    def test_an_armor_only_piece_of_another_material_still_fills_an_empty_slot(self):
        mail = piece(
            "Plain Mail Chest", 5, 4, 3, level=40, req=40, armor=300, holder="Grug"
        )
        self.assertEqual(
            ["Plain Mail Chest"], [e.name for e in es.choose(tank(), [], [mail])]
        )


class ArmorOnAJewelrySlotIsNotAGain(unittest.TestCase):
    def test_nine_stamina_beats_fifty_armor_on_a_finger(self):
        worn = piece(
            "Archaedic Stone of Strength",
            11,
            4,
            0,
            level=47,
            req=40,
            armor=50,
            slot=10,
            holder="Grug",
        )
        seal = piece(
            "Emperor's Seal",
            11,
            4,
            0,
            level=61,
            req=55,
            stats=((STA, 9),),
            holder="Grug",
        )
        self.assertEqual(
            ["Emperor's Seal"], [e.name for e in es.choose(tank(), [worn], [seal])]
        )

    def test_the_armor_term_is_zero_for_a_ring(self):
        ring = piece("Iron Ring", 11, 4, 0, armor=50, holder="Grug")
        self.assertEqual(0.0, es.value(ring, tank())[1])
