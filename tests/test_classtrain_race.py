"""No member is walked to train a spell its race can never learn (#792).

Bloodlust (Horde) and Heroism (Alliance) are one faction pair on the shaman
trainer list. The bridge read every class trainer spell, so each side counted
the other's as owed forever; the core refused it and the member was walked
again every cooldown.
"""

import pathlib
import unittest

import classtrain
import racespells

SHAMAN, ORC, DRAENEI, TAUREN = 7, 2, 11, 6
BLOODLUST, HEROISM = 2825, 32182
ROWS = [
    {"spell": 100, "level": 4, "cost": 10},
    {"spell": BLOODLUST, "level": 20, "cost": 90},
    {"spell": HEROISM, "level": 20, "cost": 90},
]


class RaceMasks(unittest.TestCase):
    def test_a_faction_pair_fits_only_its_own_side(self):
        self.assertTrue(racespells.fits(BLOODLUST, ORC, SHAMAN))
        self.assertTrue(racespells.fits(BLOODLUST, TAUREN, SHAMAN))
        self.assertFalse(racespells.fits(BLOODLUST, DRAENEI, SHAMAN))
        self.assertTrue(racespells.fits(HEROISM, DRAENEI, SHAMAN))
        self.assertFalse(racespells.fits(HEROISM, ORC, SHAMAN))

    def test_a_spell_with_no_race_row_or_an_unknown_race_fits(self):
        self.assertTrue(racespells.fits(100, ORC, SHAMAN))
        self.assertTrue(racespells.fits(HEROISM, 0, SHAMAN))
        self.assertTrue(racespells.fits(HEROISM, None, SHAMAN))


class DueLeavesOutSpellsARaceCannotLearn(unittest.TestCase):
    def test_an_orc_shaman_does_not_owe_heroism(self):
        due = classtrain.due(ROWS, set(), 30, race_id=ORC, own_class=SHAMAN)
        self.assertEqual(due, classtrain.Due(100, 2, 10))

    def test_a_draenei_shaman_does_not_owe_bloodlust(self):
        due = classtrain.due(ROWS, set(), 30, race_id=DRAENEI, own_class=SHAMAN)
        self.assertEqual(due, classtrain.Due(100, 2, 10))

    def test_a_pair_only_the_other_side_can_learn_leaves_nothing_due(self):
        rows = [r for r in ROWS if r["spell"] == HEROISM]
        due = classtrain.due(rows, set(), 30, race_id=ORC, own_class=SHAMAN)
        self.assertEqual(due, classtrain.Due())
        self.assertFalse(due.affords(10**9))

    def test_without_a_race_the_old_count_stands(self):
        self.assertEqual(classtrain.due(ROWS, set(), 30).count, 3)


class BridgePassesTheMembersRace(unittest.TestCase):
    def test_the_known_spells_read_carries_race_into_due(self):
        src = (pathlib.Path(__file__).resolve().parent.parent / "bridge.py").read_text()
        self.assertIn("c.race AS race_id", src)
        self.assertIn("race[name] or None, klass[name])", src)


if __name__ == "__main__":
    unittest.main()
