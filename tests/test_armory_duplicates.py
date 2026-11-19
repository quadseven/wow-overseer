"""The same item worn twice is a thing the armory read says out loud.

A live read found a level 60 member wearing one trinket in both trinket
slots. Nothing in the armory payload said so: a reader had to compare the
slot entries pairwise to notice. `gear.duplicates` on each member, and
`duplicates` on the whole read, name every item worn in more than one slot,
and mark which of them is a fault: two copies of one trinket share a
cooldown, while a pair of the same ring or a matched pair of weapons is two
real pieces.

Ticket: quadseven/wow-overseer#2358.
"""

import unittest

import armory
import family

BOOK = armory.TalentBook.load(".")
ITEMS = armory.ItemBook.load(".")
ROSTER = family.roster()
FIRST, SECOND = ROSTER[0], ROSTER[1]

SLOT = {name: index for index, name in enumerate(armory.EQUIPPED_SLOTS)}
HEART, HEART_NAME = 17744, "Heart of Noxxion"
BAND, BAND_NAME = 11984, "Cobalt Ring"
BLADE, BLADE_NAME = 2244, "Krol Blade"


def char(name=FIRST):
    return {
        "name": name,
        "level": 60,
        "race": 1,
        "class": 1,
        "online": 1,
        "activeTalentGroup": 0,
    }


def item(slot_name, entry, item_name, name=FIRST):
    return {
        "name": name,
        "slot": SLOT[slot_name],
        "entry": entry,
        "durability": 0,
        "item_name": item_name,
        "quality": 3,
        "item_level": 51,
        "required_level": 46,
        "max_durability": 0,
    }


def build(equipment_rows, char_rows=None):
    return armory.build_armory(
        [char()] if char_rows is None else char_rows, equipment_rows, [], BOOK, ITEMS
    )


def gear_of(payload, name=FIRST):
    return next(m for m in payload["members"] if m["name"] == name)["gear"]


class TheSameItemWornTwiceTest(unittest.TestCase):
    def test_one_trinket_in_both_trinket_slots_is_named_as_a_fault(self):
        payload = build(
            [
                item("trinket 1", HEART, HEART_NAME),
                item("trinket 2", HEART, HEART_NAME),
            ]
        )
        self.assertEqual(
            gear_of(payload)["duplicates"],
            [
                {
                    "entry": HEART,
                    "name": HEART_NAME,
                    "slots": ["trinket 1", "trinket 2"],
                    "fault": True,
                    "said": "Heart of Noxxion is worn twice: trinket 1 and trinket 2",
                }
            ],
        )

    def test_two_different_trinkets_are_not_a_duplicate(self):
        payload = build(
            [
                item("trinket 1", HEART, HEART_NAME),
                item("trinket 2", 11815, "Hand of Justice"),
            ]
        )
        self.assertEqual(gear_of(payload)["duplicates"], [])

    def test_a_member_with_nothing_on_reports_none_rather_than_no_key(self):
        """An absent key reads the same as "not checked"; an empty list is
        the answer "checked, and there are none"."""
        payload = build([])
        self.assertEqual(gear_of(payload)["duplicates"], [])
        self.assertEqual(payload["duplicates"], [])

    def test_a_pair_of_the_same_ring_is_listed_but_is_not_a_fault(self):
        """Two copies of one ring are two real rings. The read still names
        the pair, so the reader is told rather than left to assume, but it
        does not call it wrong."""
        payload = build(
            [item("finger 1", BAND, BAND_NAME), item("finger 2", BAND, BAND_NAME)]
        )
        (pair,) = gear_of(payload)["duplicates"]
        self.assertEqual(pair["slots"], ["finger 1", "finger 2"])
        self.assertFalse(pair["fault"])

    def test_a_matched_pair_of_weapons_is_listed_but_is_not_a_fault(self):
        payload = build(
            [
                item("main hand", BLADE, BLADE_NAME),
                item("off hand", BLADE, BLADE_NAME),
            ]
        )
        (pair,) = gear_of(payload)["duplicates"]
        self.assertEqual(pair["slots"], ["main hand", "off hand"])
        self.assertFalse(pair["fault"])

    def test_any_other_slot_pair_is_a_fault_not_only_trinkets(self):
        """The read is over every slot. The same entry in two slots that are
        not a ring pair or a weapon pair is never two useful pieces."""
        payload = build(
            [item("neck", BAND, BAND_NAME), item("finger 1", BAND, BAND_NAME)]
        )
        (pair,) = gear_of(payload)["duplicates"]
        self.assertEqual(pair["slots"], ["neck", "finger 1"])
        self.assertTrue(pair["fault"])

    def test_each_duplicated_item_is_listed_once_in_slot_order(self):
        payload = build(
            [
                item("trinket 2", HEART, HEART_NAME),
                item("trinket 1", HEART, HEART_NAME),
                item("finger 2", BAND, BAND_NAME),
                item("finger 1", BAND, BAND_NAME),
                item("head", 9999901, "A Helm"),
            ]
        )
        self.assertEqual(
            [(d["entry"], d["slots"]) for d in gear_of(payload)["duplicates"]],
            [
                (BAND, ["finger 1", "finger 2"]),
                (HEART, ["trinket 1", "trinket 2"]),
            ],
        )

    def test_the_whole_read_names_who_wears_what_twice(self):
        """One list for a sweep over the family: the member, the item and
        the slots, without walking every member's slots."""
        payload = build(
            [
                item("trinket 1", HEART, HEART_NAME, name=SECOND),
                item("trinket 2", HEART, HEART_NAME, name=SECOND),
                item("trinket 1", HEART, HEART_NAME),
            ],
            char_rows=[char(), char(SECOND)],
        )
        self.assertEqual(gear_of(payload)["duplicates"], [])
        self.assertEqual(
            payload["duplicates"],
            [
                {
                    "member": SECOND,
                    "entry": HEART,
                    "name": HEART_NAME,
                    "slots": ["trinket 1", "trinket 2"],
                    "fault": True,
                    "said": "Heart of Noxxion is worn twice: trinket 1 and trinket 2",
                }
            ],
        )

    def test_the_one_member_read_carries_it_on_the_member(self):
        """/api/armory/member answers with the member alone, so the list has
        to travel on the member's own gear block and not only on the family
        read."""
        payload = armory.build_armory(
            [char()],
            [
                item("trinket 1", HEART, HEART_NAME),
                item("trinket 2", HEART, HEART_NAME),
            ],
            [],
            BOOK,
            ITEMS,
            families=[("", [FIRST])],
        )
        (pair,) = payload["members"][0]["gear"]["duplicates"]
        self.assertEqual(pair["entry"], HEART)

    def test_an_absent_member_does_not_break_the_family_list(self):
        payload = build([], char_rows=[])
        self.assertEqual(payload["duplicates"], [])


if __name__ == "__main__":
    unittest.main()
