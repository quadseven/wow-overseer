"""No member is walked to train a spell the trainer can never teach it (#792).

A live check after the race table shipped found 118 of 191 refused trainer
walks sent only for rows the trainer cannot teach that member: a learn row
whose taught spell the member already holds (Summon Felsteed 1710 teaches
Felsteed 5784, which is all character_spell records), a learn row whose taught
spell only another race can learn (34768 teaches the blood elf warhorse),
Dual Wield on the rogue list, and bear spells for a druid without Bear Form.
"""

import unittest

import classtrain
import taughtspells

PALADIN, ROGUE, WARLOCK, DRUID = 2, 4, 9, 11
HUMAN, NIGHT_ELF, DRAENEI, BLOOD_ELF = 1, 4, 11, 10


def row(spell, level, cost=100, req=0):
    return {"spell": spell, "level": level, "cost": cost, "req1": req}


class LearnRowCountsWhenTheTaughtSpellIsHeld(unittest.TestCase):
    def test_a_warlock_holding_felsteed_does_not_owe_summon_felsteed(self):
        rows = [row(1710, 20, 10000)]
        due = classtrain.due(rows, {5784, 33388}, 34, race_id=HUMAN, own_class=WARLOCK)
        self.assertEqual(due, classtrain.Due())

    def test_a_warlock_without_felsteed_still_owes_it(self):
        rows = [row(1710, 20, 10000)]
        due = classtrain.due(rows, set(), 34, race_id=HUMAN, own_class=WARLOCK)
        self.assertEqual(due, classtrain.Due(10000, 1, 10000))

    def test_a_paladin_holding_warhorse_and_judgement_owes_neither_row(self):
        rows = [row(13820, 20, 7000), row(10321, 4, 100)]
        due = classtrain.due(
            rows, {13819, 20271}, 48, race_id=DRAENEI, own_class=PALADIN
        )
        self.assertEqual(due, classtrain.Due())

    def test_the_standing_card_reads_the_learn_row_as_learned(self):
        state = classtrain.spell_state(row(13820, 20), {13819}, 48, 80)
        self.assertEqual(state, "learned")

    def test_a_row_requiring_a_learn_row_is_reachable_through_its_taught_spell(self):
        rows = [row(900002, 30, 50, req=1710)]
        due = classtrain.due(rows, {5784}, 34, race_id=HUMAN, own_class=WARLOCK)
        self.assertEqual(due.count, 1)


class RaceCheckRunsOnTheTaughtSpell(unittest.TestCase):
    def test_a_draenei_paladin_does_not_owe_the_blood_elf_warhorse(self):
        rows = [row(34768, 20, 7000), row(13820, 20, 7000)]
        due = classtrain.due(rows, set(), 48, race_id=DRAENEI, own_class=PALADIN)
        self.assertEqual(due, classtrain.Due(7000, 1, 7000))

    def test_a_blood_elf_paladin_owes_its_own_warhorse_only(self):
        rows = [row(34768, 20, 7000), row(13820, 20, 7000)]
        due = classtrain.due(rows, set(), 48, race_id=BLOOD_ELF, own_class=PALADIN)
        self.assertEqual(due, classtrain.Due(7000, 1, 7000))


class RogueHasDualWield(unittest.TestCase):
    def test_a_rogue_does_not_owe_dual_wield(self):
        rows = [row(674, 10, 300)]
        due = classtrain.due(rows, set(), 48, race_id=HUMAN, own_class=ROGUE)
        self.assertEqual(due, classtrain.Due())

    def test_a_warrior_still_owes_dual_wield(self):
        rows = [row(674, 20, 300)]
        due = classtrain.due(rows, set(), 48, race_id=HUMAN, own_class=1)
        self.assertEqual(due.count, 1)


class DruidWithoutBearForm(unittest.TestCase):
    BEAR = [row(99, 10), row(5229, 12), row(5211, 14), row(779, 16)]

    def test_bear_spells_are_left_out_without_bear_form(self):
        rows = self.BEAR + [row(5176, 1)]
        due = classtrain.due(rows, set(), 20, race_id=NIGHT_ELF, own_class=DRUID)
        self.assertEqual(due, classtrain.Due(100, 1, 100))

    def test_bear_spells_are_owed_with_bear_form(self):
        due = classtrain.due(self.BEAR, {5487}, 20, race_id=NIGHT_ELF, own_class=DRUID)
        self.assertEqual(due.count, 4)

    def test_dire_bear_form_counts_as_bear_form(self):
        due = classtrain.due(self.BEAR, {9634}, 40, race_id=NIGHT_ELF, own_class=DRUID)
        self.assertEqual(due.count, 4)


class FrozenTables(unittest.TestCase):
    def test_the_measured_cases_are_in_the_tables(self):
        self.assertEqual(taughtspells.taught(1710)[0], 5784)
        self.assertEqual(taughtspells.taught(13820)[0], 13819)
        self.assertEqual(taughtspells.taught(10321)[0], 20271)
        self.assertEqual(taughtspells.taught(34768)[0], 34769)
        self.assertEqual(taughtspells.taught(100), (100,))
        for spell in (99, 5229, 5211, 779):
            self.assertIn(spell, taughtspells.BEAR_FORM_ONLY)

    def test_the_bridge_reads_the_taught_spells_and_bear_form(self):
        from test_guildsocial_bridge import bridge

        for spell in (5784, 13819, 20271, 34769, 5487, 9634):
            self.assertIn(str(spell), bridge._CLASS_KNOWN_SQL)
        self.assertEqual(bridge._CLASS_KNOWN_SQL.count("%s"), 1)

    def test_the_bridge_leaves_out_a_held_felsteed(self):
        from unittest import mock

        from test_guildsocial_bridge import bridge

        trainer = [{"class_id": WARLOCK, "spell": 1710, "level": 20, "cost": 10000}]
        known = [
            {
                "name": "Locky",
                "class_id": WARLOCK,
                "race_id": HUMAN,
                "level": 34,
                "spell": 5784,
            },
            {
                "name": "Newby",
                "class_id": WARLOCK,
                "race_id": HUMAN,
                "level": 34,
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
            got = bridge._class_training_due(["Locky", "Newby"])
        self.assertEqual(got["Locky"].count, 0)
        self.assertEqual(got["Newby"].count, 1)


if __name__ == "__main__":
    unittest.main()
