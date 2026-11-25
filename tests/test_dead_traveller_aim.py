"""A dead or ghost leader is aimed nowhere, so the quest drive does not
cycle against refused walks while the corpse run never starts.

The replay: every pass asks for the dead leader's column on every cycle, the
module refuses and hands the aim back, the quest drive takes over, and the
next pass asks again. The gate must hold every claimant on every cycle.
"""

import pathlib
import unittest

import errandgate as gate


class TheDeadHold(unittest.TestCase):
    def test_a_dead_leader_is_held_for_every_claimant_on_every_cycle(self):
        claimants = sorted(gate.ECONOMY_CLAIMANTS | set(gate.OTHER_CLAIMANTS))
        written = 0
        for _cycle in range(19):
            for claimant in claimants:
                verdict = gate.dead_hold(True)
                if verdict.allow:
                    written += 1
                self.assertIn("corpse run", verdict.said("Zug", claimant))
        self.assertEqual(0, written)

    def test_a_living_leader_is_allowed(self):
        self.assertTrue(gate.dead_hold(False).allow)
        self.assertEqual("", gate.dead_hold(False).said("Zug", "bank"))

    def test_rows_read_dead_or_ghost(self):
        self.assertTrue(gate.is_dead_row({"health": 0, "corpses": 0}))
        self.assertTrue(gate.is_dead_row({"health": 1, "corpses": 1}))
        self.assertFalse(gate.is_dead_row({"health": 900, "corpses": 0}))
        self.assertFalse(gate.is_dead_row(None))

    def test_the_town_slot_door_asks_before_writing_any_aim(self):
        src = (pathlib.Path(__file__).parent.parent / "bridge.py").read_text()
        door = src.split("async def _claim_town_slot", 1)[1]
        self.assertLess(
            door.index("_traveller_is_dead"),
            door.index("professions.Errand(character=character"),
        )


if __name__ == "__main__":
    unittest.main()
