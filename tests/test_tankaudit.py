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


if __name__ == "__main__":
    unittest.main()
