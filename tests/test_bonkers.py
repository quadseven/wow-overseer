"""Isolation tests for the operator-provisioned Bonkers cohort."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bonkers  # noqa: E402
import bonds  # noqa: E402


class BonkersDefinitionTests(unittest.TestCase):
    def test_the_proposed_five_have_stable_horde_pairs(self):
        self.assertEqual(
            [(m.name, m.race, m.char_class, m.faction) for m in bonkers.COHORT],
            [
                ("Blammo", "orc", "warrior", "horde"),
                ("Hexmama", "troll", "priest", "horde"),
                ("Moojuice", "tauren", "druid", "horde"),
                ("Rotgut", "undead", "rogue", "horde"),
                ("Zapzap", "blood elf", "mage", "horde"),
            ],
        )

    def test_validation_accepts_the_definition(self):
        self.assertEqual(bonkers.validate(), bonkers.COHORT)
        self.assertEqual(len(bonkers.names()), 5)

    def test_names_do_not_overlap_the_alliance_family(self):
        self.assertEqual(bonkers.overlap_with(bonds.FAMILY), ())

    def test_duplicate_name_is_rejected(self):
        members = list(bonkers.COHORT)
        members[-1] = bonkers.Member("Blammo", "blood elf", "mage")
        with self.assertRaisesRegex(ValueError, "unique"):
            bonkers.validate(members)

    def test_non_horde_member_is_rejected(self):
        members = list(bonkers.COHORT)
        members[0] = bonkers.Member("Blammo", "human", "warrior", "alliance")
        with self.assertRaisesRegex(ValueError, "Horde"):
            bonkers.validate(members)

    def test_invalid_race_class_pair_is_rejected(self):
        members = list(bonkers.COHORT)
        members[0] = bonkers.Member("Blammo", "orc", "mage")
        with self.assertRaisesRegex(ValueError, "race/class"):
            bonkers.validate(members)


if __name__ == "__main__":
    unittest.main()
