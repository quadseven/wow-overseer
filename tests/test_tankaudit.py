"""Seated-tank spellbook audit: pure seam tests with fixture rows only."""

import pathlib
import sys
import unittest

from _stub_modules import PYMYSQL, stub_modules

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
with stub_modules(pymysql=PYMYSQL):
    import tankaudit

# Fixture trainer rows for one class: spell, level it asks, cost, reqs.
TRAINER = [
    {"spell": 100, "level": 10, "cost": 100, "req1": 0, "req2": 0, "req3": 0},
    {"spell": 200, "level": 20, "cost": 200, "req1": 100, "req2": 0, "req3": 0},
    {"spell": 300, "level": 30, "cost": 300, "req1": 0, "req2": 0, "req3": 0},
    {"spell": 400, "level": 70, "cost": 400, "req1": 0, "req2": 0, "req3": 0},
]


def _seat(name, seat="tank", level=30, class_id=1):
    return {
        "name": name,
        "seat": seat,
        "class_id": class_id,
        "class": "Warrior",
        "level": level,
    }


class AuditTank(unittest.TestCase):
    def test_complete_when_every_due_spell_is_known(self):
        out = tankaudit.audit_tank(_seat("Tankone"), TRAINER, {100, 200, 300})
        self.assertTrue(out["complete"])
        self.assertEqual(out["missing"], [])
        self.assertEqual(out["name"], "Tankone")

    def test_trainable_now_spell_is_missing(self):
        out = tankaudit.audit_tank(_seat("Tankone"), TRAINER, {100, 200})
        self.assertFalse(out["complete"])
        self.assertEqual(
            out["missing"], [{"spell": 300, "level": 30, "state": "trainable"}]
        )

    def test_needs_first_spell_is_missing_with_its_state(self):
        # 200 is due at level 20 but requires 100, which is not known.
        out = tankaudit.audit_tank(_seat("Tankone"), TRAINER, {300})
        states = {m["spell"]: m["state"] for m in out["missing"]}
        self.assertEqual(states[100], "trainable")
        self.assertEqual(states[200], "needs")

    def test_above_level_spell_is_not_missing(self):
        out = tankaudit.audit_tank(_seat("Tankone", level=10), TRAINER, set())
        spells = [m["spell"] for m in out["missing"]]
        self.assertIn(100, spells)
        self.assertNotIn(400, spells)


# Fixture rows for a chain no trainer visit can start: 500 is due at 10
# and requires 999, which is not a trainer row at all (a talent, a
# class-book spell); 501 is due at 20 and requires 500. This is the live
# shape of the warrior tanks' Mortal Strike ranks 2-4, whose rank 1 no
# class trainer sells (#2361).
GATED = [
    {"spell": 500, "level": 10, "cost": 100, "req1": 999, "req2": 0, "req3": 0},
    {"spell": 501, "level": 20, "cost": 100, "req1": 500, "req2": 0, "req3": 0},
]


class GatedChains(unittest.TestCase):
    def test_a_chain_no_trainer_row_starts_is_not_missing(self):
        out = tankaudit.audit_tank(_seat("Tankone"), GATED, set())
        self.assertTrue(out["complete"])
        self.assertEqual(out["missing"], [])

    def test_a_gated_chain_does_not_hide_a_teachable_spell(self):
        out = tankaudit.audit_tank(_seat("Tankone"), TRAINER + GATED, {100, 200})
        self.assertEqual(
            out["missing"], [{"spell": 300, "level": 30, "state": "trainable"}]
        )


# 750 is Plate Mail, a proficiency spell (classtrain.PROFICIENCY_SPELLS):
# a tank holding the Plate Mail skill (293) counts as knowing it, the way
# the training read and the guild training pass already judge it. The
# live audit flagged it trainable for a tank whose training read counts
# it learned, because the audit never saw the member's skills (#2361).
PLATE = [{"spell": 750, "level": 40, "cost": 100, "req1": 0, "req2": 0, "req3": 0}]


class ProficiencySkills(unittest.TestCase):
    def test_a_proficiency_spell_held_as_a_skill_is_learned(self):
        out = tankaudit.audit_tank(
            _seat("Tankone", level=40), PLATE, set(), skills={293}
        )
        self.assertTrue(out["complete"])
        self.assertEqual(out["missing"], [])

    def test_a_proficiency_spell_without_the_skill_is_missing(self):
        out = tankaudit.audit_tank(_seat("Tankone", level=40), PLATE, set())
        self.assertEqual(
            out["missing"], [{"spell": 750, "level": 40, "state": "trainable"}]
        )


class AuditTanks(unittest.TestCase):
    def test_only_filled_tank_seats_are_audited(self):
        seats = [
            _seat("Tankone"),
            _seat("Healone", seat="healer"),
            _seat(None),
            _seat("Tanktwo"),
        ]
        out = tankaudit.audit_tanks(
            seats,
            {1: TRAINER},
            {"Tankone": {100, 200, 300}, "Tanktwo": {100}},
        )
        self.assertEqual(out["audited"], 2)
        self.assertEqual([t["name"] for t in out["tanks"]], ["Tankone", "Tanktwo"])
        self.assertEqual(out["incomplete"], 1)
        self.assertEqual(out["missing_total"], 2)

    def test_skills_ride_along_per_tank(self):
        out = tankaudit.audit_tanks(
            [_seat("Tankone", level=40)],
            {1: PLATE},
            {"Tankone": set()},
            skills_by_name={"Tankone": {293}},
        )
        self.assertTrue(out["tanks"][0]["complete"])
        self.assertEqual(out["missing_total"], 0)


# Fixture trainer row for the one spell the ticket names explicitly.
# The id and its trainer level come from the repo's own Spell.dbc-derived
# trainer facts (data/mc-spells.json: Warrior, level 32).
WARRIOR_TRAINER = [
    {"spell": 18499, "level": 32, "cost": 100, "req1": 0, "req2": 0, "req3": 0},
]


class NamedSpells(unittest.TestCase):
    def test_berserker_rage_is_named_when_missing(self):
        out = tankaudit.audit_tank(_seat("Tankone", level=40), WARRIOR_TRAINER, set())
        self.assertFalse(out["complete"])
        self.assertEqual(
            out["missing"],
            [
                {
                    "spell": 18499,
                    "level": 32,
                    "state": "trainable",
                    "name": "Berserker Rage",
                }
            ],
        )

    def test_berserker_rage_is_not_missing_when_known(self):
        out = tankaudit.audit_tank(_seat("Tankone", level=40), WARRIOR_TRAINER, {18499})
        self.assertTrue(out["complete"])
        self.assertEqual(out["missing"], [])

    def test_unnamed_spells_carry_no_name(self):
        out = tankaudit.audit_tank(_seat("Tankone"), TRAINER, {100, 200})
        self.assertEqual(len(out["missing"]), 1)
        self.assertNotIn("name", out["missing"][0])


if __name__ == "__main__":
    unittest.main()
