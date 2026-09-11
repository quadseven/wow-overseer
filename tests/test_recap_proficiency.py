"""Whether a character can hold a thing at all (mod-overseer#411).

THE MEASUREMENT THIS FILE EXISTS FOR. The loot board offered Kam's Walking
Stick to a rogue, against the one-hand mace the rogue was already holding, and
listed a second character as also wanting it:

    entry 2280  Kam's Walking Stick
      class 2 (weapon)  subclass 10 (STAFF)  InventoryType 17 (two-hand)
      ItemLevel 27  RequiredLevel 22  AllowableClass -1
    entry 6472  Stinging Viper
      class 2  subclass 4 (one-hand mace)  InventoryType 13  ItemLevel 24

A rogue can never hold a staff. It passed because `allowable_class` was the
only class gate and -1 means the ITEM restricts nobody: whether a character
may hold a weapon is a proficiency, kept in that character's own
`character_skills` rows, and it appears nowhere in `item_template`.

WHAT IT PINS, in order of what it would cost to get wrong again:

  1. THE ROGUE IS NOT A CANDIDATE FOR 2280, and the board says which check
     excluded them rather than dropping the name.
  2. EVERY MEMBER IS CHECKED. The board named a second wanter and nobody
     looked at them, so these cases assert the whole list in both directions.
  3. AN UNKNOWN ANSWER IS NOT A REFUSAL. When the realm hands over no skill
     rows the board must behave exactly as it did before, item level plus the
     caveats, rather than quietly emptying itself.
  4. THE CAVEATS TRACK THE GAPS. The two that #411 closed disappear only when
     proficiency really was checked; the two whose gaps are still real stay.

Stdlib only, no database, no HTTP, like its siblings.

Tickets: mod-overseer#411.
"""
import unittest

import recap

# The core's own skill ids, SharedDefines.h:3104-3199 at the pinned revision.
SWORDS = 43
MACES = 54
STAVES = 136
DAGGERS = 173
PLATE = 293
MAIL = 413
LEATHER = 414
CLOTH = 415
SHIELD = 433

ROSTER = ["Bork", "Grog", "Grug", "Og", "Ugga"]

# The two items, exactly as the world table carries them.
KAMS = {"Entry": 3669, "Item": 2280, "Chance": 50.0, "GroupId": 1,
        "creature": 3669, "item_name": "Kam's Walking Stick", "quality": 2,
        "item_level": 27, "required_level": 22, "class": 2, "subclass": 10,
        "inventory_type": 17, "displayid": None, "allowable_class": -1}
VIPER = {"Entry": 3669, "Item": 6472, "Chance": 50.0, "GroupId": 1,
         "creature": 3669, "item_name": "Stinging Viper", "quality": 2,
         "item_level": 24, "required_level": 0, "class": 2, "subclass": 4,
         "inventory_type": 13, "displayid": None, "allowable_class": -1}


def worn(who, slot, name, ilvl, klass=4, subclass=2, inv_type=5):
    return {"name": who, "slot": slot, "entry": 900 + slot, "item_name": name,
            "quality": 2, "item_level": ilvl, "class": klass,
            "subclass": subclass, "inventory_type": inv_type,
            "displayid": None}


def skill(who, *ids, value=1):
    return [{"name": who, "skill": one, "value": value} for one in ids]


# The five, by what their `character_skills` rows actually say. Only two of
# them hold the staff line, which is the whole of the case: the ranking listed
# a rogue and one other, and neither of them is in that pair.
ROGUE_SKILLS = skill("Ugga", DAGGERS, SWORDS, MACES, CLOTH, LEATHER)
PALADIN_SKILLS = skill("Bork", SWORDS, MACES, CLOTH, LEATHER, MAIL, PLATE,
                       SHIELD)
MAGE_SKILLS = skill("Grug", STAVES, DAGGERS, CLOTH)
PRIEST_SKILLS = skill("Grog", STAVES, MACES, CLOTH)
WARRIOR_SKILLS = skill("Og", SWORDS, MACES, CLOTH, LEATHER, MAIL, SHIELD)

ALL_SKILLS = (ROGUE_SKILLS + PALADIN_SKILLS + MAGE_SKILLS + PRIEST_SKILLS
              + WARRIOR_SKILLS)

CHARS = [{"name": name, "level": 27, "class": 1} for name in ROSTER]
WORN = [worn(name, 4, "a tunic", 20) for name in ROSTER]


def member(name, skills):
    return recap.family_members(CHARS, WORN, [name], skills)[0]


class TheStaffAndTheRogue(unittest.TestCase):
    """mod-overseer#411 itself, as the operator saw it."""

    def test_the_rogue_is_refused_the_staff(self):
        v = recap.verdict(KAMS, member("Ugga", ROGUE_SKILLS))
        self.assertEqual(v["verdict"], recap.NO_PROFICIENCY)

    def test_and_the_refusal_names_the_check_and_the_weapon(self):
        """A name that disappears without a reason is the next bug."""
        v = recap.verdict(KAMS, member("Ugga", ROGUE_SKILLS))
        self.assertIn("staff", v["why"])
        self.assertIn("Ugga", v["why"])

    def test_the_mace_it_was_compared_against_is_not_refused(self):
        """So the refusal is about the staff, not about weapons in general."""
        v = recap.verdict(VIPER, member("Ugga", ROGUE_SKILLS))
        self.assertNotEqual(v["verdict"], recap.NO_PROFICIENCY)

    def test_a_character_who_holds_the_line_is_still_offered_it(self):
        v = recap.verdict(KAMS, member("Grug", MAGE_SKILLS))
        self.assertNotEqual(v["verdict"], recap.NO_PROFICIENCY)

    def test_a_refusal_outranks_nothing_and_never_reads_as_wanted(self):
        v = recap.verdict(KAMS, member("Ugga", ROGUE_SKILLS))
        self.assertNotIn(v["verdict"], (recap.UPGRADE, recap.EMPTY))


class EveryCandidateIsChecked(unittest.TestCase):
    """The board named a second wanter and nobody looked at them."""

    ENCOUNTERS = [{"entry": 586, "creditEntry": 3669, "name": "Kam Deepfury"}]

    def board(self, skills=None):
        return recap.build_lootboard(34, "The Stockades", self.ENCOUNTERS,
                                     [KAMS], CHARS, WORN, {}, ROSTER,
                                     skills)

    def drop(self, skills=None):
        return self.board(skills)["bosses"][0]["drops"][0]

    def test_neither_the_rogue_nor_the_other_wanter_is_a_candidate(self):
        wanted = self.drop(ALL_SKILLS)["wanted_by"]
        self.assertNotIn("Ugga", wanted)
        self.assertNotIn("Bork", wanted)

    def test_the_ones_who_can_hold_it_still_are(self):
        wanted = self.drop(ALL_SKILLS)["wanted_by"]
        self.assertIn("Grug", wanted)
        self.assertIn("Grog", wanted)

    def test_every_member_still_gets_a_verdict_with_a_reason(self):
        """Excluded is not absent. All five are readable on the drop."""
        readers = self.drop(ALL_SKILLS)["readers"]
        self.assertEqual(len(readers), len(ROSTER))
        for reader in readers:
            self.assertTrue(reader["why"])

    def test_the_three_who_cannot_hold_it_say_so_by_name(self):
        readers = {r["who"]: r for r in self.drop(ALL_SKILLS)["readers"]}
        for name in ("Ugga", "Bork", "Og"):
            self.assertEqual(readers[name]["verdict"], recap.NO_PROFICIENCY)
            self.assertIn("staff", readers[name]["why"])

    def test_without_skill_rows_the_board_is_exactly_what_it_was(self):
        """A read that fell through its guard must not empty the board."""
        wanted = self.drop()["wanted_by"]
        self.assertIn("Ugga", wanted)


class TheCaveatsTrackTheGaps(unittest.TestCase):
    """A caveat that outlives its gap teaches distrust of the whole footer."""

    def test_the_proficiency_caveat_goes_once_proficiency_is_checked(self):
        notes = recap.caveats_for(KAMS, proficiency_checked=True)
        self.assertFalse([n for n in notes if "proficiency" in n])

    def test_and_stays_while_it_is_not(self):
        notes = recap.caveats_for(KAMS, proficiency_checked=False)
        self.assertTrue([n for n in notes if "proficiency" in n])

    def test_the_shield_caveat_goes_with_it(self):
        shield = dict(KAMS, **{"class": 4, "subclass": 6,
                               "inventory_type": 14})
        self.assertFalse(recap.caveats_for(shield, proficiency_checked=True))
        self.assertTrue(recap.caveats_for(shield, proficiency_checked=False))

    def test_the_two_hander_caveat_stays_because_its_gap_is_real(self):
        """This board ranks by item level, and item levels do not add, so it
        cannot price an off hand honestly however much it knows."""
        notes = recap.caveats_for(KAMS, proficiency_checked=True)
        self.assertTrue([n for n in notes if "off hand" in n])

    def test_the_one_hander_caveat_stays_too(self):
        notes = recap.caveats_for(VIPER, proficiency_checked=True)
        self.assertTrue([n for n in notes if "dual wield" in n])

    def test_a_caveat_still_names_nobody(self):
        for checked in (True, False):
            for note in recap.caveats_for(KAMS, proficiency_checked=checked):
                for name in ROSTER:
                    self.assertNotIn(name, note)


class TheSkillMapIsTheCoresOwn(unittest.TestCase):
    """ItemTemplate::GetSkill, and nothing invented beside it."""

    def test_a_staff_needs_the_staff_line(self):
        self.assertEqual(recap.item_skill(KAMS), STAVES)

    def test_a_one_hand_mace_needs_the_mace_line(self):
        self.assertEqual(recap.item_skill(VIPER), MACES)

    def test_a_shield_needs_the_shield_line(self):
        self.assertEqual(
            recap.item_skill(dict(KAMS, **{"class": 4, "subclass": 6,
                                           "inventory_type": 14})),
            SHIELD)

    def test_a_ring_needs_nothing(self):
        self.assertEqual(
            recap.item_skill(dict(KAMS, **{"class": 4, "subclass": 0,
                                           "inventory_type": 11})),
            0)

    def test_a_cloak_needs_nothing_though_its_subclass_is_cloth(self):
        """The core exempts the three worn-regardless slots, and so does the
        module's own scorer. Gating them would refuse somebody their cloak."""
        self.assertEqual(
            recap.item_skill(dict(KAMS, **{"class": 4, "subclass": 1,
                                           "inventory_type": 16})),
            0)

    def test_a_bag_needs_nothing(self):
        self.assertEqual(
            recap.item_skill(dict(KAMS, **{"class": 1, "subclass": 0,
                                           "inventory_type": 18})),
            0)


class WhatIsNotKnownIsNotARefusal(unittest.TestCase):
    """The third state, and why it is None rather than an empty set."""

    def test_no_rows_at_all_leaves_every_member_unknown(self):
        who = recap.family_members(CHARS, WORN, ROSTER)
        self.assertTrue(all(m["skills"] is None for m in who))

    def test_a_member_absent_from_the_rows_stays_unknown(self):
        """Not an empty set, which would refuse them every weapon on the
        board on the strength of a read that returned nothing for them."""
        who = {m["name"]: m for m in
               recap.family_members(CHARS, WORN, ROSTER, ROGUE_SKILLS)}
        self.assertIsNotNone(who["Ugga"]["skills"])
        self.assertIsNone(who["Grug"]["skills"])

    def test_an_unknown_member_is_ranked_the_old_way(self):
        v = recap.verdict(KAMS, member("Grug", ROGUE_SKILLS))
        self.assertNotEqual(v["verdict"], recap.NO_PROFICIENCY)

    def test_a_skill_row_at_zero_does_not_count_as_holding_it(self):
        """`Player::GetSkillValue(skill) == 0` is the core's own test."""
        zeroed = skill("Ugga", STAVES, value=0) + ROGUE_SKILLS
        who = recap.family_members(CHARS, WORN, ["Ugga"], zeroed)[0]
        self.assertNotIn(STAVES, who["skills"])
        self.assertEqual(recap.verdict(KAMS, who)["verdict"],
                         recap.NO_PROFICIENCY)


class TheArmourLadderStillWorksWhereItIsStillUsed(unittest.TestCase):
    """The worn-armour heuristic is now the fallback, not the rule."""

    PLATE_CHEST = dict(KAMS, **{"class": 4, "subclass": 4,
                                "inventory_type": 5, "required_level": 0})

    def test_with_skills_known_the_answer_is_the_skill_row(self):
        who = member("Og", WARRIOR_SKILLS)  # mail, no plate
        self.assertEqual(recap.verdict(self.PLATE_CHEST, who)["verdict"],
                         recap.NO_PROFICIENCY)

    def test_and_a_plate_wearer_is_not_refused(self):
        who = member("Bork", PALADIN_SKILLS)
        self.assertNotEqual(recap.verdict(self.PLATE_CHEST, who)["verdict"],
                            recap.NO_PROFICIENCY)

    def test_without_skills_the_old_ladder_still_answers(self):
        who = recap.family_members(CHARS, [worn("Og", 4, "a mail tunic", 20,
                                          subclass=3)], ["Og"])[0]
        self.assertEqual(recap.verdict(self.PLATE_CHEST, who)["verdict"],
                         recap.TOO_HEAVY)


if __name__ == "__main__":
    unittest.main()
