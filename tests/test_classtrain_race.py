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


class ClassMaskSemantics(unittest.TestCase):
    """A row with a race mask AND a class mask needs both (the core's rule)."""

    def setUp(self):
        self.spell = 900001
        racespells.ROWS[self.spell] = ((1 << (ORC - 1), 1 << (SHAMAN - 1)),)
        self.addCleanup(racespells.ROWS.pop, self.spell, None)

    def test_right_race_wrong_class_does_not_fit(self):
        self.assertFalse(racespells.fits(self.spell, ORC, 8))

    def test_right_race_and_class_fits(self):
        self.assertTrue(racespells.fits(self.spell, ORC, SHAMAN))

    def test_a_class_mask_of_zero_means_any_class(self):
        racespells.ROWS[self.spell] = ((1 << (ORC - 1), 0),)
        self.assertTrue(racespells.fits(self.spell, ORC, 8))
        self.assertFalse(racespells.fits(self.spell, DRAENEI, 8))


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

    def test_the_bridge_filters_by_the_members_race(self):
        from unittest import mock

        from test_guildsocial_bridge import bridge

        trainer = [
            {"class_id": SHAMAN, "spell": s, "level": lv, "cost": c}
            for s, lv, c in ((100, 4, 10), (BLOODLUST, 20, 90), (HEROISM, 20, 90))
        ]
        known = [
            {
                "name": "Orcy",
                "class_id": SHAMAN,
                "race_id": ORC,
                "level": 30,
                "spell": None,
            },
            {
                "name": "Draney",
                "class_id": SHAMAN,
                "race_id": DRAENEI,
                "level": 30,
                "spell": None,
            },
        ]

        def read(cur, what, sql, params=()):
            return trainer if what == "class trainer spells" else known

        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        with (
            mock.patch.object(bridge, "_connect", return_value=conn),
            mock.patch.object(bridge, "_corps_read", side_effect=read),
            mock.patch.dict(bridge._CLASS_TRAINER_ROWS, clear=True),
        ):
            got = bridge._class_training_due(["Orcy", "Draney"])
        self.assertEqual(classtrain.Due(100, 2, 10), got["Orcy"])
        self.assertEqual(classtrain.Due(100, 2, 10), got["Draney"])


if __name__ == "__main__":
    unittest.main()
